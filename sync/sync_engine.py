"""
sync_engine.py — Слой-переходник offline-first синхронизации (вариант А).

Зачем: модели данных десктопа и сервера НЕ совпадают. Десктоп хранит студентов,
преподавателей и группы как JSON-списки/словари в kv_store, а бэкенд — как
отдельные строки (users/groups/subjects/...). Этот модуль переводит одно в другое
в обе стороны, чтобы прога продолжала хранить данные как раньше, а на сервер
уходил/приходил формат API.

Устройство (честно, без прикрас):
  • «Чистые» функции перевода (subjects_to_rows, config_from_pull и т.п.) — без БД и без
    сети, легко тестируются round-trip'ом.
  • Функции _collect_* / _merge_* работают с локальной БД ПРЯМЫМ SQL — это ОСОЗНАННО, а
    не недосмотр: запись через data_store.set_* БУДИТ фоновый синк, и применение
    серверных данных зациклилось бы («синк → запись → синк»). Поэтому приём с сервера
    идёт мимо data_store, напрямую в таблицы, с меткой сервера (stamp=False по смыслу).
    Плата — слой знает схему SQLite; при смене схемы править и здесь, и в data_store.
  • Оркестрация — функции sync_once/reconcile + модульный флаг _session_full_pull_done.
    Класса SyncEngine здесь НЕТ (раньше докстринг обещал его — это было неправдой).
    Флаг безопасен: синк крутится в ОДНОМ фоновом потоке (sync_runner), параллельных
    циклов нет. Появятся — заворачивать состояние в класс.

Сетевой обмен — через sync_client. Любая сетевая ошибка не критична: синк
откладывается, прога работает офлайн.

Push тоже ДЕЛЬТА (раньше уезжал полный снимок базы каждый цикл — трафик рос вместе с
числом занятий/оценок). Граница — локальная метка `_push_watermark`; чтобы дельта не
теряла правки, действуют три страховки: нестрогое сравнение `>=`, лаг PUSH_SAFETY_LAG_S
на случай отхода часов назад и полный снимок раз в FULL_PUSH_EVERY циклов и на старте
сессии. Push идемпотентен, поэтому «отправить лишний раз» всегда дешевле, чем потерять.
"""
from datetime import datetime, timezone

import log

_log = log.get("sync")


def _now() -> str:
    #UTC + микросекунды (единый формат с сервером и data_store._now_iso) —
    #чтобы LWW-сравнение строк не зависело от часового пояса клиента.
    return datetime.now(timezone.utc).isoformat()


def _ts_key(ts: str):
    """Метка времени → сопоставимое значение. РАЗБИРАЕМ строку, а не сравниваем как текст.

    Голое строковое сравнение ISO-меток хрупко: `datetime.isoformat()` ВЫБРАСЫВАЕТ
    микросекунды, когда они нулевые («…T14:30:00+00:00» против «…T14:30:00.000001+00:00»),
    а суффикс «Z» лексикографически БОЛЬШЕ «+00:00» и «.». Стоит одной стороне сменить
    формат — и LWW начнёт молча терять более свежие правки. Разбор в datetime это
    исключает; нераспознанное — сравниваем как строку (безопасный откат)."""
    from datetime import datetime, timezone
    s = (ts or "").strip()
    if not s:
        return (0, "")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:                       #наивную метку считаем UTC
            d = d.replace(tzinfo=timezone.utc)
        return (1, d.timestamp())
    except (ValueError, TypeError):
        return (0, s)


def _should_apply(inc_ts: str, cur_ts: str, inc_deleted: bool) -> bool:
    """LWW с tie-break: применяем, если входящая метка позже; при РАВНОЙ метке —
    применяем только удаление (надгробие не должно «воскресать» из-за устаревшего
    живого пуша с той же меткой)."""
    a, b = _ts_key(inc_ts), _ts_key(cur_ts)
    if a[0] != b[0]:            #одна метка разобралась, другая нет — разобранная новее
        return a[0] > b[0]
    if a > b:
        return True
    return a == b and bool(inc_deleted)


