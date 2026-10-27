"""Учётка студента после выдачи пароля: первичная настройка, замок, восстановление кодом.

Порядок задан Владом 27.10.2026:
  1. Администратор выдаёт случайный пароль (лист «логин · пароль») и вписывает почту,
     которую студент сообщил колледжу (`UserContact.admin_email`).
  2. Студент входит по выданному паролю — и сразу получает просьбу привязать почту и
     сменить пароль. Код подтверждения уходит, ТОЛЬКО если введённая почта совпадает с
     записью колледжа.
  3. После этого учётка ПРИНАДЛЕЖИТ СТУДЕНТУ (`owned_by_student`): администратор больше
     не видит пароля (он и так стёрт — `issued_credentials.forget`), не может его
     сбросить, не может включить студента в лист выдачи и не может подменить почту, на
     которую приходит код восстановления.
  4. Забыл пароль — две неудачные попытки на странице входа открывают «Забыли пароль?»:
     код приходит на почту, совпадающую И со своей подтверждённой, И с записью колледжа;
     по коду — новый пароль дважды.

🔑 ПАРОЛЬ МЕНЯЕТ ТА ЖЕ ДВЕРЬ, ЧТО И РАНЬШЕ. Верный код не меняет пароль сам — он выдаёт
одноразовый ключ (`PasswordReset`, тот же, что уходил ссылкой), а смену делает
существующий `/auth/recover/confirm`: второй фактор, слот хеша, отзыв всех сессий и
доверенных устройств, стирание выданного пароля, письмо «пароль изменён». Второй путь
записи пароля означал бы второй список «что не забыть», и первым забытым оказался бы
отзыв сессий захватчика.

⚠️ Код живёт в `shared_state` со сроком, а не в таблице: он одноразовый и короткий, а
`take` даёт ровно-один-раз даже при нескольких процессах. Перезапуск службы код теряет —
это честная цена: человек запросит новый.
"""
from __future__ import annotations

import hmac
import secrets
import threading
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from . import events, issued_credentials, login_guard, mailer, shared_state, throttle
from .models import PasswordReset, User

#Код из письма действует столько же, сколько код подтверждения почты: человек ждёт его
#прямо сейчас, а короткий срок обесценивает украденное письмо.
CODE_TTL_S = login_guard.EMAIL_CODE_TTL_MIN * 60
#Неверных вводов на ОДИН код. Общий счётчик попыток входа (`throttle`) считает их тоже,
#но он сбрасывается через минуты; свой потолок сжигает код, чтобы шесть цифр нельзя было
#перебирать бесконечно серией коротких заходов.
#🔥 ДВА ПОТОЛКА, А НЕ ОДИН (Полковник, 28.10.2026). С одним общим посторонний, знающий
#только логин, пятью неверными вводами сжигал код, который сейчас ждёт владелец, — то
#есть мешал восстановлению, ничего не взламывая. Теперь код сгорает для АДРЕСА после
#пяти его ошибок, а для всех — только после двадцати: владелец со своего адреса вводит
#код, даже если кто-то перебирал его с другого. 20 из миллиона на код при пяти кодах в
#час — перебору это не помогает.
MAX_CODE_TRIES = 5
MAX_CODE_TRIES_TOTAL = 20
#Письма: не чаще раза в минуту и не больше пяти в час на одну учётку. Иначе кнопка
#«прислать код» становится способом завалить чужой ящик письмами от колледжа.
RESEND_S = 60
LETTERS_PER_HOUR = 5
#Одноразовый ключ после верного кода — на ввод нового пароля дважды хватает с запасом.
TICKET_TTL_MIN = 10

_K_CODE = "pwrec:code:"
_K_SENT = "pwrec:sent:"
_K_HOUR = "pwrec:hour:"


# ─────────────────────────────────────────────────────────────────────────────────────
# ЧЬЯ УЧЁТКА
# ─────────────────────────────────────────────────────────────────────────────────────

