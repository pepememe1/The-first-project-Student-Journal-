"""
webauthn_router.py — Passkeys (WebAuthn): вход по Face ID / отпечатку БЕЗ пароля.

Как это работает:
  • Регистрация ключа (уже вошедший пользователь включает биометрию): сервер выдаёт
    challenge → устройство создаёт пару ключей, приватный кладёт в защищённое хранилище
    (Secure Enclave / TEE), публичный отдаёт серверу. Сервер хранит ТОЛЬКО публичный.
  • Вход по ключу: сервер выдаёт challenge → устройство просит биометрию и подписывает
    challenge приватным ключом → сервер проверяет подпись публичным ключом и, если ок,
    выдаёт обычную пару JWT (как при входе паролем). Пароль при этом не участвует.

Discoverable-режим (resident key): пользователю не нужно вводить логин — браузер сам
показывает доступные passkey этого сайта, а сервер узнаёт пользователя по id ключа.

Challenge держим В ПАМЯТИ процесса с TTL (как throttle/events) — для одного сервера
колледжа достаточно; challenge одноразовый и живёт минуты.
"""
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import User, WebAuthnCredential
from ..config import WEBAUTHN_RP_ID, WEBAUTHN_ORIGIN, WEBAUTHN_RP_NAME
from .auth import _issue_token_pair
from .. import events, audit

from webauthn import (generate_registration_options, verify_registration_response,
                      generate_authentication_options, verify_authentication_response,
                      options_to_json)
from webauthn.helpers.structs import (PublicKeyCredentialDescriptor,
                                       AuthenticatorSelectionCriteria, ResidentKeyRequirement,
                                       UserVerificationRequirement)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

router = APIRouter(prefix="/auth/webauthn", tags=["webauthn"])

#Одноразовые challenge в памяти: ключ → (challenge_bytes, expires_ts). TTL 5 минут.
_CHALLENGE_TTL = 300
_reg_challenges: dict = {}
_auth_challenges: dict = {}


def _put(store: dict, key: str, challenge: bytes):
    #Заодно подчищаем протухшие, чтобы словарь не рос.
    now = time.time()
    for k in [k for k, (_, exp) in store.items() if exp < now]:
        store.pop(k, None)
    store[key] = (challenge, now + _CHALLENGE_TTL)


def _pop(store: dict, key: str):
    v = store.pop(key, None)
    if not v:
        return None
    challenge, exp = v
    return challenge if time.time() <= exp else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Регистрация passkey (пользователь уже вошёл паролем и включает биометрию) ──────