#Пользователи (студенты/преподаватели) синхронизируются ПРЯМЫМ upsert'ом из таблицы users
#(без переводчика — план №2, Стадия 2): сбор в _collect_users(), приём в _merge_users().
#Конвертацию desktop↔server-формы делает data_store на границе UI (get/set_students и т.п.).
#Группы — так же (таблица groups): _collect_groups() / _merge_groups().


#Предметы (list имён)  <->  subjects
def subjects_to_rows(names: list) -> list:
    return [{"id": f"subj:{n}", "name": n, "updated_at": _now(), "deleted": False}
            for n in names if n]


def rows_to_subjects(rows: list) -> list:
    return sorted({r.get("name", "") for r in rows
                   if not r.get("deleted") and r.get("name")})


#Конфиг + админ
#admin_password_hash уезжает как пользователь role=admin; остальные ключи — в config.

def admin_user_from_config(cfg: dict, admin_login: str = "admin") -> dict:
    h = cfg.get("admin_password_hash")
    if not h:
        return None
    return {
        "id": f"admin:{admin_login}", "role": "admin", "login": admin_login,
        "password_hash": h, "full_name": "Администратор",
        "surname": "", "name": "", "group_name": "",
        "subjects": [], "group_assignments": {},
        "updated_at": cfg.get("admin_updated_at", "") or _now(), "deleted": False,
    }


def config_to_rows(cfg: dict) -> list:
    rows = []
    for k, v in cfg.items():
        if k == "admin_password_hash":   #уезжает как admin-пользователь
            continue
        rows.append({"key": k, "value": v, "updated_at": _now(), "deleted": False})
    return rows


def config_from_pull(config_rows: list, users: list, admin_login: str = "admin") -> dict:
    """Собирает обратно словарь config: ключи из config + хеш админа из users."""
    cfg = {}
    for r in config_rows:
        if not r.get("deleted") and r.get("key"):
            cfg[r["key"]] = r.get("value")
    for u in users:
        if u.get("role") == "admin" and not u.get("deleted") and u.get("password_hash"):
            cfg["admin_password_hash"] = u["password_hash"]
            break
    return cfg


#Сбор локальных данных в формат API (push) и применение (pull)
#Локальное хранилище — через data_store/DBManager (offline-first не ломаем).

def _collect_lessons() -> list:
    from contextlib import closing
    from core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:
            cur = conn.cursor()
            #Шлём ВСЕ занятия, включая надгробия (deleted=1) — иначе удаление не доедет
            #до других ПК и занятие воскреснет на следующем pull.
            cur.execute("SELECT id,group_name,subject,type,number,topic,date,"
                        "retake_date,hour,COALESCE(updated_at,''),COALESCE(deleted,0),"
                        "COALESCE(year,''),COALESCE(semester,0) FROM lessons")
            rows = cur.fetchall()
    except Exception as e:
        _log.error("не удалось прочитать занятия для синка: %s", e)
    out = []
    for r in rows:
        out.append({
            "id": r[0], "group_name": r[1], "subject": r[2], "type": r[3],
            "number": r[4], "topic": r[5], "date": r[6], "retake_date": r[7],
            "hour": r[8], "extra": {}, "updated_at": r[9] or _now(),
            "deleted": bool(r[10]),
            "year": r[11], "semester": r[12],   #учебный период — общий с сервером/вебом
        })
    return out


def _collect_grades() -> list:
    from contextlib import closing
    from core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:
            cur = conn.cursor()
            #Шлём ВСЕ оценки, включая надгробия (deleted=1) — чтобы удаление оценки
            #распространилось, а не «воскресло» при следующем pull.
            cur.execute("SELECT student_f,student_n,lesson_id,grade,"
                        "COALESCE(updated_at,''),COALESCE(device,''),"
                        "COALESCE(deleted,0),COALESCE(student_id,'') FROM grades")
            rows = cur.fetchall()
    except Exception as e:
        _log.error("не удалось прочитать оценки для синка: %s", e)
    out = []
    for f, n, lid, grade, uat, dev, deleted, sid in rows:
        out.append({
            "id": f"{f}|{n}|{lid}", "student_f": f, "student_n": n, "lesson_id": lid,
            "grade": grade, "device": dev, "updated_at": uat or _now(),
            "deleted": bool(deleted),
            #Этап 1 миграции: ключ пока ФИО, но неизменяемый id везём рядом. Сервер его
            #сохранит, и после бэкофилла привязку можно будет переключить, не потеряв
            #историю переименованных студентов.
            "student_id": sid,
        })
    return out


