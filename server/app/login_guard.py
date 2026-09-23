# -*- coding: utf-8 -*-
"""login_guard.py — защита входа (4.0): контакты человека, код из письма, доверенные
устройства.

━━ ТРИ ВЕЩИ, И КАЖДАЯ ОТВЕЧАЕТ НА СВОЙ ВОПРОС ━━
  • КОНТАКТЫ (`UserContact`) — куда вообще можно прислать код. Своя почта считается
    способом защиты только после подтверждения кодом из письма: иначе код входа ушёл бы
    тому, кто её вписал.
  • ПОДТВЕРЖДЕНИЕ ВХОДА — вход с НЕдоверенного устройства при наличии способа защиты
    требует код из письма. Механизм тот же, что у второго фактора: пока код не введён,
    токена доступа НЕ СУЩЕСТВУЕТ, есть только короткий challenge (§2FA в CLAUDE.md).
    «Токен с пометкой „ещё не подтвердил“» пришлось бы проверять в двухстах ручках.
  • ДОВЕРЕННОЕ УСТРОЙСТВО (`TrustedDevice`) — где спрашивать код не нужно и где сессия
    живёт без потолка по возрасту.

━━ СВЕРКА КОНТАКТОВ ━━
У человека две пары данных: то, что он сообщил колледжу лично (`admin_*`, вписывает
администратор), и то, что указал сам в профиле (`self_*`). Угнавший аккаунт меняет
СВОЮ пару — до записи в деканате ему не дотянуться. Поэтому:
  • пары совпали — всё в порядке;
  • различаются — поле у администратора горит красным (повод спросить студента);
  • подтверждение входа идёт ТОЛЬКО на совпавший способ. Почта разошлась с записью
    колледжа — код на неё не шлём: он ушёл бы, возможно, угнавшему. SMS у нас нет
    (отдельного сервиса нет, и это был бы новый субобработчик ПДн), поэтому если совпал
    лишь телефон — подтверждать входа нечем, и администратор видит красное поле.

⚠️ Подтверждение действует ТОЛЬКО для веба и мобильного приложения. Десктоп проходит
жёсткий барьер устройства (§4.11) — это и есть его «доверенное устройство», а мост входа
программы (`desktop/local_api.py`) код из письма показать не умеет и не должен.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from jose import JWTError, jwt

from . import audit, config, events, gost, mailer, reg_utils, shared_state, throttle
from .models import TrustedDevice, User, UserContact

CONFIRM_TYPE = "login_confirm"
#Сколько живёт код подтверждения СВОЕЙ почты (в настройках). Письмо доходит не мгновенно,
#а человек в этот момент не торопится — пятнадцати минут хватает с запасом.
EMAIL_CODE_TTL_MIN = 15
#Пометка «этот challenge уже обменян на токены». Без неё перехваченная пара
#«challenge + код» годилась бы на ВТОРОЙ вход в течение тех же десяти минут.
_USED_PREFIX = "login_confirm:used:"


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _mac(purpose: str, value: str) -> str:
    """HMAC серверным секретом. Код в открытом виде не лежит нигде: ни в базе (она
    уходит в резервные копии), ни в challenge (его видит браузер, и шесть цифр
    перебрались бы офлайн за секунды, будь там простой хеш)."""
    key = (config.JWT_SECRET or "").encode("utf-8")
    return hmac.new(key, f"{purpose}|{value}".encode("utf-8"), hashlib.sha256).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(10 ** 6):06d}"


def _dec(value: str) -> str:
    return gost.decrypt(value) if value else ""


def _enc(value: str) -> str:
    return gost.encrypt(value) if value else ""


def mask_email(email: str) -> str:
    """«ivanova@yandex.ru» → «i*****a@yandex.ru». Адрес целиком на форме входа — это
    подсказка тому, кто подбирает пароль, какой ящик ломать следующим."""
    email = (email or "").strip()
    if "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        hidden = local[:1] + "*"
    else:
        hidden = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{hidden}@{domain}"


# ─────────────────────────────────────────────────────────────────────────────────────
# КОНТАКТЫ
# ─────────────────────────────────────────────────────────────────────────────────────

def contact_row(db, user_id: str, create: bool = False):
    row = db.get(UserContact, user_id)
    if row is None and create:
        row = UserContact(user_id=user_id)
        db.add(row)
    return row


def _norm_email(value: str) -> str:
    return (value or "").strip().lower()


def _compare(admin_value: str, self_value: str) -> str:
    """'match' | 'mismatch' | 'unknown'. Сравнивать есть что, только когда заполнены обе
    стороны: пустое поле — не расхождение, а «не знаем»."""
    if not admin_value or not self_value:
        return "unknown"
    return "match" if admin_value == self_value else "mismatch"


def confirm_email(db, user: User) -> str:
    """Куда слать код подтверждения входа ('' — подтверждать нечем).

    Три условия, и все обязательны: своя почта ПОДТВЕРЖДЕНА, она не расходится с
    записью колледжа, и почта на сервере вообще настроена. Последнее не мелочь: без
    SMTP код не уйдёт никогда, и требование подтверждения заперло бы человека."""
    row = contact_row(db, user.id)
    if row is None or not row.self_email or not row.self_email_verified_at:
        return ""
    own = _norm_email(_dec(row.self_email))
    if not own:
        return ""
    if _compare(_norm_email(_dec(row.admin_email)), own) == "mismatch":
        return ""
    if not mailer.configured():
        return ""
    return own


def contact_view(db, user: User, for_admin: bool = False) -> dict:
    """Контакты для показа. `for_admin` добавляет запись колледжа и сверку."""
    row = contact_row(db, user.id)
    own_email = _norm_email(_dec(row.self_email)) if row else ""
    own_phone = _dec(row.self_phone) if row else ""
    out = {
        "self_email": own_email,
        "self_email_verified": bool(row and row.self_email and row.self_email_verified_at),
        "self_phone": own_phone,
        "pending_email": _norm_email(_dec(row.pending_email)) if row else "",
        "mail_configured": mailer.configured(),
    }
    if for_admin:
        adm_email = _norm_email(_dec(row.admin_email)) if row else ""
        adm_phone = _dec(row.admin_phone) if row else ""
        channel = confirm_email(db, user)
        out.update({
            "admin_email": adm_email,
            "admin_phone": adm_phone,
            "email_state": _compare(adm_email, own_email),
            "phone_state": _compare(adm_phone, own_phone),
            "confirm_channel": mask_email(channel) if channel else "",
        })
    return out


def _clean_email_or_fail(value: str) -> str:
    """Почта: пусто — «стереть», иначе строго разрешённые домены.

    ⚠️ Список доменов ТОТ ЖЕ, что у регистрации (`reg_utils.valid_email`), и не из
    вредности: письмо на иностранный ящик — это передача адреса человека иностранной
    компании (п. 5.6.1 политики ВСГУТУ «трансграничная передача не осуществляется»)."""
    email = _norm_email(value)
    if email and not reg_utils.valid_email(email):
        raise HTTPException(status_code=400,
                            detail="Разрешены только почты @yandex.ru, @mail.ru, @esstu.ru")
    return email


def _clean_phone_or_fail(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    phone = reg_utils.normalize_phone(raw)
    if not phone:
        raise HTTPException(status_code=400, detail="Некорректный номер телефона")
    return phone


def set_admin_contacts(db, user: User, email: str, phone: str) -> None:
    """Запись колледжа — то, что человек сообщил лично. Коммит — за вызывающим."""
    row = contact_row(db, user.id, create=True)
    row.admin_email = _enc(_clean_email_or_fail(email))
    row.admin_phone = _enc(_clean_phone_or_fail(phone))
    row.updated_at = _now()


def set_self_phone(db, user: User, phone: str) -> None:
    row = contact_row(db, user.id, create=True)
    row.self_phone = _enc(_clean_phone_or_fail(phone))
    row.updated_at = _now()


def remove_self_email(db, user: User) -> None:
    row = contact_row(db, user.id)
    if row is None:
        return
    row.self_email = ""
    row.self_email_verified_at = ""
    row.pending_email = row.pending_mac = row.pending_expires_at = ""
    row.updated_at = _now()


def _code_letter(title: str, lead: str, code: str) -> tuple:
    text = (f"Здравствуйте!\n\n{lead}\n\nКод: {code}\n\n"
            "Код одноразовый и действует несколько минут. Никому его не сообщайте — "
            "сотрудники колледжа его никогда не спрашивают.\n\n"
            "Если вы ничего не запрашивали — просто проигнорируйте письмо.")
    html = mailer._brand_html(title, [
        lead,
        f"Код: <b style='font-size:22px;letter-spacing:4px'>{code}</b>",
        "Код одноразовый и действует несколько минут. Никому его не сообщайте — "
        "сотрудники колледжа его никогда не спрашивают."])
    return text, html


def _guard_attempts(request, login: str) -> str:
    """Ограничитель попыток ввода кода — ТОТ ЖЕ `throttle`, что у пароля и TOTP.

    Свой счётчик означал бы, что перебор кода можно вести, не задевая счётчик пароля
    (тот же довод, что в `mfa._consume`)."""
    ip = throttle.client_ip(request) if request is not None else ""
    left = throttle.seconds_until_unlocked(ip, login)
    if left > 0:
        raise HTTPException(status_code=429,
                            detail=f"Слишком много попыток. Повторите через {left} с.",
                            headers={"Retry-After": str(left)})
    return ip


def start_email_verification(db, user: User, email: str, request=None) -> str:
    """Отправить код подтверждения на НОВУЮ свою почту. Возвращает маску адреса.

    Письмо уходит СИНХРОННО (ручка — обычный `def`, то есть в пуле потоков, а не в
    цикле событий): человек ждёт код прямо сейчас, и «письмо ушло» должно быть правдой,
    а не надеждой фонового потока."""
    email = _clean_email_or_fail(email)
    if not email:
        raise HTTPException(status_code=400, detail="Укажите почту")
    if not mailer.configured():
        raise HTTPException(status_code=503,
                            detail="Отправка почты на сервере не настроена — подтвердить "
                                   "адрес сейчас нельзя. Сообщите администратору.")
    _guard_attempts(request, user.login)
    code = _new_code()
    row = contact_row(db, user.id, create=True)
    row.pending_email = _enc(email)
    row.pending_mac = _mac(f"email:{user.id}:{email}", code)
    row.pending_expires_at = (_now_dt() + timedelta(minutes=EMAIL_CODE_TTL_MIN)).isoformat()
    row.updated_at = _now()
    db.commit()
    text, html = _code_letter("Подтверждение почты",
                              "Этот адрес указали для защиты входа в электронный журнал.",
                              code)
    if not mailer.send_email(email, "GradeBookAI — подтверждение почты", text, html=html):
        raise HTTPException(status_code=503,
                            detail="Письмо не отправилось. Попробуйте ещё раз чуть позже.")
    return mask_email(email)


def confirm_email_verification(db, user: User, code: str, request=None) -> str:
    """Проверить код и сделать почту подтверждённой. Возвращает сам адрес."""
    ip = _guard_attempts(request, user.login)
    row = contact_row(db, user.id)
    if row is None or not row.pending_email or not row.pending_mac:
        raise HTTPException(status_code=400, detail="Сначала запросите код")
    email = _norm_email(_dec(row.pending_email))
    if not row.pending_expires_at or row.pending_expires_at < _now():
        raise HTTPException(status_code=400, detail="Срок кода истёк — запросите новый")
    expected = _mac(f"email:{user.id}:{email}", (code or "").strip())
    if not hmac.compare_digest(expected, row.pending_mac):
        throttle.register_failure(ip, user.login, login_exists=True)
        raise HTTPException(status_code=400, detail="Код не подошёл")
    throttle.register_success(ip, user.login)
    old = _norm_email(_dec(row.self_email)) if row.self_email_verified_at else ""
    row.self_email = _enc(email)
    row.self_email_verified_at = _now()
    row.pending_email = row.pending_mac = row.pending_expires_at = ""
    row.updated_at = _now()
    db.commit()
    #Прежний подтверждённый адрес узнаёт о замене. Это единственный сигнал владельцу,
    #если почту сменил тот, кто завладел его открытой сессией.
    if old and old != email:
        _send_in_background(old, "GradeBookAI — адрес почты изменён",
                            "Адрес почты для защиты входа в электронный журнал изменён. "
                            "Если это были не вы — выйдите из всех сессий (Настройки → "
                            "Аккаунт → Сессии) и сообщите администратору.")
    return email


def _send_in_background(email: str, subject: str, lead: str) -> None:
    """Уведомление, от которого ничего не зависит, — в фоновом потоке.

    SMTP это сотни миллисекунд, а то и секунды; держать ради них ответ человеку незачем.
    След обязателен: «письмо не пришло» иначе неотличимо от «не туда посмотрел»."""
    text = f"Здравствуйте!\n\n{lead}"
    html = mailer._brand_html(subject.split("—")[-1].strip() or "Уведомление", [lead])

    def _worker():
        try:
            if not mailer.send_email(email, subject, text, html=html):
                events.record("warn", "notice_mail_failed",
                              "письмо-уведомление не отправлено", "", "")
        except Exception as e:      # noqa: BLE001
            events.record("warn", "notice_mail_failed", f"письмо-уведомление: {e}", "", "")

    threading.Thread(target=_worker, daemon=True).start()


def notify_by_mail(db, user: User, subject: str, lead: str) -> bool:
    """Письмо на ПОДТВЕРЖДЁННУЮ свою почту, если она есть. True — отправка начата."""
    row = contact_row(db, user.id)
    if row is None or not row.self_email or not row.self_email_verified_at:
        return False
    if not mailer.configured():
        return False
    _send_in_background(_norm_email(_dec(row.self_email)), subject, lead)
    return True


# ─────────────────────────────────────────────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ ВХОДА КОДОМ ИЗ ПИСЬМА
# ─────────────────────────────────────────────────────────────────────────────────────

def start_login_confirmation(db, user: User, email: str, trust: bool, request=None) -> dict:
    """Пароль верен, устройство не доверенное — шлём код и отдаём challenge.

    ⚠️ Письмо не ушло — это ОТКАЗ (503), а не «пустим так». Иначе поломка почты
    отключала бы защиту входа у всех разом и молча. Цена названа: пока SMTP лежит,
    войти с НОВОГО устройства нельзя; доверенные устройства работают как прежде.
    """
    code = _new_code()
    jti = uuid.uuid4().hex
    payload = {
        "sub": user.login, "typ": CONFIRM_TYPE, "jti": jti, "trust": bool(trust),
        "mac": _mac(f"login:{jti}", code),
        "exp": _now_dt() + timedelta(minutes=config.LOGIN_CONFIRM_TTL_MIN),
    }
    challenge = jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALG)
    text, html = _code_letter("Подтверждение входа",
                              "Кто-то вошёл в ваш аккаунт электронного журнала с нового "
                              "устройства. Если это вы — введите код на странице входа.",
                              code)
    if not mailer.send_email(email, "GradeBookAI — код входа", text, html=html):
        audit.log(db, request, actor=user.login, role=user.role,
                  action="login.confirm.mail_failed", level="warn",
                  detail="код подтверждения входа не отправлен")
        raise HTTPException(status_code=503,
                            detail="Не удалось отправить код подтверждения на почту. "
                                   "Попробуйте войти чуть позже.")
    audit.log(db, request, actor=user.login, role=user.role,
              action="login.confirm.sent", detail="код подтверждения входа отправлен")
    return {"mfa_required": True, "method": "email", "channel": mask_email(email),
            "challenge": challenge, "expires_in": config.LOGIN_CONFIRM_TTL_MIN * 60}


def is_confirm_challenge(token: str) -> bool:
    """Challenge этого вида? Без проверки срока — её сделает `check_confirmation`."""
    try:
        data = jwt.decode(token or "", config.JWT_SECRET, algorithms=[config.JWT_ALG],
                          options={"verify_exp": False})
    except JWTError:
        return False
    return data.get("typ") == CONFIRM_TYPE


def check_confirmation(db, token: str, code: str, request=None) -> tuple:
    """challenge + код из письма → (пользователь, хочет ли доверять устройству)."""
    try:
        data = jwt.decode(token or "", config.JWT_SECRET, algorithms=[config.JWT_ALG])
    except JWTError:
        raise HTTPException(status_code=401,
                            detail="Срок подтверждения истёк, войдите заново") from None
    if data.get("typ") != CONFIRM_TYPE:
        raise HTTPException(status_code=401, detail="Неверный токен подтверждения")
    user = db.query(User).filter(User.login == data.get("sub"),
                                 User.deleted == False).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    ip = _guard_attempts(request, user.login)
    jti = str(data.get("jti") or "")
    if not jti or shared_state.get(_USED_PREFIX + jti):
        raise HTTPException(status_code=401, detail="Код уже использован, войдите заново")
    code = re.sub(r"\D", "", code or "")
    if not hmac.compare_digest(_mac(f"login:{jti}", code), str(data.get("mac") or "")):
        throttle.register_failure(ip, user.login, login_exists=True)
        audit.log(db, request, actor=user.login, role=user.role,
                  action="login.confirm.failed", level="warn",
                  detail="неверный код подтверждения входа")
        raise HTTPException(status_code=400, detail="Код не подошёл")
    throttle.register_success(ip, user.login)
    shared_state.set(_USED_PREFIX + jti, 1, ttl=config.LOGIN_CONFIRM_TTL_MIN * 60 + 60)
    audit.log(db, request, actor=user.login, role=user.role,
              action="login.confirm.ok", detail="вход подтверждён кодом из письма")
    return user, bool(data.get("trust"))


# ─────────────────────────────────────────────────────────────────────────────────────
# ДОВЕРЕННЫЕ УСТРОЙСТВА
# ─────────────────────────────────────────────────────────────────────────────────────

def _token_hash(secret: str) -> str:
    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


def _ua(request) -> str:
    return ((request.headers.get("user-agent", "") if request is not None else "")
            or "")[:300]


def _expired(dev: TrustedDevice) -> bool:
    """Вышел и не возвращался дольше срока — доверие снято."""
    if not dev.logged_out_at:
        return False
    try:
        out = datetime.fromisoformat(dev.logged_out_at)
    except ValueError:
        return True
    if out.tzinfo is None:
        out = out.replace(tzinfo=timezone.utc)
    return _now_dt() - out > timedelta(days=config.TRUSTED_DEVICE_IDLE_DAYS)


def issue_trust(db, user: User, request=None) -> tuple:
    """Завести доверенное устройство. Возвращает (строка, токен для клиента).

    Токен — «id.секрет». Секрет в базе только хешем. Коммит — за вызывающим."""
    secret = secrets.token_urlsafe(32)
    dev = TrustedDevice(id=uuid.uuid4().hex, login=user.login, token_hash=_token_hash(secret),
                        created_at=_now(), last_login_at=_now(), logged_out_at="",
                        revoked=False, user_agent=_ua(request),
                        ip=throttle.client_ip(request) if request is not None else "")
    db.add(dev)
    return dev, f"{dev.id}.{secret}"


def check_trust(db, user: User, token: str):
    """Доверенное ли это устройство для этого человека. None — нет.

    Устаревшее (вышел больше 15 дней назад) снимается ЗДЕСЬ, при попытке входа, — ровно
    тогда, когда это имеет значение. Коммит — за вызывающим."""
    token = (token or "").strip()
    if "." not in token:
        return None
    dev_id, secret = token.split(".", 1)
    dev = db.get(TrustedDevice, dev_id)
    if dev is None or dev.revoked or dev.login != user.login:
        return None
    if not hmac.compare_digest(dev.token_hash or "", _token_hash(secret)):
        return None
    if _expired(dev):
        dev.revoked = True
        return None
    return dev


def mark_login(dev: TrustedDevice, request=None) -> None:
    dev.last_login_at = _now()
    dev.logged_out_at = ""
    if request is not None:
        dev.user_agent = _ua(request) or dev.user_agent
        dev.ip = throttle.client_ip(request) or dev.ip


def device_alive(db, device_id: str) -> bool:
    """Держит ли устройство за сессией «без срока» (для `/auth/refresh`)."""
    if not device_id:
        return False
    dev = db.get(TrustedDevice, device_id)
    return bool(dev is not None and not dev.revoked and not _expired(dev))


def on_logout(db, device_id: str) -> None:
    """Человек вышел: доверие не снимаем сразу, запускаем 15-дневный срок."""
    dev = db.get(TrustedDevice, device_id) if device_id else None
    if dev is not None and not dev.revoked:
        dev.logged_out_at = _now()


def revoke_device(db, device_id: str) -> None:
    dev = db.get(TrustedDevice, device_id) if device_id else None
    if dev is not None:
        dev.revoked = True


def revoke_all_devices(db, login: str, keep: str = "") -> int:
    """Снять доверие со всех устройств человека (кроме `keep`). Коммит — за вызывающим."""
    n = 0
    for dev in db.query(TrustedDevice).filter(TrustedDevice.login == login,
                                              TrustedDevice.revoked == False).all():  # noqa: E712
        if keep and dev.id == keep:
            continue
        dev.revoked = True
        n += 1
    return n
