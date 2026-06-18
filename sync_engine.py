"""
sync_engine.py — Слой-переходник offline-first синхронизации (вариант А).

Зачем: модели данных десктопа и сервера НЕ совпадают. Десктоп хранит студентов,
преподавателей и группы как JSON-списки/словари в kv_store, а бэкенд — как
отдельные строки (users/groups/subjects/...). Этот модуль переводит одно в другое
в обе стороны, чтобы прога продолжала хранить данные как раньше, а на сервер
уходил/приходил формат API.

Принцип: здесь ТОЛЬКО перевод и оркестрация. Локальное хранилище — по-прежнему
через data_store/DBManager (offline-first не ломаем). Сетевой обмен — через
sync_client. Любая сетевая ошибка не критична: синк откладывается, прога работает.

Ниже «чистые» функции перевода (без БД и без сети) — их легко тестировать
прогонкой round-trip через сервер. Класс SyncEngine связывает их с локальным
хранилищем и клиентом (его проводка в жизненный цикл приложения — отдельный шаг).
"""
from datetime import datetime


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─────────────────────────────────────────────────────────────
#  Стабильные идентификаторы сущностей (нужны для upsert на сервере)
# ─────────────────────────────────────────────────────────────
def _student_id(s: dict) -> str:
    login = (s.get("login") or "").strip()
    if login:
        return f"stud:{login}"
    return f"stud:{s.get('surname','')}|{s.get('name','')}|{s.get('group','')}"


def _teacher_id(fullname: str, data: dict) -> str:
    login = (data.get("login") or "").strip()
    return f"teach:{login}" if login else f"teach:{fullname}"


# ─────────────────────────────────────────────────────────────
#  Студенты  ↔  users(role=student)
# ─────────────────────────────────────────────────────────────
def students_to_users(students: list) -> list:
    out = []
    for s in students:
        out.append({
            "id": _student_id(s), "role": "student",
            "login": s.get("login", ""), "password_hash": s.get("password_hash", ""),
            "surname": s.get("surname", ""), "name": s.get("name", ""),
            "group_name": s.get("group", ""), "full_name": "",
            "subjects": [], "group_assignments": {},
            "updated_at": s.get("updated_at", "") or _now(),
            "deleted": bool(s.get("deleted", False)),
        })
    return out


def users_to_students(users: list) -> list:
    out = []
    for u in users:
        if u.get("role") != "student" or u.get("deleted"):
            continue
        out.append({
            "surname": u.get("surname", ""), "name": u.get("name", ""),
            "group": u.get("group_name", ""), "login": u.get("login", ""),
            "password_hash": u.get("password_hash", ""),
            "updated_at": u.get("updated_at", ""),
        })
    return out


# ─────────────────────────────────────────────────────────────
#  Преподаватели (dict {ФИО: data})  ↔  users(role=teacher)
# ─────────────────────────────────────────────────────────────
def teachers_to_users(teachers: dict) -> list:
    out = []
    for fullname, d in teachers.items():
        out.append({
            "id": _teacher_id(fullname, d), "role": "teacher",
            "login": (d.get("login") or ""), "password_hash": d.get("password_hash", ""),
            "full_name": fullname, "surname": "", "name": "", "group_name": "",
            "subjects": d.get("subjects", []) or [],
            "group_assignments": d.get("group_assignments", {}) or {},
            "updated_at": d.get("updated_at", "") or _now(),
            "deleted": bool(d.get("deleted", False)),
        })
    return out


def users_to_teachers(users: list) -> dict:
    out = {}
    for u in users:
        if u.get("role") != "teacher" or u.get("deleted"):
            continue
        out[u.get("full_name", "")] = {
            "login": u.get("login", ""), "password_hash": u.get("password_hash", ""),
            "subjects": u.get("subjects") or [],
            "group_assignments": u.get("group_assignments") or {},
            "updated_at": u.get("updated_at", ""),
        }
    return out


# ─────────────────────────────────────────────────────────────
#  Группы (list)  ↔  groups
# ─────────────────────────────────────────────────────────────
def groups_to_rows(groups: list) -> list:
    return [{
        "id": f"grp:{g.get('name','')}", "name": g.get("name", ""),
        "subjects": g.get("subjects", []) or [],
        "updated_at": g.get("updated_at", "") or _now(),
        "deleted": bool(g.get("deleted", False)),
    } for g in groups]