def _collect_users() -> list:
    """Пользователи (студенты/преподаватели) из таблицы users в СЕРВЕРНОЙ форме (со
    надгробиями) — прямой push, без переводчика. Расшифровку blob'а делает data_store.
    Админ добавляется отдельно (его хеш — в config)."""
    from data_store import users_for_sync
    return users_for_sync()


def _collect_groups() -> list:
    """Группы из таблицы в формате API (со надгробиями) — прямой upsert, без переводчика."""
    import json as _json
    from contextlib import closing
    from core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:   #закроется и при исключении
            cur = conn.cursor()
            cur.execute("SELECT id,name,COALESCE(subjects,'[]'),COALESCE(updated_at,''),"
                        "COALESCE(deleted,0) FROM groups")
            rows = cur.fetchall()
    except Exception as e:
        #НЕ глушим молча: при залоченной/битой БД пустой список уехал бы как «нет групп»,
        #и локальные группы просто перестали бы синхронизироваться — без следа в логах.
        _log.error("не удалось прочитать группы для синка: %s", e)
    out = []
    for gid, name, subj, uat, deleted in rows:
        try:
            subjects = _json.loads(subj) if subj else []
        except Exception:
            subjects = []
        out.append({"id": gid or f"grp:{name}", "name": name, "subjects": subjects,
                    "updated_at": uat or _now(), "deleted": bool(deleted)})
    return out


def _collect_term_grades() -> list:
    from contextlib import closing
    from core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:
            cur = conn.cursor()
            #Шлём ВСЕ итоговые, включая надгробия (deleted=1) — иначе снятие оценки не
            #доедет до других ПК/сайта и она «воскреснет» на следующем pull.
            cur.execute("SELECT id,student_f,student_n,subject,COALESCE(year,''),"
                        "COALESCE(semester,0),COALESCE(grade,''),COALESCE(form,''),"
                        "COALESCE(updated_at,''),COALESCE(deleted,0),"
                        "COALESCE(student_id,'') FROM term_grades")
            rows = cur.fetchall()
    except Exception as e:
        _log.error("не удалось прочитать итоговые оценки для синка: %s", e)
    out = []
    for r in rows:
        out.append({
            "id": r[0], "student_f": r[1], "student_n": r[2], "subject": r[3],
            "year": r[4], "semester": r[5], "grade": r[6], "form": r[7],
            "updated_at": r[8] or _now(), "deleted": bool(r[9]),
            "student_id": r[10],            #этап 1 миграции — см. _collect_grades
        })
    return out


def _filter_since(rows: list, since: str) -> list:
    """Оставляет строки, изменённые не раньше метки. Граница НЕ строгая (`>=`) — по той же
    причине, что и в дельта-pull (§3 CLAUDE.md): push и запись могут попасть в один тик
    часов, и при строгом «>» такая правка выпала бы из дельты навсегда. Push идемпотентен,
    поэтому лишний повтор безвреден, а потеря — нет."""
    if not since:
        return rows
    key = _ts_key(since)
    return [r for r in rows if _ts_key(r.get("updated_at", "")) >= key]


def collect_local(since: str = "") -> dict:
    """Читает локальное состояние и переводит в формат API (для push).

    since != "" — собираем ДЕЛЬТУ: только строки с updated_at >= since. Предметы и конфиг
    отдаём всегда: их локальные «метки» синтезируются на лету (`_now()`), реальной истории
    изменений у них нет, а объём — десятки строк, фильтровать нечего."""
    from data_store import get_store
    from subjects import load_subjects
    st = get_store()
    cfg = st._config()
    #Пользователи — прямо из таблицы users (серверная форма, со надгробиями). Админ —
    #синтетически из config (его хеш там и живёт).
    users = _collect_users()
    admin = admin_user_from_config(cfg, st.get_admin_login())
    if admin:
        users.append(admin)
    return {
        "users": _filter_since(users, since),
        "subjects": subjects_to_rows(load_subjects()),
        "config": config_to_rows(cfg),
        "groups": _filter_since(_collect_groups(), since),
        "lessons": _filter_since(_collect_lessons(), since),
        "grades": _filter_since(_collect_grades(), since),
        "term_grades": _filter_since(_collect_term_grades(), since),
        "schedule_overrides": _filter_since(_collect_schedule_overrides(), since),
    }


