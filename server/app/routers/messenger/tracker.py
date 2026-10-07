"""
tracker.py — трекер задач беседы: работы, колонки, задачи, исполнители, история.

Часть пакета `routers/messenger`. Просьба Ярослава (05.10.2026): владелец включает
трекер в настройках беседы — у всех участников появляется кнопка, открывающая доску; в
беседе несколько «работ», в них задачи и распределение; назначенному приходит письмо во
вкладку «Уведомления». Планка названа прямо: «должно быть на уровне Яндекс Трекера» —
отсюда ключ работы и номера задач («KURS-12»), тип и приоритет задачи, дата начала и
срок, оценка и затраченное время, подзадачи, связи, метки, чек-лист, комментарии и
история изменений.

━━ ГЛАВНОЕ РЕШЕНИЕ: ПРАВКИ УХОДЯТ ПАЧКОЙ, ПО КНОПКЕ «СОХРАНИТЬ» ━━━━━━━━━━━━━━━━━━━━━━
Требование дословно: «чтобы уведомления из трекера не спамили, если кучу задач делят на
кучу людей, — сделать кнопку сохранить, при нажатии на которую сохранятся все действия и
придут уведомления тем, кого назначили». Поэтому записывающая ручка ОДНА —
`POST …/tracker/save` со списком операций. Клиент копит их у себя и присылает разом;
сервер применяет их одной транзакцией и шлёт каждому назначенному РОВНО ОДНО письмо со
всеми его новыми задачами.

⚠️ Отдельных ручек «создать задачу», «назначить» НЕТ намеренно. Появись они — письмо
пришлось бы слать на каждую, и правило «одно письмо на сохранение» держалось бы на
аккуратности клиента: первый же экран, зовущий ручку напрямую, вернул бы спам.

━━ ПРАВА ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • включить, выключить, сменить режим — ТОЛЬКО владелец беседы;
  • вести трекер (работы, колонки, задачи, исполнители) — владелец, админы беседы, роль с
    правом `tracker`; либо любой участник, если владелец включил «ставить задачи может
    каждый» (`open_edit`);
  • исполнитель без права вести трекер в СВОЕЙ задаче двигает её по колонкам, отмечает
    пункты чек-листа и пишет затраченное время — и ничего больше;
  • комментировать может любой участник, которому в этой беседе можно писать.

🔒 ТЕКСТ В ТРЕКЕРЕ — ТАКАЯ ЖЕ ЗАПИСЬ, КАК СООБЩЕНИЕ (инвариант §4.27: «новая дверь записи
наследует ВСЕ запреты старой той же функцией»). Название задачи, описание и комментарий
видят все участники. Заглушённый в беседе (`/mute`), человек под мьютом модерации и
читатель канала без права писать не могут и сюда: пачка с ЛЮБЫМ текстом идёт через
`messages._ensure_may_write`. Мат маскируется тем же фильтром, что в сообщениях.
Без этого трекер стал бы обходом мьюта: пиши не в чат, а в название задачи.

⚠️ ОПЕРАЦИЯ ЛИБО ПРИМЕНЯЕТСЯ ЦЕЛИКОМ, ЛИБО НЕ МЕНЯЕТ НИЧЕГО. Каждая сначала проверяет
ВСЁ и только потом пишет. Точек сохранения (SAVEPOINT) здесь нет намеренно: у pysqlite
они работают только с ручным управлением транзакциями, которого в проекте нет нигде.
"""
import re

from ._common import *      # noqa: F401,F403 — роутеры, модели, хелперы
from .messages import _ensure_may_write
from ...models import (TrackerActivity, TrackerAssignee, TrackerColumn, TrackerComment,
                       TrackerProject, TrackerTask)

#Где трекер вообще бывает. В личном чате и «Избранном» распределять задачи некому, чат
#модерации — служебный поток.
_TRACKER_KINDS = ("group", "channel")
_COLUMN_KINDS = ("todo", "doing", "review", "done")
#Приоритеты и типы — те же пять и пять, что у Яндекс Трекера: человеку, который им
#пользовался, не надо переучиваться.
_PRIORITIES = ("trivial", "minor", "normal", "critical", "blocker")
_TASK_KINDS = ("task", "bug", "improvement", "epic", "milestone")
_LINK_KINDS = ("relates", "blocks", "depends")
#Колонки новой работы. Четыре, а не три: «На проверке» — то, чем учебная задача
#отличается от личного списка дел (сделал ≠ приняли).
_DEFAULT_COLUMNS = (("К выполнению", "todo"), ("В работе", "doing"),
                    ("На проверке", "review"), ("Готово", "done"))

#Потолки. Трекер — не хранилище: без них одна пачка завела бы десять тысяч задач, и
#открытие доски у всех участников превратилось бы в выгрузку базы на одноядерном сервере.
_MAX_OPS = 500
_MAX_PROJECTS = 40
_MAX_COLUMNS = 12
_MAX_TASKS = 800                 #на беседу
_MAX_ASSIGNEES = 20
_MAX_LABELS = 30
_MAX_CHECKLIST = 60
_MAX_LINKS = 20
_MAX_TITLE = 200
_MAX_DESCRIPTION = 4000
_MAX_COMMENT = 2000
_MAX_SHORT = 80                  #название колонки, метки — короче
_MAX_HOURS = 9999.0
_MAX_PARENT_DEPTH = 12           #глубина «подзадача подзадачи…», дальше считаем циклом
#🔒 Сколько строк одна пачка вправе переписать «за компанию» (нашёл Полковник 07.10.2026).
#Пачка идёт под замком записи ВСЕГО сервера. Смена типа колонки переписывает признак
#завершения у каждой её задачи, смена меток работы — метки у каждой задачи работы: 500
#таких операций над колонкой в 800 задач — это 400 000 записей в одной транзакции, и всё
#это время никто в колледже не может выставить оценку. Завести беседу и включить в ней
#трекер может и студент, так что это не оплошность, а готовый способ положить запись.
#Потолок с запасом покрывает честную работу (удалить работу на 800 задач, сменить тип
#большой колонки пару раз) и режет только размножение.
_MAX_WORK = 4000

#id объектов выдаёт КЛИЕНТ: операции одной пачки ссылаются друг на друга («создай задачу
#в только что созданной колонке»), и ждать ответа сервера ради id значило бы отказаться
#от самой пачки. Формат проверяется жёстко — id уходит в первичный ключ.
_ID_RE = {
    "project": re.compile(r"^trkp:[0-9a-f]{8,40}$"),
    "column": re.compile(r"^trkc:[0-9a-f]{8,40}$"),
    "task": re.compile(r"^trkt:[0-9a-f]{8,40}$"),
}
_SMALL_ID_RE = re.compile(r"^[0-9a-z_-]{1,40}$")        #метки, пункты чек-листа, комментарии
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")
_COLOR_RE = re.compile(r"^[a-z0-9_-]{0,24}$")           #id пресета палитры, не CSS
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")