def rows_to_groups(rows: list) -> list:
    return [{
        "name": r.get("name", ""), "subjects": r.get("subjects") or [],
        "updated_at": r.get("updated_at", ""),
    } for r in rows if not r.get("deleted") and r.get("name")]


# ─────────────────────────────────────────────────────────────
#  Предметы (list имён)  ↔  subjects
# ─────────────────────────────────────────────────────────────
def subjects_to_rows(names: list) -> list:
    return [{"id": f"subj:{n}", "name": n, "updated_at": _now(), "deleted": False}
            for n in names if n]


def rows_to_subjects(rows: list) -> list:
    return sorted({r.get("name", "") for r in rows
                   if not r.get("deleted") and r.get("name")})


# ─────────────────────────────────────────────────────────────
#  Конфиг + админ
#  admin_password_hash уезжает как пользователь role=admin; остальные ключи — в config.
# ─────────────────────────────────────────────────────────────
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
        if k == "admin_password_hash":   # уезжает как admin-пользователь
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


# ─────────────────────────────────────────────────────────────
#  Сбор локальных данных в формат API (push) и применение (pull)
#  Локальное хранилище — через data_store/DBManager (offline-first не ломаем).
# ─────────────────────────────────────────────────────────────
def _collect_lessons() -> list:
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id,group_name,subject,type,number,topic,date,"
                "retake_date,hour,COALESCE(updated_at,'') FROM lessons")
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "group_name": r[1], "subject": r[2], "type": r[3],
            "number": r[4], "topic": r[5], "date": r[6], "retake_date": r[7],
            "hour": r[8], "extra": {}, "updated_at": r[9] or _now(), "deleted": False,
        })
    return out


def _collect_grades() -> list:
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT student_f,student_n,lesson_id,grade,"
                "COALESCE(updated_at,''),COALESCE(device,'') FROM grades")
    rows = cur.fetchall()
    conn.close()
    out = []
    for f, n, lid, grade, uat, dev in rows:
        out.append({
            "id": f"{f}|{n}|{lid}", "student_f": f, "student_n": n, "lesson_id": lid,
            "grade": grade, "device": dev, "updated_at": uat or _now(), "deleted": False,
        })
    return out


def collect_local() -> dict:
    """Читает всё локальное состояние и переводит в формат API (для push)."""
    from data_store import get_store
    from subjects import load_subjects
    st = get_store()
    cfg = st._config()
    users = students_to_users(st.get_students()) + teachers_to_users(st.get_teachers())
    admin = admin_user_from_config(cfg, st.get_admin_login())
    if admin:
        users.append(admin)
    return {
        "users": users,
        "groups": groups_to_rows(st.get_groups()),
        "subjects": subjects_to_rows(load_subjects()),
        "config": config_to_rows(cfg),
        "lessons": _collect_lessons(),
        "grades": _collect_grades(),
    }


def _merge_by_key(local_list: list, remote_list: list, key_fn) -> list:
    """Слияние двух списков по ключу: побеждает запись с более поздним updated_at.
    Удалённые (deleted) — выкидываем. Возвращает объединённый список без надгробий."""
    m = {key_fn(r): r for r in local_list}
    for r in remote_list:
        k = key_fn(r)
        loc = m.get(k)
        if loc is None or (r.get("updated_at", "") >= loc.get("updated_at", "")):
            m[k] = r
    return [r for r in m.values() if not r.get("deleted")]