def apply_remote(changes: dict):
    """Применяет пришедшие с сервера изменения в локальное хранилище (LWW-слияние).
    Пишем с stamp=False — сохраняем серверные метки, чтобы синк не зациклился."""
    from data_store import get_store, _kv_set
    from subjects import load_subjects, save_subjects
    st = get_store()
    users = changes.get("users", []) or []

    #Пользователи — прямой LWW-upsert в таблицу users (студенты/преподаватели). Админ
    #(role=admin) в таблицу НЕ пишем — его хеш применяется в config ниже (config_from_pull).
    if users:
        _merge_users(users)

    #Группы — прямой LWW-upsert в таблицу groups (как lessons/term_grades), без переводчика.
    if changes.get("groups"):
        _merge_groups(changes["groups"])

    #Предметы (объединение множеств)
    if "subjects" in changes:
        cur = set(load_subjects())
        save_subjects(sorted(cur | set(rows_to_subjects(changes["subjects"]))))

    #Конфиг (ключи) + хеш админа
    if "config" in changes or users:
        new_cfg = config_from_pull(changes.get("config", []), users, st.get_admin_login())
        cfg = st._config()
        cfg.update(new_cfg)
        _kv_set("config", cfg, wake=False)   #серверные данные — синк не будим

    #Занятия и оценки
    if changes.get("lessons"):
        _merge_lessons(changes["lessons"])
    if changes.get("grades"):
        _merge_grades(changes["grades"])
    if changes.get("term_grades"):
        _merge_term_grades(changes["term_grades"])
    #Правки расписания (overlay) — общие веб↔десктоп, прямой LWW-upsert (как группы).
    if changes.get("schedule_overrides"):
        _merge_schedule_overrides(changes["schedule_overrides"])


def _merge_lessons(remote: list):
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    for l in remote:
        lid = l.get("id")
        if not lid:
            continue
        rdel = bool(l.get("deleted"))
        cur.execute("SELECT COALESCE(updated_at,'') FROM lessons WHERE id=?", (lid,))
        row = cur.fetchone()
        #LWW с tie-break: применяем, если входящая метка позже (или при равной —
        #если это удаление). Так удаление с сервера тоже применяется к локали.
        if not (row is None or _should_apply(l.get("updated_at", ""), row[0] or "", rdel)):
            continue
        #deleted переносим как есть: 1 — занятие становится надгробием (исчезнет из
        #журнала, фильтр deleted=0 в load_from_db), 0 — обычное активное занятие.
        cur.execute(
            "INSERT OR REPLACE INTO lessons "
            "(id,group_name,subject,type,number,topic,date,retake_date,hour,"
            "year,semester,updated_at,deleted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lid, l.get("group_name", ""), l.get("subject", ""), l.get("type", ""),
             l.get("number", 0), l.get("topic", ""), l.get("date", ""),
             l.get("retake_date", ""), l.get("hour", 0),
             l.get("year", "") or "", int(l.get("semester", 0) or 0),
             l.get("updated_at", ""), 1 if rdel else 0))
    conn.commit()
    conn.close()


