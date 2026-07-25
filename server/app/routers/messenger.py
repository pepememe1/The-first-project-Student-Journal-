"""
messenger.py — встроенный мессенджер (Фаза 1: ядро личных чатов).

Отдельная ОНЛАЙН-подсистема (см. docs/MESSENGER-PLAN.md): сообщения хранятся на сервере,
истина всегда на сервере, конфликтов LWW нет — поэтому НЕ через sync-движок и НЕ в
SYNC_MODELS. Метку времени сообщения ставит СЕРВЕР (как в /sync/push), чтобы порядок не
зависел от часов клиента. Доступ к беседе — только участникам (роль проверяется всегда).

Фаза 1 (это): личные чаты (direct) — открыть/список/история/новые/отправка/прочтение.
Дальше по плану: действия над сообщением (ответ/закреп/пересылка/удаление/жалоба), группы,
каналы, WebSocket+presence, пуши. Транспорт Фазы 1 — обычный HTTP (клиент опрашивает
?after=<id>); WebSocket добавим отдельной фазой.
"""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import (
    APIRouter, Body, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect,
)
from sqlalchemy.orm import Session

from .. import audit, events, msg_limit
from ..db import get_db, SessionLocal
from ..deps import get_current_user, require_admin
from ..security import decode_token
from ..models import (
    Conversation, ConversationParticipant, Message, MessageHidden, MessageReport,
    MutedUser, User, direct_conversation_id,
)

router = APIRouter(prefix="/web/messenger", tags=["messenger"])
#Модерация — ТОЛЬКО админ (require_admin), отдельный префикс. Каждый просмотр чужой
#переписки пишется в аудит (152-ФЗ, подотчётность — см. MESSENGER-PLAN.md §3, §10).
mod_router = APIRouter(prefix="/web/admin/messenger", tags=["messenger-moderation"])


# ── WebSocket: живые события (Фаза 7) ────────────────────────────────────────────────
# Транспорт-энхансер поверх опроса: сервер шлёт участникам ЛЁГКИЙ сигнал «в беседе что-то
# изменилось», клиент по нему сразу подтягивает свежее (не парсит каждое событие — так
# надёжнее и опрос остаётся страховкой). Реестр соединений — в памяти процесса (1 воркер;
# при масштабировании на процессы понадобится общий брокер, напр. Redis pub/sub — §5 плана).
class _WSManager:
    def __init__(self):
        self._by_user: dict[str, set] = {}
        self._loop = None

    def bind_loop(self):
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    async def connect(self, uid: str, ws: WebSocket, subprotocol: str = None):
        #Если клиент авторизовался через Sec-WebSocket-Protocol, браузер требует, чтобы
        #сервер ЭХОМ вернул один из предложенных сабпротоколов — иначе рукопожатие рвётся.
        await ws.accept(subprotocol=subprotocol)
        self._by_user.setdefault(uid, set()).add(ws)

    def disconnect(self, uid: str, ws: WebSocket):
        s = self._by_user.get(uid)
        if s:
            s.discard(ws)
            if not s:
                self._by_user.pop(uid, None)

    async def send_users(self, uids, data: dict):
        for uid in uids:
            for ws in list(self._by_user.get(uid, ())):
                try:
                    await ws.send_json(data)
                except Exception:
                    pass

    def emit_users(self, uids, data: dict):
        """Вызывается из СИНХРОННЫХ REST-обработчиков (пул потоков) — планируем корутину в
        цикл событий приложения. Нет цикла (никто не подключён по WS) → просто ничего."""
        loop = self._loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.send_users(list(uids), data), loop)
        except Exception:
            pass


ws_manager = _WSManager()


def _participant_ids(db: Session, conv_id: str) -> list:
    return [p.user_id for p in db.query(ConversationParticipant)
            .filter(ConversationParticipant.conversation_id == conv_id).all()]


def _broadcast(db: Session, conv_id: str, kind: str = "changed"):
    """Лёгкий сигнал участникам беседы: «подтяни свежее». Никогда не роняет запрос."""
    try:
        ws_manager.emit_users(_participant_ids(db, conv_id),
                              {"type": kind, "conversation_id": conv_id})
    except Exception:
        pass


def _notify_recipients(db: Session, conv: Conversation, sender: User):
    """Пуш о новом сообщении получателям, которых НЕТ в приложении (по presence). Через
    RuStore Push, как уведомления об оценке. Контент НЕ уходит третьей стороне (§12 плана):
    заголовок — имя отправителя/название беседы, тело — нейтральное «Новое сообщение».
    Best-effort: сбой доставки не влияет на отправку сообщения."""
    try:
        from .. import rustore_push
        online = _online_logins()
        ids = [i for i in _participant_ids(db, conv.id) if i != sender.id]
        if not ids:
            return
        #Получатели, замьютившие ЭТУ беседу, пушей не получают (их выбор — тишина).
        muted_here = {p.user_id for p in db.query(ConversationParticipant)
                      .filter(ConversationParticipant.conversation_id == conv.id,
                              ConversationParticipant.muted == True).all()}  # noqa: E712
        ids = [i for i in ids if i not in muted_here]
        if not ids:
            return
        recips = db.query(User).filter(User.id.in_(ids)).all()
        sender_name = sender.full_name or sender.name or sender.login or "Сообщение"
        title = (conv.title if conv.kind in ("group", "channel") and conv.title else sender_name)
        body = f"{sender_name}: новое сообщение" if conv.kind in ("group", "channel") else "Новое сообщение"
        for u in recips:
            if u.login in online:
                continue                     #активному в приложении пуш не нужен
            rustore_push.notify_login(db, u.login, title, body,
                                      {"type": "message", "conversation_id": conv.id})
    except Exception:
        pass

_MAX_MSG_CHARS = 4000          #лимит длины сообщения (защита БД от «простыней»/спама)
_DEFAULT_PAGE = 50            #сколько сообщений отдаём за один запрос истории
_MAX_PAGE = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Хелперы ──────────────────────────────────────────────────────────────────────────
def _online_logins() -> set:
    """Логины, активные прямо сейчас (по in-memory presence, окно ~90 c). Клиенты
    мессенджера опрашивают сервер каждые несколько секунд → get_current_user отмечает их
    активными, поэтому этот сигнал отражает «кто сейчас в приложении»."""
    try:
        return {r["login"] for r in events.online()}
    except Exception:
        return set()