@router.post("/register/begin")
def register_begin(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Опции для создания passkey. Исключаем уже привязанные ключи (не плодить дубли)."""
    existing = db.query(WebAuthnCredential).filter(WebAuthnCredential.login == user.login).all()
    exclude = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
               for c in existing]
    opts = generate_registration_options(
        rp_id=WEBAUTHN_RP_ID,
        rp_name=WEBAUTHN_RP_NAME,
        user_name=user.login,
        user_id=user.login.encode("utf-8"),
        user_display_name=(user.full_name or f"{user.surname} {user.name}".strip() or user.login),
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            #resident key = passkey «находимый» (вход без ввода логина);
            #user_verification PREFERRED = просить биометрию/PIN, если устройство умеет.
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    _put(_reg_challenges, user.login, opts.challenge)
    return json.loads(options_to_json(opts))


@router.post("/register/complete")
def register_complete(body: dict = Body(...), request: Request = None,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Проверяем созданный ключ и сохраняем публичную часть."""
    challenge = _pop(_reg_challenges, user.login)
    if challenge is None:
        raise HTTPException(status_code=400, detail="Регистрация ключа истекла — начните заново")
    credential = body.get("credential") or body
    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=WEBAUTHN_RP_ID,
            expected_origin=WEBAUTHN_ORIGIN,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось проверить ключ: {e}") from e
    cred_id = bytes_to_base64url(verification.credential_id)
    if db.get(WebAuthnCredential, cred_id) is None:
        db.add(WebAuthnCredential(
            credential_id=cred_id, login=user.login,
            public_key=bytes_to_base64url(verification.credential_public_key),
            sign_count=verification.sign_count,
            transports=",".join(body.get("transports") or []),
            device_name=(body.get("device_name") or "Устройство").strip()[:60],
            created_at=_now(), last_used=""))
        db.commit()
    audit.log(db, request, actor=user.login, role=user.role, action="passkey.register")
    return {"ok": True}


# ── Вход по passkey (без пароля; discoverable — логин вводить не нужно) ────────────
@router.post("/login/begin")
def login_begin(body: dict = Body(default={}), db: Session = Depends(get_db)):
    """Опции для входа по биометрии. По умолчанию discoverable (браузер сам покажет
    passkey сайта). Если передан login — сузим до его ключей (быстрее выбор)."""
    login = (body or {}).get("login", "").strip() if isinstance(body, dict) else ""
    allow = None
    if login:
        creds = db.query(WebAuthnCredential).filter(WebAuthnCredential.login == login).all()
        allow = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
                 for c in creds] or None
    opts = generate_authentication_options(
        rp_id=WEBAUTHN_RP_ID,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    #Discoverable-вход логина не знает — храним challenge под общим ключом "".
    _put(_auth_challenges, login or "", opts.challenge)
    return json.loads(options_to_json(opts))


@router.post("/login/complete")
def login_complete(body: dict = Body(...), request: Request = None, db: Session = Depends(get_db)):
    """Проверяем подпись challenge публичным ключом и выдаём JWT (как обычный вход)."""
    credential = body.get("credential") or body
    cred_id = credential.get("id") or credential.get("rawId") or ""
    row = db.get(WebAuthnCredential, cred_id)
    if row is None:
        raise HTTPException(status_code=400,
                            detail="Ключ не найден. Войдите паролем и включите вход по биометрии.")
    #challenge мог быть сохранён под логином (если он передавался) или под "" (discoverable).
    challenge = _pop(_auth_challenges, body.get("login", "") or "")
    if challenge is None:
        challenge = _pop(_auth_challenges, row.login)
    if challenge is None:
        raise HTTPException(status_code=400, detail="Сессия входа истекла — попробуйте снова")
    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=WEBAUTHN_RP_ID,
            expected_origin=WEBAUTHN_ORIGIN,
            credential_public_key=base64url_to_bytes(row.public_key),
            credential_current_sign_count=row.sign_count,
            require_user_verification=False,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Проверка биометрии не удалась: {e}") from e
    row.sign_count = verification.new_sign_count
    row.last_used = _now()
    db.commit()
    u = db.query(User).filter(User.login == row.login, User.deleted == False).first()  # noqa: E712
    if not u:
        raise HTTPException(status_code=400, detail="Пользователь не найден")
    events.record("info", "login", f"вход по passkey (роль {u.role})", u.login)
    audit.log(db, request, actor=u.login, role=u.role, action="login.passkey")
    tok = _issue_token_pair(db, u, request)
    #Возвращаем и логин: при входе по passkey клиент не вводил его, а профилю он нужен.
    return {"access_token": tok.access_token, "refresh_token": tok.refresh_token,
            "role": tok.role, "name": tok.name, "login": u.login}


# ── Управление своими ключами (для настроек профиля) ──────────────────────────────
@router.get("/credentials")
def list_credentials(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    creds = (db.query(WebAuthnCredential)
             .filter(WebAuthnCredential.login == user.login)
             .order_by(WebAuthnCredential.created_at).all())
    return {"credentials": [{"id": c.credential_id, "device_name": c.device_name,
                             "created_at": c.created_at, "last_used": c.last_used}
                            for c in creds]}


@router.post("/credentials/delete")
def delete_credential(body: dict = Body(...), request: Request = None,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(WebAuthnCredential, (body.get("id") or ""))
    if row is not None and row.login == user.login:
        db.delete(row)
        db.commit()
        audit.log(db, request, actor=user.login, role=user.role, action="passkey.delete")
    return {"ok": True}