def _merge_users(remote: list):
    """Слияние пользователей (студенты/преподаватели) с сервера — прямой LWW с tie-break
    в таблицу users. payload шифруем в blob (Fernet+DPAPI) — хеши паролей и ПДн на диске
    защищены (152-ФЗ). role=admin пропускаем: его хеш применяется в config (не тут)."""
    import json as _json
    from core import DBManager
    from security import encrypt_value
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, role TEXT, "
                "updated_at TEXT DEFAULT '', deleted INTEGER DEFAULT 0, blob TEXT DEFAULT '')")
    for u in remote:
        role = u.get("role")
        if role not in ("student", "teacher"):
            continue
        uid = u.get("id")
        if not uid:
            continue
        rdel = bool(u.get("deleted"))
        cur.execute("SELECT COALESCE(updated_at,'') FROM users WHERE id=?", (uid,))
        row = cur.fetchone()
        if not (row is None or _should_apply(u.get("updated_at", ""), row[0] or "", rdel)):
            continue
        cur.execute("INSERT OR REPLACE INTO users (id,role,updated_at,deleted,blob) "
                    "VALUES (?,?,?,?,?)",
                    (uid, role, u.get("updated_at", ""), 1 if rdel else 0,
                     encrypt_value(_json.dumps(u, ensure_ascii=False))))
    conn.commit()
    conn.close()


_SOVR_COLS = ("id", "group_name", "week", "day", "pair_no", "action", "subject",
              "time", "room", "teacher", "kind")


def _ensure_sovr_table(cur):
    cur.execute("CREATE TABLE IF NOT EXISTS schedule_overrides (id TEXT PRIMARY KEY, "
                "group_name TEXT, week INTEGER DEFAULT 1, day TEXT, pair_no INTEGER DEFAULT 0, "
                "action TEXT DEFAULT 'set', subject TEXT, time TEXT, room TEXT, teacher TEXT, "
                "kind TEXT, updated_at TEXT DEFAULT '', deleted INTEGER DEFAULT 0)")


def _collect_schedule_overrides() -> list:
    """Правки расписания из локальной таблицы (со надгробиями) — прямой upsert в синк."""
    from contextlib import closing
    from core import DBManager
    rows = []
    try:
        with closing(DBManager.get_conn()) as conn:
            cur = conn.cursor()
            _ensure_sovr_table(cur)
            cur.execute("SELECT id,group_name,week,day,pair_no,action,subject,time,room,"
                        "teacher,kind,COALESCE(updated_at,''),COALESCE(deleted,0) "
                        "FROM schedule_overrides")
            rows = cur.fetchall()
    except Exception as e:
        _log.error("не удалось прочитать правки расписания для синка: %s", e)
    out = []
    for r in rows:
        out.append({"id": r[0], "group_name": r[1], "week": r[2], "day": r[3], "pair_no": r[4],
                    "action": r[5], "subject": r[6], "time": r[7], "room": r[8], "teacher": r[9],
                    "kind": r[10], "updated_at": r[11], "deleted": bool(r[12])})
    return out


def _merge_schedule_overrides(remote: list):
    """Слияние правок расписания с сервера — прямой LWW-upsert (как группы). Пишем прямо
    в таблицу, синк не будим (серверные данные, а не UI-правка)."""
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    _ensure_sovr_table(cur)
    for o in remote:
        oid = o.get("id")
        if not oid:
            continue
        rdel = bool(o.get("deleted"))
        cur.execute("SELECT COALESCE(updated_at,'') FROM schedule_overrides WHERE id=?", (oid,))
        row = cur.fetchone()
        if not (row is None or _should_apply(o.get("updated_at", ""), row[0] or "", rdel)):
            continue
        cur.execute(
            "INSERT OR REPLACE INTO schedule_overrides "
            "(id,group_name,week,day,pair_no,action,subject,time,room,teacher,kind,updated_at,deleted) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (oid, o.get("group_name", ""), int(o.get("week") or 1), o.get("day", ""),
             int(o.get("pair_no") or 0), o.get("action", "set"), o.get("subject", ""),
             o.get("time", ""), o.get("room", ""), o.get("teacher", ""), o.get("kind", ""),
             o.get("updated_at", ""), 1 if rdel else 0))
    conn.commit()
    conn.close()