def _safe_user(u: User, online_logins: set = None, muted: bool = False) -> dict:
    """Безопасные поля пользователя для карточки/каталога (НИЧЕГО, что помогает входу в
    чужой аккаунт — см. MESSENGER-PLAN.md §9: без логина, почты, телефона, хэша, device-id).
    У студента — группа; у преподавателя — предметы, которые ведёт. online — по presence.
    `muted` (глобальный мьют модерацией) заполняем ТОЛЬКО в админ-контексте — рядовым
    пользователям состояние мьюта чужого аккаунта в каталоге ни к чему."""
    prefs = u.prefs if isinstance(u.prefs, dict) else {}
    d = {
        "id": u.id,
        "full_name": u.full_name or u.name or u.login or "",
        "role": u.role,
        "group_name": u.group_name or "",
        "online": bool(online_logins) and (u.login in online_logins),
        #Аватарка (обрезанная 256×256 data:URL из prefs) — её видят ВСЕ (карточка, список,
        #модерация). Это публичное «лицо» аккаунта, не чувствительное поле.
        "avatar": prefs.get("avatar", "") or "",
        #Публичная часть профиля, которую человек настраивает сам (см. routers/me.py):
        #«О себе» и цвет плашки (id пресета палитры — клиент сопоставит его с цветом).
        "bio": prefs.get("bio", "") or "",
        "profile_color": prefs.get("profile_color", "") or "",
        "muted": bool(muted),
    }
    if u.role == "teacher":
        d["subjects"] = u.subjects or []
    return d


def _is_muted(db: Session, user_id: str) -> bool:
    """Замьючен ли пользователь глобально (модерацией). Один индексный поиск по PK."""
    return db.query(MutedUser).filter(MutedUser.user_id == user_id).first() is not None


def _muted_set(db: Session, user_ids) -> set:
    """Множество замьюченных из набора id — чтобы не бить БД по одному в списках модерации."""
    ids = {i for i in user_ids if i}
    if not ids:
        return set()
    rows = db.query(MutedUser.user_id).filter(MutedUser.user_id.in_(ids)).all()
    return {r[0] for r in rows}


def _guard_can_write(db: Session, user: User) -> None:
    """Единый барьер записи в мессенджер: глобальный мьют модерацией (403) + анти-флуд (429).
    Зовётся из всех точек, создающих сообщения (отправка, пересылка). Порядок: сперва мьют
    (жёсткий запрет), потом частота."""
    if _is_muted(db, user.id):
        raise HTTPException(
            status_code=403,
            detail="Вы ограничены модерацией и временно не можете отправлять сообщения.")
    wait = msg_limit.check(user.id)
    if wait:
        raise HTTPException(
            status_code=429,
            detail="Не отправляйте сообщения так часто. Подождите немного.",
            headers={"Retry-After": str(wait)})


#Создавать группы и каналы могут ТОЛЬКО преподаватели (и админ как суперпользователь).
#Требование заказчика: студенты не заводят каналы/группы, чтобы не спамить и не собирать
#людей без ведома. Личные чаты студентам по-прежнему доступны (open_direct не ограничен).
_CREATOR_ROLES = ("teacher", "admin")


def _guard_can_create(db: Session, user: User) -> None:
    if user.role not in _CREATOR_ROLES:
        raise HTTPException(
            status_code=403, detail="Группы и каналы могут создавать только преподаватели.")
    if _is_muted(db, user.id):
        raise HTTPException(
            status_code=403, detail="Вы ограничены модерацией и не можете создавать беседы.")


def _participant(db: Session, conv_id: str, user_id: str):
    """Участие пользователя в беседе (или None). Это же — проверка доступа к беседе."""
    return (db.query(ConversationParticipant)
            .filter(ConversationParticipant.conversation_id == conv_id,
                    ConversationParticipant.user_id == user_id)
            .first())


def _require_participant(db: Session, conv_id: str, user: User) -> ConversationParticipant:
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Беседа не найдена")
    p = _participant(db, conv_id, user.id)
    if p is None:
        raise HTTPException(status_code=403, detail="Нет доступа к этой беседе")
    return p


def _hidden_ids(db: Session, conv_id: str, user_id: str) -> set:
    """id сообщений этой беседы, скрытых у пользователя («удалить у себя»)."""
    rows = (db.query(MessageHidden.message_id)
            .join(Message, Message.id == MessageHidden.message_id)
            .filter(Message.conversation_id == conv_id, MessageHidden.user_id == user_id)
            .all())
    return {r[0] for r in rows}


def _names_for(db: Session, sender_ids) -> dict:
    """Карта id→ФИО для набора отправителей (в группах/каналах показываем автора)."""
    ids = {s for s in sender_ids if s}
    if not ids:
        return {}
    rows = db.query(User).filter(User.id.in_(ids)).all()
    return {u.id: (u.full_name or u.name or u.login or u.id) for u in rows}


def _msg_out(m: Message, me_id: str = "", sender_name: str = "") -> dict:
    """Сериализация сообщения для клиента. Удалённое-у-всех отдаём тумбстоуном (без текста).
    `mine` вычисляет сервер (клиент своего id не знает — в JWT/сторе только логин+роль).
    `sender_name` нужен в группах/каналах (в личном чате имя не показываем)."""
    deleted = bool(m.deleted_at)
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "sender_id": m.sender_id,
        "sender_name": sender_name,
        "mine": bool(me_id) and m.sender_id == me_id,
        "body": "" if deleted else (m.body or ""),
        "created_at": m.created_at,
        "edited_at": "" if deleted else (m.edited_at or ""),
        "deleted": deleted,
        "reply_to_id": m.reply_to_id or None,
        "pinned": bool(m.pinned) and not deleted,
        #Шапка «Переслано от …» (снимок имени источника):
        "forwarded_from": (m.fwd_sender_name or "") if (m.fwd_from_sender_id and not deleted) else None,
    }


def _peer_of_direct(db: Session, conv_id: str, me_id: str):
    """Второй участник личного чата (для заголовка/карточки). None, если не найден."""
    other = (db.query(ConversationParticipant)
             .filter(ConversationParticipant.conversation_id == conv_id,
                     ConversationParticipant.user_id != me_id)
             .first())
    if other is None:
        return None
    return db.query(User).filter(User.id == other.user_id).first()