def owned_by_student(db, user: User) -> bool:
    """Студент привязал почту колледжа и живёт на СВОЁМ пароле — администратор её не трогает.

    Три условия, и все обязательны:
      • это студент с заданным паролем;
      • своя почта подтверждена и совпадает с записью колледжа (`matched_self_email`) —
        значит восстановить пароль студент может сам, кодом из письма;
      • выданный колледжем пароль больше не действует (сменён самим человеком).
    Без второго условия замок запер бы учётку, которую восстановить нечем; без третьего
    закрыл бы администратору пароль, который он сам же и выдал на бумаге.
    ⚠️ `issued_credentials.state` может стереть устаревший шифротекст — коммитит вызывающий.
    """
    if user is None or user.role != "student" or not user.password_hash:
        return False
    if not login_guard.matched_self_email(db, user):
        return False
    return issued_credentials.state(db, user)["state"] != issued_credentials.STATE_ISSUED


def owned_refusal() -> HTTPException:
    """Единый отказ администратору: одна формулировка на все запертые двери."""
    return HTTPException(
        status_code=409,
        detail="Студент привязал свою почту и сменил пароль — учётка принадлежит ему. "
               "Пароль он восстанавливает сам: «Забыли пароль?» на странице входа, код "
               "придёт на его почту.",
        headers={"X-Gb-Reason": "account_owned"})


def onboarding_view(db, user: User) -> dict:
    """Что показать студенту после входа: нужна ли первичная настройка и с какого шага.

    Настройка нужна, пока студент живёт на ВЫДАННОМ пароле: его знает каждый, кто держал
    в руках лист группы. Без этой просьбы бумажный пароль оставался бы рабочим годами."""
    if user.role != "student":
        return {"needed": False}
    issued = issued_credentials.state(db, user)["state"] == issued_credentials.STATE_ISSUED
    matched = bool(login_guard.matched_self_email(db, user))
    return {
        "needed": issued,
        "admin_email_set": bool(login_guard.admin_email_of(db, user)),
        "email_verified": matched,
        "mail_ready": mailer.configured(),
        "step": "password" if matched else "email",
    }


def require_onboarding(db, user: User) -> None:
    """Дверь первичной настройки открыта только студенту на выданном пароле.

    🔑 Почему здесь не спрашивают текущий пароль, хотя `/me/password` спрашивает. Текущий
    пароль — выданный, он напечатан на листе группы: повторный ввод не доказал бы ничего
    сверх того, что уже доказал вход. Защита здесь другая — почта обязана совпасть с
    записью колледжа и подтвердиться кодом, а до неё держатель листа не дотянется."""
    if user.role != "student" or \
            issued_credentials.state(db, user)["state"] != issued_credentials.STATE_ISSUED:
        raise HTTPException(status_code=409,
                            detail="Первичная настройка уже пройдена. Пароль и почта "
                                   "меняются в настройках аккаунта.")


def check_onboarding_email(db, user: User, email: str, request) -> str:
    """Почта для первичной настройки обязана совпасть с записью колледжа. Возвращает её.

    ⚠️ Несовпадение засчитывается как неудачная попытка входа: иначе держатель листа
    перебирал бы адреса, выясняя почту студента."""
    admin = login_guard.admin_email_of(db, user)
    if not admin:
        raise HTTPException(status_code=409,
                            detail="Администратор ещё не внёс вашу почту. Сообщите её "
                                   "куратору или администратору и повторите позже.",
                            headers={"X-Gb-Reason": "admin_email_missing"})
    ip = login_guard._guard_attempts(request, user.login)
    typed = (email or "").strip().lower()
    if typed != admin:
        throttle.register_failure(ip, user.login, login_exists=True)
        raise HTTPException(status_code=400,
                            detail="Почта не совпадает с той, что вы сообщили колледжу. "
                                   "Проверьте адрес.")
    return typed


# ─────────────────────────────────────────────────────────────────────────────────────
# ВОССТАНОВЛЕНИЕ КОДОМ
# ─────────────────────────────────────────────────────────────────────────────────────

def _code_mac(user: User, code: str) -> str:
    return login_guard._mac(f"pwreset:{user.id}", code)


def _student(db, login: str):
    if not login:
        return None
    return db.query(User).filter(User.login == login, User.role == "student",
                                 User.deleted == False).first()  # noqa: E712


def _may_send(login: str) -> bool:
    """Пропустить письмо, если не упёрлись в частоту. `claim` — ровно один из двух
    одновременных запросов: пара «проверил → записал» отправила бы оба письма."""
    if shared_state.window_count(_K_HOUR + login, 3600) >= LETTERS_PER_HOUR:
        return False
    if not shared_state.claim(_K_SENT + login, RESEND_S):
        return False
    shared_state.window_add(_K_HOUR + login, 3600)
    return True


