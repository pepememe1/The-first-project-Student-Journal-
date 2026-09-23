# -*- coding: utf-8 -*-
"""account.py — учётная запись (4.0): свой пароль, свои сессии, свои контакты; выдача
стартовых паролей группам и «доп. данные» в редакторе пользователя.

━━ ДВЕ ГРУППЫ РУЧЕК, И У НИХ РАЗНЫЕ ДВЕРИ ━━
  • `/me/*` — о САМОМ себе: личность берётся из токена (`get_current_user`), чужой
    аккаунт подставить нечем.
  • `/web/accounts/*` — о ДРУГИХ: администратор — о любом, куратор — только о студентах
    своих `curated_groups`. Проверка на СЕРВЕРЕ, в одной функции (`_scope_student` /
    `_scope_group`); спрятанная у преподавателя кнопка — не защита, тот же запрос
    отправляется руками.

⚠️ Все ручки — обычный `def`, не `async def`: здесь хеш пароля (200k+200k итераций) и
отправка почты, а блокирующий вызов в `async def` останавливает ВЕСЬ сервер — колледжу,
а не одному человеку (инвариант из шапки CLAUDE.md, куплен настоящим дефектом).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import (account_sessions, audit, events, issued_credentials, login_guard,
                rustore_push, throttle)
from .. import webdata as W
from ..db import get_db
from ..deps import current_jti, get_current_user
from ..models import AuthSession, Group, User
from ..security import MIN_PASSWORD_LEN, verify_password
from ..models import set_user_password

router = APIRouter(tags=["account"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kick(user_id: str) -> None:
    """Разорвать живые сокеты. Рвутся ВСЕ, включая вкладку того, кто нажал кнопку, —
    она переподключится сама за секунду; зато сокет закрытой сессии не доживёт до конца
    срока, получая сигналы о переписке (тот же довод, что у выхода, см. auth.logout)."""
    from .auth import _kick_sockets
    _kick_sockets(user_id)


def _after_password_change(db: Session, user: User, by_admin: bool) -> None:
    """Сообщить владельцу, что пароль изменён: письмо во вкладку «Уведомления», пуш на
    все устройства и письмо на подтверждённую почту. Самого пароля нет НИГДЕ.

    Никогда не бросает: пароль уже сменён и закоммичен, и сбой уведомления не имеет
    права превращать успешное действие в ошибку."""
    try:
        rustore_push.notify_password_changed(db, user.login, by_admin=by_admin)
    except Exception as e:      # noqa: BLE001
        events.record("warn", "password_notice_failed", f"уведомление не создано: {e}",
                      user.login, "")
    lead = ("Администратор выдал вам новый пароль от электронного журнала."
            if by_admin else "Пароль от вашего аккаунта в электронном журнале изменён.")
    try:
        login_guard.notify_by_mail(
            db, user, "GradeBookAI — пароль изменён",
            lead + " Если это были не вы — выйдите из всех сессий (Настройки → Аккаунт → "
                   "Сессии → «Выйти из всех сессий») и сообщите администратору.")
    except Exception as e:      # noqa: BLE001
        events.record("warn", "password_notice_failed", f"письмо не отправлено: {e}",
                      user.login, "")


# ─────────────────────────────────────────────────────────────────────────────────────
# СВОЙ ПАРОЛЬ
# ─────────────────────────────────────────────────────────────────────────────────────

@router.post("/me/password")
def change_own_password(body: dict = Body(...), request: Request = None,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Сменить СВОЙ пароль. Нужен текущий пароль (и код второго фактора, если он есть).

    ⚠️ Зачем эта ручка вообще появилась (4.0). Самообслуживание на форме входа выключено
    (12.09.2026, решение Влада: пароль выдаёт колледж), а смены пароля изнутри кабинета
    не было вовсе — то есть студент, получивший стартовый пароль на бумаге, не мог
    сменить его НИКАК. Граница «придуманный самим пароль не виден никому» без этой двери
    была бы пустым обещанием.

    ⚠️ Прочие сессии НЕ закрываются: уведомление «если это были не вы — выйдите из всех
    сессий» обращено к владельцу, и выбить его из журнала значило бы отнять у него
    ровно ту кнопку, которой он ответил бы захватчику.
    """
    current = body.get("current") or ""
    new = body.get("new") or ""
    if len(new) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=400,
                            detail=f"Пароль не короче {MIN_PASSWORD_LEN} символов")
    if new == current:
        raise HTTPException(status_code=400, detail="Новый пароль совпадает с текущим")
    ip = throttle.client_ip(request)
    left = throttle.seconds_until_unlocked(ip, user.login)
    if left > 0:
        raise HTTPException(status_code=429,
                            detail=f"Слишком много попыток. Повторите через {left} с.",
                            headers={"Retry-After": str(left)})
    with throttle.hash_slot() as got:
        if not got:
            raise HTTPException(status_code=503,
                                detail="Сервер сейчас занят. Повторите через несколько секунд.",
                                headers={"Retry-After": str(int(throttle.HASH_WAIT_S) or 1)})
        ok = verify_password(current, user.password_hash or "")
    if not ok:
        #Тот же счётчик, что у входа: иначе смена пароля стала бы обходной дорогой к
        #перебору текущего пароля из украденной сессии.
        throttle.register_failure(ip, user.login, login_exists=True)
        audit.log(db, request, actor=user.login, role=user.role,
                  action="password.change.reject", level="warn",
                  detail="неверный текущий пароль")
        raise HTTPException(status_code=400, detail="Текущий пароль неверен")
    from . import mfa as _mfa
    _mfa.guard_action(db, user, str(body.get("code") or ""), request, what="смена пароля")
    with throttle.hash_slot() as got:
        if not got:
            raise HTTPException(status_code=503,
                                detail="Сервер сейчас занят. Повторите через несколько секунд.",
                                headers={"Retry-After": str(int(throttle.HASH_WAIT_S) or 1)})
        set_user_password(user, new)
    user.updated_at = _now()
    issued_credentials.forget(db, user)
    db.commit()
    throttle.register_success(ip, user.login)
    audit.log(db, request, actor=user.login, role=user.role, action="password.change",
              detail="пароль изменён самим пользователем")
    _after_password_change(db, user, by_admin=False)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────────────