#Поля операций, которые несут ТЕКСТ, написанный человеком. По ним решается, нужна ли
#проверка «можно ли ему писать в эту беседу» (см. шапку).
_TEXT_FIELDS = ("title", "description", "body", "text", "key")

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def make_key(title: str, taken) -> str:
    """Ключ работы из её названия: «Курсовая работа» → «KR», «Диплом» → «DIPLO».

    Несколько слов — аббревиатура, одно — его начало. Занятый ключ получает номер
    («KR2»): ключ уникален в беседе, иначе «KR-3» значило бы две разные задачи."""
    latin = "".join(_TRANSLIT.get(ch, ch) for ch in str(title or "").lower())
    words = re.findall(r"[a-z0-9]+", latin)
    base = "".join(w[0] for w in words[:5]) if len(words) >= 2 else ""
    if len(base) < 2:
        base = (words[0] if words else "")[:5]
    base = re.sub(r"^[0-9]+", "", base).upper()[:6]
    if len(base) < 2:
        base = "TASK"
    key, n = base, 2
    taken = set(taken or ())
    while key in taken:
        key = f"{base[:8]}{n}"
        n += 1
    return key


def _clean(text, limit: int) -> str:
    """Текст от человека: обрезка, потолок длины, маска мата — тем же фильтром и тем же
    набором символов, что у сообщений чата."""
    s = str(text or "").strip()[:limit]
    if not s:
        return ""
    import profanity_filter
    return profanity_filter.censor(s, mask=profanity_filter.MESSENGER_SAFE_MASK)


def _settings(db: Session, conv_id: str):
    return db.get(TrackerSettings, conv_id)


def _tracker_conv(db: Session, conv_id: str, user: User):
    """Беседа и участие в ней. Трекер бывает только в обычных группах и каналах."""
    conv = _conversation(db, conv_id)
    part = _require_participant(db, conv_id, user)
    if conv.kind not in _TRACKER_KINDS or conv.is_system:
        raise HTTPException(status_code=400,
                            detail="Трекер задач бывает только в группах и каналах")
    return conv, part


def _enabled_or_409(db: Session, conv_id: str):
    st = _settings(db, conv_id)
    if st is None or not st.enabled:
        raise HTTPException(status_code=409, detail="Трекер в этой беседе выключен")
    return st


def _owner_or_403(part: ConversationParticipant) -> None:
    if part.role != "owner":
        raise HTTPException(status_code=403,
                            detail="Трекер включает и настраивает владелец беседы")


def _can_manage(db: Session, part: ConversationParticipant, st) -> bool:
    """Вправе ли участник ВЕСТИ трекер (см. «Права» в шапке)."""
    if part.role == "owner":
        return True
    if "tracker" in _permissions_for(db, part):
        return True
    return bool(st is not None and st.open_edit)


def _members(db: Session, conv_id: str) -> list:
    """Участники беседы — те, кого можно назначить. Подпись — той же дверью, что у
    сообщений (`moderator_display_name`): модератор виден номером и здесь."""
    parts = (db.query(ConversationParticipant)
             .filter(ConversationParticipant.conversation_id == conv_id).all())
    urows = {u.id: u for u in db.query(User).filter(
        User.id.in_([p.user_id for p in parts]))} if parts else {}
    out = []
    for p in parts:
        u = urows.get(p.user_id)
        if u is None:
            continue
        prefs = u.prefs if isinstance(u.prefs, dict) else {}
        out.append({
            "user_id": u.id,
            "full_name": moderator_display_name(u) or u.id,
            "avatar": prefs.get("avatar", "") or "",
            "profile_color": prefs.get("profile_color", "") or "",
            "user_role": u.role or "",
            "group_name": u.group_name or "",
            "role": p.role,
        })
    out.sort(key=lambda x: (x["full_name"] or "").lower())
    return out


def _task_out(t: TrackerTask, key: str, assignees: list, comments: int) -> dict:
    return {
        "id": t.id, "project_id": t.project_id, "column_id": t.column_id,
        "number": int(t.number or 0), "key": f"{key}-{int(t.number or 0)}" if key else "",
        "kind": t.kind or "task", "title": t.title or "",
        "description": t.description or "", "priority": t.priority or "normal",
        "start_date": t.start_date or "", "deadline": t.deadline or "",
        "estimate": float(t.estimate or 0), "spent": float(t.spent or 0),
        "position": int(t.position or 0),
        "labels": list(t.labels or []), "checklist": list(t.checklist or []),
        "parent_id": t.parent_id or "", "links": list(t.links or []),
        "assignees": assignees, "comment_count": comments,
        "created_by": t.created_by or "", "created_at": t.created_at or "",
        "updated_at": t.updated_at or "", "completed_at": t.completed_at or "",
    }


def _state(db: Session, conv: Conversation, part: ConversationParticipant, user: User) -> dict:
    """Полное состояние трекера беседы — одним ответом.

    Доска рисуется целиком и правится у клиента до кнопки «Сохранить», поэтому отдаём
    всё разом: работы с колонками, задачи с исполнителями, состав беседы. Комментарии —
    только числом: их текст и история грузятся при открытии задачи."""
    st = _settings(db, conv.id)
    enabled = bool(st is not None and st.enabled)
    base = {
        "conversation_id": conv.id, "title": conv.title or "",
        "enabled": enabled,
        "open_edit": bool(st is not None and st.open_edit),
        #Включает и выключает только владелец — он же решает, кто ведёт задачи.
        "can_configure": part.role == "owner",
        "can_manage": enabled and _can_manage(db, part, st),
        "me": user.id,
    }
    if not enabled:
        #Выключенный трекер данных не отдаёт вовсе — даже тем, кто их когда-то видел.
        return {**base, "members": [], "projects": [], "tasks": []}
    cid = conv.id
    members = _members(db, cid)
    member_ids = {m["user_id"] for m in members}
    projects = (db.query(TrackerProject).filter(TrackerProject.conversation_id == cid)
                .order_by(TrackerProject.position, TrackerProject.created_at).all())
    columns = (db.query(TrackerColumn).filter(TrackerColumn.conversation_id == cid)
               .order_by(TrackerColumn.position).all())
    tasks = (db.query(TrackerTask).filter(TrackerTask.conversation_id == cid)
             .order_by(TrackerTask.position, TrackerTask.created_at).all())
    by_task = {}
    for a in db.query(TrackerAssignee).filter(TrackerAssignee.conversation_id == cid).all():
        #Вышедший из беседы исполнителем не показывается: назначить на него нельзя, а
        #строка в списке вела бы на человека, которого здесь уже нет.
        if a.user_id in member_ids:
            by_task.setdefault(a.task_id, []).append(a.user_id)
    counts = dict(db.query(TrackerComment.task_id, func.count(TrackerComment.id))
                  .filter(TrackerComment.conversation_id == cid)
                  .group_by(TrackerComment.task_id).all())
    cols_by_project = {}
    for c in columns:
        cols_by_project.setdefault(c.project_id, []).append(
            {"id": c.id, "title": c.title or "", "kind": c.kind or "todo",
             "position": int(c.position or 0)})
    keys = {p.id: (p.key or "") for p in projects}
    return {
        **base,
        "members": members,
        "projects": [{
            "id": p.id, "key": p.key or "", "title": p.title or "",
            "description": p.description or "",
            "color": p.color or "", "position": int(p.position or 0),
            "archived": bool(p.archived), "labels": list(p.labels or []),
            "columns": cols_by_project.get(p.id, []),
            "created_by": p.created_by or "", "created_at": p.created_at or "",
        } for p in projects],
        "tasks": [_task_out(t, keys.get(t.project_id, ""), by_task.get(t.id, []),
                            int(counts.get(t.id, 0))) for t in tasks],
    }