def _send_code(email: str, code: str) -> None:
    """Письмо — В ФОНЕ, после ответа: SMTP идёт только при существующей учётке, и его
    секунды выдали бы, есть ли такой студент (тот же довод, что у `_send_reset_link`)."""
    text, html = login_guard._code_letter(
        "Восстановление пароля",
        "Кто-то (надеемся, вы) запросил восстановление пароля к электронному журналу. "
        "Введите этот код на странице входа.", code)

    def _worker():
        try:
            if not mailer.send_email(email, "GradeBookAI — код восстановления пароля",
                                     text, html=html):
                events.record("warn", "recover_code_mail_failed",
                              "письмо с кодом восстановления не отправлено", "", "")
        except Exception as e:      # noqa: BLE001
            events.record("warn", "recover_code_mail_failed",
                          f"письмо с кодом восстановления не отправлено: {e}", "", "")

    threading.Thread(target=_worker, daemon=True).start()


def start(db, login: str, email: str) -> str:
    """Отправить код, если всё сходится. Возвращает причину для журнала аудита.

    Ответ человеку НЕ зависит от результата (это решает вызывающий): иначе форма
    «логин + почта» стала бы способом выяснить почту любого студента."""
    login = (login or "").strip()
    typed = (email or "").strip().lower()
    u = _student(db, login) if typed else None
    if u is None:
        return "учётка не найдена"
    target = login_guard.matched_self_email(db, u)
    if not target:
        return "своя почта не подтверждена или не совпадает с записью колледжа"
    if typed != target:
        return "введённая почта не совпадает"
    if not mailer.configured():
        return "отправка почты на сервере не настроена"
    if not _may_send(login):
        return "письмо уже отправлялось недавно"
    code = login_guard._new_code()
    shared_state.set(_K_CODE + login, {"mac": _code_mac(u, code), "tries": 0, "by_ip": {}},
                     ttl=CODE_TTL_S)
    _send_code(target, code)
    return "код отправлен"


def verify(db, login: str, code: str, request) -> str:
    """Проверить код и выдать одноразовый ключ смены пароля. Возвращает ключ.

    ⚠️ Текст отказа ОДИН на «кода нет», «истёк», «не подошёл» и «такой учётки нет»:
    разные тексты рассказали бы, по каким логинам код недавно запрашивали."""
    login = (login or "").strip()
    code = (code or "").strip()
    ip = login_guard._guard_attempts(request, login)
    bad = HTTPException(status_code=400,
                        detail="Код не подошёл или истёк. Запросите новый.")
    u = _student(db, login)
    cur = shared_state.get(_K_CODE + login) if u is not None else None
    who = ip or "-"
    burned_here = bool(cur) and int((cur.get("by_ip") or {}).get(who, 0)) >= MAX_CODE_TRIES
    if not cur or not code or burned_here or not hmac.compare_digest(
            _code_mac(u, code), str(cur.get("mac") or "")):
        throttle.register_failure(ip, login, login_exists=u is not None)
        if cur:
            def _bump(c):
                if not c:
                    return None
                tries = int(c.get("tries") or 0) + 1
                if tries >= MAX_CODE_TRIES_TOTAL:
                    return None
                by_ip = dict(c.get("by_ip") or {})
                by_ip[who] = int(by_ip.get(who, 0)) + 1
                return {**c, "tries": tries, "by_ip": by_ip}
            shared_state.update(_K_CODE + login, _bump, ttl=CODE_TTL_S)
        raise bad
    #Одноразовость — `take`: из двух одновременных верных вводов ключ получит один.
    got = shared_state.take(_K_CODE + login)
    if not got or not hmac.compare_digest(str(got.get("mac") or ""), str(cur.get("mac") or "")):
        raise bad
    throttle.register_success(ip, login)
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    db.add(PasswordReset(
        token=token, login=login, created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=TICKET_TTL_MIN)).isoformat(),
        used_at="", ip=ip))
    #Прежние невостребованные ключи (ссылка из старого письма) гасим: действующим
    #остаётся ровно один — тот, что выдан сейчас.
    (db.query(PasswordReset)
       .filter(PasswordReset.login == login, PasswordReset.used_at == "",
               PasswordReset.token != token)
       .update({"used_at": now.isoformat()}))
    db.commit()
    return token
