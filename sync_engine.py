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