def _merge_groups(remote: list):
    """Слияние групп с сервера — прямой LWW с tie-break в таблицу groups (как занятия).
    Пишем напрямую в таблицу (не через data_store.set_groups) — так синк НЕ будит сам
    себя (это применение серверных данных, а не UI-правка)."""
    import json as _json
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS groups (id TEXT PRIMARY KEY, name TEXT, "
                "subjects TEXT DEFAULT '[]', updated_at TEXT DEFAULT '', deleted INTEGER DEFAULT 0)")
    for g in remote:
        name = g.get("name", "")
        gid = g.get("id") or (f"grp:{name}" if name else "")
        if not gid:
            continue
        rdel = bool(g.get("deleted"))
        cur.execute("SELECT COALESCE(updated_at,'') FROM groups WHERE id=?", (gid,))
        row = cur.fetchone()
        if not (row is None or _should_apply(g.get("updated_at", ""), row[0] or "", rdel)):
            continue
        cur.execute("INSERT OR REPLACE INTO groups (id,name,subjects,updated_at,deleted) "
                    "VALUES (?,?,?,?,?)",
                    (gid, name, _json.dumps(g.get("subjects") or [], ensure_ascii=False),
                     g.get("updated_at", ""), 1 if rdel else 0))
    conn.commit()
    conn.close()


def _merge_grades(remote: list):
    """Слияние оценок с сервера. Оценки — чувствительные данные, поэтому здесь НЕ
    слепой LWW, а детектор конфликтов: если серверное значение оценки расходится
    с локальным и локальное не новее — расхождение пишем в sync_conflicts и НЕ
    затираем работу преподавателя (он решит вручную через conflict_dialog).
    Если значения совпали или локальное новее — конфликта нет."""
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    #Таблица конфликтов нужна гарантированно (на случай, если init не отработал).
    cur.execute("CREATE TABLE IF NOT EXISTS sync_conflicts ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "student_f TEXT, student_n TEXT, lesson_id TEXT,"
                "local_grade TEXT, remote_grade TEXT, remote_device TEXT,"
                "remote_at TEXT, detected_at TEXT, resolved INTEGER DEFAULT 0)")
    now_iso = _now()
    for g in remote:
        f, n, lid = g.get("student_f"), g.get("student_n"), g.get("lesson_id")
        rgrade = g.get("grade", "")
        rat = g.get("updated_at", "")
        rdev = g.get("device", "")
        rdel = bool(g.get("deleted"))
        cur.execute("SELECT grade, COALESCE(updated_at,''), COALESCE(deleted,0) FROM grades "
                    "WHERE student_f=? AND student_n=? AND lesson_id=?", (f, n, lid))
        local = cur.fetchone()

        #Удаление с сервера (надгробие). Применяем по LWW (новее побеждает); диалог
        #конфликтов для удалений не заводим — это не «два разных балла», а явное
        #удаление. Если локальная правка новее — оставляем её (уедет на сервер).
        if rdel:
            if local is None:
                continue                       #нечего удалять
            lgrade, lat, ldel = local
            if ldel:
                continue                       #уже удалено
            if lat and rat and lat > rat:
                continue                       #локальная правка новее — оставляем
            cur.execute("UPDATE grades SET deleted=1, updated_at=?, device=?, "
                        "student_id=COALESCE(NULLIF(?,''),student_id) "
                        "WHERE student_f=? AND student_n=? AND lesson_id=?",
                        (rat, rdev, g.get("student_id", "") or "", f, n, lid))
            continue

        #Активная оценка с сервера.
        if local is None:
            #Локально такой оценки нет — просто принимаем серверную.
            cur.execute(
                "INSERT OR REPLACE INTO grades "
                "(student_f,student_n,lesson_id,grade,updated_at,device,deleted,"
                "student_id) VALUES (?,?,?,?,?,?,0,?)",
                (f, n, lid, rgrade, rat, rdev, g.get("student_id", "") or ""))
            continue
        lgrade, lat, ldel = local
        if ldel:
            #Локально оценка была удалена, а с сервера пришла активная (её
            #восстановили на другом ПК). Применяем, если серверная не старше нашего
            #надгробия — иначе наше удаление новее и уедет на сервер.
            if not (lat and rat and lat > rat):
                cur.execute(
                    "INSERT OR REPLACE INTO grades "
                    "(student_f,student_n,lesson_id,grade,updated_at,device,deleted,"
                    "student_id) VALUES (?,?,?,?,?,?,0,?)",
                    (f, n, lid, rgrade, rat, rdev, g.get("student_id", "") or ""))
            continue
        if (lgrade or "") == (rgrade or ""):
            continue   #значения совпали — менять нечего
        if lat and rat and lat > rat:
            continue   #локальная правка новее — оставляем, она уедет на сервер
        #Значения разошлись, и серверное не старше локального → НАСТОЯЩИЙ конфликт.
        #Локальное значение НЕ трогаем; фиксируем расхождение для ручного решения.
        cur.execute("SELECT 1 FROM sync_conflicts WHERE student_f=? AND student_n=? "
                    "AND lesson_id=? AND resolved=0", (f, n, lid))
        if cur.fetchone() is None:   #не плодим дубли по одной и той же оценке
            cur.execute(
                "INSERT INTO sync_conflicts "
                "(student_f,student_n,lesson_id,local_grade,remote_grade,"
                "remote_device,remote_at,detected_at,resolved) "
                "VALUES (?,?,?,?,?,?,?,?,0)",
                (f, n, lid, lgrade, rgrade, rdev, rat, now_iso))
    conn.commit()
    conn.close()


