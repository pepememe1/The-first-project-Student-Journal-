"""
overrides.py — Правки расписания администратором (overlay поверх портала), ДЕСКТОП.

Полный аналог веб-редактора: админ правит расписание группы (ячейка неделя·день·№ пары):
`set` — задать/заменить пару, `remove` — скрыть портальную. Хранится в локальной таблице
`schedule_overrides`, СИНХРОНИЗИРУЕТСЯ на сервер (SYNC_MODELS) — правки общие с вебом и
работают офлайн. id ячейки ДЕТЕРМИНИРОВАННЫЙ и одинаков с сервером (ключ синка).

Метку updated_at ставим предварительно локально (для локального LWW/сбора); при push
СЕРВЕР её пере-штампует — как для групп/занятий (инвариант §3).
"""
from datetime import datetime, timezone

from schedule.model import Lesson, WEEKDAYS


def override_id(group: str, week, day: str, pair_no) -> str:
    """Тот же формат, что на сервере (models.schedule_override_id)."""
    return f"sovr:{group}|{int(week)}|{day}|{int(pair_no)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn():
    from core import DBManager
    return DBManager.get_conn()


def _ensure(cur):
    cur.execute("CREATE TABLE IF NOT EXISTS schedule_overrides (id TEXT PRIMARY KEY, "
                "group_name TEXT, week INTEGER DEFAULT 1, day TEXT, pair_no INTEGER DEFAULT 0, "
                "action TEXT DEFAULT 'set', subject TEXT, time TEXT, room TEXT, teacher TEXT, "
                "kind TEXT, updated_at TEXT DEFAULT '', deleted INTEGER DEFAULT 0)")


def list_overrides(group: str = None) -> list:
    """Активные правки (без надгробий). group=None — все."""
    conn = _conn()
    cur = conn.cursor()
    try:
        _ensure(cur)
        if group:
            cur.execute("SELECT id,group_name,week,day,pair_no,action,subject,time,room,"
                        "teacher,kind FROM schedule_overrides WHERE group_name=? AND "
                        "COALESCE(deleted,0)=0", (group,))
        else:
            cur.execute("SELECT id,group_name,week,day,pair_no,action,subject,time,room,"
                        "teacher,kind FROM schedule_overrides WHERE COALESCE(deleted,0)=0")
        rows = cur.fetchall()
    except Exception:
        rows = []
    conn.close()
    keys = ("id", "group_name", "week", "day", "pair_no", "action", "subject", "time",
            "room", "teacher", "kind")
    return [dict(zip(keys, r)) for r in rows]


def set_override(group: str, week: int, day: str, pair_no: int, action: str = "set",
                 subject: str = "", time: str = "", room: str = "", teacher: str = "",
                 kind: str = "") -> str:
    """Задать/заменить/скрыть пару. Возвращает id ячейки. Будит синк (уедет на сервер)."""
    oid = override_id(group, week, day, pair_no)
    conn = _conn()
    cur = conn.cursor()
    _ensure(cur)
    cur.execute(
        "INSERT OR REPLACE INTO schedule_overrides "
        "(id,group_name,week,day,pair_no,action,subject,time,room,teacher,kind,updated_at,deleted) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)",
        (oid, group, int(week), day, int(pair_no), action, subject.strip(), time.strip(),
         room.strip(), teacher.strip(), kind.strip(), _now()))
    conn.commit()
    conn.close()
    _wake()
    return oid


def delete_override(oid: str) -> bool:
    """Убрать правку (надгробие) — ячейка вернётся к порталу. Будит синк."""
    conn = _conn()
    cur = conn.cursor()
    _ensure(cur)
    cur.execute("UPDATE schedule_overrides SET deleted=1, updated_at=? WHERE id=?", (_now(), oid))
    conn.commit()
    conn.close()
    _wake()
    return True


def _wake():
    try:
        from sync_runner import trigger as _t
        _t()
    except Exception:
        pass


def apply_to_group(gs, group: str):
    """Накладывает правки на GroupSchedule (мутирует gs.weeks) — для отображения/предметов.
    gs может быть None (портала нет) → строим расписание только из правок."""
    from schedule.model import GroupSchedule
    if gs is None:
        gs = GroupSchedule(name=group)
    ovs = list_overrides(group)
    if not ovs:
        return gs
    for ov in ovs:
        wk, day, pn = int(ov["week"]), ov["day"], int(ov["pair_no"])
        if day not in WEEKDAYS:
            continue
        daylist = gs.weeks.setdefault(wk, {}).setdefault(day, [])
        # убрать существующую пару с этим номером
        daylist[:] = [x for x in daylist if getattr(x, "pair_no", None) != pn]
        if ov["action"] == "set":
            daylist.append(Lesson(pair_no=pn, time=ov.get("time", ""), kind=ov.get("kind", ""),
                                  subject=ov.get("subject", ""), teacher=ov.get("teacher", ""),
                                  room=ov.get("room", ""), raw=ov.get("subject", "")))
        daylist.sort(key=lambda x: getattr(x, "pair_no", 0) or 0)
    return gs