# ── Каталог пользователей и поиск по ФИО ─────────────────────────────────────────────
_PAGE_USERS = 30


@router.get("/users")
def directory(role: str = Query("student"), q: str = Query(""), page: int = Query(0),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Каталог/поиск для выбора собеседника. Вкладки — по роли (student|teacher), поиск по
    ФИО, сортировка по алфавиту, постранично. Отдаём ТОЛЬКО безопасные поля (§9).

    Поиск и сортировку делаем в Python (не SQL ilike): SQLite без ICU не умеет
    регистронезависимый LIKE для кириллицы, а датасет колледжа умещается в память.
    На PostgreSQL позже можно перейти на ILIKE + индекс. Себя из списка исключаем."""
    role = role if role in ("student", "teacher") else "student"
    rows = (db.query(User)
            .filter(User.role == role, User.deleted == False, User.id != user.id).all())  # noqa: E712
    ql = (q or "").strip().lower()
    if ql:
        rows = [u for u in rows if ql in (u.full_name or u.name or "").lower()]
    rows.sort(key=lambda u: (u.full_name or u.name or u.login or "").lower())
    total = len(rows)
    page = max(0, int(page or 0))
    chunk = rows[page * _PAGE_USERS:(page + 1) * _PAGE_USERS]
    onl = _online_logins()
    return {"users": [_safe_user(u, onl) for u in chunk],
            "total": total, "page": page, "page_size": _PAGE_USERS}


@router.get("/users/{user_id}/profile")
def user_profile(user_id: str, _user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Публичная карточка (портфолио) — только безопасные поля."""
    u = db.query(User).filter(User.id == user_id, User.deleted == False).first()  # noqa: E712
    if u is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return {"profile": _safe_user(u, _online_logins())}


# ── Открыть/создать личный чат ───────────────────────────────────────────────────────
@router.post("/chats/direct/{user_id}")
def open_direct(user_id: str, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Открыть личный чат с пользователем (создать, если ещё нет). Идемпотентно — беседа
    ключуется детерминированным id пары, повторный вызов вернёт ту же."""
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Нельзя написать самому себе")
    peer = db.query(User).filter(User.id == user_id, User.deleted == False).first()  # noqa: E712
    if peer is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    conv_id = direct_conversation_id(user.id, peer.id)
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if conv is None:
        now = _now()
        conv = Conversation(id=conv_id, kind="direct", created_at=now)
        db.add(conv)
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=user.id,
                                       role="member", joined_at=now))
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=peer.id,
                                       role="member", joined_at=now))
        db.commit()
    return {"conversation_id": conv_id, "kind": "direct", "peer": _safe_user(peer, _online_logins())}


# ── Список бесед ─────────────────────────────────────────────────────────────────────
@router.get("/chats")
def list_chats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Беседы текущего пользователя: собеседник/заголовок, последнее сообщение, непрочитанные.
    Закреплённые чаты — сверху, дальше по времени последнего сообщения (убыв.)."""
    parts = (db.query(ConversationParticipant)
             .filter(ConversationParticipant.user_id == user.id).all())
    onl = _online_logins()
    out = []
    for p in parts:
        conv = db.query(Conversation).filter(Conversation.id == p.conversation_id).first()
        if conv is None:
            continue
        #Всё, что старше моей метки очистки, для меня не существует (удалённая переписка).
        lastq = db.query(Message).filter(Message.conversation_id == conv.id)
        if p.cleared_at:
            lastq = lastq.filter(Message.created_at > p.cleared_at)
        last = lastq.order_by(Message.id.desc()).first()
        #Чат удалён у меня и с тех пор ничего не приходило — не показываем его в списке.
        #Появится новое сообщение — вернётся сам (см. _unhide_participants).
        if p.hidden and last is None:
            continue
        #Непрочитанное: чужие сообщения позже моей метки прочтения, не удалённые у всех.
        unread = (db.query(Message)
                  .filter(Message.conversation_id == conv.id,
                          Message.sender_id != user.id,
                          Message.deleted_at == "",
                          Message.created_at > (p.last_read_at or ""),
                          Message.created_at > (p.cleared_at or ""))
                  .count())
        item = {
            "conversation_id": conv.id,
            "kind": conv.kind,
            "pinned": bool(p.pinned),
            "muted": bool(p.muted),
            "unread": unread,
            "last_message": _msg_out(last, user.id) if last else None,
            "last_at": (last.created_at if last else conv.created_at) or "",
        }
        if conv.kind == "direct":
            peer = _peer_of_direct(db, conv.id, user.id)
            item["title"] = (peer.full_name or peer.name or peer.login) if peer else "Диалог"
            item["peer"] = _safe_user(peer, onl) if peer else None
        else:
            item["title"] = conv.title or ""
        out.append(item)
    #Сортировка: сначала закреплённые, потом по времени последней активности (новые выше).
    out.sort(key=lambda x: (not x["pinned"], _neg_key(x["last_at"])))
    return {"chats": out}


def _neg_key(iso: str):
    """Ключ сортировки «по убыванию времени» для строковых ISO-меток (позже → выше)."""
    return "" if not iso else "".join(chr(255 - b) for b in iso.encode("utf-8"))


# ── История и новые сообщения ────────────────────────────────────────────────────────
@router.get("/chats/{conv_id}/messages")
def messages(conv_id: str, before: int = Query(0), after: int = Query(0),
             limit: int = Query(_DEFAULT_PAGE),
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Сообщения беседы. `before=<id>` — история вверх (старее указанного), `after=<id>` —
    новые (для опроса). Без параметров — последние `limit`. Скрытые «у себя» не отдаём;
    удалённые у всех — тумбстоуном. Всегда в хронологическом порядке (старые→новые)."""
    part = _require_participant(db, conv_id, user)
    limit = max(1, min(int(limit or _DEFAULT_PAGE), _MAX_PAGE))
    hidden = _hidden_ids(db, conv_id, user.id)

    q = db.query(Message).filter(Message.conversation_id == conv_id)
    if hidden:
        q = q.filter(~Message.id.in_(hidden))
    #«Удалённая у себя» переписка: всё, что было до очистки, пользователю не показываем.
    if part.cleared_at:
        q = q.filter(Message.created_at > part.cleared_at)

    if after:
        rows = q.filter(Message.id > after).order_by(Message.id.asc()).limit(limit).all()
    elif before:
        rows = (q.filter(Message.id < before)
                .order_by(Message.id.desc()).limit(limit).all())
        rows.reverse()                       #отдаём в хронологии
    else:
        rows = q.order_by(Message.id.desc()).limit(limit).all()
        rows.reverse()
    names = _names_for(db, [m.sender_id for m in rows])
    return {"messages": [_msg_out(m, user.id, names.get(m.sender_id, "")) for m in rows]}


# ── Отправка ─────────────────────────────────────────────────────────────────────────
@router.post("/chats/{conv_id}/messages")
def send_message(conv_id: str, payload: dict = Body(...),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Отправить сообщение. Сервер ставит created_at (UTC). reply_to_id — необязательный
    ответ на сообщение этой же беседы. В канал пишут только авторы (writer/admin/owner)."""
    part = _require_participant(db, conv_id, user)
    conv = _conversation(db, conv_id)
    if conv.kind == "channel" and part.role not in _WRITER_ROLES:
        raise HTTPException(status_code=403, detail="В канал могут писать только авторы")
    _guard_can_write(db, user)               #глобальный мьют (403) + анти-флуд (429)
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    if len(body) > _MAX_MSG_CHARS:
        body = body[:_MAX_MSG_CHARS]
    reply_to = int(payload.get("reply_to_id") or 0)
    if reply_to:
        ok = (db.query(Message)
              .filter(Message.id == reply_to, Message.conversation_id == conv_id).first())
        if ok is None:
            reply_to = 0                     #ответ на чужое/несуществующее — игнорируем связь

    m = Message(conversation_id=conv_id, sender_id=user.id, body=body,
                created_at=_now(), reply_to_id=reply_to)
    db.add(m)
    db.commit()
    db.refresh(m)
    #Отправитель прочитал свою же беседу вплоть до этого сообщения.
    _mark_read(db, conv_id, user.id, m.created_at)
    _unhide_participants(db, conv_id)        #«удалённый» чат возвращается с новым сообщением
    _broadcast(db, conv_id)                  #живой сигнал участникам (WS)
    _notify_recipients(db, conv, user)       #пуш офлайн-получателям
    return _msg_out(m, user.id, user.full_name or user.name or user.login or "")


# ── Прочтение ────────────────────────────────────────────────────────────────────────
def _mark_read(db: Session, conv_id: str, user_id: str, upto_iso: str) -> None:
    p = _participant(db, conv_id, user_id)
    if p is not None and upto_iso and upto_iso > (p.last_read_at or ""):
        p.last_read_at = upto_iso
        db.commit()


@router.post("/chats/{conv_id}/read")
def mark_read(conv_id: str, payload: dict = Body(default={}),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Отметить беседу прочитанной до указанного сообщения (или до последнего)."""
    _require_participant(db, conv_id, user)
    upto = ""
    mid = int(payload.get("last_message_id") or 0)
    if mid:
        m = db.query(Message).filter(Message.id == mid,
                                     Message.conversation_id == conv_id).first()
        upto = m.created_at if m else ""
    if not upto:
        last = (db.query(Message).filter(Message.conversation_id == conv_id)
                .order_by(Message.id.desc()).first())
        upto = last.created_at if last else _now()
    _mark_read(db, conv_id, user.id, upto)
    return {"ok": True, "last_read_at": upto}


def _unhide_participants(db: Session, conv_id: str) -> None:
    """Новая активность возвращает беседу тем, кто «удалил» её у себя: снимаем флаг hidden.
    Метку cleared_at НЕ трогаем — старая история для них так и остаётся скрытой."""
    (db.query(ConversationParticipant)
     .filter(ConversationParticipant.conversation_id == conv_id,
             ConversationParticipant.hidden == True)                      # noqa: E712
     .update({"hidden": False}, synchronize_session=False))
    db.commit()


@router.delete("/chats/{conv_id}")
def delete_conversation(conv_id: str, clear_only: bool = Query(False),
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Удалить переписку У СЕБЯ: история до текущего момента больше не показывается, чат
    уходит из списка. У собеседника переписка остаётся — это личное действие, а не
    удаление чужих данных (иначе один человек стирал бы историю другому).

    clear_only=1 — «очистить историю»: сообщения скрываем, но чат остаётся в списке.
    Группу/канал при удалении ещё и покидаем — иначе беседа вернулась бы с первым же
    сообщением, хотя пользователь ушёл из неё осознанно."""
    p = _require_participant(db, conv_id, user)
    conv = _conversation(db, conv_id)
    p.cleared_at = _now()
    p.last_read_at = p.cleared_at          #«хвоста» непрочитанного после очистки нет
    if clear_only:
        db.commit()
        return {"ok": True, "conversation_id": conv_id, "cleared": True}
    if conv.kind in ("group", "channel"):
        db.delete(p)                        #выйти из группы/канала = перестать получать
    else:
        p.hidden = True                     #личный чат/модерация — просто убрать из списка
    db.commit()
    return {"ok": True, "conversation_id": conv_id, "deleted": True}


@router.post("/chats/{conv_id}/mute")
def mute_conversation(conv_id: str, payload: dict = Body(default={}),
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Замьютить/размьютить беседу У СЕБЯ (без пушей по ней; переписка продолжает работать).
    Это личное состояние участника, на других не влияет."""
    p = _require_participant(db, conv_id, user)
    p.muted = bool(payload.get("muted", True))
    db.commit()
    return {"ok": True, "conversation_id": conv_id, "muted": bool(p.muted)}


# ── Действия над сообщением (см. MESSENGER-PLAN.md §6) ────────────────────────────────
_MANAGER_ROLES = ("owner", "admin")
_WRITER_ROLES = ("owner", "admin", "writer")


def _conversation(db: Session, conv_id: str) -> Conversation:
    c = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if c is None:
        raise HTTPException(status_code=404, detail="Беседа не найдена")
    return c


def _message_in_conv(db: Session, mid: int) -> Message:
    m = db.query(Message).filter(Message.id == mid).first()
    if m is None:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    return m


def _can_delete_for_all(part: ConversationParticipant, m: Message, user_id: str) -> bool:
    """Удалить у всех: автор всегда; в группе/канале — ещё owner/admin (модерируют чужое)."""
    return m.sender_id == user_id or part.role in _MANAGER_ROLES


def _can_pin(part: ConversationParticipant, conv: Conversation) -> bool:
    """Закреплять: в личном чате — оба; в группе — owner/admin; в канале — писатели."""
    if conv.kind == "direct":
        return True
    if conv.kind == "channel":
        return part.role in _WRITER_ROLES
    return part.role in _MANAGER_ROLES


@router.patch("/messages/{mid}")
def edit_message(mid: int, payload: dict = Body(...),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Редактировать СВОЁ сообщение (ставит edited_at)."""
    m = _message_in_conv(db, mid)
    _require_participant(db, m.conversation_id, user)
    if m.sender_id != user.id:
        raise HTTPException(status_code=403, detail="Можно править только свои сообщения")
    if m.deleted_at:
        raise HTTPException(status_code=400, detail="Сообщение удалено")
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    m.body = body[:_MAX_MSG_CHARS]
    m.edited_at = _now()
    db.commit()
    db.refresh(m)
    _broadcast(db, m.conversation_id)
    return _msg_out(m, user.id)


@router.delete("/messages/{mid}")
def delete_message(mid: int, scope: str = Query("self"),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Удалить сообщение. scope=self — скрыть у себя (MessageHidden, у других остаётся);
    scope=all — тумбстоун у всех (автор, либо admin/owner в группе/канале)."""
    m = _message_in_conv(db, mid)
    part = _require_participant(db, m.conversation_id, user)
    if scope == "all":
        if not _can_delete_for_all(part, m, user.id):
            raise HTTPException(status_code=403, detail="Нельзя удалить это сообщение у всех")
        if not m.deleted_at:
            m.deleted_at = _now()
            m.pinned = False               #удалённое не остаётся закреплённым
            db.commit()
            _broadcast(db, m.conversation_id)
        return {"ok": True, "scope": "all", "id": mid}
    #scope=self — скрыть только у себя (идемпотентно).
    exists = (db.query(MessageHidden)
              .filter(MessageHidden.message_id == mid, MessageHidden.user_id == user.id).first())
    if exists is None:
        db.add(MessageHidden(message_id=mid, user_id=user.id))
        db.commit()
    return {"ok": True, "scope": "self", "id": mid}


@router.post("/messages/{mid}/pin")
def pin_message(mid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _message_in_conv(db, mid)
    part = _require_participant(db, m.conversation_id, user)
    conv = _conversation(db, m.conversation_id)
    if not _can_pin(part, conv):
        raise HTTPException(status_code=403, detail="Недостаточно прав для закрепления")
    if m.deleted_at:
        raise HTTPException(status_code=400, detail="Сообщение удалено")
    m.pinned = True
    m.pinned_at = _now()
    m.pinned_by = user.id
    db.commit()
    db.refresh(m)
    _broadcast(db, m.conversation_id)
    return _msg_out(m, user.id)


@router.delete("/messages/{mid}/pin")
def unpin_message(mid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    m = _message_in_conv(db, mid)
    part = _require_participant(db, m.conversation_id, user)
    conv = _conversation(db, m.conversation_id)
    if not _can_pin(part, conv):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    m.pinned = False
    db.commit()
    _broadcast(db, m.conversation_id)
    return {"ok": True, "id": mid}


@router.get("/chats/{conv_id}/pinned")
def pinned_messages(conv_id: str, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Закреплённые сообщения беседы (для плашки сверху)."""
    _require_participant(db, conv_id, user)
    hidden = _hidden_ids(db, conv_id, user.id)
    q = (db.query(Message)
         .filter(Message.conversation_id == conv_id, Message.pinned == True,  # noqa: E712
                 Message.deleted_at == ""))
    if hidden:
        q = q.filter(~Message.id.in_(hidden))
    rows = q.order_by(Message.id.desc()).all()
    return {"pinned": [_msg_out(m, user.id) for m in rows]}


@router.post("/messages/forward")
def forward_messages(payload: dict = Body(...),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Переслать сообщения в другие беседы. Пропускаем адресатов, где пользователь не
    участник, и источники, которых он не видит/удалённые. Копия несёт снимок источника."""
    mids = [int(x) for x in (payload.get("message_ids") or [])]
    targets = [str(x) for x in (payload.get("to_conversation_ids") or [])]
    if not mids or not targets:
        raise HTTPException(status_code=400, detail="Нужны message_ids и to_conversation_ids")
    _guard_can_write(db, user)               #пересылка — тоже создание сообщений
    made = 0
    for conv_id in targets:
        if _participant(db, conv_id, user.id) is None:
            continue                       #в чужую беседу переслать нельзя
        for mid in mids:
            src = db.query(Message).filter(Message.id == mid).first()
            if src is None or src.deleted_at:
                continue
            if _participant(db, src.conversation_id, user.id) is None:
                continue                   #нельзя переслать то, что не видишь
            sender = db.query(User).filter(User.id == src.sender_id).first()
            #Источник пересылки — исходный автор оригинала (а не тот, кто раньше переслал).
            db.add(Message(
                conversation_id=conv_id, sender_id=user.id, body=src.body, created_at=_now(),
                fwd_from_sender_id=(src.fwd_from_sender_id or src.sender_id),
                fwd_from_conv_id=(src.fwd_from_conv_id or src.conversation_id),
                fwd_from_created_at=(src.fwd_from_created_at or src.created_at),
                fwd_sender_name=(src.fwd_sender_name or (sender.full_name if sender else "")),
            ))
            made += 1
    db.commit()
    for conv_id in targets:
        _broadcast(db, conv_id)
    return {"forwarded": made}


# ── Жалоба = тикет модерации (см. MESSENGER-PLAN.md §6.7, §10) ────────────────────────
_REASONS = {"spam", "harassment", "threats", "fraud", "illegal", "flood", "other"}


@router.post("/reports")
def report_message(payload: dict = Body(...),
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Пожаловаться на сообщение → создаётся тикет модерации со СНИМКОМ текста (контекст
    сохранится, даже если сообщение потом удалят). На своё сообщение жаловаться нельзя."""
    mid = int(payload.get("message_id") or 0)
    m = _message_in_conv(db, mid)
    _require_participant(db, m.conversation_id, user)   #жаловаться может только участник
    if m.sender_id == user.id:
        raise HTTPException(status_code=400, detail="Нельзя пожаловаться на своё сообщение")
    reason = payload.get("reason_code")
    reason = reason if reason in _REASONS else "other"
    desc = (payload.get("description") or "").strip()[:2000]
    rep = MessageReport(
        message_id=mid, conversation_id=m.conversation_id,
        message_snapshot=m.body or "", reporter_id=user.id, reported_user_id=m.sender_id,
        reason_code=reason, description=desc, created_at=_now(), status="open",
    )
    db.add(rep)
    db.commit()
    db.refresh(rep)
    return {"ok": True, "report_id": rep.id}


# ── Группы и каналы (см. MESSENGER-PLAN.md §5) ───────────────────────────────────────
def _require_manager(db: Session, conv_id: str, user: User) -> ConversationParticipant:
    p = _require_participant(db, conv_id, user)
    if p.role not in _MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return p


@router.post("/chats/group")
def create_group(payload: dict = Body(...), user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Создать группу: создатель — owner, выбранные — участники (member)."""
    _guard_can_create(db, user)
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Нужно название группы")
    now = _now()
    conv_id = f"conv:{uuid4().hex}"
    db.add(Conversation(id=conv_id, kind="group", title=title[:120],
                        about=(payload.get("about") or "")[:500], owner_id=user.id, created_at=now))
    db.add(ConversationParticipant(conversation_id=conv_id, user_id=user.id,
                                   role="owner", joined_at=now))
    seen = {user.id}
    for uid in (payload.get("member_ids") or []):
        if uid in seen or db.query(User).filter(User.id == uid, User.deleted == False).first() is None:  # noqa: E712
            continue
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=uid,
                                       role="member", joined_at=now))
        seen.add(uid)
    db.commit()
    return {"conversation_id": conv_id, "kind": "group", "title": title}


@router.post("/chats/channel")
def create_channel(payload: dict = Body(...), user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Создать канал: создатель — owner, выбранные — writer (пишут); остальные вступают как reader."""
    _guard_can_create(db, user)
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Нужно название канала")
    now = _now()
    conv_id = f"conv:{uuid4().hex}"
    db.add(Conversation(id=conv_id, kind="channel", title=title[:120],
                        about=(payload.get("about") or "")[:500], owner_id=user.id,
                        is_public=bool(payload.get("is_public", True)), created_at=now))
    db.add(ConversationParticipant(conversation_id=conv_id, user_id=user.id,
                                   role="owner", joined_at=now))
    seen = {user.id}
    for uid in (payload.get("writer_ids") or []):
        if uid in seen or db.query(User).filter(User.id == uid, User.deleted == False).first() is None:  # noqa: E712
            continue
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=uid,
                                       role="writer", joined_at=now))
        seen.add(uid)
    db.commit()
    return {"conversation_id": conv_id, "kind": "channel", "title": title}


@router.get("/channels")
def public_channels(q: str = Query(""), user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Каталог публичных каналов для вступления."""
    rows = (db.query(Conversation)
            .filter(Conversation.kind == "channel", Conversation.is_public == True).all())  # noqa: E712
    ql = (q or "").strip().lower()
    out = []
    for c in rows:
        if ql and ql not in (c.title or "").lower():
            continue
        subs = (db.query(ConversationParticipant)
                .filter(ConversationParticipant.conversation_id == c.id).count())
        out.append({"conversation_id": c.id, "title": c.title, "about": c.about,
                    "subscribers": subs, "joined": _participant(db, c.id, user.id) is not None})
    out.sort(key=lambda x: (x["title"] or "").lower())
    return {"channels": out}


@router.post("/chats/{conv_id}/join")
def join_chat(conv_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Присоединиться к публичному каналу (как reader) → канал появится в списке чатов."""
    conv = _conversation(db, conv_id)
    if conv.kind != "channel" or not conv.is_public:
        raise HTTPException(status_code=403, detail="К этой беседе нельзя присоединиться")
    if _participant(db, conv_id, user.id) is None:
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=user.id,
                                       role="reader", joined_at=_now()))
        db.commit()
    return {"ok": True, "conversation_id": conv_id}


@router.post("/chats/{conv_id}/leave")
def leave_chat(conv_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Покинуть беседу (группу/канал)."""
    p = _participant(db, conv_id, user.id)
    if p is not None:
        db.delete(p)
        db.commit()
    return {"ok": True}


@router.post("/chats/{conv_id}/members")
def add_members(conv_id: str, payload: dict = Body(...),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Добавить участников (owner/admin). В канал добавляются как reader, в группу — member."""
    _require_manager(db, conv_id, user)
    conv = _conversation(db, conv_id)
    role = "reader" if conv.kind == "channel" else "member"
    now = _now()
    added = 0
    for uid in (payload.get("user_ids") or []):
        if _participant(db, conv_id, uid) is not None:
            continue
        if db.query(User).filter(User.id == uid, User.deleted == False).first() is None:  # noqa: E712
            continue
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=uid, role=role, joined_at=now))
        added += 1
    db.commit()
    return {"added": added}


@router.delete("/chats/{conv_id}/members/{uid}")
def remove_member(conv_id: str, uid: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Убрать участника (owner/admin); себя может убрать любой (=покинуть). Владельца не трогаем."""
    if uid != user.id:
        _require_manager(db, conv_id, user)
    else:
        _require_participant(db, conv_id, user)
    p = _participant(db, conv_id, uid)
    if p is not None and p.role != "owner":
        db.delete(p)
        db.commit()
    return {"ok": True}


@router.post("/chats/{conv_id}/members/{uid}/role")
def set_member_role(conv_id: str, uid: str, payload: dict = Body(...),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Назначить роль участнику (только owner). Владельца не понижаем этим эндпоинтом."""
    p = _require_participant(db, conv_id, user)
    if p.role != "owner":
        raise HTTPException(status_code=403, detail="Роли меняет только владелец")
    role = payload.get("role")
    if role not in ("admin", "member", "writer", "reader"):
        raise HTTPException(status_code=400, detail="Некорректная роль")
    tp = _participant(db, conv_id, uid)
    if tp is None:
        raise HTTPException(status_code=404, detail="Участник не найден")
    if tp.role == "owner":
        raise HTTPException(status_code=400, detail="Нельзя изменить роль владельца")
    tp.role = role
    db.commit()
    return {"ok": True}


@router.get("/chats/{conv_id}")
def conversation_info(conv_id: str, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Инфо о беседе (для шапки группы/канала): тип, название, участники и их роли, моя роль."""
    conv = _conversation(db, conv_id)
    part = _require_participant(db, conv_id, user)
    parts = (db.query(ConversationParticipant)
             .filter(ConversationParticipant.conversation_id == conv_id).all())
    urows = {u.id: u for u in db.query(User).filter(
        User.id.in_([p.user_id for p in parts]))} if parts else {}
    onl = _online_logins()
    people = []
    for p in parts:
        u = urows.get(p.user_id)
        prefs = (u.prefs if u is not None and isinstance(u.prefs, dict) else {})
        people.append({
            "user_id": p.user_id,
            "full_name": (u.full_name or u.name or u.login) if u else p.user_id,
            "role": p.role,                       #owner | admin | writer | member | reader
            "online": bool(u) and u.login in onl,
            #Карточка участника в панели «О беседе»: аватар и контекст (группа/предметы).
            "avatar": prefs.get("avatar", "") or "",
            "bio": prefs.get("bio", "") or "",
            "profile_color": prefs.get("profile_color", "") or "",
            "user_role": (u.role if u else ""),   #student | teacher | admin (роль в системе)
            "group_name": (u.group_name or "") if u else "",
            "subjects": (u.subjects or []) if (u is not None and u.role == "teacher") else [],
        })
    #Владелец — первым, дальше по роли и алфавиту: сразу видно, кто создал беседу.
    _ORDER = {"owner": 0, "admin": 1, "writer": 2, "member": 3, "reader": 4}
    people.sort(key=lambda x: (_ORDER.get(x["role"], 9), (x["full_name"] or "").lower()))
    return {"conversation_id": conv.id, "kind": conv.kind, "title": conv.title,
            "about": conv.about, "owner_id": conv.owner_id, "is_public": conv.is_public,
            "my_role": part.role, "participants": people, "subscribers": len(people)}


# ── Чат с модерацией (сторона пользователя, кнопка ⚙) ────────────────────────────────
@router.get("/moderation")
def moderation_chat(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Личная беседа пользователя с командой модерации (создаётся при первом обращении).
    Пользователь пишет как обычно (он участник); отвечает модерация через админ-эндпоинт."""
    #Админ САМ и есть модерация — обращаться ему некуда (отвечает через /web/admin/messenger).
    #Иначе появлялся бы бессмысленный чат «админ пишет сам себе в поддержку».
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Администратор отвечает на обращения, а не пишет в них")
    conv_id = f"mod:{user.id}"
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if conv is None:
        now = _now()
        conv = Conversation(id=conv_id, kind="moderation", title="Модерация", created_at=now)
        db.add(conv)
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=user.id,
                                       role="member", joined_at=now))
        db.commit()
    return {"conversation_id": conv_id, "kind": "moderation"}


# ── Модерация (админ) — очередь тикетов, просмотр бесед (с аудитом), ответ ────────────
def _report_out(db: Session, r: MessageReport) -> dict:
    reporter = db.query(User).filter(User.id == r.reporter_id).first()
    reported = db.query(User).filter(User.id == r.reported_user_id).first()
    onl = _online_logins()
    mset = _muted_set(db, [r.reporter_id, r.reported_user_id])
    return {
        "id": r.id, "message_id": r.message_id, "conversation_id": r.conversation_id,
        "message_snapshot": r.message_snapshot, "reason_code": r.reason_code,
        "description": r.description, "created_at": r.created_at, "status": r.status,
        "reporter_name": (reporter.full_name if reporter else r.reporter_id),
        "reported_name": (reported.full_name if reported else r.reported_user_id),
        #Карточки участников (аватар, ФИО, роль, группа/предметы, состояние мьюта) — админ
        #в жалобе видит, КТО пожаловался и НА КОГО, с лицом, контекстом и кнопкой мьюта.
        "reporter": _safe_user(reporter, onl, r.reporter_id in mset) if reporter else None,
        "reported": _safe_user(reported, onl, r.reported_user_id in mset) if reported else None,
        "handled_by": r.handled_by, "resolution_note": r.resolution_note,
    }


@mod_router.get("/reports")
def mod_reports(status: str = Query("open"), admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    """Очередь жалоб (тикетов). status='' — все, иначе фильтр по статусу."""
    q = db.query(MessageReport)
    if status:
        q = q.filter(MessageReport.status == status)
    rows = q.order_by(MessageReport.id.desc()).limit(300).all()
    return {"reports": [_report_out(db, r) for r in rows]}


_REPORT_STATUSES = {"open", "in_review", "resolved", "dismissed"}


@mod_router.post("/reports/{rid}/resolve")
def mod_resolve(rid: int, payload: dict = Body(...), request: Request = None,
                admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Обработать тикет: сменить статус + заметка. Пишется в аудит."""
    r = db.query(MessageReport).filter(MessageReport.id == rid).first()
    if r is None:
        raise HTTPException(status_code=404, detail="Тикет не найден")
    status = payload.get("status")
    if status not in _REPORT_STATUSES:
        raise HTTPException(status_code=400, detail="Некорректный статус")
    r.status = status
    r.handled_by = admin.login
    r.handled_at = _now()
    r.resolution_note = (payload.get("resolution_note") or "")[:1000]
    db.commit()
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.report.resolve", target=str(rid), detail=status)
    return {"ok": True}


@mod_router.get("/conversations")
def mod_conversations(q: str = Query(""), kind: str = Query(""),
                      admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Список бесед для модерации (поиск по участникам, фильтр по типу)."""
    query = db.query(Conversation)
    if kind:
        query = query.filter(Conversation.kind == kind)
    convs = query.order_by(Conversation.created_at.desc()).limit(300).all()
    ql = (q or "").strip().lower()
    onl = _online_logins()
    out = []
    for c in convs:
        parts = (db.query(ConversationParticipant)
                 .filter(ConversationParticipant.conversation_id == c.id).all())
        names, people = [], []
        mset = _muted_set(db, [p.user_id for p in parts])
        for p in parts:
            u = db.query(User).filter(User.id == p.user_id).first()
            if u:
                names.append(u.full_name or u.login)
                #карточка: аватар, ФИО, роль, группа/предметы + состояние глобального мьюта
                people.append(_safe_user(u, onl, u.id in mset))
        if ql and not any(ql in n.lower() for n in names):
            continue
        out.append({"conversation_id": c.id, "kind": c.kind,
                    "title": c.title or " · ".join(names), "participants": names,
                    "people": people})
    return {"conversations": out}


@mod_router.get("/conversations/{conv_id}/messages")
def mod_conversation_messages(conv_id: str, request: Request = None,
                              admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Прочитать ЛЮБУЮ беседу (модерация). Каждый вызов пишется в аудит (152-ФЗ)."""
    _conversation(db, conv_id)
    rows = (db.query(Message).filter(Message.conversation_id == conv_id)
            .order_by(Message.id.asc()).all())
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.moderation.view", target=conv_id)
    return {"messages": [_msg_out(m) for m in rows]}


@mod_router.post("/conversations/{conv_id}/reply")
def mod_reply(conv_id: str, payload: dict = Body(...), request: Request = None,
              admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Ответ модерации в ЧАТ ОБРАЩЕНИЙ пользователя (kind='moderation'). Отправитель — админ;
    проверка участия НЕ применяется (это и есть право модерации). Пишется в аудит.

    ⚠️ Ограничено kind='moderation': раньше эндпоинт позволял админу вписать сообщение в
    ЛЮБУЮ беседу, включая приватный 1-на-1 чужих людей, от своего имени — это выходит за
    рамки «ответа модерации». Модерация читает любую переписку (mod_conversation_messages,
    с аудитом), но писать может только в официальный чат обращений."""
    conv = _conversation(db, conv_id)
    if conv.kind != "moderation":
        raise HTTPException(
            status_code=403,
            detail="Ответ модерации доступен только в чате обращений пользователя.")
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    m = Message(conversation_id=conv_id, sender_id=admin.id, body=body[:_MAX_MSG_CHARS],
                created_at=_now())
    db.add(m)
    db.commit()
    db.refresh(m)
    _broadcast(db, conv_id)
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.moderation.reply", target=conv_id)
    return _msg_out(m, admin.id)


@mod_router.delete("/messages/{mid}")
def mod_delete_message(mid: int, request: Request = None,
                       admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Удалить ЛЮБОЕ сообщение у всех (модерация). Обычный DELETE /messages/{id} требует
    участия в беседе и авторства — админ в чужой переписке не участник, поэтому для
    модерации отдельный эндпоинт. Сообщение становится тумбстоуном (текст стирается,
    факт остаётся), закрепление снимается. Пишется в аудит (152-ФЗ, подотчётность)."""
    m = _message_in_conv(db, mid)
    if not m.deleted_at:
        m.deleted_at = _now()
        m.pinned = False
        db.commit()
        _broadcast(db, m.conversation_id)
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.moderation.delete", target=str(mid), detail=m.conversation_id)
    return {"ok": True, "id": mid, "deleted": True}


@mod_router.post("/users/{uid}/mute")
def mod_mute_user(uid: str, payload: dict = Body(default={}), request: Request = None,
                  admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Глобальный мьют/размьют пользователя модерацией: замьюченный не может отправлять
    сообщения и создавать беседы (см. _guard_can_write/_guard_can_create). Пишется в аудит.
    Другого админа мьютить нельзя (модераторы не глушат друг друга)."""
    target = db.query(User).filter(User.id == uid, User.deleted == False).first()  # noqa: E712
    if target is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if target.role == "admin":
        raise HTTPException(status_code=400, detail="Нельзя замьютить администратора")
    muted = bool(payload.get("muted", True))
    row = db.query(MutedUser).filter(MutedUser.user_id == uid).first()
    if muted and row is None:
        db.add(MutedUser(user_id=uid, muted_by=admin.login, muted_at=_now()))
    elif not muted and row is not None:
        db.delete(row)
    db.commit()
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.moderation.mute" if muted else "msg.moderation.unmute", target=uid)
    return {"ok": True, "user_id": uid, "muted": muted}


# ── WebSocket-эндпоинт ───────────────────────────────────────────────────────────────
def _ws_token(ws: WebSocket, query_token: str) -> tuple:
    """Достаёт JWT для WS. ПРЕДПОЧТИТЕЛЬНО — из заголовка Sec-WebSocket-Protocol (клиент шлёт
    ['bearer', <jwt>]): так токен НЕ попадает в URL и, значит, в access-логи прокси. Фолбэк —
    старый ?token= в query (для уже раздатых клиентов). Возвращает (token, subprotocol_echo):
    если авторизация прошла через сабпротокол, его надо вернуть эхом в accept()."""
    raw = ws.headers.get("sec-websocket-protocol", "")
    if raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        #ожидаем ["bearer", "<jwt>"]; JWT состоит из tchar (base64url + точки) — валидный токен
        if len(parts) >= 2 and parts[0] == "bearer":
            return parts[1], "bearer"
    return query_token, None


@router.websocket("/ws")
async def messenger_ws(ws: WebSocket, token: str = Query("")):
    """Живой канал событий. Авторизация — JWT через Sec-WebSocket-Protocol (не светит токен в
    логах), с фолбэком на ?token= в query. Клиент получает {type:'changed', conversation_id}
    и подтягивает свежее; может слать {type:'typing', conversation_id} — сервер ретранслирует
    остальным участникам."""
    jwt_token, subproto = _ws_token(ws, token)
    payload = decode_token(jwt_token) if jwt_token else None
    if not payload:
        await ws.close(code=4401)
        return
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.login == payload.get("sub"),
                                     User.deleted == False).first()  # noqa: E712
    finally:
        db.close()
    if user is None:
        await ws.close(code=4401)
        return

    ws_manager.bind_loop()
    await ws_manager.connect(user.id, ws, subprotocol=subproto)
    try:
        while True:
            data = await ws.receive_json()
            if isinstance(data, dict) and data.get("type") == "typing" and data.get("conversation_id"):
                db2 = SessionLocal()
                try:
                    ids = [i for i in _participant_ids(db2, data["conversation_id"]) if i != user.id]
                finally:
                    db2.close()
                await ws_manager.send_users(
                    ids, {"type": "typing", "conversation_id": data["conversation_id"], "user_id": user.id})
    except WebSocketDisconnect:
        ws_manager.disconnect(user.id, ws)
    except Exception:
        ws_manager.disconnect(user.id, ws)
