# -*- coding: utf-8 -*-
"""mfa.py — второй фактор входа: заведение, подтверждение, проверка, сброс.

━━ КАК УСТРОЕН ВХОД С ВТОРЫМ ФАКТОРОМ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    POST /auth/login       логин+пароль верны, но второй фактор включён
                           → 200 с {"mfa_required": true, "challenge": "<токен>"}
                             и БЕЗ токена доступа
    POST /auth/mfa/verify  challenge + шестизначный код (или код восстановления)
                           → обычная пара токенов

⚠️ ПОЧЕМУ ОТДЕЛЬНЫЙ КОРОТКИЙ ТОКЕН, А НЕ «ПОЛУПРАВА» У ОБЫЧНОГО. Токен с пометкой
«ещё не прошёл второй фактор» пришлось бы проверять В КАЖДОЙ ручке продукта, а их
за две сотни. Первая забытая — это доступ к журналу по одному паролю, и найти
её потом нечем. Здесь забыть негде: пока второй фактор не пройден, обычного
токена НЕ СУЩЕСТВУЕТ. Тот же приём и по той же причине, что заявка в беседу
отдельной таблицей вместо флага на участнике.

⚠️ Challenge живёт 5 минут и подписан тем же ключом, но с типом `mfa`. Тип
проверяется явно: без этого challenge годился бы как обычный токен доступа.

━━ ОБЯЗАТЕЛЬНОСТЬ ДЛЯ АДМИНИСТРАТОРА ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Пароль администратора — единственная дверь к персональным данным всего колледжа.
Поэтому на БОЕВОМ сервере роль `admin` без второго фактора не получает ничего,
кроме права его завести (см. deps.require_admin).

⚠️ Признак «боевой» берём у существующего `config.IS_PROD`, который выводится из
настроек, а не отдельным флагом. Отдельный флаг немедленно разошёлся бы с
действительностью — ровно это уже записано в config.py про GRADEBOOK_ENV. И это
же автоматически освобождает ЛОКАЛЬНЫЙ сервер внутри программы: там журнал обязан
работать офлайн, а второй фактор туда не синхронизируется намеренно.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .. import audit, config, qr, throttle, totp
from ..db import get_db
from ..deps import get_current_user
from ..models import User, UserMFA

router = APIRouter(prefix="/auth/mfa", tags=["mfa"])

#🔥 БЫЛО ПЯТЬ МИНУТ, И ЭТОГО НЕ ХВАТАЛО (03.09.2026, воспроизведено на бою).
#Человек вводит пароль, открывает телефон — и попадает в список записей, где рядом
#лежат «GradeBookAI», рабочая почта и десяток чужих сервисов. Пока он ищет нужную и
#пробует не ту, пять минут выходят. Дальше сервер отвечает 401, окно кода ПРОПАДАЕТ,
#и человек видит форму входа — со стороны это читается как «журнал меня выкинул».
#Ровно эта жалоба и пришла от Ярослава.
#
#⚠️ Десять минут — это НЕ ослабление: challenge не даёт доступа ни к чему, он лишь
#позволяет предъявить код. Всё, что он ускоряет для атакующего, — возможность вводить
#шестизначные коды, а их ограничивает `throttle` (восемь попыток и замок), а не срок
#этого токена. Настоящая защита здесь — ограничитель попыток, и он не тронут.
CHALLENGE_TTL_MIN = 10
CHALLENGE_TYPE = "mfa"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def required_for(user: User) -> bool:
    """Обязателен ли второй фактор этой роли на этом сервере."""
    return bool(config.IS_PROD) and user.role == "admin"


def row_for(db: Session, user_id: str) -> UserMFA | None:
    return db.query(UserMFA).filter(UserMFA.user_id == user_id).first()


def is_active(db: Session, user_id: str) -> bool:
    row = row_for(db, user_id)
    return bool(row and row.confirmed_at)


def make_challenge(user: User) -> str:
    payload = {
        "sub": user.login,
        "typ": CHALLENGE_TYPE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=CHALLENGE_TTL_MIN),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALG)


def _user_from_challenge(db: Session, token: str) -> User:
    try:
        data = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALG])
    except JWTError:
        #from None: причина здесь и есть сообщение, трейсбек JWTError только шумит.
        raise HTTPException(status_code=401,
                            detail="Срок подтверждения истёк, войдите заново") from None
    #⚠️ Тип проверяем ЯВНО. Без этой строки challenge был бы валидным токеном
    #доступа: подпись у него та же, а `get_current_user` смотрит на `sub`.
    if data.get("typ") != CHALLENGE_TYPE:
        raise HTTPException(status_code=401, detail="Неверный токен подтверждения")
    user = db.query(User).filter(User.login == data.get("sub"),
                                 User.deleted == False).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user


def _consume(db: Session, row: UserMFA, code: str, request: Request, login: str) -> bool:
    """Проверить код и ПОГАСИТЬ его. Возвращает True при успехе.

    Здесь же ограничитель попыток: шесть цифр — это миллион вариантов, и без
    ограничителя они перебираются за вечер. Пользуемся тем же `throttle`, что и
    вход по паролю: заводить второй счётчик значило бы, что перебор кода можно
    вести, не задевая счётчик пароля.
    """
    ip = throttle.client_ip(request)
    left = throttle.seconds_until_unlocked(ip, login)
    if left > 0:
        raise HTTPException(status_code=429,
                            detail=f"Слишком много попыток. Повторите через {left} с.",
                            headers={"Retry-After": str(left)})

    step = totp.verify(row.secret, code, after_step=int(row.last_step or 0))
    if step is not None:
        row.last_step = step
        throttle.register_success(ip, login)
        return True

    #Код восстановления — тот же путь входа, поэтому и гасится так же: один раз.
    hashes = list(row.recovery_hashes or [])
    for i, stored in enumerate(hashes):
        if stored and totp.check_recovery(code, stored):
            hashes[i] = ""                      # погашен навсегда
            row.recovery_hashes = hashes
            row.recovery_used = int(row.recovery_used or 0) + 1
            throttle.register_success(ip, login)
            return True

    #login_exists=True: логин заведомо существует — мы уже проверили пароль.
    throttle.register_failure(ip, login, login_exists=True)
    return False


# ─────────────────────────────────────────────────────────────────────────────────
# Заведение
# ─────────────────────────────────────────────────────────────────────────────────

@router.get("/status")
def mfa_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = row_for(db, user.id)
    left = sum(1 for h in (row.recovery_hashes or []) if h) if row else 0
    return {
        "enabled": bool(row and row.confirmed_at),
        "required": required_for(user),
        "recovery_left": left,
        "confirmed_at": (row.confirmed_at if row else "") or "",
    }


@router.post("/setup")
def mfa_setup(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Выдать секрет и строку для аутентификатора. Фактор ЕЩЁ НЕ ДЕЙСТВУЕТ.

    ⚠️ Повторный вызов при уже подтверждённом факторе отвергаем: иначе тот, кто
    доберётся до открытой сессии, просто перезаведёт фактор на свой телефон и
    получит постоянный вход. Перезавести можно только через `disable`, а он
    требует действующего кода.
    """
    row = row_for(db, user.id)
    if row and row.confirmed_at:
        raise HTTPException(status_code=409,
                            detail="Второй фактор уже настроен. Сначала отключите текущий.")
    secret = totp.new_secret()
    if row is None:
        row = UserMFA(user_id=user.id, created_at=_now())
        db.add(row)
    row.secret = secret
    row.confirmed_at = ""
    row.last_step = 0
    row.recovery_hashes = []
    row.recovery_used = 0
    db.commit()
    uri = totp.provisioning_uri(secret, user.login)
    #QR рисуем ЗДЕСЬ, а не отдельной ручкой: отдельная ручка означала бы второй адрес,
    #по которому отдаётся секрет второго фактора, и её пришлось бы отдельно закрывать
    #ролью и сроком. Здесь секрет и так уже в ответе — новой поверхности не появляется.
    size, path = qr.svg_path(uri)
    return {
        "secret": secret,
        "uri": uri,
        "digits": totp.DIGITS,
        "period": totp.STEP_SECONDS,
        #Матрица уходит как `d` для одного <path>: строкой разметки её не сделать, и
        #вставлять ответ сервера через v-html не приходится (см. qr.py).
        "qr": {"size": size, "path": path},
    }


