"""
me.py — Личные настройки текущего пользователя (self-scope).

Зачем отдельный эндпоинт, а не общий /sync/push: обобщённый push ограничен по роли
(PUSH_SCOPE — ученик не пушит ничего, преподаватель только оценки/занятия). Чтобы
персональная тема оформления «роумилась» через БД, пользователю нужно уметь менять
СВОЮ строку — но строго свою и только поле prefs (пароль/роль/чужие записи не
трогаются). Это и делает POST /me/prefs: личность берётся из JWT (get_current_user),
поэтому подменить чужой профиль нельзя. Права ролей при этом не ослабляем.

Метку updated_at ставит сервер — как и в /sync/push, чтобы LWW не зависел от часов
клиента, и обновлённый prefs уехал другим устройствам этого же пользователя на pull.
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import rustore_push
from ..db import get_db
from ..deps import get_current_user
from ..models import NotifyEvent, PushToken, User

router = APIRouter(prefix="/me", tags=["me"])

#Личные настройки — это тема оформления и мелкие флаги. Ограничиваем размер, чтобы
#авторизованный пользователь не «раздул» свою строку произвольным JSON (защита БД).
_MAX_PREFS_BYTES = 16 * 1024

#ПУБЛИЧНЫЕ поля профиля (их видят другие пользователи в карточке — см. messenger._safe_user),
#поэтому режем их на СЕРВЕРЕ, а не только в UI: клиента можно обойти запросом напрямую.
_MAX_BIO_CHARS = 400        #«О себе» — тот же лимит показывает счётчик в интерфейсе
_MAX_COLOR_ID = 32          #id пресета палитры ('violet', 'teal', …)


def _sanitize_public_profile(prefs: dict) -> None:
    """Обрезает публичные поля профиля на месте.

    Список цветов НЕ дублируем на сервере: он живёт в палитре клиента
    (web/src/theme/palette.js и ui/themes.py). Здесь ограничиваем только длину, а
    неизвестный id клиент сам отобразит стандартным акцентом — так нет второго
    источника правды, который мог бы разъехаться с первым."""
    if "bio" in prefs:
        bio = prefs.get("bio")
        prefs["bio"] = (bio if isinstance(bio, str) else "").strip()[:_MAX_BIO_CHARS]
    if "profile_color" in prefs:
        col = prefs.get("profile_color")
        prefs["profile_color"] = (col if isinstance(col, str) else "").strip()[:_MAX_COLOR_ID]


def _sanitize_notify(prefs: dict) -> None:
    """Приводит `prefs.notify` к строгому виду: только известные категории, только «да/нет».

    Сюда приходит произвольный JSON от авторизованного клиента, а читает его СЕРВЕР при
    каждой отправке пуша (`rustore_push.category_enabled`). Мусор в этом поле — это не
    «некрасиво», а неверное решение о доставке: строка "false" истинна в Python, и
    выключенная в интерфейсе категория продолжала бы приходить.

    Незнакомые ключи выбрасываем: список категорий задаёт СЕРВЕР, иначе клиент мог бы
    насорить в поле, которое сам же не читает."""
    if "notify" not in prefs:
        return
    box = prefs.get("notify")
    if not isinstance(box, dict):
        prefs.pop("notify", None)
        return
    prefs["notify"] = {k: bool(v) for k, v in box.items()
                       if k in rustore_push.ALL_CATEGORIES}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/prefs")
def get_prefs(user: User = Depends(get_current_user)):
    """Текущие личные настройки вошедшего пользователя."""
    return {"prefs": user.prefs or {}}


@router.post("/prefs")
def set_prefs(payload: dict = Body(...), user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Сливает переданные ключи в prefs ТЕКУЩЕГО пользователя (только своя строка).

    Принимаем либо {"prefs": {...}}, либо сразу плоский словарь — обе формы удобны
    клиенту. Существующие ключи prefs сохраняются, новые перекрывают одноимённые."""
    incoming = payload.get("prefs") if isinstance(payload.get("prefs"), dict) else payload
    if not isinstance(incoming, dict):
        incoming = {}
    merged = dict(user.prefs or {})
    merged.update(incoming)
    _sanitize_public_profile(merged)     #«О себе» и цвет плашки видны другим — режем здесь
    _sanitize_notify(merged)             #категории уведомлений читает сервер — приводим к «да/нет»
    #Лимит на размер настроек: не даём авторизованному пользователю раздувать БД.
    try:
        size = len(json.dumps(merged, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректные настройки") from None
    if size > _MAX_PREFS_BYTES:
        raise HTTPException(status_code=413, detail="Слишком большой объём настроек")
    user.prefs = merged
    #JSON-столбец меняем «по месту» — подсказываем ORM, что поле грязное, иначе
    #переприсваивание того же объекта может не попасть в UPDATE.
    flag_modified(user, "prefs")
    user.updated_at = _now()
    db.commit()
    return {"ok": True, "prefs": merged, "updated_at": user.updated_at}


#Пуш-уведомления (RuStore Push)
#Токен привязан к КОНКРЕТНОМУ телефону, поэтому живёт в отдельной таблице и НЕ входит
#в синхронизацию: на другие устройства пользователя ему ехать незачем.

@router.post("/push-token")
def register_push_token(payload: dict = Body(...),
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Приложение сообщает свой токен устройства (при запуске и при его обновлении).

    Вызывается КАЖДЫЙ запуск, а не только при первом получении токена: так поле
    last_seen остаётся свежим, и уборка не выбросит живое устройство. RuStore умеет
    менять токен молча — поэтому запись ключуется самим токеном, а не пользователем."""
    token = (payload.get("token") or "").strip()
    if not token or len(token) > 1024:
        raise HTTPException(status_code=400, detail="Нужен непустой token")
    platform = (payload.get("platform") or "android").strip()[:32]
    now = datetime.now(timezone.utc).isoformat()

    row = db.get(PushToken, token)
    if row is None:
        row = PushToken(token=token, created_at=now)
        db.add(row)
    #Логин перезаписываем ВСЕГДА: на одном телефоне мог войти другой пользователь, и
    #слать ему чужие уведомления недопустимо.
    row.login = user.login or ""
    row.platform = platform
    row.last_seen = now
    row.fail_count = 0
    db.commit()
    return {"ok": True}


@router.delete("/push-token")
def delete_push_token(payload: dict = Body(default={}),
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Отписка при выходе из аккаунта. Без неё следующий владелец телефона (или тот же
    человек под другим логином) продолжал бы получать чужие уведомления."""
    token = (payload.get("token") or "").strip()
    q = db.query(PushToken).filter(PushToken.login == (user.login or ""))
    if token:
        q = q.filter(PushToken.token == token)
    removed = q.delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "removed": removed}


#Вкладка «Уведомления» — список писем, чтение, отметки о прочтении.
#
#⚠️ ПОРЯДОК ОБЪЯВЛЕНИЯ МАРШРУТОВ ЗДЕСЬ ЗНАЧИМ. Статический "/events/unread-count" обязан
#идти РАНЬШЕ шаблонного "/events/{event_id}": FastAPI сопоставляет маршруты сверху вниз,
#и при обратном порядке запрос за счётчиком попал бы в обработчик события с
#event_id="unread-count" и вернул 404 вместо числа.

@router.get("/events/unread-count")
def unread_events_count(user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Только число непрочитанных — для значка в интерфейсе.

    Отдельный дешёвый COUNT: ради цифры в углу экрана незачем выгружать список событий
    при каждом открытии страницы."""
    n = (db.query(NotifyEvent)
         .filter(NotifyEvent.login == (user.login or ""), NotifyEvent.read_at == "")
         .count())
    return {"unread": n}


@router.post("/events/read-all")
def mark_all_events_read(user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """«Прочитать все». Фильтр по login обязателен: без него UPDATE прошёлся бы по
    чужим строкам."""
    now = datetime.now(timezone.utc).isoformat()
    n = (db.query(NotifyEvent)
         .filter(NotifyEvent.login == (user.login or ""), NotifyEvent.read_at == "")
         .update({NotifyEvent.read_at: now}, synchronize_session=False))
    db.commit()
    return {"ok": True, "updated": n}


@router.post("/events/{event_id}/read")
def mark_event_read(event_id: str,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Отметить одно событие прочитанным (клик по письму в списке).

    Чужое событие — 404, а не 403, по той же причине, что и в get_notify_event: 403
    подтвердил бы факт существования события."""
    row = db.get(NotifyEvent, event_id)
    if row is None or row.login != (user.login or ""):
        raise HTTPException(status_code=404, detail="Событие не найдено")
    if not row.read_at:
        row.read_at = datetime.now(timezone.utc).isoformat()
        db.commit()
    return {"ok": True, "read_at": row.read_at}


@router.get("/events/{event_id}")
def get_notify_event(event_id: str,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Куда открыть экран по нажатому уведомлению + текст письма.

    Проверка владельца обязательна: id события уезжает в пуш и оседает на телефоне,
    поэтому его нельзя считать секретом. На чужой id отвечаем 404, а НЕ 403 — 403
    подтвердил бы, что такое событие существует, и превратил бы перебор id в способ
    узнать чужую активность."""
    row = db.get(NotifyEvent, event_id)
    if row is None or row.login != (user.login or ""):
        raise HTTPException(status_code=404, detail="Событие не найдено")
    if not row.read_at:
        row.read_at = datetime.now(timezone.utc).isoformat()
        db.commit()
    #Поля title/body/payload добавлены позже: у событий, накопленных до этого, они
    #пустые — клиент в таком случае показывает текст по kind, как делал раньше.
    return {"id": row.id, "kind": row.kind, "subject": row.subject,
            "lesson_id": row.lesson_id, "created_at": row.created_at,
            "title": row.title or "", "body": row.body or "",
            "payload": row.payload or {}, "read_at": row.read_at or ""}


def _fire_due_reminders(db: Session, user: User) -> int:
    """Превратить наступившие напоминания в обычные события. Возвращает их число.

    Полностью в try/except: напоминания — вспомогательная фича, и её сбой не имеет права
    лишить человека уведомлений об оценках, ради которых он сюда и пришёл."""
    try:
        from datetime import datetime, timezone
        from ..models import Reminder
        now = datetime.now(timezone.utc).isoformat()
        due = (db.query(Reminder)
               .filter(Reminder.login == (user.login or ""),
                       Reminder.fired_at == "",
                       Reminder.remind_at <= now)
               .all())
        if not due:
            return 0
        from .. import rustore_push
        for r in due:
            #Пуш шлём тем же путём, что и остальные события: человек мог поставить
            #напоминание неделю назад и приложение с тех пор не открывать.
            rustore_push.notify_reminder(db, user.login, r.text, r.conversation_id)
            r.fired_at = now
        db.commit()
        return len(due)
    except Exception as e:      # noqa: BLE001
        print(f"[reminders] не удалось обработать напоминания: {e}")
        return 0


@router.get("/events")
def list_events(filter_: str = Query("unread", alias="filter"),
                limit: int = Query(50, ge=1, le=100),
                offset: int = Query(0, ge=0),
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Список событий пользователя.

    ⚠️ ПО УМОЛЧАНИЮ отдаёт ТОЛЬКО НЕПРОЧИТАННЫЕ — поведение менять нельзя. Этот
    эндпоинт уже вызывают установленные Android-приложения (см. web/src/services/push.js
    и нативную часть), а у пользователей на телефонах старый бандл. Полный список для
    вкладки «Уведомления» запрашивается явно: ?filter=all."""
    #Напоминания (§D19) срабатывают ЗДЕСЬ, а не по расписанию: планировщик ради одной
    #фичи означал бы вечный фоновый поток на одноядерном VPS. Проверка — один запрос по
    #индексу (login + remind_at), и делать её логично ровно там, где человек всё равно
    #пришёл за уведомлениями.
    _fire_due_reminders(db, user)
    q = db.query(NotifyEvent).filter(NotifyEvent.login == (user.login or ""))
    if filter_ != "all":
        q = q.filter(NotifyEvent.read_at == "")
    rows = (q.order_by(NotifyEvent.created_at.desc())
            .offset(offset).limit(limit).all())
    #Непрочитанные считаем отдельно: при filter=all длина списка о них ничего не говорит,
    #а значку нужно честное число.
    unread = (db.query(NotifyEvent)
              .filter(NotifyEvent.login == (user.login or ""), NotifyEvent.read_at == "")
              .count())
    return {"count": len(rows), "unread": unread,
            "items": [{"id": r.id, "kind": r.kind, "subject": r.subject,
                       "created_at": r.created_at,
                       "title": r.title or "", "body": r.body or "",
                       "read_at": r.read_at or ""} for r in rows]}
