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
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import (
    APIRouter, Body, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import audit, events, msg_limit
from ..db import get_db, SessionLocal
from ..deps import get_current_user, require_admin
from ..security import decode_token
from ..models import (
    AuthSession,
    Conversation, ConversationIgnore, ConversationParticipant, ConversationRole,
    CuratorReport, Group, Message, MessageHidden,
    MessageReport, MessageReaction, MessageEdit, MessageTemplate, MutedUser,
    NotifyEvent, ParentLink, SubjectHours,
    UserStatus, User, UserNote, direct_conversation_id,
)

router = APIRouter(prefix="/web/messenger", tags=["messenger"])
#Кэш сводок: {(беседа, id последнего сообщения) → текст}. В ПАМЯТИ и намеренно: сводка
#дёшево пересоздаётся, переживать перезапуск ей незачем, а лишняя таблица на боевом VPS
#(1 ядро, 960 МБ) стоит дороже. Новое сообщение меняет ключ — устаревшее не отдастся.
_SUMMARY_CACHE = {}
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
        if loop is None or loop.is_closed():   #нет живого цикла (никто по WS / цикл закрыт)
            return
        try:
            asyncio.run_coroutine_threadsafe(self.send_users(list(uids), data), loop)
        except Exception:
            pass

    async def close_user(self, uid: str, code: int = 4001):
        """Разорвать ВСЕ живые сокеты пользователя."""
        for ws in list(self._by_user.get(uid, ())):
            try:
                await ws.close(code=code)
            except Exception:
                #Сокет мог умереть сам (клиент закрыл вкладку) — это штатный исход
                #гонки, а не сбой. Важно, что из реестра он всё равно уйдёт ниже.
                pass
        self._by_user.pop(uid, None)

    def kick_user(self, uid: str):
        """🔒 Отзыв сессии обязан РВАТЬ уже открытый сокет, а не только закрывать вход.

        Проверка отзыва стоит на ПОДКЛЮЧЕНИИ, и этого мало: сокет живёт часами. После
        «Выйти» или блокировки админом украденный токен продолжал получать карту
        активности бесед (в каких чатах идёт переписка) и слать «печатает…» — ровно до
        того момента, когда клиент сам отвалится. Тексты не утекали (их отдаёт HTTP, а
        он отзыв проверяет), но чёрный список jti заводился именно ради того, чтобы
        доступ закрывался МГНОВЕННО, а не «когда-нибудь».

        Зовётся из СИНХРОННЫХ обработчиков (logout, отзыв сессий админом) — отсюда тот
        же приём с планированием корутины в цикл, что у `emit_users`."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.close_user(uid), loop)
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


def _notify_recipients(db: Session, conv: Conversation, sender: User, skip_ids: set = None):
    """Пуш о новом сообщении получателям, которых НЕТ в приложении (по presence). Через
    RuStore Push, как уведомления об оценке. Контент НЕ уходит третьей стороне (§12 плана):
    заголовок — имя отправителя/название беседы, тело — нейтральное «Новое сообщение».
    `skip_ids` — §D8: тихо упомянутые (@!Фамилия) не получают пуш по ЭТОМУ сообщению
    (только бейдж при следующем открытии). Best-effort: сбой доставки не роняет отправку."""
    try:
        from .. import rustore_push
        online = _online_logins()
        ids = [i for i in _participant_ids(db, conv.id) if i != sender.id and i not in (skip_ids or ())]
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

def _notify_loud_mentions(db: Session, conv: Conversation, sender: User, mentions: list) -> None:
    """ГРОМКАЯ отметка (`/@!Фамилия`): письмо во вкладку «Уведомления» → «Система» + пуш.

    Почему письмо, а не только значок в чате: смысл громкого пинга — «увидь это, даже
    если сейчас не в мессенджере». Значок «@» в списке чатов увидит лишь тот, кто и так
    открыл вкладку сообщений, а `NotifyEvent` доезжает до всех платформ разом (веб,
    десктоп, телефон) уже существующим механизмом уведомлений.

    Текст письма собирается ЗДЕСЬ, на сервере, как и остальные уведомления (см. модель
    NotifyEvent): тон и формулировка не должны разъезжаться по платформам, а история
    обязана остаться правдивой, даже если шаблон потом поправят.

    ⚠️ Мьют беседы уважаем: замьютивший её просил тишины, и «громкость» отметки — не
    повод это обойти. Best-effort: сбой уведомления не роняет уже отправленное сообщение.
    """
    loud_ids = {m["user_id"] for m in mentions if m.get("loud")}
    if not loud_ids:
        return
    try:
        muted_here = {p.user_id for p in db.query(ConversationParticipant)
                      .filter(ConversationParticipant.conversation_id == conv.id,
                              ConversationParticipant.muted == True).all()}  # noqa: E712
        loud_ids -= muted_here
        loud_ids.discard(sender.id)          #отметить самого себя — не событие
        if not loud_ids:
            return
        sender_name = sender.full_name or sender.name or sender.login or "Собеседник"
        where = (conv.title if conv.kind in ("group", "channel") and conv.title
                 else f"переписке с {sender_name}")
        title = "Вас отметили"
        body = f"{sender_name} отметил(а) вас в чате «{where}»."
        online = _online_logins()
        for u in db.query(User).filter(User.id.in_(loud_ids)).all():
            if not u.login:
                continue
            db.add(NotifyEvent(id=str(uuid4()), login=u.login, kind="mention",
                               subject="", lesson_id="", created_at=_now(), read_at="",
                               title=title, body=body,
                               payload={"conversation_id": conv.id}))
            if u.login not in online:
                from .. import rustore_push
                rustore_push.notify_login(db, u.login, title, body,
                                          {"type": "message", "conversation_id": conv.id})
        db.commit()
    except Exception:
        db.rollback()


#Сколько непрочитанных сообщений со «@» просматриваем в поисках отметки (см. list_chats).
#Отметка ищется САМАЯ РАННЯЯ, поэтому лимит режет хвост очень старых непрочитанных — а
#там значок «@» уже не помогает: чат в таком состоянии открывают целиком, а не по кнопке.
_MENTION_SCAN_LIMIT = 200

_MAX_MSG_CHARS = 4000          #лимит длины сообщения (защита БД от «простыней»/спама)
_DEFAULT_PAGE = 50            #сколько сообщений отдаём за один запрос истории
_MAX_PAGE = 100
_MAX_NOTE_CHARS = 300           #личная заметка о человеке (UserNote) — короче «О себе»,
                                #это памятка себе, а не публичный текст


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


def _safe_user(u: User, online_logins: set = None, muted: bool = False, status: dict = None) -> dict:
    """Безопасные поля пользователя для карточки/каталога (НИЧЕГО, что помогает входу в
    чужой аккаунт — см. MESSENGER-PLAN.md §9: без логина, почты, телефона, хэша, device-id).
    У студента — группа; у преподавателя — предметы, которые ведёт. online — по presence.
    `muted` (глобальный мьют модерацией) заполняем ТОЛЬКО в админ-контексте — рядовым
    пользователям состояние мьюта чужого аккаунта в каталоге ни к чему.
    `status` — §D7: {kind, custom_text} НАКЛАДКА поверх presence (dnd/studying/away);
    kind='' значит статуса нет — клиент показывает просто online/не в сети."""
    prefs = u.prefs if isinstance(u.prefs, dict) else {}
    st = status or {}
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
        #Баннер карточки — гифка с CDN Klipy вместо однотонной плашки цвета. Пусто —
        #рисуем плашку по profile_color, как и раньше (баннер НЕ заменяет цвет: цвет
        #по-прежнему красит имя и подложку аватарки, гифка ложится только на полосу).
        "profile_banner": prefs.get("profile_banner", "") or "",
        #Стиль никнейма (§5.4) — тоже публичный, тем же путём, что цвет плашки: id из
        #фиксированного списка (routers/me.py::NAME_FONTS), клиент сам сопоставит его со
        #шрифтом. Пусто — уже проверено на входе (me.py::_sanitize_name_font), но берём
        #через or "" ещё раз: строки в БД могли остаться от ДО того, как поле завели.
        "name_font": prefs.get("name_font", "") or "",
        #Эффект и цвет имени (3.7) — та же публичная тройка, что и шрифт: без них у
        #собеседника имя рисовалось бы выбранным шрифтом, но без выбранного вида.
        "name_effect": prefs.get("name_effect", "") or "",
        "name_color": prefs.get("name_color", "") or "",
        "muted": bool(muted),
        "status_kind": st.get("kind", "") or "",
        "status_text": st.get("custom_text", "") or "",
    }
    if u.role == "teacher":
        d["subjects"] = u.subjects or []
    return d


_STATUS_KINDS = {"", "dnd", "studying", "away"}


def _status_map(db: Session, user_ids) -> dict:
    """§D7: карта id→{kind, custom_text} для набора пользователей (пачкой, один запрос)."""
    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    rows = db.query(UserStatus).filter(UserStatus.user_id.in_(ids)).all()
    return {r.user_id: {"kind": r.kind, "custom_text": r.custom_text} for r in rows}


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


def _create_flood_ticket(db: Session, user: User) -> None:
    """§D2: систематический флуд (3+ нарушений всплеска за 10 минут) — автотикет модерации,
    без ручного создания. reporter_id='system' — отличает автообнаружение от жалобы человека."""
    db.add(MessageReport(
        message_id=0, conversation_id="",
        message_snapshot="Автоматически: систематическая частая отправка сообщений.",
        reporter_id="system", reported_user_id=user.id,
        reason_code="flood", description="", created_at=_now(), status="open",
    ))
    db.commit()


def _guard_can_write(db: Session, user: User) -> None:
    """Единый барьер записи в мессенджер: глобальный мьют модерацией (403) → маскот-кулдаун
    (429 с эскалацией, §D2) → жёсткий анти-флуд (429, задел на скрипт, игнорирующий UI).
    Зовётся из всех точек, создающих сообщения (отправка, пересылка)."""
    if _is_muted(db, user.id):
        raise HTTPException(
            status_code=403,
            detail="Вы ограничены модерацией и временно не можете отправлять сообщения.")
    mascot_wait, violations = msg_limit.mascot_check(user.id)
    if mascot_wait:
        if violations == 3:                    #ровно на переходе к «систематическому»
            _create_flood_ticket(db, user)
        raise HTTPException(
            status_code=429,
            detail={"message": "Не отправляйте сообщения так часто.",
                    "cooldown_seconds": mascot_wait, "mascot": True},
            headers={"Retry-After": str(mascot_wait)})
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


def _parent_group_names(db: Session, parent: User) -> set:
    """Группы, к которым родитель причастен через ПОДТВЕРЖДЁННЫХ детей.

    Именно они определяют, с кем родителю вообще можно переписываться: с родителями той же
    группы и с её куратором. Группы непривязанных или неподтверждённых детей сюда не
    попадают — доступ даёт согласие студента, а не заявка сотрудника."""
    from .parent import active_children
    return {s.group_name for s in active_children(db, parent) if s.group_name}


def _guard_direct_allowed(db: Session, user: User, peer: User) -> None:
    """Кому вообще можно написать лично. Ограничение существует только вокруг РОДИТЕЛЕЙ.

    Родитель — не участник учебного процесса, а внешний человек с доступом к данным своего
    ребёнка. Пускать его в переписку со всем колледжем нельзя: это ни студентам, ни
    преподавателям не нужно, а поводов для конфликтов даёт много. Поэтому родителю открыты
    только два направления: родители той же группы и куратор этой группы. Симметрично: и
    написать родителю может только тот, кому родитель мог бы написать сам."""
    if "parent" not in (user.role, peer.role):
        return
    parent, other = (user, peer) if user.role == "parent" else (peer, user)
    groups = _parent_group_names(db, parent)
    if not groups:
        raise HTTPException(
            status_code=403,
            detail="Переписка станет доступна, когда студент подтвердит доступ к журналу.")
    if other.role == "parent":
        #Двум родителям нужна ОБЩАЯ группа (их дети учатся вместе).
        if groups & _parent_group_names(db, other):
            return
        raise HTTPException(status_code=403,
                            detail="Писать можно только родителям своей группы.")
    if other.role == "teacher" and groups & set(other.curated_groups or []):
        return          #куратор группы ребёнка
    if other.role == "admin":
        return          #обращение в администрацию колледжа закрывать не за чем
    raise HTTPException(status_code=403,
                        detail="Родителю доступна переписка только с куратором и "
                               "родителями своей группы.")


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
    """Карта id→ФИО для набора отправителей (в группах/каналах показываем автора).
    §D12: синтетический "system" (автопосты в системные каналы) — всегда «Вектор»."""
    ids = {s for s in sender_ids if s}
    if not ids:
        return {}
    out = {}
    if "system" in ids:
        out["system"] = SYSTEM_SENDER_NAME
        ids = ids - {"system"}
    if ids:
        rows = db.query(User).filter(User.id.in_(ids)).all()
        out.update({u.id: (u.full_name or u.name or u.login or u.id) for u in rows})
    return out


#Отправитель служебных постов (ответы Вектора, системные каналы). Не настоящий User —
#строка-заглушка, поэтому её не найти в справочнике; клиент подписывает такие сообщения
#как «Вектор» (SYSTEM_SENDER_NAME ниже).
SYSTEM_SENDER_ID = "system"

#§D8 + «пинги»: три формы отметки, они же — то, что подставляет автодополнение по «/@».
#  @Фамилия      — обычная отметка: подсветка + пуш офлайн-получателю (как было);
#  /@Фамилия     — ТИХАЯ: только подсветка и значок «@» в списке чатов, без пуша;
#  /@!Фамилия    — ГРОМКАЯ: звуковой сигнал у получателя + письмо во вкладку «Система»
#  /!@Фамилия      («Вас отметили в чате …») + пуш. Обе перестановки «!» принимаются:
#                  вспомнить порядок двух подряд идущих символов невозможно, а ошибиться
#                  в громкости отметки — неприятно (либо звонит зря, либо молчит нужное).
#Историческая форма @!Фамилия (тихая, без слэша) сохранена — она уже в переписках.
_MENTION_RE = re.compile(r"(/)?(?:@(!?)|(!)@)([A-Za-zА-Яа-яЁё]+)")


def _parse_mentions(db: Session, body: str, participant_ids) -> list:
    """§D8: находит отметки среди УЧАСТНИКОВ беседы (формы — см. _MENTION_RE выше).

    Сопоставление — по ПЕРВОМУ слову ФИО (фамилии), регистронезависимо, без разбора
    склонений: осознанно просто, как и остальной MVP мессенджера (см. MESSENGER-PLAN
    §D8 — точный морфологический разбор там же не предполагался).

    Возвращает [{user_id, silent, loud}]: `silent` глушит пуш (как раньше), `loud`
    дополнительно даёт звук и письмо в «Систему». Одного поля мало — «громко» это не
    «не тихо»: обычная @Фамилия остаётся посередине (пуш есть, звонка нет)."""
    ids = [i for i in participant_ids if i]
    if not ids or "@" not in body:
        return []
    rows = db.query(User).filter(User.id.in_(ids)).all()
    surnames = {}
    for u in rows:
        first = (u.full_name or u.name or "").split(" ", 1)[0].strip().lower()
        if first:
            surnames.setdefault(first, u.id)
    out, seen = [], set()
    for m in _MENTION_RE.finditer(body):
        slash, bang_after, bang_before, name = m.group(1), m.group(2), m.group(3), m.group(4)
        uid = surnames.get(name.lower())
        if not uid or uid in seen:
            continue
        seen.add(uid)
        bang = bool(bang_after or bang_before)
        #«!» без слэша — историческая ТИХАЯ форма (@!Фамилия), её смысл не меняем: в
        #переписках уже есть такие сообщения, и переворачивать их задним числом нельзя.
        loud = bool(slash) and bang
        silent = (bang and not slash) or (bool(slash) and not bang)
        out.append({"user_id": uid, "silent": silent, "loud": loud})
    return out


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
        "kind": getattr(m, "kind", "") or "text",          #§D6: text | system
        "body": "" if deleted else (m.body or ""),
        "body_format": getattr(m, "body_format", "") or "markdown",  #§D1
        "created_at": m.created_at,
        "edited_at": "" if deleted else (m.edited_at or ""),
        "deleted": deleted,
        "reply_to_id": m.reply_to_id or None,
        "pinned": bool(m.pinned) and not deleted,
        #Шапка «Переслано от …» (снимок имени источника):
        "forwarded_from": (m.fwd_sender_name or "") if (m.fwd_from_sender_id and not deleted) else None,
        "mentions": [] if deleted else (getattr(m, "mentions", None) or []),   #§D8
        "reactions": [],   #§D3: заполняется в списке сообщений (_attach_reactions)
        "reply_count": 0,  #Треды: заполняется в списке сообщений (_attach_reply_counts)
        #§12: kind="report" — метаданные кнопки «Отчёт №N» (заполняется _attach_report_meta).
        "report": None,
        #kind="activity"/"board" — карточка активности и сохранённая доска
        #(PLAN-ACTIVITIES §10). Тот же приём, что у отчёта: в теле сообщения лежит только
        #id, а объект подмешивается при выдаче — статус активности меняется ПОСЛЕ отправки
        #(идёт → завершена), и переотправлять ради этого сообщение незачем.
        "activity": None,
        "board": None,
    }


def _attach_reactions(db: Session, msgs: list, me_id: str) -> None:
    """§D3: догрузить реакции пачкой для списка сериализованных сообщений (по id) и
    сгруппировать: [{emoji, count, mine}]. Один запрос на всю страницу."""
    ids = [m["id"] for m in msgs]
    if not ids:
        return
    rows = db.query(MessageReaction).filter(MessageReaction.message_id.in_(ids)).all()
    by_msg = {}
    for r in rows:
        grp = by_msg.setdefault(r.message_id, {})
        cell = grp.setdefault(r.emoji, {"emoji": r.emoji, "count": 0, "mine": False})
        cell["count"] += 1
        if r.user_id == me_id:
            cell["mine"] = True
    for m in msgs:
        m["reactions"] = list(by_msg.get(m["id"], {}).values())


def _attach_reply_counts(db: Session, msgs: list) -> None:
    """Треды (docs/MESSENGER-ADDON-PLAN-GPT-SMART.md §3.3): число ответов на сообщение —
    для бейджа «N ответов». Своей сущности треда не заводим: ветка = сообщения этой же
    беседы с reply_to_id == id родителя (переиспользуем уже существующее поле)."""
    ids = [m["id"] for m in msgs]
    if not ids:
        return
    rows = (db.query(Message.reply_to_id, func.count(Message.id))
            .filter(Message.reply_to_id.in_(ids), Message.deleted_at == "")
            .group_by(Message.reply_to_id).all())
    counts = {rid: cnt for rid, cnt in rows}
    for m in msgs:
        m["reply_count"] = counts.get(m["id"], 0)


def _attach_report_meta(db: Session, msgs: list) -> None:
    """§12: у сообщений kind="report" тело — просто report_id; номер/архивность кнопки
    «Отчёт №N» досчитываем пачкой (тело сообщения НЕ меняем — statuses «архивный» может
    смениться ПОСЛЕ отправки, а сообщение переотправлять незачем)."""
    ids = [m["body"] for m in msgs if m["kind"] == "report" and m["body"]]
    if not ids:
        return
    rows = db.query(CuratorReport).filter(CuratorReport.id.in_(ids)).all()
    by_id = {r.id: r for r in rows}
    for m in msgs:
        if m["kind"] != "report":
            continue
        r = by_id.get(m["body"])
        if r is not None:
            m["report"] = {"id": r.id, "seq": r.seq, "group": r.group_name,
                           #Дата границы — на кнопке: два отчёта подряд иначе неразличимы.
                           "cutoff_date": r.cutoff_date or "",
                           "archived": _report_archived(r, db)}


def _report_archived(rep, db) -> bool:
    """Архивна ли кнопка отчёта куратора.

    🔥 Считаем по КАЛЕНДАРЮ, а не только по сохранённому флагу. Флаг ставил ровно один
    код — перевод термина вперёд (`/admin/term/rollover`), а его сдвиг в будущее теперь
    запрещён: он дважды уводил боевой сервер на год вперёд, и у группы оказывались
    предметы двух курсов сразу. Если оставить только флаг, отчёты перестали бы
    архивироваться вовсе и «Отчёт №3» за прошлый семестр выглядел бы действующим.

    Сохранённый флаг уважаем (его могли поставить раньше) — он лишь дополняется
    честным сравнением периода отчёта с текущим."""
    if bool(getattr(rep, "archived", False)):
        return True
    #⚠️ `webdata` в этом модуле импортируется ВНУТРИ функций, а не на уровне файла —
    #модульного `W` тут нет, и обращение к нему дало бы NameError уже в рантайме, при
    #полностью зелёной компиляции (эта грабля в проекте уже стоила отдельного разбора).
    from .. import webdata as W
    try:
        cy, cs = W.current_term(W.load_config(db))
        return (int(str(rep.year).split("/")[0]), int(rep.semester)) <                (int(str(cy).split("/")[0]), int(cs))
    except (TypeError, ValueError, AttributeError, IndexError):
        return False


def _poll_cell(a, viewer_id: str) -> dict:
    """Опрос ДЛЯ ЛЕНТЫ: голосуют прямо в сообщении, как в Telegram.

    🔒 Распределение голосов кладём ТОЛЬКО создателю либо когда автор явно включил
    открытые голоса. Прочим — свой выбор и общее число проголосовавших: число ничего не
    раскрывает и снимает вопрос «дошло ли», а чужой голос без согласия автора опроса
    показывать нельзя."""
    from ..routers import activities as _act
    snap = _act.activity_state.get(a.id)
    live = (snap or {}).get("payload") or {}
    params = a.params or {}
    #Идёт — берём живые голоса; завершён — снимок, сохранённый при завершении. Без
    #снимка завершённый опрос показывал бы «проголосовало: 0», хотя голосовали все.
    votes = live.get("votes") if snap is not None else (params.get("final_votes") or {})
    votes = votes or {}
    opts = list(params.get("options") or [])
    public = bool(params.get("public_votes"))
    mine = votes.get(viewer_id)
    cell = {"question": params.get("question") or "", "options": opts,
            "my_choice": mine if mine is not None else None,
            "voted_count": len(votes), "ends_at": live.get("ends_at") or "",
            "public_votes": public}
    if public or viewer_id == a.host_id:
        cell["tally"] = [sum(1 for v in votes.values() if int(v) == i) for i in range(len(opts))]
    return cell


def _attach_activity_meta(db: Session, msgs: list, viewer_id: str = "") -> None:
    """kind="activity" — карточка-кнопка активности; kind="board" — сохранённая доска.

    Как и у отчёта, в теле сообщения лежит ТОЛЬКО id: статус активности меняется после
    отправки (идёт → завершена), а переотправлять сообщение ради этого незачем — клиент
    гасит кнопку по `status`."""
    from ..models import Activity, BoardArtifact
    #Опрос — тоже активность, просто рисуется в ленте кнопками, а не ссылкой.
    act_ids = [m["body"] for m in msgs if m["kind"] in ("activity", "poll") and m["body"]]
    board_ids = [m["body"] for m in msgs if m["kind"] == "board" and m["body"]]
    acts = ({a.id: a for a in db.query(Activity).filter(Activity.id.in_(act_ids)).all()}
            if act_ids else {})
    boards = ({b.id: b for b in db.query(BoardArtifact)
               .filter(BoardArtifact.id.in_(board_ids)).all()} if board_ids else {})
    #⚠️ Сверяем беседу: объект догружаем ТОЛЬКО там, где он и живёт. Без этой проверки
    #пересланная (или вручную созданная с чужим id) карточка отдавала бы заголовок и
    #статус активности людям, которые к её беседе отношения не имеют. Пересылку таких
    #сообщений мы запретили отдельно, но одного запрета мало: правило «чужое не
    #показываем» должно держаться и там, где строка уже как-то оказалась в ленте.
    for m in msgs:
        if m["kind"] in ("activity", "poll"):
            a = acts.get(m["body"])
            if a is not None and a.conversation_id == m.get("conversation_id"):
                m["activity"] = {"id": a.id, "kind": a.kind, "title": a.title or "",
                                 "status": a.status, "started_at": a.started_at or "",
                                 "finished_at": a.finished_at or ""}
                if a.kind == "poll":
                    m["activity"].update(_poll_cell(a, viewer_id))
        elif m["kind"] == "board":
            b = boards.get(m["body"])
            if b is not None and b.conversation_id == m.get("conversation_id"):
                m["board"] = {"id": b.id, "title": b.title or "", "sheet": b.sheet or "blank",
                              "strokes_count": len(b.strokes or [])}


def _attach_rich_meta(db: Session, msgs: list, viewer_id: str = "") -> None:
    """ЕДИНАЯ точка догрузки всего, что у сообщения лежит в теле одним лишь id.

    ⚠️ Заведена намеренно вместо перечисления вызовов по местам. Раньше
    `_attach_report_meta` звался из ПЯТИ мест, и добавление второго такого вида
    (активности) означало не забыть дописать рядом ещё пять строк. Забыть одну — значит
    отдать клиенту сырой `act:9f3…` вместо кнопки, причём именно в том месте, куда
    заглядывают реже всего (превью последнего сообщения в списке чатов). Тот же приём и
    та же причина, что у обёртки `_safe()` в сборе дельты синка: правило живёт в ОДНОМ
    месте, и новый вид сообщения нельзя забыть подключить."""
    if not msgs:
        return
    _attach_report_meta(db, msgs)
    _attach_activity_meta(db, msgs, viewer_id)


#§D3: белый список эмодзи-реакций (как в плане). Ничего сверх — предсказуемо и безопасно.
_REACTIONS = {"👍", "✅", "❤️", "😂", "👀", "🔥", "💯", "❓", "📌"}


#§D6: разделитель полей системного события — НЕ двоеточие: id участника сам содержит ':'
#(формат stud:{login}/teach:{login}), и простой split(':') на клиенте расклеивал бы его на
#куски (баг был найден при добавлении Qt-рендера и относится и к вебу тоже). \x1f (Unit
#Separator) — непечатный символ, набрать с клавиатуры невозможно, коллизий не бывает.
_SYS_SEP = "\x1f"


def _system(db: Session, conv_id: str, event: str, *args: str) -> Message:
    """§D6: вставить СИСТЕМНОЕ сообщение в ленту (вступил/вышел/закрепил/…). Тело —
    'событие\\x1fаргумент\\x1f...', клиент рендерит по-человечески. Не шлёт пуш, но
    триггерит WS-обновление (см. вызывающий код — broadcast делает он сам).
    Возвращает созданную строку — нужна командам (/mute), которые отдают её клиенту
    как результат отправки, а не только «побочным эффектом»."""
    body = _SYS_SEP.join((event, *args))
    m = Message(conversation_id=conv_id, sender_id="system", body=body,
               created_at=_now(), kind="system")
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


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


def _may_list_parent(db: Session, viewer: User, parent: User) -> bool:
    """Показывать ли этого родителя в каталоге у данного пользователя."""
    if viewer.role == "admin":
        return True
    groups = _parent_group_names(db, parent)
    if viewer.role == "teacher":
        return bool(groups & set(viewer.curated_groups or []))
    if viewer.role == "parent":
        return bool(groups & _parent_group_names(db, viewer))
    return False


@router.get("/users")
def directory(role: str = Query("student"), q: str = Query(""), page: int = Query(0),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Каталог/поиск для выбора собеседника. Вкладки — по роли (student|teacher), поиск по
    ФИО, сортировка по алфавиту, постранично. Отдаём ТОЛЬКО безопасные поля (§9).

    Поиск и сортировку делаем в Python (не SQL ilike): SQLite без ICU не умеет
    регистронезависимый LIKE для кириллицы, а датасет колледжа умещается в память.
    На PostgreSQL позже можно перейти на ILIKE + индекс. Себя из списка исключаем.

    ⚠️ Роли отбираются по БЕЛОМУ списку. Благодаря этому роль `parent` невидима по
    построению: чтобы кого-то скрыть, ничего делать не нужно — нужно явно РАЗРЕШИТЬ.
    Вкладка «Родители» открыта только куратору и администратору, причём куратору видны
    лишь родители его групп."""
    allowed = ("student", "teacher")
    if user.role == "admin" or (user.role == "teacher" and (user.curated_groups or [])):
        allowed += ("parent",)
    #Сам родитель ищет только других родителей — списка студентов и преподавателей у него нет.
    if user.role == "parent":
        allowed = ("parent",)
    role = role if role in allowed else allowed[0]
    rows = (db.query(User)
            .filter(User.role == role, User.deleted == False, User.id != user.id).all())  # noqa: E712
    if role == "parent":
        #Показываем только тех, с кем переписка реально разрешена — иначе каталог обещал
        #бы собеседника, а открытие чата отвечало бы 403.
        rows = [u for u in rows if _may_list_parent(db, user, u)]
    ql = (q or "").strip().lower()
    if ql:
        rows = [u for u in rows if ql in (u.full_name or u.name or "").lower()]
    rows.sort(key=lambda u: (u.full_name or u.name or u.login or "").lower())
    total = len(rows)
    page = max(0, int(page or 0))
    chunk = rows[page * _PAGE_USERS:(page + 1) * _PAGE_USERS]
    onl = _online_logins()
    sm = _status_map(db, [u.id for u in chunk])
    out = [_safe_user(u, onl, status=sm.get(u.id)) for u in chunk]
    if role == "parent":
        #§12: подпись «род. <группа>» в каталоге — куратор видит родителя, но не всегда
        #знает, чей он, пока не откроет карточку. Только АКТИВНЫЕ/подтверждённые дети
        #(та же логика, что определяет саму видимость родителя, см. _may_list_parent).
        groups_by_id = {u.id: sorted(_parent_group_names(db, u)) for u in chunk}
        for d in out:
            d["groups"] = groups_by_id.get(d["id"], [])
    return {"users": out, "total": total, "page": page, "page_size": _PAGE_USERS}


@router.get("/users/{user_id}/profile")
def user_profile(user_id: str, _user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Публичная карточка (портфолио) — только безопасные поля."""
    u = db.query(User).filter(User.id == user_id, User.deleted == False).first()  # noqa: E712
    if u is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    #Родитель невидим и здесь. Иначе скрытие в каталоге обходилось бы прямым запросом по
    #id: карточка отдаёт ФИО и «О себе», то есть ровно то, что мы прячем.
    if u.role == "parent" and u.id != _user.id and not _may_list_parent(db, _user, u):
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    sm = _status_map(db, [user_id])
    return {"profile": _safe_user(u, _online_logins(), status=sm.get(user_id))}


@router.get("/users/{user_id}/shared")
def user_shared(user_id: str, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """«Общие группы»/«Общие каналы» на карточке чужого профиля (Discord-style).

    Пересечение бесед, где участвуем ОБА — безопасно по построению: раскрываем только
    те группы/каналы, в которых вызывающий и так уже состоит, ничего нового о чужом
    членстве не утекает. `saved`/личные ЛС/модерация в пересечение не входят намеренно —
    «общее» здесь означает ровно то, что показывает Discord (сервера), а не любую беседу."""
    mine = {r[0] for r in db.query(ConversationParticipant.conversation_id)
            .filter(ConversationParticipant.user_id == user.id).all()}
    theirs = {r[0] for r in db.query(ConversationParticipant.conversation_id)
              .filter(ConversationParticipant.user_id == user_id).all()}
    shared_ids = mine & theirs
    if not shared_ids:
        return {"groups": [], "channels": []}
    convs = (db.query(Conversation)
             .filter(Conversation.id.in_(shared_ids), Conversation.kind.in_(("group", "channel")))
             .order_by(Conversation.title).all())
    groups = [{"id": c.id, "title": c.title} for c in convs if c.kind == "group"]
    channels = [{"id": c.id, "title": c.title} for c in convs if c.kind == "channel"]
    return {"groups": groups, "channels": channels}


@router.get("/users/{user_id}/note")
def get_user_note(user_id: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Личная заметка ВЫЗЫВАЮЩЕГО о человеке (Discord-style «Notes») — видна только ему.

    Разрешена и про САМОГО СЕБЯ (author_id == about_user_id == user_id): «памятка себе»
    на своей же карточке профиля — так просил заказчик, отдельного запрета не заводим.
    404-проверку существования цели не делаем: заметка — это данные автора, не цели, и
    её можно писать даже про кого-то, кого только что удалили (текст останется историей)."""
    row = (db.query(UserNote)
           .filter(UserNote.author_id == user.id, UserNote.about_user_id == user_id)
           .first())
    return {"text": row.text if row else ""}


@router.post("/users/{user_id}/note")
def set_user_note(user_id: str, payload: dict = Body(...),
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Сохраняет/стирает заметку. Пустой текст после обрезки — УДАЛЯЕТ строку, а не
    оставляет пустую: иначе таблица копила бы мёртвые записи на каждое «написал и стёр»."""
    text = str(payload.get("text") or "").strip()[:_MAX_NOTE_CHARS]
    row = (db.query(UserNote)
           .filter(UserNote.author_id == user.id, UserNote.about_user_id == user_id)
           .first())
    if not text:
        if row is not None:
            db.delete(row)
            db.commit()
        return {"ok": True, "text": ""}
    if row is None:
        row = UserNote(author_id=user.id, about_user_id=user_id)
        db.add(row)
    row.text = text
    row.updated_at = _now()
    db.commit()
    return {"ok": True, "text": text}


# ── Статус пользователя (§D7) ─────────────────────────────────────────────────────────
@router.get("/status")
def get_my_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Мой текущий статус (для инициализации переключателя в UI)."""
    row = db.query(UserStatus).filter(UserStatus.user_id == user.id).first()
    return {"kind": row.kind if row else "", "custom_text": row.custom_text if row else ""}


@router.post("/status")
def set_my_status(payload: dict = Body(...), user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Установить свой статус (dnd/studying/away, '' — сбросить). custom_text — только у
    преподавателя (см. MESSENGER-PLAN §D7); у прочих ролей молча игнорируем текст."""
    kind = payload.get("kind") or ""
    if kind not in _STATUS_KINDS:
        raise HTTPException(status_code=400, detail="Некорректный статус")
    text = (payload.get("custom_text") or "").strip()[:80] if user.role == "teacher" else ""
    row = db.query(UserStatus).filter(UserStatus.user_id == user.id).first()
    if row is None:
        row = UserStatus(user_id=user.id)
        db.add(row)
    row.kind = kind
    row.custom_text = text
    row.updated_at = _now()
    db.commit()
    return {"ok": True, "kind": row.kind, "custom_text": row.custom_text}


# ── Шаблоны быстрых ответов преподавателя ────────────────────────────────────────────
# docs/MESSENGER-ADDON-PLAN-GPT.md «Шаблоны сообщений преподавателя»: часто используемые
# фразы одним кликом («Работа принята», «Исправьте ошибки»). Личный набор, НЕ AI —
# преподаватель сам пишет текст один раз и переиспользует. Лимит — защита от «простыней».
_MAX_TEMPLATES = 20


@router.get("/templates")
def list_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(MessageTemplate).filter(MessageTemplate.user_id == user.id)
            .order_by(MessageTemplate.position.asc(), MessageTemplate.id.asc()).all())
    return {"templates": [{"id": t.id, "body": t.body} for t in rows]}


@router.post("/templates")
def create_template(payload: dict = Body(...), user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Шаблоны доступны преподавателям и администрации")
    body = (payload.get("body") or "").strip()[:500]
    if not body:
        raise HTTPException(status_code=400, detail="Пустой шаблон")
    count = db.query(MessageTemplate).filter(MessageTemplate.user_id == user.id).count()
    if count >= _MAX_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Не больше {_MAX_TEMPLATES} шаблонов")
    t = MessageTemplate(user_id=user.id, body=body, position=count, created_at=_now())
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "body": t.body}


@router.delete("/templates/{tid}")
def delete_template(tid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    t = (db.query(MessageTemplate)
         .filter(MessageTemplate.id == tid, MessageTemplate.user_id == user.id).first())
    if t is None:
        raise HTTPException(status_code=404, detail="Шаблон не найден")
    db.delete(t)
    db.commit()
    return {"ok": True}


# ── Открыть/создать личный чат ───────────────────────────────────────────────────────
def _ensure_direct(db: Session, user: User, peer: User) -> str:
    """id личного чата пары (создать, если его ещё нет). Идемпотентно: id детерминирован.
    ⚠️ Границы переписки (_guard_direct_allowed) проверяет ВЫЗЫВАЮЩИЙ — тут только беседа."""
    conv_id = direct_conversation_id(user.id, peer.id)
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if conv is None:
        now = _now()
        db.add(Conversation(id=conv_id, kind="direct", created_at=now))
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=user.id,
                                       role="member", joined_at=now))
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=peer.id,
                                       role="member", joined_at=now))
        db.commit()
    return conv_id


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
    #Проверяем ЗДЕСЬ, а не только в каталоге: id собеседника можно подставить руками, и
    #фильтр в поиске сам по себе ничего не защищает (инвариант «UI-скрытие — не защита»).
    _guard_direct_allowed(db, user, peer)

    conv_id = _ensure_direct(db, user, peer)
    sm = _status_map(db, [peer.id])
    return {"conversation_id": conv_id, "kind": "direct",
            "peer": _safe_user(peer, _online_logins(), status=sm.get(peer.id))}


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
        if p.cleared_upto_id:
            lastq = lastq.filter(Message.id > p.cleared_upto_id)
        if p.cleared_at:                     #legacy-строки, очищенные до появления id-границы
            lastq = lastq.filter(Message.created_at > p.cleared_at)
        last = lastq.order_by(Message.id.desc()).first()
        #Чат удалён у меня и с тех пор ничего не приходило — не показываем его в списке.
        #Появится новое сообщение — вернётся сам (см. _unhide_participants).
        if p.hidden and last is None:
            continue
        #Непрочитанное: чужие сообщения позже моей метки прочтения, не удалённые у всех.
        #Служебные события («вступил в беседу», «закреплено») в счётчик НЕ идут: это не
        #обращение к тебе, а отметка в ленте, а красный кружок непрочитанного заставляет
        #открыть чат — в канале на сотню читателей он не гас бы никогда.
        unread = (db.query(Message)
                  .filter(Message.conversation_id == conv.id,
                          Message.sender_id != user.id,
                          Message.kind != "system",
                          Message.deleted_at == "",
                          Message.created_at > (p.last_read_at or ""),
                          Message.created_at > (p.cleared_at or ""),
                          Message.id > (p.cleared_upto_id or 0))
                  .count())
        #Имя автора последнего сообщения нужно списку чатов (в группе/канале строка
        #выглядит как «Иванов: текст» — без имени непонятно, кто написал). В личном чате
        #и у своих сообщений имя не нужно: клиент подписывает их «Вы».
        sender_name = ""
        if last is not None and conv.kind in ("group", "channel") and last.sender_id != user.id:
            if last.sender_id == "system":
                sender_name = SYSTEM_SENDER_NAME
            else:
                su = db.query(User).filter(User.id == last.sender_id).first()
                sender_name = (su.full_name or su.name or "") if su else ""
        #Непрочитанная ОТМЕТКА меня: список чатов рисует «@» вместо числа сообщений, а
        #сам чат — кнопку перемотки к этому сообщению. Ищем самое РАННЕЕ непрочитанное
        #упоминание, а не последнее: перематывать нужно к началу пропущенного разговора,
        #иначе всё, что писали до отметки, так и останется непрочитанным.
        #mentions — JSON-список [{user_id, silent, loud}], поэтому фильтруем в Python:
        #переносимого способа искать по элементу JSON-массива в SQLite и PostgreSQL
        #одновременно нет (тот же приём, что в directory()).
        #⚠️ Список чатов опрашивается раз в 3.5 с, поэтому выборку сужаем ДО Python:
        #`body LIKE '%@%'` отсекает подавляющее большинство строк (отметка по построению
        #содержит «@» в тексте — mentions собирается из него же), а лимит держит запрос
        #дешёвым даже в канале на сотню непрочитанных. Без этого на одноядерном VPS
        #каждый тик вычитывал бы всю непрочитанную переписку по всем беседам сразу.
        mention_id, mention_loud = 0, False
        for cand in (db.query(Message)
                     .filter(Message.conversation_id == conv.id,
                             Message.sender_id != user.id,
                             Message.deleted_at == "",
                             Message.body.like("%@%"),
                             Message.created_at > (p.last_read_at or ""),
                             Message.id > (p.cleared_upto_id or 0))
                     .order_by(Message.id.asc()).limit(_MENTION_SCAN_LIMIT).all()):
            hit = next((x for x in (cand.mentions or []) if x.get("user_id") == user.id), None)
            if hit:
                mention_id, mention_loud = cand.id, bool(hit.get("loud"))
                break
        item = {
            "conversation_id": conv.id,
            "kind": conv.kind,
            "pinned": bool(p.pinned),
            "archived": bool(p.archived),
            "muted": bool(p.muted),
            "unread": unread,
            "mention_message_id": mention_id,     #0 — меня не отмечали
            "mention_loud": mention_loud,
            "last_message": _msg_out(last, user.id, sender_name) if last else None,
            "last_at": (last.created_at if last else conv.created_at) or "",
        }
        if conv.kind == "direct":
            peer = _peer_of_direct(db, conv.id, user.id)
            item["title"] = (peer.full_name or peer.name or peer.login) if peer else "Диалог"
            item["peer"] = _safe_user(peer, onl, status=_status_map(db, [peer.id]).get(peer.id)) if peer else None
        else:
            item["title"] = conv.title or ""
        out.append(item)
    #Номер отчёта в строке списка («📊 Отчёт №3 по группе К75/1») — иначе там оказался бы
    #сырой id из тела сообщения.
    _attach_rich_meta(db, [x["last_message"] for x in out if x["last_message"]], user.id)
    #Сортировка: сначала закреплённые, потом по времени последней активности (новые выше).
    out.sort(key=lambda x: (not x["pinned"], _neg_key(x["last_at"])))
    return {"chats": out}


def _neg_key(iso: str):
    """Ключ сортировки «по убыванию времени» для строковых ISO-меток (позже → выше)."""
    return "" if not iso else "".join(chr(255 - b) for b in iso.encode("utf-8"))


# ── Организация списка чатов: закреп/архив/избранное ─────────────────────────────────
# Дополнения из docs/MESSENGER-ADDON-PLAN-GPT*.md, отобранные как «действительно полезное
# и удобное» (без ИИ-упрощений учёбы — см. §5.4 CLAUDE.md). Личное состояние участника,
# как mute — на собеседника не влияет.
@router.post("/chats/{conv_id}/pin")
def pin_chat(conv_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Закрепить чат в списке у СЕБЯ (сортировка — см. list_chats)."""
    part = _require_participant(db, conv_id, user)
    part.pinned = True
    db.commit()
    return {"ok": True}


@router.delete("/chats/{conv_id}/pin")
def unpin_chat(conv_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    part = _require_participant(db, conv_id, user)
    part.pinned = False
    db.commit()
    return {"ok": True}


@router.post("/chats/{conv_id}/archive")
def archive_chat(conv_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """В архив — чат уходит из основного списка, но НЕ удаляется (в отличие от DELETE
    /chats/{conv_id}). В отличие от «удалить у себя» (hidden), новое сообщение чат из
    архива само не выводит — только явная расархивация, это и есть смысл архива."""
    part = _require_participant(db, conv_id, user)
    part.archived = True
    db.commit()
    return {"ok": True}


@router.delete("/chats/{conv_id}/archive")
def unarchive_chat(conv_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    part = _require_participant(db, conv_id, user)
    part.archived = False
    db.commit()
    return {"ok": True}


def _saved_conv_id(user_id: str) -> str:
    return f"saved:{user_id}"


def _ensure_saved(db: Session, user: User) -> str:
    """id «Избранного» пользователя (создать лениво при первом обращении)."""
    conv_id = _saved_conv_id(user.id)
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if conv is None:
        now = _now()
        db.add(Conversation(id=conv_id, kind="saved", title="Избранное",
                            owner_id=user.id, created_at=now))
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=user.id,
                                       role="owner", joined_at=now, pinned=True))
        db.commit()
    return conv_id


@router.post("/chats/saved")
def open_saved(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """«Избранное» (Saved Messages) — личный чат с самим собой: заметки, ссылки, код себе,
    без надобности заводить отдельную сущность заметок — переиспользуем ВСЮ инфраструктуру
    сообщений (Markdown, реакции, правка, пересылка). Один на пользователя, создаётся лениво
    при первом открытии. Закреплён по умолчанию — как в Telegram, всегда сверху списка."""
    return {"conversation_id": _ensure_saved(db, user)}


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
    if part.cleared_upto_id:
        q = q.filter(Message.id > part.cleared_upto_id)
    if part.cleared_at:                      #legacy-строки (очищены до id-границы)
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
    out = [_msg_out(m, user.id, names.get(m.sender_id, "")) for m in rows]
    _attach_reactions(db, out, user.id)      #§D3: реакции пачкой
    _attach_reply_counts(db, out)            #Треды: бейдж «N ответов»
    _attach_rich_meta(db, out, user.id)               #кнопки: отчёт куратора, активность, доска
    return {"messages": out}


@router.get("/chats/{conv_id}/messages/thread/{message_id}")
def message_thread(conv_id: str, message_id: int,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Треды: ответы на КОНКРЕТНОЕ сообщение этой беседы (см. `_attach_reply_counts`).
    Своей сущности «ветки» не заводим — фильтр по уже существующему `reply_to_id`."""
    _require_participant(db, conv_id, user)
    hidden = _hidden_ids(db, conv_id, user.id)
    q = (db.query(Message)
         .filter(Message.conversation_id == conv_id, Message.reply_to_id == message_id))
    if hidden:
        q = q.filter(~Message.id.in_(hidden))
    rows = q.order_by(Message.id.asc()).all()
    names = _names_for(db, [m.sender_id for m in rows])
    out = [_msg_out(m, user.id, names.get(m.sender_id, "")) for m in rows]
    _attach_reactions(db, out, user.id)
    _attach_rich_meta(db, out, user.id)               #иначе в ветке ответов вместо кнопки сырой id
    return {"messages": out}


@router.get("/chats/{conv_id}/messages/search")
def search_messages(conv_id: str, q: str = Query(""), limit: int = Query(50),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Поиск по тексту ВНУТРИ одной беседы. Регистронезависимое вхождение делаем в Python
    (та же причина, что и в directory(): SQLite без ICU не даёт регистронезависимый LIKE
    для кириллицы, а объём переписки учебного заведения в память умещается)."""
    part = _require_participant(db, conv_id, user)
    needle = (q or "").strip().lower()
    if not needle:
        return {"messages": []}
    hidden = _hidden_ids(db, conv_id, user.id)
    qq = (db.query(Message)
          .filter(Message.conversation_id == conv_id, Message.deleted_at == "",
                  Message.kind == "text"))
    if part.cleared_upto_id:
        qq = qq.filter(Message.id > part.cleared_upto_id)
    if part.cleared_at:                      #legacy-строки (очищены до id-границы)
        qq = qq.filter(Message.created_at > part.cleared_at)
    if hidden:
        qq = qq.filter(~Message.id.in_(hidden))
    rows = qq.order_by(Message.id.desc()).limit(2000).all()   #верхняя граница выборки
    limit = max(1, min(int(limit or 50), 100))
    matched = [m for m in rows if needle in (m.body or "").lower()][:limit]
    names = _names_for(db, [m.sender_id for m in matched])
    out = [_msg_out(m, user.id, names.get(m.sender_id, "")) for m in matched]
    _attach_rich_meta(db, out, user.id)
    return {"messages": out}


def _visible_messages_query(db: Session, conv_id: str, part, user_id: str):
    """Базовая выборка ВИДИМЫХ пользователю сообщений беседы (границы очистки и скрытия).

    Вынесено из search_messages, чтобы умный поиск и сводка не собирали те же условия
    заново: забытая граница `cleared_upto_id` означала бы показ переписки, которую человек
    у себя удалил."""
    hidden = _hidden_ids(db, conv_id, user_id)
    qq = (db.query(Message)
          .filter(Message.conversation_id == conv_id, Message.deleted_at == "",
                  Message.kind == "text"))
    if part.cleared_upto_id:
        qq = qq.filter(Message.id > part.cleared_upto_id)
    if part.cleared_at:                      #legacy-строки (очищены до id-границы)
        qq = qq.filter(Message.created_at > part.cleared_at)
    if hidden:
        qq = qq.filter(~Message.id.in_(hidden))
    return qq


@router.get("/chats/{conv_id}/messages/ai-search")
def ai_search_messages(conv_id: str, q: str = Query(""), limit: int = Query(30),
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """§17: поиск по СМЫСЛУ внутри беседы.

    Как это устроено и почему именно так: модель получает ТОЛЬКО поисковый запрос и
    придумывает к нему словоформы и синонимы («домашка» → «дз», «задание», «задали»), а
    сопоставление с сообщениями делаем мы сами. Переписка модели не показывается вовсе.

    Настоящий семантический поиск (эмбеддинги + векторный индекс) потребовал бы
    проиндексировать всю переписку и держать индекс в памяти — на боевом одноядерном VPS
    с 960 МБ это не поедет, а отправлять чужие сообщения в облако ради поиска тем более
    нельзя. Расширение запроса даёт основную пользу без обеих этих цен.

    Модель недоступна → `expanded` пуст и результат совпадает с обычным поиском."""
    part = _require_participant(db, conv_id, user)
    needle = (q or "").strip().lower()
    if not needle:
        return {"messages": [], "expanded": []}

    from ..webdata import load_config
    from .. import messenger_ai
    extra = messenger_ai.expand_query(load_config(db), needle)

    rows = (_visible_messages_query(db, conv_id, part, user.id)
            .order_by(Message.id.desc()).limit(2000).all())
    scored = []
    for m in rows:
        score = messenger_ai.match_score(m.body, needle, extra)
        if score:
            scored.append((score, m))
    #Сортировка: сначала релевантность, при равной — свежие выше (id убывает).
    scored.sort(key=lambda p: (p[0], p[1].id), reverse=True)
    limit = max(1, min(int(limit or 30), 100))
    matched = [m for _s, m in scored[:limit]]
    names = _names_for(db, [m.sender_id for m in matched])
    out = [_msg_out(m, user.id, names.get(m.sender_id, "")) for m in matched]
    _attach_rich_meta(db, out, user.id)
    return {"messages": out,
            "expanded": extra}


@router.get("/chats/{conv_id}/summary")
def chat_summary(conv_id: str, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """§18: краткая сводка переписки.

    Запускается ТОЛЬКО кнопкой. Автоматическая сводка при открытии чата означала бы запрос
    к модели на каждый вход в диалог — на одноядерном VPS это заметная нагрузка и лишние
    деньги за токены ради текста, который чаще всего никто не прочтёт.

    ФИО реальных людей маскируются ДО отправки (messenger_ai.mask_names): сообщения здесь
    модели действительно нужны, но персональные данные в облако уезжать не должны.

    Результат кэшируется по (беседа, id последнего сообщения) — пока в чат никто не
    написал, повторное нажатие отдаёт готовое и ничего не стоит."""
    part = _require_participant(db, conv_id, user)
    rows = (_visible_messages_query(db, conv_id, part, user.id)
            .order_by(Message.id.asc()).all())
    if len(rows) < 3:
        return {"summary": "", "reason": "too_short", "messages": len(rows)}

    #В ключ входит и МЕТКА последнего сообщения, не только его id. Причина не
    #теоретическая: id — автоинкремент внутри базы, и после восстановления сервера из
    #бэкапа они начинают выдаваться заново. Кэш в памяти процесса это переживёт и отдал бы
    #сводку ЧУЖОГО (уже несуществующего) разговора. Метка времени такой коллизии не даёт.
    cache_key = (conv_id, rows[-1].id, rows[-1].created_at)
    cached = _SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return {"summary": cached, "cached": True, "messages": len(rows)}

    from ..webdata import load_config
    from .. import messenger_ai
    names = _names_for(db, [m.sender_id for m in rows])
    transcript = messenger_ai.build_transcript(db, rows, names)
    summary = messenger_ai.summarize(load_config(db), transcript)
    if not summary:
        #Честно говорим, что не получилось, вместо выдуманного текста.
        return {"summary": "", "reason": "no_model", "messages": len(rows)}
    #Кэш маленький и в памяти: переживать перезапуск ему незачем, а место на VPS дорого.
    if len(_SUMMARY_CACHE) > 200:
        _SUMMARY_CACHE.clear()
    _SUMMARY_CACHE[cache_key] = summary
    return {"summary": summary, "cached": False, "messages": len(rows)}


# ── §19. Напоминания из сообщений ───────────────────────────────────────────────────
# Разбор даты ДЕТЕРМИНИРОВАННЫЙ (reminder_parse.py в корне репо), без модели — несмотря на
# название фичи в плане. Причина та же, что у записи оценок голосом: «завтра в 15:00»
# регулярка разбирает надёжнее, чем LLM, а модель ошибается МОЛЧА — напоминание, съехавшее
# на день, хуже ненайденного, потому что на него уже положились. Плюс это приватность:
# текст личной переписки никуда не уезжает.

def _reminder_out(r) -> dict:
    return {"id": r.id, "conversation_id": r.conversation_id, "message_id": r.message_id,
            "text": r.text, "remind_at": r.remind_at, "fired_at": r.fired_at or ""}


@router.get("/messages/{mid}/reminder-suggest")
def reminder_suggest(mid: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Что предложить напомнить по этому сообщению. `when` пустой — даты не нашли.

    Функция намеренно консервативна: не уверена — не предлагает. Ложная подсказка
    раздражает сильнее, чем её отсутствие."""
    m = db.query(Message).filter(Message.id == mid).first()
    if m is None or m.deleted_at:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _require_participant(db, m.conversation_id, user)
    import reminder_parse
    found = reminder_parse.parse_reminder(m.body or "", datetime.now(timezone.utc))
    if not found:
        return {"when": "", "matched": ""}
    return {"when": found["when"].isoformat(), "matched": found["matched"]}


@router.post("/messages/{mid}/reminder")
def reminder_create(mid: int, payload: dict = Body(default={}),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Поставить напоминание по сообщению. `when` (ISO) — явно выбранное время; без него
    берём разобранное из текста."""
    from ..models import Reminder
    m = db.query(Message).filter(Message.id == mid).first()
    if m is None or m.deleted_at:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _require_participant(db, m.conversation_id, user)

    when = (payload.get("when") or "").strip()
    if not when:
        import reminder_parse
        found = reminder_parse.parse_reminder(m.body or "", datetime.now(timezone.utc))
        if not found:
            raise HTTPException(status_code=400,
                                detail="В сообщении нет даты — укажите время вручную.")
        when = found["when"].isoformat()
    try:
        parsed = datetime.fromisoformat(when)
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверный формат времени") from None
    if parsed.tzinfo is None:
        #Клиент прислал локальное время без зоны. Считаем его UTC — иначе сравнение с
        #remind_at (тоже UTC) было бы сдвинуто на часовой пояс.
        parsed = parsed.replace(tzinfo=timezone.utc)

    #Текст храним СНИМКОМ: автор может отредактировать или удалить сообщение, а напоминание
    #должно остаться тем, на что человек рассчитывал.
    row = Reminder(login=user.login or "", conversation_id=m.conversation_id,
                   message_id=m.id, text=(m.body or "")[:1000],
                   remind_at=parsed.isoformat(), created_at=_now(), fired_at="")
    db.add(row)
    db.commit()
    return {"ok": True, "reminder": _reminder_out(row)}


@router.get("/reminders")
def reminders_list(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Мои ещё не сработавшие напоминания (ближайшие сверху)."""
    from ..models import Reminder
    rows = (db.query(Reminder)
            .filter(Reminder.login == (user.login or ""), Reminder.fired_at == "")
            .order_by(Reminder.remind_at.asc()).limit(100).all())
    return {"reminders": [_reminder_out(r) for r in rows]}


@router.delete("/reminders/{rid}")
def reminder_delete(rid: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Отменить напоминание. Чужое не трогаем — 404 одинаков для «нет» и «не твоё»."""
    from ..models import Reminder
    row = db.get(Reminder, rid)
    if row is None or row.login != (user.login or ""):
        raise HTTPException(status_code=404, detail="Напоминание не найдено")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/messages/{mid}/read_by")
def message_read_by(mid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Кто прочитал сообщение — переиспользует УЖЕ существующий per-участнику
    `last_read_at` (без новой таблицы «строка на каждое прочтение каждым»): читатель —
    участник, чья метка прочтения НЕ РАНЬШЕ момента отправки этого сообщения."""
    m = db.query(Message).filter(Message.id == mid).first()
    if m is None:
        raise HTTPException(status_code=404, detail="Сообщение не найдено")
    _require_participant(db, m.conversation_id, user)
    rows = (db.query(ConversationParticipant)
            .filter(ConversationParticipant.conversation_id == m.conversation_id,
                    ConversationParticipant.user_id != m.sender_id,
                    ConversationParticipant.last_read_at >= m.created_at).all())
    ids = [r.user_id for r in rows]
    if not ids:
        return {"users": []}
    #⚠️ (живой отзыв Влада, панель «Реакции» в контекстном меню) Точки «когда именно
    #прочитали ИМЕННО ЭТО сообщение» у нас нет и заводить её не будем (см. докстринг
    #выше — сознательно без новой таблицы «строка на каждое прочтение каждым»). Честная
    #замена — last_read_at участника: раз он ≥ момента отправки, значит человек дошёл
    #этим чтением как минимум досюда, и last_read_at — самая точная метка, какая у нас
    #есть. Как в Telegram — не «увидел именно эту секунду», а «где он сейчас в ленте».
    read_at_by_id = {r.user_id: (r.last_read_at or "") for r in rows}
    onl = _online_logins()
    users = db.query(User).filter(User.id.in_(ids)).all()
    return {"users": [dict(_safe_user(u, onl), last_read_at=read_at_by_id.get(u.id, ""))
                      for u in users]}


# ── Перевод ──────────────────────────────────────────────────────────────────────────
@router.post("/translate")
def translate_text(payload: dict = Body(...), user: User = Depends(get_current_user)):
    """Перевести произвольный текст на выбранный язык.

    Эндпоинт НЕ привязан к сообщению намеренно: им пользуется и кнопка «перевести» на
    чужой реплике, и предпросмотр своего текста до отправки. Привязка к id сообщения
    добавила бы проверку участия там, где переводится собственный черновик.

    Своего лимита частоты нет: перевод идёт по нажатию человека, а результат кэшируется
    (одну реплику в групповом чате открывают несколько человек). Автоперевод исходящих
    ограничен тем же анти-флудом, что и сама отправка. ⚠️ Переводчик — Google Translate
    (3.5.5, см. translate_service.py), от БД больше не зависит вовсе."""
    from .. import translate_service
    text = (payload.get("text") or "").strip()
    dst = (payload.get("to") or "").strip().lower()
    src = (payload.get("from") or translate_service.AUTO).strip().lower()
    if not text:
        raise HTTPException(status_code=400, detail="Нужен текст")
    return translate_service.translate(text, dst, src)


@router.get("/translate/languages")
def translate_languages(_user: User = Depends(get_current_user)):
    """Список языков одним источником: клиент не держит свою копию, иначе однажды
    покажет язык, которого сервер не знает."""
    from .. import translate_service
    return {"languages": [{"code": c, "name": n}
                          for c, n in translate_service.LANGUAGES.items()],
            "auto": translate_service.AUTO}


# ── GIF-пикер (Klipy) ────────────────────────────────────────────────────────────────
@router.get("/gifs/categories")
def gif_categories(_user: User = Depends(get_current_user)):
    from .. import gif_service
    return {"categories": gif_service.categories()}


@router.get("/gifs/trending")
def gif_trending(page: int = Query(1, ge=1), _user: User = Depends(get_current_user)):
    from .. import gif_service
    return gif_service.trending(page=page)


@router.get("/gifs/search")
def gif_search(q: str = Query(...), page: int = Query(1, ge=1),
              _user: User = Depends(get_current_user)):
    from .. import gif_service
    return gif_service.search(q, page=page)


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
    if part.silenced:                        #«/mute»-заглушка модератора — не глобальный мьют
        raise HTTPException(status_code=403, detail="Вы заглушены в этой беседе")
    _guard_can_write(db, user)               #глобальный мьют (403) + анти-флуд (429)
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Пустое сообщение")
    #GIF-пикер (Klipy, §messenger_gifs): тело — прямая ссылка на CDN, а не текст, набранный
    #человеком. Слэш-команды/упоминания/цензура ниже пропускаются целиком для этого вида —
    #прогонять URL через censor() рискованно: случайное совпадение с корнем матерного слова
    #испортило бы саму ссылку (censor меняет символы НА МЕСТЕ, длина та же).
    is_gif = (payload.get("kind") or "").strip() == "gif"
    if is_gif:
        from .. import gif_service
        if not gif_service.is_allowed_url(body):
            raise HTTPException(status_code=400, detail="Недопустимая ссылка на GIF")
    elif len(body) > _MAX_MSG_CHARS:
        body = body[:_MAX_MSG_CHARS]
    reply_to = int(payload.get("reply_to_id") or 0)
    if reply_to:
        ok = (db.query(Message)
              .filter(Message.id == reply_to, Message.conversation_id == conv_id).first())
        if ok is None:
            reply_to = 0                     #ответ на чужое/несуществующее — игнорируем связь

    #§D10: идемпотентность. Повторный POST с тем же client_nonce (ретрай при обрыве сети)
    #возвращает уже созданное сообщение, а не плодит дубль.
    nonce = str(payload.get("client_nonce") or "").strip()[:64]
    if nonce:
        dup = (db.query(Message)
               .filter(Message.conversation_id == conv_id, Message.client_nonce == nonce).first())
        if dup is not None:
            out = _msg_out(dup, user.id, user.full_name or user.name or user.login or "")
            _attach_rich_meta(db, [out], user.id)
            return out

    mentions = []
    if not is_gif:
        #§12: «/отчет [группа]» — команда, а не сообщение: разбираем ДО сохранения и отдаём
        #созданную кнопку отчёта. Иначе текст команды оставался бы в ленте мусором (особенно
        #заметным в чате родителей), а ошибка («не та группа», «нет прав») тонула молча.
        #⚠️ ПОСЛЕ проверки nonce: отчёт — это запись в БД, и повтор запроса (ретрай сети,
        #двойное нажатие) не должен плодить второй такой же. Тот же nonce уезжает и в
        #сообщение-кнопку, поэтому ретрай находит её выше и возвращает как есть.
        rep_msg = _handle_report_command(db, conv_id, body, user, nonce)
        if rep_msg is not None:
            out = _msg_out(rep_msg, user.id, user.full_name or user.name or user.login or "")
            _attach_rich_meta(db, [out], user.id)     #иначе клиент получит сырой id вместо кнопки
            return out

        #/mute, /clear — тоже команды, не сообщения: разбираем ДО сохранения текста (как
        #/отчет выше), иначе литеральная строка команды осела бы в ленте мусором.
        mute_msg = _handle_mute_command(db, conv_id, body, user, part)
        if mute_msg is not None:
            return _msg_out(mute_msg, user.id, "")
        clear_msg = _handle_clear_command(db, conv_id, body, user, part)
        if clear_msg is not None:
            return _msg_out(clear_msg, user.id, "")

        #§D8: упоминания — среди участников ЭТОЙ беседы (иначе @Фамилия постороннего человека
        #молча ни на что бы не сработала, но и не должна давать доступ к чужим данным).
        mentions = _parse_mentions(db, body, _participant_ids(db, conv_id))

        #Цензура мата — маскируем звёздочками (НЕ блокируем отправку, как автомодерация
        #Twitch/Discord). После всех slash-команд (иначе испортили бы их разбор) и ПОСЛЕ
        #упоминаний (плейсхолдер @Фамилия матом не считается), но ДО сохранения — что легло
        #в БД, то и видят все читатели постфактум. `body` переиспользуется ниже в
        #_handle_vector_command — так что и вопрос Вектору уходит уже очищенным.
        import profanity_filter
        body = profanity_filter.censor(body, mask=profanity_filter.MESSENGER_SAFE_MASK)

    m = Message(conversation_id=conv_id, sender_id=user.id, body=body,
                created_at=_now(), reply_to_id=reply_to, mentions=mentions,
                kind="gif" if is_gif else "text",
                body_format="plain" if is_gif else "markdown", client_nonce=nonce)
    db.add(m)
    db.commit()
    db.refresh(m)
    #Отправитель прочитал свою же беседу вплоть до этого сообщения.
    _mark_read(db, conv_id, user.id, m.created_at)
    _unhide_participants(db, conv_id)        #«удалённый» чат возвращается с новым сообщением
    _broadcast(db, conv_id)                  #живой сигнал участникам (WS)
    silent_ids = {mm["user_id"] for mm in mentions if mm.get("silent")}
    _notify_recipients(db, conv, user, skip_ids=silent_ids)   #пуш офлайн — минус тихие упоминания
    #Громкая отметка (`/@!Фамилия`) — звук у получателя (его включает клиент по флагу
    #`loud` в mentions) + письмо в «Систему». Ставим ПОСЛЕ обычной рассылки: обычный пуш
    #о сообщении и «вас отметили» — разные события, и второе не должно съесть первое.
    _notify_loud_mentions(db, conv, user, mentions)
    if is_gif:
        #Best-effort, ПОСЛЕ commit — статистика показов Klipy не имеет права мешать уже
        #созданному сообщению, даже если их API прямо сейчас недоступен.
        from .. import gif_service
        gif_service.mark_shared((payload.get("gif_slug") or "").strip())
    else:
        _handle_vector_command(db, conv_id, body, user, reply_to=reply_to)
    return _msg_out(m, user.id, user.full_name or user.name or user.login or "")


_VECTOR_CMD_RE = re.compile(r"^/vector(?:@\w+)?\s*(.*)$", re.IGNORECASE | re.DOTALL)

#Сколько последних заметок отдаём Вектору как контекст и сколько символов максимум.
#Ограничение не косметическое: длинный контекст — это и деньги за токены, и риск, что
#модель начнёт отвечать по заметке вместо журнала.
_CTX_MESSAGES = 20
_CTX_CHARS = 1500


def _mask_names(db: Session, text: str) -> str:
    """Заменяет ФИО реальных пользователей на «Студент»/«Преподаватель».

    ⚠️ ОБЯЗАТЕЛЬНО перед отправкой в облачную модель: заметки — свободный текст, и в них
    легко попадают фамилии одногруппников. Продукт публично обещает, что ПДн в облако не
    уходят (README, §6), и заметки — не исключение. Маскируем от длинных совпадений к
    коротким, иначе «Иванов» съел бы «Иванов Иван» и остаток имени утёк бы."""
    rows = db.query(User).filter(User.deleted == False).all()          # noqa: E712
    pairs = []
    for u in rows:
        label = "Преподаватель" if u.role == "teacher" else "Студент"
        for name in (u.full_name, u.surname, u.name):
            if name and len(name.strip()) >= 3:
                pairs.append((name.strip(), label))
    for name, label in sorted(pairs, key=lambda p: -len(p[0])):
        if name.lower() in text.lower():
            text = re.sub(re.escape(name), label, text, flags=re.IGNORECASE)
    return text


def _saved_context(db: Session, conv_id: str, user: User) -> str:
    """Последние заметки «Избранного» — контекст для команды /vector.

    Зачем: без него вопрос «а когда это?» или «что я писал про экзамен» опирается только на
    формулировку самого вопроса. Берём ТОЛЬКО этот личный чат (он виден одному человеку),
    свежие сообщения, без удалённых, и обезличиваем перед отправкой в модель."""
    part = _participant(db, conv_id, user.id)
    q = db.query(Message).filter(Message.conversation_id == conv_id,
                                 Message.deleted_at == "")
    if part is not None and part.cleared_upto_id:
        q = q.filter(Message.id > part.cleared_upto_id)      #очищенное не воскрешаем
    rows = q.order_by(Message.id.desc()).limit(_CTX_MESSAGES).all()
    rows.reverse()
    lines = []
    for m in rows:
        body = (m.body or "").strip()
        #Сами команды в контекст не тянем — это шум, а не заметка.
        if not body or _VECTOR_CMD_RE.match(body):
            continue
        who = "Вектор" if m.sender_id == "system" else "Я"
        lines.append(f"{who}: {body}")
    text = "\n".join(lines)[-_CTX_CHARS:]
    return _mask_names(db, text) if text else ""


def _is_vector_message(db: Session, conv_id: str, message_id: int) -> bool:
    """Является ли сообщение ответом Вектора в ЭТОЙ беседе (отправитель — 'system')."""
    if not message_id:
        return False
    row = (db.query(Message)
           .filter(Message.id == message_id, Message.conversation_id == conv_id).first())
    return row is not None and row.sender_id == SYSTEM_SENDER_ID


def _handle_vector_command(db: Session, conv_id: str, body: str, user: User,
                           reply_to: int = 0) -> None:
    """`docs/MESSENGER-ADDON-PLAN-GPT.md`: «AI-поиск по смыслу» — реализован не как отдельная
    embedding-инфраструктура (её негде держать на 1-ядерном VPS), а как переиспользование УЖЕ
    существующего анти-галлюцинационного Вектора (`web.py::answer_vector_question`, тот же
    код, что у `/web/vector/ask`). try/except: сбой ИИ-ответа не должен мешать самой
    отправке сообщения — она уже прошла и закоммичена выше.

    ⚠️ ТОЛЬКО в «Избранном» (личный чат с собой). Раньше команда работала в ЛЮБОМ чате, и
    ответ Вектора публиковался всем участникам: в общей беседе это и шум, и утечка контекста
    вопроса, а роль-скоуп ответа считается по СПРОСИВШЕМУ — соседи по чату увидели бы
    выборку, к которой сами доступа не имеют. Личный чат снимает оба вопроса сразу.

    ДВА способа спросить, оба только в «Избранном»:
      • `/vector <вопрос>` — как раньше, начало разговора;
      • ОТВЕТ (reply) на реплику Вектора — продолжение цепочки БЕЗ повторного префикса.
    Второй способ добавлен потому, что диалог из нескольких уточнений требовал писать
    «/vector» на каждой строке, хотя адресат из ответа и так однозначен. Отвечать на
    СВОЁ сообщение при этом ничего не запускает: адресат там не Вектор, и обычная
    цитата в личных заметках не должна внезапно уходить в модель."""
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if conv is None or conv.kind != "saved":
        return
    match = _VECTOR_CMD_RE.match(body.strip())
    if match:
        question = match.group(1).strip()
    elif _is_vector_message(db, conv_id, reply_to):
        question = body.strip()          #ответ на реплику Вектора — весь текст и есть вопрос
    else:
        return
    if not question:
        return
    try:
        from .web import answer_vector_question, user_ui_locale
        answer = answer_vector_question(question, user, db,
                                        context=_saved_context(db, conv_id, user),
                                        locale=user_ui_locale(user))
        text = (answer.get("text") or "").strip()
        if text:
            _post_system_channel_message(db, conv_id, text)
    except Exception:
        pass


# ── Прочтение ────────────────────────────────────────────────────────────────────────
def _mark_read(db: Session, conv_id: str, user_id: str, upto_iso: str) -> None:
    p = _participant(db, conv_id, user_id)
    if p is not None and upto_iso and upto_iso > (p.last_read_at or ""):
        p.last_read_at = upto_iso
        db.commit()
        #Живой сигнал собеседнику: галочка «отправлено→прочитано» в ЛС должна смениться,
        #пока оба ещё в чате, а не только при следующем входе (см. ChatThread.vue).
        _broadcast(db, conv_id)


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
    #Границу ставим по НОМЕРУ последнего сообщения, а не по времени: сообщение, пришедшее
    #в тот же тик часов, что и очистка, иначе исчезло бы у пользователя навсегда.
    #cleared_at гасим — он остаётся только у строк, очищенных до появления этого поля.
    last = (db.query(Message).filter(Message.conversation_id == conv_id)
            .order_by(Message.id.desc()).first())
    p.cleared_upto_id = last.id if last else 0
    p.cleared_at = ""
    p.last_read_at = _now()                #«хвоста» непрочитанного после очистки нет
    #«Избранное» — не переписка, а личный блокнот: он один на пользователя и всегда есть в
    #списке (как в Telegram). Удалять его нечего и незачем — любое удаление сводим к очистке.
    if conv.kind == "saved":
        db.commit()
        return {"ok": True, "conversation_id": conv_id, "cleared": True}
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

# ── Роли и права внутри беседы (кастомные роли групп/каналов) ─────────────────────────
# Фиксированный небольшой набор прав — ровно то, что просили (кик, выдача ролей, две
# модераторские команды), без раздувания в гранулярную матрицу.
#`activities` — запуск активностей в беседе (docs/PLAN-ACTIVITIES.md §3). Системная роль
#teacher/admin даёт его и БЕЗ роли беседы (проверка — в routers/activities._require_can_run):
#преподаватель ведёт занятие, а не администрирует чат, и просить владельца чата выдать
#ему роль ради этого странно. Здесь право нужно, чтобы владелец мог выдать его старосте.
_ALL_PERMISSIONS = ("kick", "manage_roles", "cmd_mute", "cmd_clear", "activities")
#Дефолт для БИЛДОВЫХ ролей, когда участнику не назначена кастомная ConversationRole —
#эквивалент того, что раньше жёстко проверял _MANAGER_ROLES (owner/admin), чтобы уже
#существующие беседы без единой кастомной роли продолжали работать ровно как раньше.
_DEFAULT_ROLE_PERMISSIONS = {"owner": set(_ALL_PERMISSIONS), "admin": set(_ALL_PERMISSIONS)}


def _permissions_for(db: Session, part: ConversationParticipant) -> set:
    """Права участника В ЭТОЙ беседе. owner — всегда полный набор (создателя не разжаловать
    этим путём). Иначе — кастомная роль, если назначена; иначе — дефолт по билдовой role."""
    if part.role == "owner":
        return set(_ALL_PERMISSIONS)
    if part.custom_role_id:
        cr = db.query(ConversationRole).filter(ConversationRole.id == part.custom_role_id).first()
        if cr is not None:
            return set(cr.permissions or [])
    return set(_DEFAULT_ROLE_PERMISSIONS.get(part.role, ()))


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
    #Цензура — ДО обрезки по длине (не после): если резать сначала, граница могла бы
    #попасть внутрь найденного слова и оставить необработанный обрубок незацензуренным
    #(см. тот же порядок в send_message).
    import profanity_filter
    body = profanity_filter.censor(body, mask=profanity_filter.MESSENGER_SAFE_MASK)
    #§D11: сохраняем текст ДО правки — модерация должна видеть оригинал (автор мог исправить
    #сообщение после жалобы). Пустых снимков не плодим.
    if (m.body or "") and m.body != body[:_MAX_MSG_CHARS]:
        db.add(MessageEdit(message_id=m.id, body_before=m.body, edited_at=_now()))
    m.body = body[:_MAX_MSG_CHARS]
    m.edited_at = _now()
    db.commit()
    db.refresh(m)
    _broadcast(db, m.conversation_id)
    return _msg_out(m, user.id)


@router.get("/messages/{mid}/history")
def message_history(mid: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """§D11: история редактирования сообщения (участникам беседы). Показывает версии ДО
    правок + текущий текст — чтобы было видно, что менялось."""
    m = _message_in_conv(db, mid)
    _require_participant(db, m.conversation_id, user)
    edits = (db.query(MessageEdit).filter(MessageEdit.message_id == mid)
             .order_by(MessageEdit.id.asc()).all())
    versions = [{"body": e.body_before, "at": e.edited_at} for e in edits]
    versions.append({"body": m.body or "", "at": m.edited_at or m.created_at, "current": True})
    return {"versions": versions}


# ── Реакции (§D3) ────────────────────────────────────────────────────────────────────
@router.post("/messages/{mid}/reactions")
def add_reaction(mid: int, payload: dict = Body(...),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Поставить реакцию-эмодзи (из белого списка). Идемпотентно: та же реакция от того же
    пользователя не дублируется."""
    emoji = str(payload.get("emoji") or "")
    if emoji not in _REACTIONS:
        raise HTTPException(status_code=400, detail="Недопустимая реакция")
    m = _message_in_conv(db, mid)
    _require_participant(db, m.conversation_id, user)
    if m.deleted_at:
        raise HTTPException(status_code=400, detail="Сообщение удалено")
    exists = (db.query(MessageReaction)
              .filter(MessageReaction.message_id == mid, MessageReaction.user_id == user.id,
                      MessageReaction.emoji == emoji).first())
    if exists is None:
        db.add(MessageReaction(message_id=mid, user_id=user.id, emoji=emoji, created_at=_now()))
        db.commit()
        _broadcast(db, m.conversation_id)
    return {"ok": True}


@router.delete("/messages/{mid}/reactions/{emoji}")
def remove_reaction(mid: int, emoji: str, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Снять СВОЮ реакцию."""
    m = _message_in_conv(db, mid)
    _require_participant(db, m.conversation_id, user)
    row = (db.query(MessageReaction)
           .filter(MessageReaction.message_id == mid, MessageReaction.user_id == user.id,
                   MessageReaction.emoji == emoji).first())
    if row is not None:
        db.delete(row)
        db.commit()
        _broadcast(db, m.conversation_id)
    return {"ok": True}


@router.get("/messages/{mid}/reactions")
def list_reactions(mid: int, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Кто какие реакции поставил (для попапа «кто поставил»)."""
    m = _message_in_conv(db, mid)
    _require_participant(db, m.conversation_id, user)
    rows = db.query(MessageReaction).filter(MessageReaction.message_id == mid).all()
    names = _names_for(db, [r.user_id for r in rows])
    out = {}
    for r in rows:
        out.setdefault(r.emoji, []).append(names.get(r.user_id, r.user_id))
    return {"reactions": [{"emoji": e, "users": u, "count": len(u)} for e, u in out.items()]}


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
    _system(db, m.conversation_id, "pin_added", str(mid))     #§D6
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
    _system(db, m.conversation_id, "pin_removed", str(mid))   #§D6
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
    out = [_msg_out(m, user.id) for m in rows]
    _attach_rich_meta(db, out, user.id)               #закреплённая карточка активности — не сырой id
    return {"pinned": out}


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
            #§12: отчёт по группе — это оценки ВСЕЙ группы. Куда он поедет дальше, решает
            #куратор/администрация; родитель или студент, получивший кнопку, переслать её
            #уже не может (иначе успеваемость группы разошлась бы по чужим чатам).
            if (src.kind or "") == "report" and user.role not in ("teacher", "admin"):
                continue
            #🔒 Карточки активности и доски НЕ пересылаются вовсе. Они привязаны к своей
            #беседе: открыть их снаружи нельзя (403 в `_require_activity_participant`), то
            #есть в чужой ленте повисла бы кнопка, которая ни у кого не работает, — а
            #вместе с ней уехали бы заголовок и статус (заголовок пишет преподаватель, там
            #бывает тема контрольной). Возражение Полковника, 15.08.2026.
            if (src.kind or "") in ("activity", "board"):
                continue
            sender = db.query(User).filter(User.id == src.sender_id).first()
            #Источник пересылки — исходный автор оригинала (а не тот, кто раньше переслал).
            db.add(Message(
                conversation_id=conv_id, sender_id=user.id, body=src.body, created_at=_now(),
                #Тип и формат обязаны переехать вместе с телом: без них пересланная кнопка
                #отчёта превращалась в текстовое сообщение с сырым id («rpt:К75/1|3»).
                kind=(src.kind or "text"), body_format=(src.body_format or "markdown"),
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


def _require_permission(db: Session, conv_id: str, user: User, permission: str) -> ConversationParticipant:
    """Как _require_manager, но по гранулярному праву (kick/manage_roles/cmd_mute/
    cmd_clear) — учитывает кастомную роль участника, а не только билдовую owner/admin."""
    p = _require_participant(db, conv_id, user)
    if permission not in _permissions_for(db, p):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return p


@router.post("/chats/group")
def create_group(payload: dict = Body(...), user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Создать группу: создатель — owner, выбранные — участники (member).

    `class_groups` (§12, режим куратора) — названия УЧЕБНЫХ групп (не путать с чат-
    группой): все студенты этих групп добавляются автоматически, вперемешку с
    индивидуально выбранными `member_ids`. Доступно ТОЛЬКО куратору и ТОЛЬКО для его
    СОБСТВЕННЫХ `curated_groups` — иначе любой преподаватель массово добавлял бы чужих
    студентов в свои чаты (роль/скоуп проверяются на сервере, а не на клиенте)."""
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
    member_ids = list(payload.get("member_ids") or [])
    curated = set(user.curated_groups or [])
    for gname in (payload.get("class_groups") or []):
        if gname not in curated:            #скоуп: только СВОИ курируемые группы
            continue
        students = (db.query(User)
                    .filter(User.role == "student", User.group_name == gname,
                            User.deleted == False).all())  # noqa: E712
        member_ids.extend(s.id for s in students)
    for uid in member_ids:
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
        #§D6: «вступил» — ТОЛЬКО для групп (см. add_members ниже). Этот эндпоинт вообще
        #только для каналов (проверка kind=="channel" выше), поэтому здесь их нет никогда.
        _broadcast(db, conv_id)
    return {"ok": True, "conversation_id": conv_id}


@router.post("/chats/{conv_id}/leave")
def leave_chat(conv_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Покинуть беседу (группу/канал)."""
    p = _participant(db, conv_id, user.id)
    if p is not None:
        conv = _conversation(db, conv_id)
        name = user.full_name or user.name or user.login
        db.delete(p)
        db.commit()
        if conv.kind == "group":       #§D6: «вышел» — только для групп, не для каналов
            _system(db, conv_id, "user_left", user.id, name)
        _broadcast(db, conv_id)
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
    joined_names = []
    for uid in (payload.get("user_ids") or []):
        if _participant(db, conv_id, uid) is not None:
            continue
        u = db.query(User).filter(User.id == uid, User.deleted == False).first()  # noqa: E712
        if u is None:
            continue
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=uid, role=role, joined_at=now))
        joined_names.append((uid, u.full_name or u.name or u.login))
        added += 1
    db.commit()
    if conv.kind == "group":            #§D6: системные «вступил» — ТОЛЬКО для групп. Канал
        for uid, name in joined_names:  #может разом набрать сотню читателей (весь курс) —
            _system(db, conv_id, "user_joined", uid, name)   #лента не должна утонуть в этом.
    if added:
        _broadcast(db, conv_id)
    return {"added": added}


@router.delete("/chats/{conv_id}/members/{uid}")
def remove_member(conv_id: str, uid: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Убрать участника (право kick — owner/admin по умолчанию, либо кастомная роль с этим
    правом); себя может убрать любой (=покинуть). Владельца не трогаем."""
    if uid != user.id:
        _require_permission(db, conv_id, user, "kick")
    else:
        _require_participant(db, conv_id, user)
    conv = _conversation(db, conv_id)
    p = _participant(db, conv_id, uid)
    if p is not None and p.role != "owner":
        u = db.query(User).filter(User.id == uid).first()
        name = (u.full_name or u.name or u.login) if u else uid
        db.delete(p)
        db.commit()
        if conv.kind == "group":        #§D6: «вышел» — только для групп
            _system(db, conv_id, "user_left", uid, name)
        _broadcast(db, conv_id)
    return {"ok": True}


@router.post("/chats/{conv_id}/members/{uid}/role")
def set_member_role(conv_id: str, uid: str, payload: dict = Body(...),
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Назначить роль участнику — билдовую (`role`) ИЛИ кастомную (`custom_role_id`,
    взаимоисключающе). Право manage_roles — по умолчанию owner/admin, либо обладатель
    кастомной роли с этим правом (см. _permissions_for). Владельца не понижаем этим путём."""
    _require_permission(db, conv_id, user, "manage_roles")
    tp = _participant(db, conv_id, uid)
    if tp is None:
        raise HTTPException(status_code=404, detail="Участник не найден")
    if tp.role == "owner":
        raise HTTPException(status_code=400, detail="Нельзя изменить роль владельца")
    custom_role_id = payload.get("custom_role_id")
    if custom_role_id:
        cr = (db.query(ConversationRole)
              .filter(ConversationRole.id == custom_role_id,
                      ConversationRole.conversation_id == conv_id).first())
        if cr is None:
            raise HTTPException(status_code=404, detail="Роль не найдена")
        tp.custom_role_id = custom_role_id
    else:
        role = payload.get("role")
        if role not in ("admin", "member", "writer", "reader"):
            raise HTTPException(status_code=400, detail="Некорректная роль")
        tp.role = role
        tp.custom_role_id = None
    db.commit()
    return {"ok": True}


# ── Кастомные роли беседы (§ролей) ─────────────────────────────────────────────────────
_ROLE_TEMPLATES = [
    {"name": "Студент", "permissions": []},
    {"name": "Староста", "permissions": ["kick", "cmd_mute", "cmd_clear"]},
    {"name": "Преподаватель", "permissions": ["kick", "manage_roles", "cmd_mute", "cmd_clear"]},
]


@router.get("/chats/{conv_id}/roles")
def list_roles(conv_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Кастомные роли беседы + шаблоны для быстрого создания (не хранятся, пока не
    сохранены — см. create_role)."""
    _require_participant(db, conv_id, user)
    rows = (db.query(ConversationRole)
            .filter(ConversationRole.conversation_id == conv_id)
            .order_by(ConversationRole.created_at).all())
    return {"roles": [{"id": r.id, "name": r.name, "permissions": r.permissions or []} for r in rows],
            "templates": _ROLE_TEMPLATES, "all_permissions": list(_ALL_PERMISSIONS)}


@router.post("/chats/{conv_id}/roles")
def create_role(conv_id: str, payload: dict = Body(...),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_permission(db, conv_id, user, "manage_roles")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Нужно название роли")
    perms = [p for p in (payload.get("permissions") or []) if p in _ALL_PERMISSIONS]
    role = ConversationRole(id=f"crole:{uuid4().hex}", conversation_id=conv_id,
                            name=name[:60], permissions=perms, created_at=_now())
    db.add(role)
    db.commit()
    return {"id": role.id, "name": role.name, "permissions": role.permissions}


@router.put("/chats/{conv_id}/roles/{role_id}")
def update_role(conv_id: str, role_id: str, payload: dict = Body(...),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_permission(db, conv_id, user, "manage_roles")
    role = (db.query(ConversationRole)
            .filter(ConversationRole.id == role_id, ConversationRole.conversation_id == conv_id).first())
    if role is None:
        raise HTTPException(status_code=404, detail="Роль не найдена")
    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Нужно название роли")
        role.name = name[:60]
    if "permissions" in payload:
        role.permissions = [p for p in (payload.get("permissions") or []) if p in _ALL_PERMISSIONS]
    db.commit()
    return {"id": role.id, "name": role.name, "permissions": role.permissions}


@router.delete("/chats/{conv_id}/roles/{role_id}")
def delete_role(conv_id: str, role_id: str, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Удалить кастомную роль — участники с ней откатываются на билдовую member."""
    _require_permission(db, conv_id, user, "manage_roles")
    role = (db.query(ConversationRole)
            .filter(ConversationRole.id == role_id, ConversationRole.conversation_id == conv_id).first())
    if role is None:
        raise HTTPException(status_code=404, detail="Роль не найдена")
    (db.query(ConversationParticipant)
     .filter(ConversationParticipant.conversation_id == conv_id,
             ConversationParticipant.custom_role_id == role_id)
     .update({"custom_role_id": None, "role": "member"}))
    db.delete(role)
    db.commit()
    return {"ok": True}


# ── Игнор участника (личное, см. модель ConversationIgnore) ────────────────────────────
@router.post("/chats/{conv_id}/ignore/{uid}")
def ignore_member(conv_id: str, uid: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    _require_participant(db, conv_id, user)
    exists = (db.query(ConversationIgnore)
              .filter(ConversationIgnore.conversation_id == conv_id,
                      ConversationIgnore.viewer_id == user.id,
                      ConversationIgnore.ignored_user_id == uid).first())
    if exists is None:
        db.add(ConversationIgnore(conversation_id=conv_id, viewer_id=user.id, ignored_user_id=uid))
        db.commit()
    return {"ok": True}


@router.delete("/chats/{conv_id}/ignore/{uid}")
def unignore_member(conv_id: str, uid: str, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _require_participant(db, conv_id, user)
    (db.query(ConversationIgnore)
     .filter(ConversationIgnore.conversation_id == conv_id,
             ConversationIgnore.viewer_id == user.id,
             ConversationIgnore.ignored_user_id == uid)
     .delete())
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
    sm = _status_map(db, [p.user_id for p in parts])
    #Кастомные роли участников — одним запросом, а не по одной на строку.
    crole_ids = {p.custom_role_id for p in parts if p.custom_role_id}
    croles = {r.id: r.name for r in (db.query(ConversationRole)
              .filter(ConversationRole.id.in_(crole_ids)).all())} if crole_ids else {}
    people = []
    for p in parts:
        u = urows.get(p.user_id)
        prefs = (u.prefs if u is not None and isinstance(u.prefs, dict) else {})
        st = sm.get(p.user_id, {})
        people.append({
            "user_id": p.user_id,
            "full_name": (u.full_name or u.name or u.login) if u else p.user_id,
            "role": p.role,                       #owner | admin | writer | member | reader
            "custom_role_id": p.custom_role_id or None,
            "custom_role_name": croles.get(p.custom_role_id, "") if p.custom_role_id else "",
            "silenced": bool(p.silenced),          #«/mute» модератора — не путать с muted
            "online": bool(u) and u.login in onl,
            #Карточка участника в панели «О беседе»: аватар и контекст (группа/предметы).
            "avatar": prefs.get("avatar", "") or "",
            "bio": prefs.get("bio", "") or "",
            "profile_color": prefs.get("profile_color", "") or "",
            "profile_banner": prefs.get("profile_banner", "") or "",   #гифка-баннер карточки
            "name_font": prefs.get("name_font", "") or "",   #§5.4 «стиль никнейма»
            "name_effect": prefs.get("name_effect", "") or "",   #3.7 — эффект и цвет имени
            "name_color": prefs.get("name_color", "") or "",
            "user_role": (u.role if u else ""),   #student | teacher | admin (роль в системе)
            "group_name": (u.group_name or "") if u else "",
            "subjects": (u.subjects or []) if (u is not None and u.role == "teacher") else [],
            #§D7: статус поверх presence (dnd/studying/away + текст у преподавателя).
            "status_kind": st.get("kind", "") or "",
            "status_text": st.get("custom_text", "") or "",
            #Галочки «отправлено/прочитано» в ЛС (клиент сравнивает created_at СВОИХ
            #сообщений с last_read_at СОБЕСЕДНИКА — без похода на сервер за каждым тиком).
            "last_read_at": p.last_read_at or "",
        })
    #Владелец — первым, дальше по роли и алфавиту: сразу видно, кто создал беседу.
    _ORDER = {"owner": 0, "admin": 1, "writer": 2, "member": 3, "reader": 4}
    people.sort(key=lambda x: (_ORDER.get(x["role"], 9), (x["full_name"] or "").lower()))
    my_ignored = [r[0] for r in (db.query(ConversationIgnore.ignored_user_id)
                                 .filter(ConversationIgnore.conversation_id == conv_id,
                                         ConversationIgnore.viewer_id == user.id).all())]
    return {"conversation_id": conv.id, "kind": conv.kind, "title": conv.title,
            "about": conv.about, "owner_id": conv.owner_id, "is_public": conv.is_public,
            "my_role": part.role, "participants": people, "subscribers": len(people),
            #Свой id клиент иначе не знает (в JWT/сторе только логин+роль) — нужен, чтобы
            #не рисовать кнопки «Выгнать»/«Игнорировать» на собственной строке участника.
            "my_user_id": user.id,
            #Права участника в ЭТОЙ беседе (§ролей) — веб решает по ним, показывать ли
            #«Выгнать»/«Выдать роль» и доступность /mute, /clear в слэш-автодополнении.
            "my_permissions": sorted(_permissions_for(db, part)),
            "my_ignored_user_ids": my_ignored,
            #§D5: метка прочтения ДО открытия чата — клиент строит по ней разделитель
            #«Новые сообщения» (снимаем ДО markReadActive, иначе она бы уже сдвинулась).
            "my_last_read_at": part.last_read_at or "",
            #Системные каналы (§D12/§12): клиенту нужно различать их тип — например,
            #показать команду /отчет только в канале отчётов куратора для группы.
            "is_system": bool(conv.is_system), "system_kind": conv.system_kind or ""}


@router.patch("/chats/{conv_id}")
def rename_conversation(conv_id: str, payload: dict = Body(...),
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Переименовать группу/канал (owner/admin). Личный чат и беседу с модерацией не
    переименовываем — у них нет своего названия. Пишет системное сообщение (§D6).

    Проверяем ТИП беседы раньше роли: у личного чата участники всегда 'member' (не
    owner/admin), и без этого порядка запрос падал бы в 403 «недостаточно прав» вместо
    внятного 400 «эту беседу нельзя переименовать» — путало бы причину отказа."""
    conv = _conversation(db, conv_id)
    part = _require_participant(db, conv_id, user)
    if conv.kind not in ("group", "channel"):
        raise HTTPException(status_code=400, detail="Эту беседу нельзя переименовать")
    if part.role not in _MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    title = (payload.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Нужно название")
    title = title[:120]
    if title != conv.title:
        conv.title = title
        if "about" in payload:
            conv.about = (payload.get("about") or "").strip()[:500]
        db.commit()
        _system(db, conv_id, "title_changed", title)   #§D6
        _broadcast(db, conv_id)
    return {"ok": True, "title": conv.title, "about": conv.about}


# ── §D12: автоматические системные каналы (оценки/объявления/расписание) ─────────────
# Превращают мессенджер из «просто чата» в хаб колледжа: авто-канал появляется у студента
# сам, без ручного создания. Технически это ОБЫЧНЫЙ kind='channel' (переиспользует всю
# инфраструктуру — закрепление/реакции/пересылка), просто отмечен is_system=True и создан
# от лица "system". Публичные точки входа вызываются ИЗВНЕ (routers/web.py — оценки,
# рассылка расписания), ОБЯЗАНЫ быть обёрнуты в try/except на СТОРОНЕ ВЫЗЫВАЮЩЕГО КОДА —
# сбой мессенджера НИКОГДА не должен ронять выставление оценки/рассылку расписания.
SYSTEM_SENDER_NAME = "Вектор"    #посты подписаны уже знакомым маскотом, а не безликой «системой»


def _ensure_system_channel(db: Session, conv_id: str, title: str, about: str,
                           reader_ids, writer_ids=()) -> Conversation:
    """Найти/создать системный канал. Не идёт через create_channel (тот проверяет роль
    вызывающего и требует явного owner-пользователя) — здесь owner условный ("system")."""
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if conv is not None:
        return conv
    now = _now()
    kind_tag = conv_id.split(":", 2)[1] if conv_id.count(":") >= 2 else ""
    conv = Conversation(id=conv_id, kind="channel", title=title[:120], about=about[:500],
                        owner_id="system", is_public=False, created_at=now,
                        is_system=True, system_kind=kind_tag)
    db.add(conv)
    writer_set = set(writer_ids)
    for uid in writer_set:
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=uid, role="writer", joined_at=now))
    for uid in reader_ids:
        if uid in writer_set:
            continue
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=uid, role="reader", joined_at=now))
    db.commit()
    return conv


def _post_system_channel_message(db: Session, conv_id: str, body: str) -> None:
    """Опубликовать пост от лица «Вектора» + пуш офлайн-читателям (не замьютившим канал)."""
    m = Message(conversation_id=conv_id, sender_id="system", body=body,
               created_at=_now(), kind="text", body_format="markdown")
    db.add(m)
    db.commit()
    _broadcast(db, conv_id)
    try:
        from .. import rustore_push
        online = _online_logins()
        parts = db.query(ConversationParticipant).filter(
            ConversationParticipant.conversation_id == conv_id).all()
        ids = [p.user_id for p in parts if not p.muted]
        if ids:
            for u in db.query(User).filter(User.id.in_(ids)).all():
                if u.login and u.login not in online:
                    #🔒 ТЕКСТ СООБЩЕНИЯ В ПУШ НЕ КЛАДЁМ. Здесь стояло `body[:120]` — и это
                    #было ЕДИНСТВЕННОЕ место во всём мессенджере, нарушавшее собственное
                    #правило продукта «содержимое не уходит третьей стороне» (см. шапку
                    #rustore_push.py и `_notify_recipients`, где давно уходит нейтральное
                    #«Новое сообщение»). Через системные каналы ходят объявления куратора и
                    #ответы Вектора на вопросы студента — то есть первые 120 символов
                    #учебных данных уезжали в инфраструктуру RuStore и оседали в её логах
                    #и в шторке уведомлений на заблокированном экране.
                    #Ради чего терпеть: ни ради чего. Человек всё равно открывает чат.
                    rustore_push.notify_login(db, u.login, SYSTEM_SENDER_NAME,
                                              "Новое сообщение",
                                              {"type": "message", "conversation_id": conv_id})
    except Exception:
        pass


def notify_grade_posted(db: Session, student_id: str, teacher_name: str, subject: str, grade: str) -> None:
    """§D12(1): «Мои оценки» — личный read-only канал студента. Публичная точка входа для
    routers/web.py (POST /web/teacher/grade); ВЫЗЫВАЮЩИЙ КОД оборачивает в try/except."""
    if not student_id:
        return
    conv_id = f"sys:grades:{student_id}"
    _ensure_system_channel(db, conv_id, "Мои оценки",
                          "Автоматические уведомления о ваших оценках.", reader_ids=[student_id])
    _post_system_channel_message(
        db, conv_id, f"**{teacher_name}** поставил(а) вам **{grade}** по {subject}")


def ensure_group_schedule_channel(db: Session, group_name: str, student_ids) -> str:
    """§D12(3): «Расписание · Группа» — read-only канал, публикует schedule.publish (админ,
    web.py). Возвращает id канала (для _post_system_channel_message вызывающим кодом)."""
    conv_id = f"sys:schedule:{group_name}"
    _ensure_system_channel(db, conv_id, f"Расписание · {group_name}",
                          "Автоматические изменения расписания вашей группы.",
                          reader_ids=student_ids)
    return conv_id


def notify_substitution(db: Session, group_name: str, text: str) -> None:
    """§D12(4): «Замены · Группа» — read-only канал точечных правок расписания.

    Почему отдельно от «Расписание · Группа», хотя источник данных общий: тот канал
    рассылается ОДНИМ постом на публикацию («расписание изменилось — проверьте»), а замена
    — это конкретная пара, которую нужно увидеть до выхода из дома. Смешав их, мы бы либо
    спамили общий канал каждой правкой ячейки, либо утопили замену в общем «что-то
    поменялось». Публичная точка входа для routers/web.py; ВЫЗЫВАЮЩИЙ оборачивает
    в try/except — сбой мессенджера не должен ронять правку расписания."""
    group_name = (group_name or "").strip()
    if not group_name or not text:
        return
    students = [u.id for u in db.query(User).filter(
        User.role == "student", User.group_name == group_name,
        User.deleted == False).all()]  # noqa: E712
    if not students:
        return
    conv_id = f"sys:substitute:{_gtoken(group_name)}"
    _ensure_system_channel(db, conv_id, f"Замены · {group_name}",
                           "Точечные изменения пар: переносы, замены, отмены.",
                           reader_ids=students)
    _post_system_channel_message(db, conv_id, text)


@router.post("/channels/practice/{group_name}")
def ensure_practice_channel(group_name: str, user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """§D12(5): «Практика · Группа» — канал производственной практики.

    В отличие от остальных системных каналов он НЕ автоматический: данных о практике в
    журнале нет, и выдумывать их нельзя. Это канал, который ведёт руками учебная часть
    (админ) или куратор группы — направления, договоры, сроки сдачи дневника. От обычного
    канала отличается тем, что появляется у студентов сам и его нельзя покинуть."""
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Доступно преподавателям и администрации")
    group_name = group_name.strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="Нужна группа")
    #Куратор ведёт практику только своих групп; администрация — любых.
    if user.role == "teacher" and group_name not in (user.curated_groups or []):
        raise HTTPException(status_code=403, detail="Эта группа вами не курируется")
    students = [u.id for u in db.query(User).filter(
        User.role == "student", User.group_name == group_name,
        User.deleted == False).all()]  # noqa: E712
    writers = [user.id]
    if user.role != "admin":
        writers += [a.id for a in db.query(User).filter(
            User.role == "admin", User.deleted == False).all()]  # noqa: E712
    conv_id = f"sys:practice:{_gtoken(group_name)}"
    _ensure_system_channel(db, conv_id, f"Практика · {group_name}",
                           "Производственная практика: направления, сроки, документы.",
                           reader_ids=students, writer_ids=writers)
    return {"ok": True, "conversation_id": conv_id}


@router.get("/my-groups")
def my_groups(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Группы, которые сотрудник может адресовать в мессенджере (объявления, отчёты).

    Нужен для ВЫПАДАЮЩЕГО СПИСКА вместо ручного ввода: имена групп колледжа вида «К75/1»
    набирали с ошибкой (лишний пробел, латинская «K»), канал не находился, и со стороны
    это выглядело как «не работает». Флаг `curated` отличает курируемые группы —
    отчёты для родителей доступны только по ним."""
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Доступно преподавателям и администрации")
    curated = set(user.curated_groups or [])
    known = [g.name for g in db.query(Group)
             .filter(Group.deleted == False).order_by(Group.name).all()]  # noqa: E712
    if user.role == "admin":
        names = known
    else:
        #Преподаватель: НАЗНАЧЕННЫЕ ему группы (не любые с совпавшим предметом) + курируемые.
        from .. import webdata as W
        ty, ts = W.current_term(W.load_config(db))
        names = sorted(set(W.teacher_group_names(db, user.id, ty, ts)) | curated)
    #Одна и та же группа могла записаться по-разному («К74/1» в занятиях и «к74/1» в
    #кураторстве) — в списке она двоилась. Схлопываем по регистру и пробелам, показывая
    #написание из СПРАВОЧНИКА групп: журнал ключуется именно им.
    canon = {n.strip().lower(): n for n in known}
    out, seen = [], set()
    for n in names:
        key = (n or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        name = canon.get(key, n)
        out.append({"name": name, "curated": key in {c.strip().lower() for c in curated}})
    return {"groups": out}


@router.post("/channels/announcements")
def ensure_announcements_channel_q(group: str = Query(...),
                                   user: User = Depends(get_current_user),
                                   db: Session = Depends(get_db)):
    """То же, что ниже, но имя группы — в QUERY, а не в пути.

    Причина ровно та же, что у /web/curator/subjects: имена групп содержат слэш («К75/1»),
    в пути он приезжает как %2F, Starlette декодирует его обратно в «/», и роут с одним
    сегментом перестаёт совпадать — эндпоинт молча 404-ил."""
    return ensure_announcements_channel(group, user, db)


@router.post("/channels/announcements/{group_name}")
def ensure_announcements_channel(group_name: str, user: User = Depends(get_current_user),
                                 db: Session = Depends(get_db)):
    """§D12(2): «Объявления · Группа» — teacher/admin открывают/создают канал (студенты
    группы — читатели, преподаватели этой группы — авторы) и дальше публикуют ОБЫЧНЫМ
    send_message (это простой kind='channel', отдельного эндпоинта «отправить объявление»
    не требуется — переиспользуем всю уже готовую инфраструктуру постинга в канал)."""
    if user.role not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Доступно преподавателям и администрации")
    group_name = group_name.strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="Нужна группа")
    students = [u.id for u in db.query(User).filter(
        User.role == "student", User.group_name == group_name, User.deleted == False).all()]  # noqa: E712
    #Авторы канала — преподаватели, которым НАЗНАЧЕНА эта группа (не «есть занятие с
    #совпавшим названием предмета где-то ещё»), см. §ролей teacher_assignments.
    from .. import webdata as W
    ty, ts = W.current_term(W.load_config(db))
    teacher_ids_here = {r.teacher_id for r in db.query(SubjectHours).filter(
        SubjectHours.group_name == group_name, SubjectHours.year == ty,
        SubjectHours.semester == ts, SubjectHours.teacher_id != "",
        SubjectHours.deleted == False).all()}  # noqa: E712
    teachers = [t.id for t in db.query(User).filter(
        User.role == "teacher", User.deleted == False).all()  # noqa: E712
        if t.id in teacher_ids_here]
    if user.role == "teacher" and user.id not in teachers:
        teachers.append(user.id)     #админ мог создать канал раньше, чем завёл занятия
    conv_id = f"sys:announce:{_gtoken(group_name)}"
    conv = _ensure_system_channel(db, conv_id, f"Объявления · {group_name}",
                                  "Объявления от преподавателей и администрации.",
                                  reader_ids=students, writer_ids=teachers)
    #Уже существующий канал: если пользователь — преподаватель этой группы и ещё не писатель,
    #добавляем (группа могла завести предметы уже ПОСЛЕ создания канала).
    if user.role == "teacher" and _participant(db, conv_id, user.id) is None:
        db.add(ConversationParticipant(conversation_id=conv_id, user_id=user.id,
                                       role="writer", joined_at=_now()))
        db.commit()
    return {"conversation_id": conv.id, "kind": "channel", "title": conv.title}


# ── §12: отчёты куратора для родителей («Отчёты · Группа») ──────────────────────────────
def _gtoken(group: str) -> str:
    """Имя группы → безопасный кусок ИДЕНТИФИКАТОРА беседы/отчёта.

    ⚠️ Слэш в id — это сломанный адрес, а не косметика. Группы колледжа называются
    «К74/1», и id вида «sys:announce:К74/1» в URL приезжает как %2F; Starlette
    раскодирует его ОБРАТНО в «/» ещё до подбора роута, путь распадается на лишний
    сегмент и не совпадает ни с одним эндпоинтом мессенджера — GET проваливался в
    SPA-фолбэк (клиент получал HTML вместо JSON и показывал пустоту), а POST отвечал
    405. Из-за этого у групп со слэшем не открывались отчёты и не работали объявления,
    хотя на «ИС-21» всё было исправно.

    «~» выбран потому, что он unreserved в RFC 3986 (в URL не кодируется вовсе) и в
    названиях групп не встречается. Обратное преобразование — _gname."""
    return (group or "").replace("/", "~")


def _gname(token: str) -> str:
    """Обратно к имени группы (см. _gtoken)."""
    return (token or "").replace("~", "/")


def _active_parent_ids_for_group(db: Session, group_name: str) -> list:
    """«Группа с родителями» — есть хотя бы одна АКТИВНАЯ (подтверждённая студентом)
    связь родитель→студент этой группы. Пересчитываем каждый раз (не кэшируем): группа
    может потерять последнего родителя (студент отозвал согласие) или обрести первого."""
    student_ids = [u.id for u in db.query(User).filter(
        User.role == "student", User.group_name == group_name,
        User.deleted == False).all()]  # noqa: E712
    if not student_ids:
        return []
    rows = (db.query(ParentLink.parent_id)
            .filter(ParentLink.student_id.in_(student_ids), ParentLink.status == "active")
            .distinct().all())
    return [r[0] for r in rows]


@router.post("/channels/curator-reports")
def ensure_curator_reports_channel_q(group: str = Query(...),
                                     user: User = Depends(get_current_user),
                                     db: Session = Depends(get_db)):
    """Имя группы в QUERY — см. пояснение у ensure_announcements_channel_q (слэш в «К75/1»)."""
    return ensure_curator_reports_channel(group, user, db)


@router.post("/channels/curator-reports/{group_name}")
def ensure_curator_reports_channel(group_name: str, user: User = Depends(get_current_user),
                                   db: Session = Depends(get_db)):
    """§12: канал «Отчёты · Группа» — куратор публикует туда `/отчет`, читают студенты
    группы И её активные родители. ТОЛЬКО куратор ЭТОЙ группы (curated_groups) и ТОЛЬКО
    если у группы есть хоть один активный родитель — без родителей отчёт для родителей
    не имеет смысла заводить."""
    group_name = group_name.strip()
    if not group_name:
        raise HTTPException(status_code=400, detail="Нужна группа")
    if user.role != "teacher" or group_name not in (user.curated_groups or []):
        raise HTTPException(status_code=403, detail="Доступно только куратору этой группы")
    parent_ids = _active_parent_ids_for_group(db, group_name)
    if not parent_ids:
        raise HTTPException(status_code=400, detail="У группы нет ни одной активной связи с родителем")
    students = [u.id for u in db.query(User).filter(
        User.role == "student", User.group_name == group_name,
        User.deleted == False).all()]  # noqa: E712
    conv_id = f"sys:curator_reports:{_gtoken(group_name)}"
    conv = _ensure_system_channel(db, conv_id, f"Отчёты · {group_name}",
                                  "Отчёты об успеваемости группы для родителей.",
                                  reader_ids=students + parent_ids, writer_ids=[user.id])
    return {"conversation_id": conv.id, "kind": "channel", "title": conv.title}


#Аргумент необязателен: «/отчет», «/отчёт К75/1», «/отчет "К75/1"».
_REPORT_CMD_RE = re.compile(r"^/отч[её]т\b\s*(.*)$", re.IGNORECASE | re.DOTALL)


def _report_groups_for(db: Session, user: User) -> list:
    """Группы, по которым этот человек вправе выпускать отчёт: куратору — его группы,
    администрации — любые. Список нужен ещё и для внятной ошибки («ваши группы: …»)."""
    if user.role == "admin":
        return [g.name for g in db.query(Group)
                .filter(Group.deleted == False).order_by(Group.name).all()]  # noqa: E712
    if user.role == "teacher":
        return list(user.curated_groups or [])
    return []


def _resolve_report_group(arg: str, conv: Conversation, allowed: list) -> str:
    """Какая группа имеется в виду: аргумент команды → канал отчётов → единственная
    курируемая группа. Угадывать при неоднозначности нельзя — отчёт не по той группе
    это выдача чужих оценок, поэтому в спорном случае просим уточнить."""
    arg = (arg or "").strip().strip('«»"\'').strip()
    if arg:
        hit = [g for g in allowed if g.strip().lower() == arg.lower()]
        if not hit:
            raise HTTPException(
                status_code=400,
                detail=f"Группа «{arg}» не найдена. Доступны: {', '.join(allowed) or '—'}")
        return hit[0]
    if conv is not None and conv.system_kind == "curator_reports":
        return _gname(conv.id.split(":", 2)[-1])
    if len(allowed) == 1:
        return allowed[0]
    raise HTTPException(
        status_code=400,
        detail=f"Укажите группу: /отчет {allowed[0] if allowed else 'К75/1'}. "
               f"Доступны: {', '.join(allowed) or '—'}")


def _create_report(db: Session, group_name: str, user: User, conv_ids: list,
                   nonce: str = "") -> Message:
    """Создать отчёт по группе и положить кнопку «Отчёт №N» в каждую из бесед.

    Хранится СНИМОК ГРАНИЦЫ (термин + дата включительно), а не готовые цифры: они
    пересчитываются живьём при каждом открытии (curator_report.collect_group) в пределах
    этой границы. Кнопка одна и та же во всех беседах — id отчёта общий, поэтому
    пересылка не плодит копий данных и не расходится с оригиналом.
    Возвращает сообщение в ПЕРВОЙ беседе (её открывает клиент после создания)."""
    from .. import webdata as W
    cfg = W.load_config(db)
    year, semester = W.current_term(cfg)
    seq = (db.query(func.count(CuratorReport.id))
           .filter(CuratorReport.group_name == group_name).scalar() or 0) + 1
    rid = f"rpt:{_gtoken(group_name)}|{seq}"
    now = _now()
    db.add(CuratorReport(id=rid, group_name=group_name, seq=seq, year=year,
                         semester=semester, cutoff_date=_iso_to_ddmmyyyy(now),
                         created_by=user.id, created_at=now, conversation_id=conv_ids[0]))
    db.commit()
    first = None
    for cid in conv_ids:
        m = Message(conversation_id=cid, sender_id=user.id, body=rid,
                    created_at=_now(), kind="report", body_format="plain",
                    #nonce ставим только ПЕРВОМУ сообщению: он уникален на беседу, и
                    #повтор запроса найдёт именно его (см. проверку в send_message).
                    client_nonce=(nonce if first is None else ""))
        db.add(m)
        db.commit()
        db.refresh(m)
        if first is None:
            first = m
            rep = db.query(CuratorReport).filter(CuratorReport.id == rid).first()
            if rep is not None:
                rep.message_id = m.id
                db.commit()
        _unhide_participants(db, cid)      #«удалённый» чат возвращается с новым сообщением
        _broadcast(db, cid)
    return first


def _handle_report_command(db: Session, conv_id: str, body: str, user: User,
                           nonce: str = ""):
    """`/отчет [группа]` — команда куратора, а не обычное сообщение.

    Работает в ЛЮБОЙ беседе, где автор может писать: в канале «Отчёты · Группа» (группа
    берётся из канала), в чате родителей или в личной переписке — тогда группу называют
    прямо в команде («/отчет К75/1»), и отчёт публикуется СРАЗУ сюда же.

    Ошибки поднимаем HTTP 400/403, а не глотаем: раньше команда молча ничего не делала —
    ни отчёта, ни объяснения, и это выглядело как «отчёты не работают».
    Возвращает созданное сообщение-кнопку (его и отдаёт /messages вместо текста команды)."""
    mt = _REPORT_CMD_RE.match(body.strip())
    if not mt:
        return None
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    allowed = _report_groups_for(db, user)
    if not allowed:
        raise HTTPException(status_code=403,
                            detail="Отчёт по группе выпускает её куратор или администрация")
    group_name = _resolve_report_group(mt.group(1), conv, allowed)
    #В КАНАЛЕ отчётов аудитория — родители, и без единой подтверждённой связи публиковать
    #там нечего. В обычном чате это ограничение не действует: адресата выбрал сам куратор.
    if conv is not None and conv.system_kind == "curator_reports" \
            and not _active_parent_ids_for_group(db, group_name):
        raise HTTPException(
            status_code=400,
            detail="У группы нет ни одного подтверждённого родителя — отчёт для родителей "
                   "публиковать некому")
    return _create_report(db, group_name, user, [conv_id], nonce)


#ℹ️ `/активность` УДАЛЕНА 17.08.2026 (решение Влада). Команда была ЕДИНСТВЕННОЙ дверью к
#активностям — оттуда и её появление здесь, и сторож достижимости в
#`web/tests/slashCommandsReachable.test.mjs`. С 3.7.4 дверь другая и лучше: кнопка в шапке
#беседы зовёт лаунчер напрямую, не спрашивая сервер. Два входа в одно место, из которых
#один надо помнить наизусть, — это не запас прочности, а лишняя поверхность: команду
#пришлось бы переводить, объяснять и проверять правами дважды.
#⚠️ Проверка права осталась там, где ей и место, — в `POST /activities/start`
#(`_require_can_run`): она НЕ была побочным эффектом команды.


_MUTE_CMD_RE = re.compile(r'^/mute\s+"?@?([^"\s]+)"?\s*$', re.IGNORECASE)
_CLEAR_CMD_RE = re.compile(r'^/clear\s+"?(\d+)"?\s*$', re.IGNORECASE)
_CLEAR_MAX_N = 100


def _resolve_participant_by_name(db: Session, conv_id: str, token: str):
    """Находит участника беседы по первому слову ФИО (та же простая эвристика, что у
    @упоминаний, см. _parse_mentions) — токен без ведущего @/кавычек."""
    token = (token or "").lstrip("@").strip().lower()
    if not token:
        return None
    ids = _participant_ids(db, conv_id)
    if not ids:
        return None
    for u in db.query(User).filter(User.id.in_(ids)).all():
        first = (u.full_name or u.name or "").split(" ", 1)[0].strip().lower()
        if first == token:
            return u
    return None


def _handle_mute_command(db: Session, conv_id: str, body: str, user: User,
                         part: ConversationParticipant):
    """`/mute "@username"` — переключатель: заглушает/снова разрешает цели писать В ЭТУ
    беседу (НЕ путать с личным `muted` — «я не хочу пуши»). Право cmd_mute — owner/admin
    по умолчанию, либо обладатель кастомной роли с этим правом."""
    mt = _MUTE_CMD_RE.match(body.strip())
    if not mt:
        return None
    if "cmd_mute" not in _permissions_for(db, part):
        raise HTTPException(status_code=403, detail="Нет права /mute в этой беседе")
    target = _resolve_participant_by_name(db, conv_id, mt.group(1))
    if target is None:
        raise HTTPException(status_code=404, detail="Участник не найден в этой беседе")
    tp = _participant(db, conv_id, target.id)
    if tp is None:
        raise HTTPException(status_code=404, detail="Участник не найден в этой беседе")
    if tp.role == "owner":
        raise HTTPException(status_code=400, detail="Нельзя заглушить владельца беседы")
    tp.silenced = not tp.silenced
    db.commit()
    name = target.full_name or target.name or target.login
    sysmsg = _system(db, conv_id, "muted" if tp.silenced else "unmuted", target.id, name)
    _broadcast(db, conv_id)
    return sysmsg


def _handle_clear_command(db: Session, conv_id: str, body: str, user: User,
                          part: ConversationParticipant):
    """`/clear "N"` — томбстоунит последние N сообщений беседы (тот же механизм, что
    модераторское удаление, не hard-delete). Право cmd_clear, лимит _CLEAR_MAX_N от
    случайного /clear 999999."""
    mt = _CLEAR_CMD_RE.match(body.strip())
    if not mt:
        return None
    if "cmd_clear" not in _permissions_for(db, part):
        raise HTTPException(status_code=403, detail="Нет права /clear в этой беседе")
    n = min(int(mt.group(1)), _CLEAR_MAX_N)
    if n <= 0:
        raise HTTPException(status_code=400, detail="Укажите количество сообщений больше нуля")
    rows = (db.query(Message)
            .filter(Message.conversation_id == conv_id, Message.deleted_at == "")
            .order_by(Message.id.desc()).limit(n).all())
    now = _now()
    for row in rows:
        row.deleted_at = now
        row.pinned = False
    db.commit()
    sysmsg = _system(db, conv_id, "cleared", str(len(rows)))
    _broadcast(db, conv_id)
    return sysmsg


@router.post("/curator-reports")
def create_curator_report(payload: dict = Body(...), user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Создать отчёт по группе и отправить его СООБЩЕНИЕМ — в личные чаты родителей
    (`to_user_ids`), в конкретные беседы (`to_conversation_ids`) или, если не указано
    ничего, себе в «Избранное», откуда его можно переслать кому угодно.

    Кнопку отчёта можно пересылать: доступ даёт участие в ЛЮБОЙ беседе, где она лежит
    (см. _require_report_access), а не только в исходной."""
    group_name = (payload.get("group") or "").strip()
    allowed = _report_groups_for(db, user)
    if not allowed:
        raise HTTPException(status_code=403,
                            detail="Отчёт по группе выпускает её куратор или администрация")
    if group_name not in allowed:
        raise HTTPException(status_code=403, detail="Эта группа вами не курируется")
    _guard_can_write(db, user)                       #мьют/анти-флуд — как у обычной отправки

    conv_ids = []
    for uid in [str(x) for x in (payload.get("to_user_ids") or [])]:
        peer = db.query(User).filter(User.id == uid, User.deleted == False).first()  # noqa: E712
        if peer is None or peer.id == user.id:
            continue
        _guard_direct_allowed(db, user, peer)        #те же границы, что у обычной переписки
        conv_ids.append(_ensure_direct(db, user, peer))
    for cid in [str(x) for x in (payload.get("to_conversation_ids") or [])]:
        part = _participant(db, cid, user.id)
        if part is None:
            continue                                 #в чужую беседу отчёт не положишь
        conv = _conversation(db, cid)
        if conv.kind == "channel" and part.role not in _WRITER_ROLES:
            continue
        conv_ids.append(cid)
    if not conv_ids:
        #Ничего не выбрано — кладём себе в «Избранное»: отчёт создан, дальше его пересылают.
        conv_ids = [_ensure_saved(db, user)]

    seen, targets = set(), []
    for cid in conv_ids:
        if cid not in seen:
            seen.add(cid)
            targets.append(cid)
    m = _create_report(db, group_name, user, targets)
    return {"ok": True, "report_id": m.body, "message_id": m.id,
            "conversation_id": targets[0], "conversation_ids": targets}


@router.get("/report-recipients")
def report_recipients(group: str = Query(...), user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Кому предложить отчёт по группе: родители с ПОДТВЕРЖДЁННОЙ связью (личные чаты) и
    уже существующие беседы группы (канал отчётов, чат родителей). Список — подсказка для
    диалога отправки; права всё равно проверяются при создании отчёта."""
    group = group.strip()
    allowed = _report_groups_for(db, user)
    if group not in allowed:
        raise HTTPException(status_code=403, detail="Эта группа вами не курируется")
    parent_ids = _active_parent_ids_for_group(db, group)
    onl = _online_logins()
    parents = [_safe_user(p, onl) for p in db.query(User)
               .filter(User.id.in_(parent_ids)).order_by(User.surname, User.name).all()] \
        if parent_ids else []
    #Беседы, которые уместно предложить: системные каналы этой группы + групповые чаты,
    #где куратор состоит (чат родителей он заводит сам обычной «Новой группой»).
    convs = []
    for p in db.query(ConversationParticipant).filter(
            ConversationParticipant.user_id == user.id).all():
        conv = db.query(Conversation).filter(Conversation.id == p.conversation_id).first()
        if conv is None or conv.kind not in ("group", "channel"):
            continue
        if conv.kind == "channel" and p.role not in _WRITER_ROLES:
            continue
        if conv.is_system and not conv.id.endswith(f":{_gtoken(group)}"):
            continue                                 #чужой группы системный канал не предлагаем
        convs.append({"conversation_id": conv.id, "title": conv.title or "",
                      "kind": conv.kind, "system": bool(conv.is_system)})
    convs.sort(key=lambda c: (not c["system"], c["title"]))
    return {"parents": parents, "conversations": convs}


def _require_report_access(db: Session, rep: CuratorReport, user: User) -> None:
    """Доступ к отчёту = участие в ЛЮБОЙ беседе, где лежит его кнопка.

    Привязка к ОДНОЙ исходной беседе делала пересылку бессмысленной: у адресата в личке
    кнопка была, а по нажатию приходило 403. Отчёт при этом не «публичный» — чтобы кнопка
    попала в беседу, туда её должен положить или переслать тот, у кого доступ уже есть."""
    conv_ids = {r[0] for r in db.query(Message.conversation_id)
                .filter(Message.kind == "report", Message.body == rep.id,
                        Message.deleted_at == "").all()}
    if rep.conversation_id:
        conv_ids.add(rep.conversation_id)
    for cid in conv_ids:
        if _participant(db, cid, user.id) is not None:
            return
    raise HTTPException(status_code=403, detail="Нет доступа к этому отчёту")


def _iso_to_ddmmyyyy(iso: str) -> str:
    """"2026-07-27T10:00:00+00:00" → "27.07.2026" (формат дат занятий, см. curator_report.py)."""
    try:
        y, m, d = iso[:10].split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return ""


@router.get("/reports/{report_id}")
def report_overview(report_id: str, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """§12: данные для оверлея отчёта — круговая (категории успеваемости) + плоские
    (проценты по предметам) диаграммы. Живой пересчёт (curator_report.collect_group),
    ограниченный ГРАНИЦЕЙ отчёта (термин + дата создания включительно) — числа могут
    чуть измениться, если позже поправят оценку ВНУТРИ этой границы, но сама граница
    «вечна» и не сдвигается новыми занятиями (см. CuratorReport в models.py)."""
    rep = db.query(CuratorReport).filter(CuratorReport.id == report_id).first()
    if rep is None:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    _require_report_access(db, rep, user)   #участник ЛЮБОЙ беседы, где лежит эта кнопка
    from .. import webdata as W
    from .. import curator_report as CR
    cfg = W.load_config(db)
    data = CR.collect_group(db, rep.group_name, rep.year, rep.semester, cfg,
                           cutoff_date=rep.cutoff_date)
    categories = CR.categorize(data["rows"])
    subjects = [{"subject": s, "avg": data["subject_group_avg"].get(s) or 0,
                "percent": round(((data["subject_group_avg"].get(s) or 0) / 5) * 100)}
               for s in data["subjects"]]
    return {"id": rep.id, "seq": rep.seq, "group": rep.group_name,
            "year": rep.year, "semester": rep.semester, "cutoff_date": rep.cutoff_date,
            "archived": _report_archived(rep, db), "students": data["students"],
            "group_avg": data["group_avg"], "categories": categories, "subjects": subjects}


@router.get("/reports/{report_id}/subject")
def report_subject_journal(report_id: str, subject: str = Query(...),
                           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """§12: дрилл-даун по предмету — журнал студентов группы (оценки построчно), справа
    средний балл и пропуски: часов пропущено и (в скобках) количество пропусков в
    единицах — т.е. сколько раз стояло «Н» (неявка), без учёта Б/О (уважительных)."""
    rep = db.query(CuratorReport).filter(CuratorReport.id == report_id).first()
    if rep is None:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    _require_report_access(db, rep, user)
    from .. import webdata as W
    from .. import curator_report as CR
    cfg = W.load_config(db)
    students = W.students_in_group(db, rep.group_name)
    lessons = W.group_lessons(db, rep.group_name, subject=subject,
                             year=rep.year, semester=rep.semester)
    cutoff = CR.parse_ddmmyyyy(rep.cutoff_date) if rep.cutoff_date else None
    if cutoff:
        lessons = [l for l in lessons
                  if (CR.parse_ddmmyyyy(l.date) or cutoff) <= cutoff]
    lessons.sort(key=lambda l: (l.number, l.hour))
    scale_map = W.lesson_scale_map(db, lessons)
    rows = []
    for s in students:
        recs = W.student_records(db, s.surname, s.name, rep.group_name)
        grades = [{"lesson_id": l.id, "type": l.type, "number": l.number,
                  "topic": l.topic, "date": l.date, "value": recs.get(l.id, "")}
                 for l in lessons]
        absc = W.absences(lessons, recs)
        rows.append({
            "student": f"{s.surname} {s.name}".strip(),
            "grades": grades,
            "average": W.average(lessons, recs, cfg, scale=scale_map),
            "missed_hours": absc["всего"], "missed_count": absc["Н"],
        })
    return {"group": rep.group_name, "subject": subject,
            "lessons": [{"id": l.id, "type": l.type, "number": l.number,
                        "topic": l.topic, "date": l.date} for l in lessons],
            "rows": rows}


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
        #⚠️ На ЧТО жалоба. Обязано уезжать клиенту: у тикета на отзыв среза понимания
        #(target_kind="activity_feedback") `message_id` — это id строки activity_feedback,
        #а НЕ сообщения. Без этого поля админка предложила бы на таком тикете «удалить
        #сообщение», и удалён был бы ПОСТОРОННИЙ текст с совпавшим номером — молча и
        #необратимо для читателей. Держит `test_feedback_report_is_marked_as_not_a_message`.
        "target_kind": getattr(r, "target_kind", "") or "message",
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
def mod_conversation_messages(conv_id: str, report_id: int = Query(0), request: Request = None,
                              admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Прочитать ЛЮБУЮ беседу (модерация). Каждый вызов пишется в аудит (152-ФЗ).

    §правка: `report_id` — необязательный, передаёт фронт ТОЛЬКО во вкладке «Жалобы»
    (просмотр из тикета, см. AdminMessenger.vue::openConversation); вкладка «Обращения»
    его не знает и продолжает работать как раньше. Если тикет уже закрыт (resolved/
    dismissed/expired) — доступ к переписке ПО ЭТОМУ ТИКЕТУ закрывается: свободный
    просмотр чужой переписки без активного расследования — риск сам по себе (живой
    отзыв). Проверка СЕРВЕРНАЯ, а не только дизейбл кнопки во фронте — иначе прямой
    запрос к этому же URL с браузерным дебагом обходил бы «закрытую» кнопку."""
    _conversation(db, conv_id)
    if report_id:
        rep = db.query(MessageReport).filter(MessageReport.id == report_id).first()
        if rep is None or rep.conversation_id != conv_id:
            raise HTTPException(status_code=404, detail="Тикет не найден")
        if rep.status not in ("open", "in_review"):
            raise HTTPException(status_code=403, detail="Тикет закрыт — переписка больше не открывается")
    rows = (db.query(Message).filter(Message.conversation_id == conv_id)
            .order_by(Message.id.asc()).all())
    #ФИО автора — иначе в переписке с 2+ участниками (жалоба, групповой чат) не видно,
    #кто что написал (тот же _names_for, что уже используют обычные списки сообщений).
    names = _names_for(db, [m.sender_id for m in rows])
    #§правка: модерация должна видеть ПОЛНУЮ картину — текст удалённых сообщений и всю
    #цепочку правок. Обычный _msg_out() их НАМЕРЕННО прячет (для всех остальных
    #читателей это правильно), здесь — противоположный, осознанный контракт: доступ и
    #так журналируется аудитом ниже, а подотчётность важнее приватности при активной
    #проверке жалобы (см. комментарий у edit_message: «модерация должна видеть оригинал»).
    ids = [m.id for m in rows]
    edits_by_msg: dict[int, list] = {}
    if ids:
        for e in (db.query(MessageEdit).filter(MessageEdit.message_id.in_(ids))
                  .order_by(MessageEdit.id.asc()).all()):
            edits_by_msg.setdefault(e.message_id, []).append({"body": e.body_before, "at": e.edited_at})
    out = []
    for m in rows:
        d = _msg_out(m, sender_name=names.get(m.sender_id, ""))
        if m.deleted_at:
            d["body"] = m.body or ""
        versions = edits_by_msg.get(m.id)
        if versions:
            d["edit_versions"] = versions + [{"body": m.body or "", "at": m.edited_at or m.created_at}]
        out.append(d)
    _attach_rich_meta(db, out, admin.id)               #админ читает ту же ленту, что и участники
    audit.log(db, request, actor=admin.login, role=admin.role,
              action="msg.moderation.view", target=conv_id)
    return {"messages": out}


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
    import profanity_filter
    body = profanity_filter.censor(body, mask=profanity_filter.MESSENGER_SAFE_MASK)
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
        #🔒 ОТЗЫВ СЕССИИ. Раньше здесь проверялись только подпись и наличие пользователя —
        #в отличие от HTTP-пути (`deps.get_current_user`), который смотрит чёрный список
        #jti. Из-за этого «Выйти» и блокировка админом НЕ разрывали живой сокет: украденный
        #токен ещё до пяти часов получал сигналы `{"changed", conversation_id}` — то есть
        #видел, в каких беседах идёт переписка, — и мог слать «печатает…». Тексты не
        #утекали (их отдаёт HTTP, а он отзыв проверяет), но это ровно та дверь, ради
        #закрытия которой чёрный список jti и заводился.
        #Токены БЕЗ jti (старого формата) пускаем, как и на HTTP: иначе выданные до
        #введения списка сессии оборвались бы у всех разом.
        jti = payload.get("jti")
        revoked = False
        if jti:
            sess = db.query(AuthSession).filter(AuthSession.jti == jti).first()
            revoked = sess is None or bool(sess.revoked)
        user = None if revoked else db.query(User).filter(
            User.login == payload.get("sub"),
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
                    #⚠️ УЧАСТИЕ ПРОВЕРЯЕМ ЗДЕСЬ. Это единственное место мессенджера, где
                    #клиент сам называет беседу, а сокет уже авторизован — и раньше этого
                    #хватало, чтобы любой вошедший разослал «печатает…» в ЧУЖОЙ чат,
                    #просто подставив его id. Содержимого это не раскрывало, но давало
                    #проверять существование бесед перебором и подсовывать людям
                    #несуществующего собеседника. У всех остальных эндпоинтов участие
                    #сверяет `_require_participant`; сокет был исключением.
                    everyone = _participant_ids(db2, data["conversation_id"])
                    ids = [i for i in everyone if i != user.id] if user.id in everyone else []
                finally:
                    db2.close()
                if ids:
                    await ws_manager.send_users(
                        ids, {"type": "typing", "conversation_id": data["conversation_id"],
                              "user_id": user.id})
    except WebSocketDisconnect:
        ws_manager.disconnect(user.id, ws)
    except Exception:
        ws_manager.disconnect(user.id, ws)