def apply_remote(changes: dict):
    """Применяет пришедшие с сервера изменения в локальное хранилище (LWW-слияние).
    Пишем с stamp=False — сохраняем серверные метки, чтобы синк не зациклился."""
    from data_store import get_store, _kv_set
    from subjects import load_subjects, save_subjects
    st = get_store()
    users = changes.get("users", []) or []

    # Студенты
    if users:
        loc = st.get_students()
        rem = users_to_students([u for u in users if u.get("role") == "student"])
        # переносим updated_at в студент-словарь для корректного LWW
        for s, u in zip(rem, [u for u in users if u.get("role") == "student"]):
            s["updated_at"] = u.get("updated_at", "")
        key = lambda r: (r.get("login") or
                         f"{r.get('surname','')}|{r.get('name','')}|{r.get('group','')}")
        st.set_students(_merge_by_key(loc, rem, key), stamp=False)

        # Преподаватели (dict → список для слияния → обратно в dict)
        loc_t = [dict(v, full_name=k) for k, v in st.get_teachers().items()]
        rem_t = []
        for u in users:
            if u.get("role") != "teacher":
                continue
            rem_t.append({
                "full_name": u.get("full_name", ""), "login": u.get("login", ""),
                "password_hash": u.get("password_hash", ""),
                "subjects": u.get("subjects") or [],
                "group_assignments": u.get("group_assignments") or {},
                "updated_at": u.get("updated_at", ""), "deleted": u.get("deleted", False),
            })
        merged_t = _merge_by_key(loc_t, rem_t, lambda r: r.get("full_name", ""))
        teachers = {r.pop("full_name"): r for r in merged_t}
        st.set_teachers(teachers, stamp=False)

    # Группы
    if "groups" in changes:
        merged_g = _merge_by_key(st.get_groups(), rows_to_groups(changes["groups"]),
                                 lambda r: r.get("name", ""))
        st.set_groups(merged_g, stamp=False)

    # Предметы (объединение множеств)
    if "subjects" in changes:
        cur = set(load_subjects())
        save_subjects(sorted(cur | set(rows_to_subjects(changes["subjects"]))))

    # Конфиг (ключи) + хеш админа
    if "config" in changes or users:
        new_cfg = config_from_pull(changes.get("config", []), users, st.get_admin_login())
        cfg = st._config()
        cfg.update(new_cfg)
        _kv_set("config", cfg)

    # Занятия и оценки
    if changes.get("lessons"):
        _merge_lessons(changes["lessons"])
    if changes.get("grades"):
        _merge_grades(changes["grades"])


def _merge_lessons(remote: list):
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    for l in remote:
        if l.get("deleted"):
            continue
        cur.execute("SELECT COALESCE(updated_at,'') FROM lessons WHERE id=?", (l["id"],))
        row = cur.fetchone()
        if row is None or l.get("updated_at", "") >= (row[0] or ""):
            cur.execute(
                "INSERT OR REPLACE INTO lessons "
                "(id,group_name,subject,type,number,topic,date,retake_date,hour,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (l["id"], l.get("group_name", ""), l.get("subject", ""), l.get("type", ""),
                 l.get("number", 0), l.get("topic", ""), l.get("date", ""),
                 l.get("retake_date", ""), l.get("hour", 0), l.get("updated_at", "")))
    conn.commit()
    conn.close()


def _merge_grades(remote: list):
    from core import DBManager
    conn = DBManager.get_conn()
    cur = conn.cursor()
    for g in remote:
        if g.get("deleted"):
            continue
        f, n, lid = g.get("student_f"), g.get("student_n"), g.get("lesson_id")
        cur.execute("SELECT COALESCE(updated_at,'') FROM grades "
                    "WHERE student_f=? AND student_n=? AND lesson_id=?", (f, n, lid))
        row = cur.fetchone()
        if row is None or g.get("updated_at", "") >= (row[0] or ""):
            cur.execute(
                "INSERT OR REPLACE INTO grades "
                "(student_f,student_n,lesson_id,grade,updated_at,device) "
                "VALUES (?,?,?,?,?,?)",
                (f, n, lid, g.get("grade", ""), g.get("updated_at", ""), g.get("device", "")))
    conn.commit()
    conn.close()


def sync_once(client) -> bool:
    """Один цикл синхронизации: отправить локальные изменения, забрать серверные.
    Возвращает True при успехе. Бросаемые сетевые ошибки ловит вызывающий код."""
    # 1. Отправляем то, что вправе отправлять (роль ограничивает на сервере).
    client.push(collect_local())
    # 2. Тянем всё (для простоты v1 — полный pull; дельту по last_sync добавим позже).
    data = client.pull(since="")
    apply_remote(data.get("changes", {}))
    return True