@router.get("/chats/{conv_id}/tracker")
def tracker_state(conv_id: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Состояние трекера беседы. Участнику; выключенный трекер — `enabled: false`."""
    conv, part = _tracker_conv(db, conv_id, user)
    return _state(db, conv, part, user)


@router.put("/chats/{conv_id}/tracker/settings")
def tracker_settings(conv_id: str, payload: dict = Body(...),
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Включить, выключить трекер, сменить «кто ведёт задачи». Только владелец беседы.

    ⚠️ Выключение НЕ стирает работы и задачи: тумблер нажимают и по ошибке, и на время
    каникул, а восстановить распределение за семестр было бы нечем. Данные просто
    перестают отдаваться и вернутся при включении."""
    conv, part = _tracker_conv(db, conv_id, user)
    _owner_or_403(part)                 #не владельцу очередь записи занимать незачем
    #🔒 Замок записи — ДО чтения строки настроек (инвариант §4.26). Строки нет, пока трекер
    #ни разу не включали: два быстрых нажатия тумблера оба видели «нет» и оба её
    #вставляли — второе падало отказом первичного ключа, то есть ответом 500 на обычный
    #двойной щелчок. Под замком второй запрос находит строку первого и просто правит её.
    from ..web import _common as _web_common
    _web_common._lock_for_write(db)
    db.expire_all()
    conv, part = _tracker_conv(db, conv_id, user)
    _owner_or_403(part)                 #владельца могли сменить, пока ждали замок
    st = _settings(db, conv_id)
    if st is None:
        st = TrackerSettings(conversation_id=conv_id, enabled=False, open_edit=False)
        db.add(st)
    was = bool(st.enabled)
    if "enabled" in payload:
        st.enabled = bool(payload.get("enabled"))
    if "open_edit" in payload:
        st.open_edit = bool(payload.get("open_edit"))
    st.updated_at = _now()
    st.updated_by = user.id
    db.commit()
    if bool(st.enabled) != was:
        #Строка в ленте — чтобы участники узнали, откуда взялась (или куда делась) кнопка.
        #Сбой сообщения настройку не отменяет: она уже сохранена.
        try:
            _system(db, conv_id, "tracker_on" if st.enabled else "tracker_off",
                    user.id, moderator_display_name(user) or user.login or "")
        except Exception as e:      # noqa: BLE001
            db.rollback()
            _hook_log.warning("трекер: системное сообщение не записано: %s", e)
    _broadcast(db, conv_id, "tracker")
    return _state(db, conv, part, user)


# ── Пачка операций ────────────────────────────────────────────────────────────────────

class _Skip(Exception):
    """Операция не применена — с причиной для человека. Остальная пачка идёт дальше."""


class _Batch:
    """Одно нажатие «Сохранить»: права вызывающего и то, что в итоге надо сообщить людям.
    Объект живёт один запрос — состояния уровня модуля здесь нет."""

    def __init__(self, db, conv, part, user, manage):
        self.db, self.conv, self.part, self.user = db, conv, part, user
        self.manage = manage
        self.now = _now()
        self.member_ids = set(_participant_ids(db, conv.id))
        self.skipped = []               #[{"i", "op", "reason"}] — что не применилось и почему
        self.applied = 0
        self.assigned = {}              #исполнитель → [id задач], назначенных ЭТОЙ пачкой
        self.initial = {}               #задача → кто был исполнителем ДО этой пачки
        self.work = 0                   #сколько строк пачка уже переписала «за компанию»
        self._mine = None               #id задач, где вызывающий — исполнитель
        self._names = None

    # ── доступ к объектам (строго своей беседы) ──────────────────────────────────────
    def project(self, pid):
        p = self.db.get(TrackerProject, str(pid or ""))
        return p if p is not None and p.conversation_id == self.conv.id else None

    def column(self, cid):
        c = self.db.get(TrackerColumn, str(cid or ""))
        return c if c is not None and c.conversation_id == self.conv.id else None

    def task(self, tid):
        t = self.db.get(TrackerTask, str(tid or ""))
        return t if t is not None and t.conversation_id == self.conv.id else None

    def is_my_task(self, task_id: str) -> bool:
        if self._mine is None:
            self.db.flush()
            self._mine = {r[0] for r in self.db.query(TrackerAssignee.task_id).filter(
                TrackerAssignee.conversation_id == self.conv.id,
                TrackerAssignee.user_id == self.user.id).all()}
        return task_id in self._mine

    def count(self, model) -> int:
        self.db.flush()
        return (self.db.query(func.count()).select_from(model)
                .filter(model.conversation_id == self.conv.id).scalar() or 0)

    def spend(self, rows: int) -> None:
        """Учесть, что операция перепишет ещё `rows` строк, — ДО первой записи (операция
        либо применяется целиком, либо не меняет ничего). См. `_MAX_WORK`."""
        if self.work + rows > _MAX_WORK:
            raise _Skip("слишком большое сохранение — сохраните частями")
        self.work += rows

    def name_of(self, uid: str) -> str:
        if self._names is None:
            self._names = _names_for(self.db, self.member_ids)
        return self._names.get(uid, "")

    def log(self, task_id: str, kind: str, **data) -> None:
        """Строка истории задачи. Значения — короткие строки: история рассказывает, ЧТО
        поменяли, а не хранит вторую копию описания."""
        clean = {k: (v[:160] if isinstance(v, str) else v) for k, v in data.items()}
        self.db.add(TrackerActivity(conversation_id=self.conv.id, task_id=task_id,
                                    actor_id=self.user.id, kind=kind, data=clean,
                                    created_at=self.now))


def _need_manage(b: _Batch):
    if not b.manage:
        raise _Skip("нет права вести трекер")


def _int_in(value, top: int) -> int:
    """Целое от нуля до потолка — или пропуск операции с понятной причиной."""
    try:
        return max(0, min(int(value), top))
    except (TypeError, ValueError, OverflowError):      #OverflowError — `Infinity` из JSON
        raise _Skip("позиция не число") from None


def _hours_in(value) -> float:
    """Часы (оценка, затрачено): неотрицательное число с двумя знаками."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError, OverflowError):      #OverflowError — целое в сотни знаков
        raise _Skip("время записано не числом") from None
    if v != v or v < 0 or v > _MAX_HOURS:         #v != v — это NaN
        raise _Skip("время вне допустимых границ")
    return round(v, 2)


def _new_id(kind: str, value) -> str:
    s = str(value or "")
    if not _ID_RE[kind].match(s):
        raise _Skip("неверный идентификатор")
    return s


def _labels_in(raw) -> list:
    out, seen = [], set()
    for it in (raw if isinstance(raw, list) else [])[:_MAX_LABELS]:
        if not isinstance(it, dict):
            continue
        lid = str(it.get("id") or "")
        title = _clean(it.get("title"), _MAX_SHORT)
        color = str(it.get("color") or "")
        if not _SMALL_ID_RE.match(lid) or lid in seen or not title:
            continue
        seen.add(lid)
        out.append({"id": lid, "title": title,
                    "color": color if _COLOR_RE.match(color) else ""})
    return out


def _label_ids_in(raw, alive: set) -> list:
    """Метки задачи: только строки-id меток ЭТОЙ работы. Словарь или число вместо id не
    должны ронять пачку отказом сервера (`x in alive` на нехешируемом — TypeError)."""
    out = []
    for x in (raw if isinstance(raw, list) else []):
        if isinstance(x, str) and x in alive and x not in out:
            out.append(x)
    return out[:_MAX_LABELS]


def _checklist_in(raw) -> list:
    out, seen = [], set()
    for it in (raw if isinstance(raw, list) else [])[:_MAX_CHECKLIST]:
        if not isinstance(it, dict):
            continue
        iid = str(it.get("id") or "")
        text = _clean(it.get("text"), _MAX_SHORT * 2)
        if not _SMALL_ID_RE.match(iid) or iid in seen or not text:
            continue
        seen.add(iid)
        out.append({"id": iid, "text": text, "done": bool(it.get("done"))})
    return out


def _date_in(raw) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if not _DATE_RE.match(s):
        raise _Skip("дата записана не датой")
    #Формат ещё не дата: «2026-13-45» под шаблон подходит. Такой срок лёг бы в базу, а
    #клиент при показе молча перенёс бы его на февраль следующего года.
    try:
        datetime.strptime(s, "%Y-%m-%dT%H:%M" if "T" in s else "%Y-%m-%d")
    except ValueError:
        raise _Skip("такой даты не существует") from None
    return s


def _links_in(b: _Batch, task_id: str, raw) -> list:
    """Связи задачи: только с задачами ЭТОЙ беседы и не с самой собой."""
    out, seen = [], set()
    b.db.flush()
    for it in (raw if isinstance(raw, list) else [])[:_MAX_LINKS]:
        if not isinstance(it, dict):
            continue
        kind, other = str(it.get("type") or ""), str(it.get("task_id") or "")
        if kind not in _LINK_KINDS or other == task_id or (kind, other) in seen:
            continue
        if b.task(other) is None:
            continue
        seen.add((kind, other))
        out.append({"type": kind, "task_id": other})
    return out


def _parent_in(b: _Batch, task_id: str, project_id: str, raw) -> str:
    """Родитель подзадачи: задача той же работы, не она сама и не её потомок."""
    pid = str(raw or "")
    if not pid:
        return ""
    b.db.flush()
    parent = b.task(pid)
    if parent is None or parent.project_id != project_id or pid == task_id:
        raise _Skip("родительская задача не найдена в этой работе")
    #Цикл «А подзадача Б, Б подзадача А» — идём вверх от родителя: встретили себя —
    #отказ. Потолок глубины заодно страхует от уже испорченных данных.
    cur, depth = parent, 0
    while cur is not None and cur.parent_id:
        depth += 1
        if cur.parent_id == task_id or depth > _MAX_PARENT_DEPTH:
            raise _Skip("задача не может быть подзадачей своей подзадачи")
        cur = b.task(cur.parent_id)
    return pid


def _set_assignees(b: _Batch, task: TrackerTask, raw, log: bool = True) -> None:
    """Привести исполнителей задачи к списку `raw`. Новых — запомнить для письма."""
    wanted = []
    for uid in (raw if isinstance(raw, list) else []):
        uid = str(uid or "")
        #Назначить можно только участника ЭТОЙ беседы: иначе письмо «вам дали задание»
        #получил бы посторонний, а в нём — название беседы и задачи.
        if uid in b.member_ids and uid not in wanted:
            wanted.append(uid)
    wanted = wanted[:_MAX_ASSIGNEES]
    b.db.flush()
    rows = b.db.query(TrackerAssignee).filter(TrackerAssignee.task_id == task.id).all()
    have = {r.user_id: r for r in rows}
    #Кто вёл задачу ДО этой пачки — запоминаем при первом касании. Сняли и вернули того же
    #человека двумя операциями одной пачки (клиент их не всегда склеивает) — задача у него
    #и так была: «Вам дали задание» о ней он уже получал.
    before = b.initial.setdefault(task.id, set(have))
    for uid, row in have.items():
        if uid not in wanted:
            b.db.delete(row)
            if log:
                b.log(task.id, "unassigned", user_id=uid, name=b.name_of(uid))
            #Сняли с задачи этой же пачкой — письма о назначении уже не нужно.
            if task.id in b.assigned.get(uid, []):
                b.assigned[uid].remove(task.id)
    for uid in wanted:
        if uid in have:
            continue
        b.db.add(TrackerAssignee(conversation_id=b.conv.id, task_id=task.id, user_id=uid,
                                 assigned_by=b.user.id, assigned_at=b.now))
        if log:
            b.log(task.id, "assigned", user_id=uid, name=b.name_of(uid))
        #Назначил сам себя — писать себе письмо незачем; вёл задачу до пачки — тоже.
        if uid != b.user.id and uid not in before:
            ids = b.assigned.setdefault(uid, [])
            if task.id not in ids:
                ids.append(task.id)
    if b._mine is not None:
        (b._mine.add if b.user.id in wanted else b._mine.discard)(task.id)


def _move_task(b: _Batch, task: TrackerTask, col: TrackerColumn, position) -> None:
    if col.project_id != task.project_id:
        raise _Skip("колонка из другой работы")
    new_position = _int_in(position, 1_000_000) if position is not None else None
    if col.id != task.column_id:
        old = b.column(task.column_id)
        b.log(task.id, "moved", **{"from": (old.title if old is not None else ""),
                                   "to": col.title or ""})
        task.column_id = col.id
        #Время завершения ставит СЕРВЕР и только на переходе: задача, которую двигают
        #внутри «Готово», не должна каждый раз «завершаться заново».
        task.completed_at = (task.completed_at or b.now) if col.kind == "done" else ""
    if new_position is not None:
        task.position = new_position
    task.updated_at = b.now


def _op_project_create(b: _Batch, op: dict):
    _need_manage(b)
    pid = _new_id("project", op.get("id"))
    if b.db.get(TrackerProject, pid) is not None:
        raise _Skip("уже есть")                 #повтор пачки после обрыва связи — не ошибка
    n = b.count(TrackerProject)
    if n >= _MAX_PROJECTS:
        raise _Skip("слишком много работ в беседе")
    title = _clean(op.get("title"), _MAX_TITLE)
    if not title:
        raise _Skip("у работы нет названия")
    taken = {r[0] for r in b.db.query(TrackerProject.key)
             .filter(TrackerProject.conversation_id == b.conv.id).all()}
    key = str(op.get("key") or "").strip().upper()
    if not _KEY_RE.match(key) or key in taken:
        key = make_key(title, taken)            #свой ключ не годится — выводим из названия
    color = str(op.get("color") or "")
    b.db.add(TrackerProject(
        id=pid, conversation_id=b.conv.id, key=key, title=title,
        description=_clean(op.get("description"), _MAX_DESCRIPTION),
        color=color if _COLOR_RE.match(color) else "",
        position=n, archived=False, labels=_labels_in(op.get("labels")), task_seq=0,
        created_by=b.user.id, created_at=b.now, updated_at=b.now))
    #Колонки по умолчанию заводит сервер, если клиент не прислал своих: работа без единой
    #колонки — доска, на которую некуда положить задачу.
    cols = op.get("columns")
    if not isinstance(cols, list) or not cols:
        cols = [{"id": "trkc:%s" % uuid4().hex, "title": t, "kind": k}
                for t, k in _DEFAULT_COLUMNS]
    seen = set()
    for i, c in enumerate(cols[:_MAX_COLUMNS]):
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "")
        #`seen` — повтор id ВНУТРИ этой же операции: `Session.get` ещё не сброшенную
        #колонку не видит, и две одинаковые дошли бы до базы отказом первичного ключа,
        #то есть ответом 500 на всю пачку вместо пропуска одной лишней строки.
        if (not _ID_RE["column"].match(cid) or cid in seen
                or b.db.get(TrackerColumn, cid) is not None):
            continue
        seen.add(cid)
        kind = str(c.get("kind") or "todo")
        b.db.add(TrackerColumn(id=cid, conversation_id=b.conv.id, project_id=pid,
                               title=_clean(c.get("title"), _MAX_SHORT) or "Без названия",
                               kind=kind if kind in _COLUMN_KINDS else "todo", position=i))


def _op_project_update(b: _Batch, op: dict):
    _need_manage(b)
    p = b.project(op.get("id"))
    if p is None:
        raise _Skip("работа не найдена")
    #⚠️ Сначала ВСЕ проверки, потом запись (так у каждой операции ниже). Отказ на третьем
    #поле после записи первых двух оставил бы в базе полуприменённую операцию, а человеку
    #она вернулась бы как «пропущена».
    title = _clean(op.get("title"), _MAX_TITLE) if "title" in op else None
    if title == "":
        raise _Skip("у работы нет названия")
    position = _int_in(op.get("position"), 10_000) if "position" in op else None
    if "labels" in op:
        b.spend(b.db.query(func.count(TrackerTask.id))
                .filter(TrackerTask.project_id == p.id).scalar() or 0)
    if title is not None:
        p.title = title
    if position is not None:
        p.position = position
    if "description" in op:
        p.description = _clean(op.get("description"), _MAX_DESCRIPTION)
    if "color" in op:
        color = str(op.get("color") or "")
        p.color = color if _COLOR_RE.match(color) else ""
    if "archived" in op:
        p.archived = bool(op.get("archived"))
    if "labels" in op:
        labels = _labels_in(op.get("labels"))
        p.labels = labels
        #Снятая метка уходит и с задач: иначе у задачи остался бы id, по которому уже
        #нечего нарисовать.
        alive = {x["id"] for x in labels}
        b.db.flush()
        for t in b.db.query(TrackerTask).filter(TrackerTask.project_id == p.id).all():
            kept = [x for x in (t.labels or []) if x in alive]
            if kept != list(t.labels or []):
                t.labels = kept
    p.updated_at = b.now


def _delete_tasks(b: _Batch, task_ids: list) -> None:
    """Удалить задачи со всем, что на них висит, и подчистить ссылки на них у соседей."""
    if not task_ids:
        return
    gone = set(task_ids)
    #Соседей, которые ссылаются на удаляемое, ищем ЛЁГКИМ запросом трёх колонок, а целиком
    #грузим только их и сами удаляемые задачи. Раньше каждая операция удаления грузила ВСЕ
    #задачи беседы: 500 удалений при 800 задачах — 400 000 объектов под замком записи.
    b.db.flush()
    near = [r[0] for r in (b.db.query(TrackerTask.id, TrackerTask.parent_id, TrackerTask.links)
                           .filter(TrackerTask.conversation_id == b.conv.id).all())
            if r[0] not in gone and (r[1] in gone or any(
                isinstance(x, dict) and x.get("task_id") in gone for x in (r[2] or [])))]
    b.spend(len(gone) + len(near))              #до первой записи: дальше отказов нет
    for model in (TrackerAssignee, TrackerComment, TrackerActivity):
        b.db.query(model).filter(model.task_id.in_(task_ids)).delete(synchronize_session=False)
    wanted = sorted(gone) + near
    for i in range(0, len(wanted), 400):        #порциями: у SQLite потолок числа параметров
        for t in b.db.query(TrackerTask).filter(TrackerTask.id.in_(wanted[i:i + 400])).all():
            if t.id in gone:
                b.db.delete(t)
                continue
            #Подзадача удалённой задачи становится обычной задачей, а не пропадает вместе
            #с родителем: удаляли одну задачу, а не дерево.
            if t.parent_id in gone:
                t.parent_id = ""
            kept = [x for x in (t.links or []) if x.get("task_id") not in gone]
            if len(kept) != len(t.links or []):
                t.links = kept
    #Удалённая задача больше не «была у человека до пачки»: создадут заново с тем же id и
    #назначат — это новое назначение, и письмо о нём положено.
    for tid in gone:
        b.initial.pop(tid, None)
    #Удалённая задача письма не заслуживает, даже если этой же пачкой на неё успели
    #кого-то назначить.
    for ids in b.assigned.values():
        ids[:] = [x for x in ids if x not in gone]
    if b._mine is not None:
        b._mine -= gone


def _op_project_delete(b: _Batch, op: dict):
    _need_manage(b)
    p = b.project(op.get("id"))
    if p is None:
        raise _Skip("работа не найдена")
    b.db.flush()
    ids = [r[0] for r in b.db.query(TrackerTask.id).filter(TrackerTask.project_id == p.id).all()]
    _delete_tasks(b, ids)
    b.db.query(TrackerColumn).filter(TrackerColumn.project_id == p.id).delete(
        synchronize_session=False)
    b.db.delete(p)


def _op_column_create(b: _Batch, op: dict):
    _need_manage(b)
    p = b.project(op.get("project_id"))
    if p is None:
        raise _Skip("работа не найдена")
    cid = _new_id("column", op.get("id"))
    if b.db.get(TrackerColumn, cid) is not None:
        raise _Skip("уже есть")
    b.db.flush()
    n = (b.db.query(func.count(TrackerColumn.id))
         .filter(TrackerColumn.project_id == p.id).scalar() or 0)
    if n >= _MAX_COLUMNS:
        raise _Skip("слишком много колонок")
    kind = str(op.get("kind") or "todo")
    position = _int_in(op.get("position"), 1000) if "position" in op else n
    b.db.add(TrackerColumn(id=cid, conversation_id=b.conv.id, project_id=p.id,
                           title=_clean(op.get("title"), _MAX_SHORT) or "Без названия",
                           kind=kind if kind in _COLUMN_KINDS else "todo",
                           position=position))


def _op_column_update(b: _Batch, op: dict):
    _need_manage(b)
    c = b.column(op.get("id"))
    if c is None:
        raise _Skip("колонка не найдена")
    kind = str(op.get("kind") or "") if "kind" in op else None
    if kind is not None and kind not in _COLUMN_KINDS:
        raise _Skip("неизвестный тип колонки")
    position = _int_in(op.get("position"), 1000) if "position" in op else None
    if kind is not None and kind != c.kind:
        b.spend(b.db.query(func.count(TrackerTask.id))
                .filter(TrackerTask.column_id == c.id).scalar() or 0)
    if "title" in op:
        c.title = _clean(op.get("title"), _MAX_SHORT) or c.title
    if position is not None:
        c.position = position
    if kind is not None and kind != c.kind:
        c.kind = kind
        #Колонка стала (или перестала быть) «готово» — её задачи меняют признак
        #завершения вместе с ней, иначе счётчик выполненного разойдётся с доской.
        b.db.flush()
        for t in b.db.query(TrackerTask).filter(TrackerTask.column_id == c.id).all():
            t.completed_at = (t.completed_at or b.now) if kind == "done" else ""


def _op_column_delete(b: _Batch, op: dict):
    _need_manage(b)
    c = b.column(op.get("id"))
    if c is None:
        raise _Skip("колонка не найдена")
    b.db.flush()
    tasks = b.db.query(TrackerTask).filter(TrackerTask.column_id == c.id).all()
    if tasks:
        #Задачи удаляемой колонки не пропадают молча: либо их переносят в названную
        #колонку той же работы, либо удаление отклоняется.
        target = b.column(op.get("move_to"))
        if target is None or target.id == c.id or target.project_id != c.project_id:
            raise _Skip("в колонке есть задачи — укажите, куда их перенести")
        b.spend(len(tasks))
        for t in tasks:
            _move_task(b, t, target, None)
    b.db.delete(c)


def _op_task_create(b: _Batch, op: dict):
    _need_manage(b)
    col = b.column(op.get("column_id"))
    if col is None:
        raise _Skip("колонка не найдена")
    tid = _new_id("task", op.get("id"))
    if b.db.get(TrackerTask, tid) is not None:
        raise _Skip("уже есть")
    if b.count(TrackerTask) >= _MAX_TASKS:
        raise _Skip("слишком много задач в беседе")
    title = _clean(op.get("title"), _MAX_TITLE)
    if not title:
        raise _Skip("у задачи нет названия")
    project = b.project(col.project_id)
    if project is None:
        raise _Skip("работа не найдена")
    priority = str(op.get("priority") or "normal")
    kind = str(op.get("kind") or "task")
    alive = {x["id"] for x in (project.labels or [])}
    start_date, deadline = _date_in(op.get("start_date")), _date_in(op.get("deadline"))
    estimate, spent = _hours_in(op.get("estimate")), _hours_in(op.get("spent"))
    position = _int_in(op.get("position") or 0, 1_000_000)
    parent_id = _parent_in(b, tid, project.id, op.get("parent_id"))
    links = _links_in(b, tid, op.get("links"))
    #Номер берём ПОСЛЕДНИМ: отклонённая задача не должна оставлять дыру в нумерации.
    project.task_seq = int(project.task_seq or 0) + 1
    t = TrackerTask(
        id=tid, conversation_id=b.conv.id, project_id=project.id, column_id=col.id,
        number=project.task_seq, kind=kind if kind in _TASK_KINDS else "task", title=title,
        description=_clean(op.get("description"), _MAX_DESCRIPTION),
        priority=priority if priority in _PRIORITIES else "normal",
        start_date=start_date, deadline=deadline, estimate=estimate, spent=spent,
        position=position,
        labels=_label_ids_in(op.get("labels"), alive),
        checklist=_checklist_in(op.get("checklist")), parent_id=parent_id, links=links,
        created_by=b.user.id, created_at=b.now, updated_at=b.now,
        completed_at=b.now if col.kind == "done" else "")
    b.db.add(t)
    b.log(tid, "created")
    if op.get("assignees"):
        _set_assignees(b, t, op.get("assignees"))


#Поля задачи, смену которых пишем в историю, и как показать их значение одной строкой.
def _show(field: str, value) -> str:
    if field in ("estimate", "spent"):
        return ("%g" % float(value or 0)) if value else ""
    return str(value or "")


def _op_task_update(b: _Batch, op: dict):
    t = b.task(op.get("id"))
    if t is None:
        raise _Skip("задача не найдена")
    fields = set(op) - {"op", "id"}
    if not b.manage:
        #Исполнитель без права вести трекер меняет в СВОЕЙ задаче только отметки пунктов
        #чек-листа и затраченное время: ни текста пунктов, ни их состава, ни прочих полей.
        if not fields or not fields <= {"checklist", "spent"} or not b.is_my_task(t.id):
            raise _Skip("нет права вести трекер")
        spent = _hours_in(op.get("spent")) if "spent" in op else None
        if "checklist" in op:
            raw = op.get("checklist")
            done = {str(x.get("id")): bool(x.get("done"))
                    for x in (raw if isinstance(raw, list) else []) if isinstance(x, dict)}
            t.checklist = [{**it, "done": done.get(it.get("id"), bool(it.get("done")))}
                           for it in (t.checklist or [])]
        if spent is not None and spent != float(t.spent or 0):
            b.log(t.id, "changed", field="spent", old=_show("spent", t.spent),
                  new=_show("spent", spent))
            t.spent = spent
        t.updated_at = b.now
        return
    title = _clean(op.get("title"), _MAX_TITLE) if "title" in op else None
    if title == "":
        raise _Skip("у задачи нет названия")
    priority = str(op.get("priority") or "") if "priority" in op else None
    if priority is not None and priority not in _PRIORITIES:
        raise _Skip("неизвестный приоритет")
    kind = str(op.get("kind") or "") if "kind" in op else None
    if kind is not None and kind not in _TASK_KINDS:
        raise _Skip("неизвестный тип задачи")
    new = {}
    if title is not None:
        new["title"] = title
    if priority is not None:
        new["priority"] = priority
    if kind is not None:
        new["kind"] = kind
    for f in ("start_date", "deadline"):
        if f in op:
            new[f] = _date_in(op.get(f))
    for f in ("estimate", "spent"):
        if f in op:
            new[f] = _hours_in(op.get(f))
    if "parent_id" in op:
        new["parent_id"] = _parent_in(b, t.id, t.project_id, op.get("parent_id"))
    links = _links_in(b, t.id, op.get("links")) if "links" in op else None
    #Проверки кончились — пишем. История получает строку только на РЕАЛЬНУЮ смену:
    #клиент присылает поля задачи целиком, и «изменено» на каждое сохранение без правок
    #превратило бы историю в шум.
    for f, value in new.items():
        old = getattr(t, f)
        if (float(old or 0) if f in ("estimate", "spent") else (old or "")) == value:
            continue
        b.log(t.id, "changed", field=f, old=_show(f, old), new=_show(f, value))
        setattr(t, f, value)
    if "description" in op:
        text = _clean(op.get("description"), _MAX_DESCRIPTION)
        if text != (t.description or ""):
            b.log(t.id, "changed", field="description")
            t.description = text
    if "labels" in op:
        project = b.project(t.project_id)
        alive = {x["id"] for x in ((project.labels if project is not None else None) or [])}
        kept = _label_ids_in(op.get("labels"), alive)
        if kept != list(t.labels or []):
            b.log(t.id, "changed", field="labels")
            t.labels = kept
    if "checklist" in op:
        items = _checklist_in(op.get("checklist"))
        if items != list(t.checklist or []):
            t.checklist = items
    if links is not None and links != list(t.links or []):
        b.log(t.id, "changed", field="links")
        t.links = links
    if "assignees" in op:
        _set_assignees(b, t, op.get("assignees"))
    t.updated_at = b.now


def _op_task_move(b: _Batch, op: dict):
    t = b.task(op.get("id"))
    if t is None:
        raise _Skip("задача не найдена")
    #Двигать по колонкам может и исполнитель: «взял в работу», «сдал на проверку» — это
    #его часть работы, и ждать ради неё ведущего трекер было бы бюрократией.
    if not b.manage and not b.is_my_task(t.id):
        raise _Skip("двигать можно только свои задачи")
    col = b.column(op.get("column_id")) if op.get("column_id") else b.column(t.column_id)
    if col is None:
        raise _Skip("колонка не найдена")
    _move_task(b, t, col, op.get("position") if "position" in op else None)


def _op_task_delete(b: _Batch, op: dict):
    _need_manage(b)
    t = b.task(op.get("id"))
    if t is None:
        raise _Skip("задача не найдена")
    b.db.flush()
    _delete_tasks(b, [t.id])


def _op_comment_add(b: _Batch, op: dict):
    t = b.task(op.get("task_id"))
    if t is None:
        raise _Skip("задача не найдена")
    body = _clean(op.get("body"), _MAX_COMMENT)
    if not body:
        raise _Skip("пустой комментарий")
    cid = str(op.get("id") or "")
    if not _SMALL_ID_RE.match(cid):
        raise _Skip("неверный идентификатор")
    b.db.flush()
    #Повтор пачки после обрыва связи не должен удвоить комментарий: клиент не знает,
    #дошла ли первая попытка, и честно пришлёт её снова.
    dup = (b.db.query(TrackerComment.id)
           .filter(TrackerComment.task_id == t.id, TrackerComment.client_id == cid,
                   TrackerComment.author_id == b.user.id).first())
    if dup is not None:
        raise _Skip("уже есть")
    b.db.add(TrackerComment(conversation_id=b.conv.id, task_id=t.id, author_id=b.user.id,
                            client_id=cid, body=body, created_at=b.now))
    b.log(t.id, "commented")


def _op_comment_delete(b: _Batch, op: dict):
    #Номер комментария — целое из базы. «Бесконечность» и число шире 64 бит — не номер:
    #первое роняло `int()`, второе — драйвер SQLite, оба отказом сервера на всю пачку.
    try:
        cid = int(op.get("id"))
    except (TypeError, ValueError, OverflowError):
        cid = 0
    c = b.db.get(TrackerComment, cid) if 0 < cid < 2 ** 63 else None
    #🔒 Сверка беседы обязательна: номера комментариев сквозные по базе, и без неё каждый,
    #кто ведёт трекер ХОТЬ ГДЕ-ТО (при «задачи ставит каждый» — любой участник любой
    #беседы), удалял бы чужие комментарии перебором номеров.
    if c is None or c.conversation_id != b.conv.id:
        raise _Skip("комментарий не найден")
    if c.author_id != b.user.id and not b.manage:
        raise _Skip("чужой комментарий")
    b.db.delete(c)


_OPS = {
    "project.create": _op_project_create, "project.update": _op_project_update,
    "project.delete": _op_project_delete,
    "column.create": _op_column_create, "column.update": _op_column_update,
    "column.delete": _op_column_delete,
    "task.create": _op_task_create, "task.update": _op_task_update,
    "task.move": _op_task_move, "task.delete": _op_task_delete,
    "comment.add": _op_comment_add, "comment.delete": _op_comment_delete,
}


def _has_text(ops: list) -> bool:
    """Несёт ли пачка текст от человека (тогда нужна проверка права писать в беседу)."""
    for op in ops:
        if any(str(op.get(k) or "").strip() for k in _TEXT_FIELDS):
            return True
        for key in ("labels", "checklist", "columns"):
            items = op.get(key)
            if isinstance(items, list) and any(
                    isinstance(x, dict) and (x.get("title") or x.get("text")) for x in items):
                return True
    return False


def _only_own_progress(ops: list) -> bool:
    """Пачка, где текст есть лишь формально: исполнитель двигает свою задачу, отмечает
    пункты чек-листа и пишет затраченное время. В операции едут прежние подписи пунктов,
    но сервер в этой ветке их НЕ читает (см. `_op_task_update`), значит и проверять
    «можно ли ему писать» не с чего: заглушённый в беседе всё ещё вправе отметить
    сделанное. Глушат ему слова, а не работу."""
    return all(op.get("op") == "task.move"
               or (op.get("op") == "task.update"
                   and set(op) - {"op", "id"} <= {"checklist", "spent"})
               for op in ops)


@router.post("/chats/{conv_id}/tracker/save")
def tracker_save(conv_id: str, payload: dict = Body(...),
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Применить пачку операций — то, что человек накопил до кнопки «Сохранить».

    Одна транзакция и одно письмо на исполнителя (см. шапку). Операция, которую применить
    нельзя (объект уже удалил другой человек, не хватило права), ПРОПУСКАЕТСЯ с причиной,
    остальные применяются: пачку собирают минутами, и отказ целиком из-за одной
    устаревшей строки стирал бы всю работу."""
    conv, part = _tracker_conv(db, conv_id, user)
    ops = payload.get("ops")
    if not isinstance(ops, list) or not ops:
        raise HTTPException(status_code=400, detail="Нечего сохранять")
    if len(ops) > _MAX_OPS:
        raise HTTPException(status_code=413,
                            detail=f"Слишком много изменений за раз (больше {_MAX_OPS}). "
                                   "Сохраняйте чаще.")
    ops = [op for op in ops if isinstance(op, dict)]
    #🔒 ЗАМОК ЗАПИСИ — ДО ВСЕГО, ОТ ЧЕГО ЗАВИСИТ «МОЖНО ЛИ» (инварианты §4.26 и §4.29;
    #нашёл Полковник 06.10.2026). Первая версия читала настройки трекера, права участника
    #и «заглушён ли он» ДО замка и под ним не перечитывала: владелец выключил трекер, снял
    #«задачи ставит каждый» или заглушил участника, пока сохранение ждёт очереди, — и пачка
    #применялась по правам, которых уже нет. Участие в беседе выше проверено без замка
    #намеренно: постороннему очередь записи занимать незачем.
    from ..web import _common as _web_common
    _web_common._lock_for_write(db)
    #Всё, что прочитано до замка, — снимок: сбрасываем и читаем заново уже под ним.
    db.expire_all()
    conv, part = _tracker_conv(db, conv_id, user)
    st = _enabled_or_409(db, conv_id)
    manage = _can_manage(db, part, st)
    #Отказ здесь ничего не оставляет: до первой операции в сессии нет ни одной правки, а
    #замок снимет закрытие сессии.
    if _has_text(ops) and not (not manage and _only_own_progress(ops)):
        _ensure_may_write(db, conv, part, user, new_message=False)
    wait = msg_limit.check(user.id)             #жёсткий анти-флуд: сохранение — тоже запись
    if wait:
        raise HTTPException(status_code=429,
                            detail="Слишком частые сохранения. Подождите немного.",
                            headers={"Retry-After": str(wait)})
    #Под этим же замком считаются номер задачи и потолки: две одновременные пачки иначе
    #выдали бы один номер двум задачам.
    b = _Batch(db, conv, part, user, manage)
    for i, op in enumerate(ops):
        name = str(op.get("op") or "")
        fn = _OPS.get(name)
        if fn is None:
            b.skipped.append({"i": i, "op": name, "reason": "неизвестная операция"})
            continue
        try:
            fn(b, op)
            #🔥 СБРОС В БАЗУ ПОСЛЕ КАЖДОЙ ПРИМЕНЁННОЙ ОПЕРАЦИИ (06.10.2026, живой прогон).
            #Сессия у нас без автосброса (`autoflush=False`), а `Session.get`, которым
            #операции ищут работу, колонку и задачу, видит только то, что уже в базе или в
            #карте объектов: добавленная предыдущей операцией колонка для него НЕ
            #существует. Самый частый первый сценарий — завёл работу, накидал в неё задач,
            #нажал «Сохранить» — применял одну работу, а все задачи пропускал с причиной
            #«колонка не найдена»: человек терял всё распределение, причём тесты были
            #зелёными (в них работа и задачи шли РАЗНЫМИ сохранениями, а клиент шлёт
            #одной пачкой всегда). Сброс здесь, а не в каждом поиске: забыть его в
            #тринадцатой операции нельзя по построению.
            #⚠️ Операция, отклонённая `_Skip`, сюда не доходит и ничего не оставляет: у
            #каждой сначала все проверки, потом запись.
            db.flush()
            b.applied += 1
        except _Skip as e:
            b.skipped.append({"i": i, "op": name, "reason": str(e)})
    db.commit()
    notified = _notify_assigned(b)
    _broadcast(db, conv_id, "tracker")
    try:
        audit.log(db, actor=user.login or user.id, role=user.role, action="tracker.save",
                  target=conv_id, detail=f"применено {b.applied}, пропущено {len(b.skipped)}")
    except Exception as e:      # noqa: BLE001
        _hook_log.warning("трекер: запись аудита не удалась: %s", e)
    return {"applied": b.applied, "skipped": b.skipped, "notified": notified,
            "state": _state(db, conv, part, user)}


def _notify_assigned(b: _Batch) -> int:
    """Письмо каждому, кого назначили этой пачкой, — ОДНО, со всеми его задачами.

    Превью нарочно без подробностей («Вам дали задание в трекере» — формулировка
    Ярослава): подробности — задача, срок, работа, кто назначил — лежат в `payload` и
    показываются на странице письма. В ПУШ, как у всех уведомлений, уходит только тип и
    id события: название беседы и задачи через посредника не едут.

    Не бросает исключений: сохранение уже состоялось, и сбой письма не должен вернуть
    человеку ошибку на работу, которая записана."""
    sent = 0
    try:
        from ... import rustore_push
        db = b.db
        targets = {uid: ids for uid, ids in b.assigned.items() if ids and uid in b.member_ids}
        if not targets:
            return 0
        users = {u.id: u for u in db.query(User).filter(User.id.in_(list(targets))).all()}
        all_ids = sorted({t for ids in targets.values() for t in ids})
        tasks = {t.id: t for t in db.query(TrackerTask).filter(TrackerTask.id.in_(all_ids)).all()}
        projects = {p.id: p for p in db.query(TrackerProject)
                    .filter(TrackerProject.conversation_id == b.conv.id).all()}
        columns = {c.id: c for c in db.query(TrackerColumn)
                   .filter(TrackerColumn.conversation_id == b.conv.id).all()}
        by_name = moderator_display_name(b.user) or b.user.login or ""
        for uid, ids in targets.items():
            u = users.get(uid)
            if u is None or not u.login:
                continue
            items = []
            for tid in ids:
                t = tasks.get(tid)
                if t is None:
                    continue
                p, c = projects.get(t.project_id), columns.get(t.column_id)
                key = f"{p.key}-{int(t.number or 0)}" if p is not None and p.key else ""
                items.append({
                    "id": t.id, "key": key, "kind": t.kind or "task", "title": t.title or "",
                    "description": (t.description or "")[:600],
                    "start_date": t.start_date or "", "deadline": t.deadline or "",
                    "priority": t.priority or "normal", "estimate": float(t.estimate or 0),
                    "project_id": t.project_id, "project": (p.title if p is not None else ""),
                    "column": (c.title if c is not None else ""),
                    "checklist_total": len(t.checklist or []),
                })
            if not items:
                continue
            title = ("Вам дали задание в трекере" if len(items) == 1
                     else f"Вам дали задания в трекере: {len(items)}")
            event_id = rustore_push._create_event(
                db, u.login, "tracker", title,
                "Откройте письмо, чтобы посмотреть задачу и срок.",
                payload={"conversation_id": b.conv.id, "conversation": b.conv.title or "",
                         "assigned_by": by_name, "assigned_by_id": b.user.id,
                         "tasks": items},
                author_login=b.user.login or "")
            sent += 1
            #Мьют беседы уважаем, как у громких отметок: письмо остаётся (это история),
            #а телефон не звонит — человек сам просил тишины от этой беседы.
            muted = (db.query(ConversationParticipant.muted)
                     .filter(ConversationParticipant.conversation_id == b.conv.id,
                             ConversationParticipant.user_id == uid).scalar())
            if not muted:
                rustore_push.notify_login(db, u.login, title, "Откройте приложение.",
                                          {"type": "tracker", "event_id": event_id})
    except Exception as e:      # noqa: BLE001
        _hook_log.warning("трекер: письмо исполнителям не отправлено: %s", e)
        try:
            b.db.rollback()
        except Exception:       # noqa: BLE001
            pass
    return sent


@router.get("/chats/{conv_id}/tracker/tasks/{task_id}/details")
def tracker_task_details(conv_id: str, task_id: str,
                         user: User = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    """Комментарии и история задачи — грузятся при её открытии, а не вместе с доской."""
    conv, _part = _tracker_conv(db, conv_id, user)
    _enabled_or_409(db, conv_id)
    t = db.get(TrackerTask, task_id)
    if t is None or t.conversation_id != conv.id:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    comments = (db.query(TrackerComment).filter(TrackerComment.task_id == task_id)
                .order_by(TrackerComment.id).all())
    history = (db.query(TrackerActivity).filter(TrackerActivity.task_id == task_id)
               .order_by(TrackerActivity.id).all())
    names = _names_for(db, {r.author_id for r in comments} | {r.actor_id for r in history})
    return {
        "comments": [{"id": r.id, "author_id": r.author_id,
                      "author_name": names.get(r.author_id, ""),
                      "body": r.body or "", "created_at": r.created_at or "",
                      "mine": r.author_id == user.id} for r in comments],
        "history": [{"id": r.id, "actor_id": r.actor_id,
                     "actor_name": names.get(r.actor_id, ""), "kind": r.kind or "",
                     "data": r.data or {}, "created_at": r.created_at or ""}
                    for r in history],
    }