def _merge_term_grades(remote: list):
    """Слияние итоговых оценок (аттестации) с сервера — простой LWW с tie-break
    (как занятия). Диалог конфликтов тут не нужен: это одна итоговая оценка за
    семестр, а не «два разных балла за занятие» — побеждает более поздняя правка."""
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    for g in remote:
        gid = g.get("id")
        if not gid:
            continue
        rdel = bool(g.get("deleted"))
        cur.execute("SELECT COALESCE(updated_at,'') FROM term_grades WHERE id=?", (gid,))
        row = cur.fetchone()
        if not (row is None or _should_apply(g.get("updated_at", ""), row[0] or "", rdel)):
            continue
        cur.execute(
            "INSERT OR REPLACE INTO term_grades "
            "(id,student_f,student_n,subject,year,semester,grade,form,updated_at,deleted,"
            "student_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (gid, g.get("student_f", ""), g.get("student_n", ""), g.get("subject", ""),
             g.get("year", ""), int(g.get("semester", 0) or 0), g.get("grade", ""),
             g.get("form", ""), g.get("updated_at", ""), 1 if rdel else 0,
             g.get("student_id", "") or ""))
    conn.commit()
    conn.close()


#Флаг «первый синк этой сессии». На старте процесса делаем ОДИН полный pull
#(since=""), даже если метка уже есть: так лечится возможный дрейф — редкая потеря
#пограничной записи из-за гонки «коммит против взятия метки». Дальше в течение
#сессии тянем только дельту. Поток синка один, поэтому простого флага достаточно.
_session_full_pull_done = False

#То же для PUSH: первый push сессии — полный. За время, пока прога была закрыта, часы
#могли сдвинуться, а правки — прийти мимо синка (восстановление из бэкапа, ручной импорт).
#Полный снимок на старте это лечит.
_session_full_push_done = False

#Страховка от «дырки» в дельта-push: локальные часы могут отойти назад (синхронизация
#времени, переезд через часовой пояс, виртуалка после сна). Тогда правка получила бы
#метку РАНЬШЕ watermark и не попала бы в дельту. Поэтому метку сдвигаем назад на лаг —
#последние две минуты правок уезжают повторно (push идемпотентен, это дёшево).
PUSH_SAFETY_LAG_S = 120

#И грубый предохранитель на всё остальное: раз в N циклов шлём полный снимок. Даже если
#какая-то правка мимо всех расчётов выпала из дельты, она уедет максимум через N циклов,
#а не потеряется навсегда. Дешевле, чем гарантировать безошибочность меток.
FULL_PUSH_EVERY = 20
_push_cycles = 0


def force_full_push():
    """Следующий push будет ПОЛНЫМ снимком (не дельтой)."""
    global _session_full_push_done
    _session_full_push_done = False