@router.post("/confirm")
def mfa_confirm(body: dict = Body(...), request: Request = None,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Подтвердить код с телефона и включить фактор. Коды восстановления — ОДИН РАЗ.

    ⚠️ Коды показываются здесь и больше нигде и никогда: хранятся только их хеши.
    Показать их «ещё раз по кнопке» невозможно по построению, и это правильно —
    иначе открытая чужая сессия выдала бы полный комплект запасных ключей.
    """
    row = row_for(db, user.id)
    if not row or not row.secret:
        raise HTTPException(status_code=400, detail="Сначала начните настройку")
    if row.confirmed_at:
        raise HTTPException(status_code=409, detail="Второй фактор уже подтверждён")

    step = totp.verify(row.secret, str(body.get("code", "")))
    if step is None:
        throttle.register_failure(throttle.client_ip(request), user.login,
                                  login_exists=True)
        raise HTTPException(status_code=400,
                            detail="Код не подошёл. Проверьте время на телефоне.")

    codes = totp.new_recovery_codes()
    row.recovery_hashes = [totp.hash_recovery(c) for c in codes]
    row.recovery_used = 0
    row.last_step = step
    row.confirmed_at = _now()
    db.commit()
    audit.log(db, request, actor=user.login, role=user.role,
              action="mfa.enabled", detail="второй фактор включён")
    return {"ok": True, "recovery_codes": codes}


@router.post("/disable")
def mfa_disable(body: dict = Body(...), request: Request = None,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Отключить фактор. Требует ДЕЙСТВУЮЩЕГО кода — иначе это не защита.

    ⚠️ Пароля здесь недостаточно: сессия уже открыта под паролем, и «подтвердите
    паролем» проверяло бы то, что уже проверено. Смысл второго фактора в том, что
    снять его может только владелец второго фактора.
    """
    row = row_for(db, user.id)
    if not row or not row.confirmed_at:
        raise HTTPException(status_code=400, detail="Второй фактор не настроен")
    if not _consume(db, row, str(body.get("code", "")), request, user.login):
        db.commit()
        raise HTTPException(status_code=400, detail="Код не подошёл")
    db.delete(row)
    db.commit()
    audit.log(db, request, actor=user.login, role=user.role,
              action="mfa.disabled", level="warn",
              detail="второй фактор отключён")
    return {"ok": True}


@router.post("/recovery/regenerate")
def mfa_regenerate(body: dict = Body(...), request: Request = None,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Выдать новый комплект кодов восстановления. Старые перестают действовать все.

    Частичное обновление («добавить ещё пять») означало бы, что утёкший старый
    список продолжает работать, — а обращаются сюда именно тогда, когда он утёк.
    """
    row = row_for(db, user.id)
    if not row or not row.confirmed_at:
        raise HTTPException(status_code=400, detail="Второй фактор не настроен")
    if not _consume(db, row, str(body.get("code", "")), request, user.login):
        db.commit()
        raise HTTPException(status_code=400, detail="Код не подошёл")
    codes = totp.new_recovery_codes()
    row.recovery_hashes = [totp.hash_recovery(c) for c in codes]
    row.recovery_used = 0
    db.commit()
    audit.log(db, request, actor=user.login, role=user.role,
              action="mfa.recovery_regenerated",
              detail="перевыпущены коды восстановления")
    return {"ok": True, "recovery_codes": codes}


# ─────────────────────────────────────────────────────────────────────────────────
# Второй фактор ЗА ПРЕДЕЛАМИ входа
#
# 🔑 Одна дверь на всех. Ниже — единственная функция, которой пользуются ЧУЖИЕ
# подсистемы (сейчас — восстановление пароля в auth.py). Своя проверка кода в каждой
# из них означала бы свой ограничитель попыток, своё гашение использованного шага и
# свой набор кодов восстановления — то есть три места, где однажды забудут погасить
# код, и подсмотренные шесть цифр будут работать все тридцать секунд.
# ─────────────────────────────────────────────────────────────────────────────────

def guard_action(db: Session, user: User, code: str, request: Request,
                 what: str) -> None:
    """Пропустить действие только с верным кодом. У кого фактора нет — пропускать молча.

    ⚠️ ПОЧЕМУ «НЕТ ФАКТОРА — ПРОХОДИ». Требовать код у того, кто его не заводил, значит
    запереть человека навсегда: взять код неоткуда, а восстановление пароля — это как
    раз та дверь, за которой он оказывается, потеряв доступ. Второй фактор здесь
    УСИЛИВАЕТ защиту тех, кто его включил, а не создаёт новый способ потерять аккаунт.

    ⚠️ Отказ несёт `X-Gb-Reason: mfa_required` — по нему страница понимает, что надо
    показать поле кода, а не «пароль не подошёл». Без признака человек видел бы отказ
    и не догадывался, чего от него хотят.

    :param what: что именно защищаем — уходит в журнал аудита, без него запись
                 «код не подошёл» не даёт понять, где это случилось.
    """
    row = row_for(db, user.id)
    if not row or not row.confirmed_at:
        return
    code = (code or "").strip()
    if not code:
        raise HTTPException(status_code=401,
                            detail="Введите код из приложения-аутентификатора",
                            headers={"X-Gb-Reason": "mfa_required"})
    ok = _consume(db, row, code, request, user.login)
    db.commit()
    if not ok:
        audit.log(db, request, actor=user.login, role=user.role,
                  action="mfa.failed", level="warn",
                  detail=f"неверный код второго фактора ({what})")
        raise HTTPException(status_code=401, detail="Код не подошёл",
                            headers={"X-Gb-Reason": "mfa_required"})
    audit.log(db, request, actor=user.login, role=user.role, action="mfa.passed",
              detail=what)
    #Подтверждённый код снимает признак подозрительной активности: владелец второго
    #фактора только что доказал, что это он.
    throttle.clear_suspicion(user.login)


# ─────────────────────────────────────────────────────────────────────────────────
# Вход
# ─────────────────────────────────────────────────────────────────────────────────

@router.post("/verify")
def mfa_verify(body: dict = Body(...), request: Request = None,
               db: Session = Depends(get_db)):
    """Второй шаг входа: challenge + код → обычная пара токенов."""
    from .auth import _issue_token_pair      # ленивый: иначе кольцо импортов

    user = _user_from_challenge(db, str(body.get("challenge", "")))
    row = row_for(db, user.id)
    if not row or not row.confirmed_at:
        raise HTTPException(status_code=400, detail="Второй фактор не настроен")

    ok = _consume(db, row, str(body.get("code", "")), request, user.login)
    db.commit()
    if not ok:
        audit.log(db, request, actor=user.login, role=user.role,
                  action="mfa.failed", level="warn",
                  detail="неверный код второго фактора")
        raise HTTPException(status_code=400, detail="Код не подошёл")

    left = sum(1 for h in (row.recovery_hashes or []) if h)
    audit.log(db, request, actor=user.login, role=user.role, action="mfa.passed")
    #Код подтверждён — след «к аккаунту подбирали пароль» гасим: дальше требовать
    #подтверждения на каждое продление сессии значило бы наказывать жертву за атаку.
    throttle.clear_suspicion(user.login)
    out = _issue_token_pair(db, user, request)
    #Предупреждаем, когда запасных ключей почти не осталось. Молча закончившиеся
    #коды означают, что при потере телефона человек узнает об этом в худший момент.
    if left <= 2:
        out = dict(out)
        out["recovery_left"] = left
    return out