# СВОИ СЕССИИ
# ─────────────────────────────────────────────────────────────────────────────────────

@router.get("/me/sessions")
def my_sessions(user: User = Depends(get_current_user), jti: str = Depends(current_jti),
                db: Session = Depends(get_db)):
    return {"sessions": account_sessions.list_for(db, user.login, jti)}


@router.post("/me/sessions/revoke-others")
def revoke_other_sessions(request: Request = None, user: User = Depends(get_current_user),
                          jti: str = Depends(current_jti), db: Session = Depends(get_db)):
    """«Выйти из всех сессий» — кроме текущей. Снимает и доверие с остальных устройств."""
    n = account_sessions.revoke_others(db, user.login, jti)
    db.commit()
    audit.log(db, request, actor=user.login, role=user.role,
              action="session.revoke_others", detail=f"закрыто сессий: {n}")
    _kick(user.id)
    return {"ok": True, "revoked": n}


@router.delete("/me/sessions/{sid}")
def revoke_my_session(sid: str, request: Request = None,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Закрыть одну сессию. Следующий её запрос получит 401 (`deps.get_current_user`)."""
    if not account_sessions.revoke_one(db, user.login, sid):
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    db.commit()
    audit.log(db, request, actor=user.login, role=user.role, action="session.revoke",
              detail="сессия закрыта из раздела «Сессии»")
    _kick(user.id)
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────────────
# СВОИ КОНТАКТЫ (почта и телефон для защиты входа)
# ─────────────────────────────────────────────────────────────────────────────────────

@router.get("/me/contacts")
def my_contacts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return login_guard.contact_view(db, user)


@router.post("/me/contacts/phone")
def set_my_phone(body: dict = Body(...), user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    login_guard.set_self_phone(db, user, str(body.get("phone") or ""))
    db.commit()
    return login_guard.contact_view(db, user)


@router.post("/me/contacts/email/start")
def start_my_email(body: dict = Body(...), request: Request = None,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    masked = login_guard.start_email_verification(db, user, str(body.get("email") or ""),
                                                  request)
    return {"ok": True, "sent_to": masked}


@router.post("/me/contacts/email/confirm")
def confirm_my_email(body: dict = Body(...), request: Request = None,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    login_guard.confirm_email_verification(db, user, str(body.get("code") or ""), request)
    audit.log(db, request, actor=user.login, role=user.role, action="contact.email_verified",
              detail="почта для защиты входа подтверждена")
    return login_guard.contact_view(db, user)


@router.delete("/me/contacts/email")
def remove_my_email(request: Request = None, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    login_guard.remove_self_email(db, user)
    db.commit()
    audit.log(db, request, actor=user.login, role=user.role, action="contact.email_removed",
              level="warn", detail="почта для защиты входа удалена")
    return login_guard.contact_view(db, user)


# ─────────────────────────────────────────────────────────────────────────────────────
# О ДРУГИХ: администратор — о любом, куратор — о студентах своих групп
# ─────────────────────────────────────────────────────────────────────────────────────

def _is_curator_of(user: User, group: str) -> bool:
    return (user.role == "teacher" and bool(group)
            and group in (user.curated_groups or []))


def _scope_group(user: User, group: str) -> None:
    """Группа доступна: администратору — любая, куратору — только курируемая."""
    if user.role == "admin" or _is_curator_of(user, group):
        return
    raise HTTPException(status_code=403, detail="Группа вне вашего кураторства")


def _scope_student(db: Session, user: User, login: str) -> User:
    """Человек, о котором спрашивают, — в пределах прав спрашивающего.

    Куратору — ТОЛЬКО студенты его групп. Клиентскому списку групп не доверяем: он
    приходит из браузера, а `curated_groups` — из базы (их назначает администратор)."""
    target = db.query(User).filter(User.login == (login or "").strip(),
                                   User.deleted == False).first()  # noqa: E712
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if user.role == "admin":
        return target
    if target.role == "student" and _is_curator_of(user, target.group_name or ""):
        return target
    raise HTTPException(status_code=403, detail="Нет доступа к этому пользователю")


@router.get("/web/accounts/extra")
def account_extra(login: str = Query(...), request: Request = None,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """«Доп. данные» в редакторе пользователя: сверка контактов и стартовый пароль.

    Куратору — только стартовый пароль: контакты студента ему для раздачи бумаги не
    нужны, а лишний показ ПДн — лишний повод для разговора при проверке 152-ФЗ."""
    target = _scope_student(db, user, login)
    cred = issued_credentials.state(db, target)
    db.commit()                               #state мог стереть устаревший шифротекст
    out = {"login": target.login, "credential": cred}
    if user.role == "admin":
        out["contacts"] = login_guard.contact_view(db, target, for_admin=True)
    if cred.get("state") == issued_credentials.STATE_ISSUED:
        #Просмотр стартового пароля — действие с доступом к учётке, след обязателен. Сам
        #пароль в журнал не пишем: журнал читают и те, кому пароль знать незачем.
        audit.log(db, request, actor=user.login, role=user.role,
                  action="credentials.view", target=target.login,
                  detail="просмотр стартового пароля")
    return out


@router.post("/web/accounts/extra")
def save_account_extra(body: dict = Body(...), request: Request = None,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Запись колледжа о контактах человека — ТОЛЬКО администратор."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    target = _scope_student(db, user, str(body.get("login") or ""))
    login_guard.set_admin_contacts(db, target, str(body.get("admin_email") or ""),
                                   str(body.get("admin_phone") or ""))
    db.commit()
    audit.log(db, request, actor=user.login, role=user.role, action="contact.admin_set",
              target=target.login, detail="запись колледжа о контактах обновлена")
    return {"ok": True, "contacts": login_guard.contact_view(db, target, for_admin=True)}


@router.post("/web/accounts/credential/reset")
def reset_credential(body: dict = Body(...), request: Request = None,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """«Сбросить» — новый стартовый пароль, снова видимый администратору и куратору.

    ⚠️ Все сессии и доверенные устройства человека закрываются: сброс делают, когда
    пароль потерян или, хуже, узнан посторонним, и старые сессии живут на том самом
    пароле, который сбросили."""
    target = _scope_student(db, user, str(body.get("login") or ""))
    had_password = bool(target.password_hash)
    with throttle.hash_slot() as got:
        if not got:
            raise HTTPException(status_code=503,
                                detail="Сервер сейчас занят. Повторите через несколько секунд.",
                                headers={"Retry-After": str(int(throttle.HASH_WAIT_S) or 1)})
        plain = issued_credentials.reset(db, target, by=user.login)
    target.updated_at = _now()
    db.query(AuthSession).filter(AuthSession.login == target.login).update({"revoked": True})
    login_guard.revoke_all_devices(db, target.login)
    db.commit()
    _kick(target.id)
    audit.log(db, request, actor=user.login, role=user.role, action="credentials.reset",
              target=target.login, detail="выдан новый стартовый пароль")
    if had_password:
        _after_password_change(db, target, by_admin=True)
    return {"ok": True, "credential": issued_credentials.state(db, target), "password": plain}


# ── «Выкатить данные групп» ──────────────────────────────────────────────────────────

#Подразделы, как их видит администратор. Заочное — ОДИН подраздел: на портале это две
#категории (zo1/zo2, разные каталоги расписания), но для раздачи паролей это одна и та же
#форма обучения, и делить её на «Заочное 1/2» значило бы заставлять искать группу дважды.
#⚠️ Категория NULL у старых групп трактуется как колледж — так же, как везде по коду
#(см. models.Group.category).
SECTION_OF_CATEGORY = {"college": "college", "bakalavriat": "bakalavriat",
                       "zo1": "zo", "zo2": "zo"}
SECTION_LABELS = {"college": "Колледж", "bakalavriat": "Бакалавриат", "zo": "Заочное"}


def _section(category) -> str:
    cat = (category or "college").strip() or "college"
    return SECTION_OF_CATEGORY.get(cat, cat)


@router.get("/web/accounts/rollout/groups")
def rollout_groups(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Группы для выдачи данных: администратору — все, куратору — только свои."""
    if user.role == "admin":
        #Архивные (выпустившиеся) не предлагаем. NULL у старых строк — «не в архиве»:
        #`archived != True` в SQL их бы молча выбросил (NULL ни с чем не сравнивается).
        rows = db.query(Group).filter(
            Group.deleted == False,                                            # noqa: E712
            or_(Group.archived == False, Group.archived.is_(None))).all()      # noqa: E712
    elif user.role == "teacher" and (user.curated_groups or []):
        names = list(user.curated_groups or [])
        rows = db.query(Group).filter(Group.name.in_(names),
                                      Group.deleted == False).all()        # noqa: E712
        #Курируемая группа могла ещё не завестись строкой в `groups` (есть только у
        #студентов в `group_name`) — показываем её всё равно, иначе куратор не увидит
        #собственную группу и решит, что кнопка сломана.
        known = {r.name for r in rows}
        rows = list(rows) + [Group(id=f"grp:{n}", name=n, category=None)
                             for n in names if n not in known]
    else:
        raise HTTPException(status_code=403,
                            detail="Доступно администратору и кураторам групп")
    #Число студентов — ОДНИМ запросом на все группы, а не по запросу на каждую: групп на
    #бою под три сотни.
    counts = dict(db.query(User.group_name, func.count(User.id))
                  .filter(User.role == "student", User.deleted == False)          # noqa: E712
                  .group_by(User.group_name).all())
    cfg = W.load_config(db)
    out = []
    for g in rows:
        if not g.name:
            continue
        out.append({"name": g.name, "section": _section(g.category),
                    "course": W.group_course(db, g.name, cfg),
                    "students": int(counts.get(g.name, 0) or 0)})
    out.sort(key=lambda x: (x["section"], x["course"] or 99, x["name"]))
    used = {x["section"] for x in out}
    sections = [{"key": k, "label": SECTION_LABELS.get(k, k)}
                for k in ("college", "bakalavriat", "zo") if k in used]
    sections += [{"key": k, "label": SECTION_LABELS.get(k, k)}
                 for k in sorted(used) if k not in SECTION_LABELS]
    return {"sections": sections, "groups": out}


@router.get("/web/accounts/rollout/students")
def rollout_students(group: str = Query(...), user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Студенты группы для галочек. Сам пароль здесь НЕ отдаётся — только состояние."""
    _scope_group(user, group)
    out = []
    for s in W.students_in_group(db, group):
        st = issued_credentials.state(db, s)
        state = st["state"]
        if state == issued_credentials.STATE_NONE and s.password_hash:
            state = "preset"            #пароль задан до 4.0 — выгрузка его не тронет
        out.append({"id": s.id, "login": s.login or "", "name": W.display_name(s),
                    "state": state})
    db.commit()
    return {"group": group, "students": out}


_ROLLOUT_NOTES = {
    "changed": "сменил пароль сам — сбросьте в редакторе",
    "preset": "пароль задан ранее — не менялся",
}


@router.post("/web/accounts/rollout/export")
def rollout_export(body: dict = Body(...), request: Request = None,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Документ .xlsx «№ · ФИО · логин · пароль» для группы.

    ⚠️ Состав берём у СЕРВЕРА (студенты группы), а из тела — только какие из них
    отмечены: id не из этой группы молча отбрасываются. Иначе куратор, подставив чужой
    id, получил бы пароль студента чужой группы.
    ⚠️ В журнал аудита — факт выдачи и числа, без единого пароля."""
    group = str(body.get("group") or "").strip()
    _scope_group(user, group)
    wanted = {str(x) for x in (body.get("student_ids") or [])}
    reset_existing = bool(body.get("reset_existing")) and user.role == "admin"
    rows, fresh = [], 0
    with throttle.hash_slot(wait=60) as got:
        #Выдача новых паролей считает хеш на каждого — это десятки хешей подряд, и
        #занять ими оба слота значило бы запереть вход всему колледжу. Один слот на всю
        #выгрузку: вход других людей в это время идёт через второй.
        if not got:
            raise HTTPException(status_code=503,
                                detail="Сервер сейчас занят. Повторите через несколько секунд.")
        for s in W.students_in_group(db, group):
            if s.id not in wanted:
                continue
            password, mark = issued_credentials.for_rollout(db, s, by=user.login,
                                                            reset_existing=reset_existing)
            if mark == "new":
                fresh += 1
                s.updated_at = _now()
            rows.append({"n": len(rows) + 1, "name": W.display_name(s),
                         "login": s.login or "", "password": password,
                         "note": _ROLLOUT_NOTES.get(mark, "")})
    db.commit()
    if not rows:
        raise HTTPException(status_code=400, detail="Не отмечено ни одного студента группы")
    audit.log(db, request, actor=user.login, role=user.role, action="credentials.rollout",
              target=group, detail=f"строк в документе: {len(rows)}, выдано новых: {fresh}")
    from .. import xlsx_export
    data = xlsx_export.build_credentials_xlsx(group, rows)
    from urllib.parse import quote
    fname = f"Данные_входа_{group}.xlsx".replace(" ", "_").replace("/", "-")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f"attachment; filename=export.xlsx; filename*=UTF-8''{quote(fname)}",
                 "Cache-Control": "no-store"})