def force_full_pull():
    """Сбрасывает флаг «полный pull сессии уже сделан», чтобы СЛЕДУЮЩИЙ sync_once
    тянул всё с сервера (since=""), а не дельту. Нужно после reset_synced_local_data:
    кэш стёрт, и его надо наполнить заново полным снимком сервера."""
    global _session_full_pull_done
    _session_full_pull_done = False


def reconcile(client) -> bool:
    """Реконсиляция «сервер = истина»: стереть локальный кэш данных и наполнить его
    заново ПОЛНЫМ снимком сервера. После этого локальные данные точно соответствуют
    серверу — «осиротевшие» локальные записи (которых на сервере нет) исчезают.

    ВАЖНО: вызывать только когда сервер ДОСТУПЕН и токен валиден (проверять заранее),
    иначе после очистки кэша полный pull не пройдёт и останется пустая база.

    СНАЧАЛА отправляем локальные изменения, и лишь потом стираем кэш. Иначе офлайн-
    правки, накопленные на клиентском ПК (например, оценки преподавателя, выставленные
    без сети и ещё не ушедшие на сервер), были бы уничтожены reset_synced_local_data()
    ДО отправки — безвозвратная потеря. Push идемпотентен: сервер применит только реально
    изменённое, а после полного pull эти же правки вернутся в кэш уже с серверной меткой.
    """
    from data_store import reset_synced_local_data
    #Спасаем офлайн-правки: пуш перед очисткой. Ошибку глушим — если сервер вдруг отпал
    #между проверкой доступности и этим вызовом, дальше упадёт pull и вызывающий уйдёт в
    #офлайн-ветку, а несохранённый кэш останется на месте (reset ещё не выполнен).
    try:
        client.push(collect_local())
    except Exception as e:
        _log.warning("пуш офлайн-правок перед сбросом кэша не удался: %s", e)
        raise   #не стираем кэш, если правки не удалось отправить — данные важнее «чистоты»
    reset_synced_local_data()
    force_full_pull()
    force_full_push()   #кэш стёрт — «уже отправленному» верить нельзя, шлём полный снимок
    return sync_once(client)


def sync_once(client) -> bool:
    """Один цикл синхронизации: отправить локальные изменения, забрать серверные.
    Возвращает True при успехе. Бросаемые сетевые ошибки ловит вызывающий код."""
    global _session_full_pull_done, _session_full_push_done, _push_cycles
    from datetime import timedelta

    from data_store import (get_push_watermark, get_sync_watermark,
                            set_push_watermark, set_sync_watermark)

    #1. Отправляем ДЕЛЬТУ локальных правок (роль ограничивает на сервере). Раньше уезжал
    #полный снимок базы каждый цикл: сервер применял только изменившееся, но трафик рос
    #вместе с базой. Полный снимок оставляем для первого цикла сессии и раз в
    #FULL_PUSH_EVERY циклов — как самоизлечение.
    full_push = (not _session_full_push_done) or (_push_cycles % FULL_PUSH_EVERY == 0)
    #Метку берём ДО сбора: правка, сделанная во время push, попадёт в СЛЕДУЮЩУЮ дельту,
    #а не провалится между сбором и сохранением метки.
    mark = (datetime.now(timezone.utc) - timedelta(seconds=PUSH_SAFETY_LAG_S)).isoformat()
    client.push(collect_local("" if full_push else get_push_watermark()))
    #Метку двигаем только после УСПЕШНОГО push: упало — правки останутся в дельте.
    set_push_watermark(mark)
    _session_full_push_done = True
    _push_cycles += 1

    #2. Тянем ДЕЛЬТУ: только изменения позже метки last_sync — это снимает главный
    #тормоз (раньше каждый цикл качал всю базу). Первый pull сессии — полный
    #(since=""), для самоизлечения; последующие — по сохранённой метке.
    since = "" if not _session_full_pull_done else get_sync_watermark()
    data = client.pull(since=since)
    apply_remote(data.get("changes", {}))

    #3. Сдвигаем метку на server_time этого pull. Сервер берёт её ДО выборки, поэтому
    #следующая дельта не пропустит записи, появившиеся во время текущего запроса.
    server_time = data.get("server_time", "")
    if server_time:
        set_sync_watermark(server_time)
    _session_full_pull_done = True
    return True
