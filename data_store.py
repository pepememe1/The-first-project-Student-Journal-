"""
data_store.py — Хранилище данных GradeBookAI на PostgreSQL + SQLite.

Заменяет github_storage.py. Никаких обращений в интернет.

Архитектура (как и просили — PostgreSQL на сервере колледжа в локальной сети):
  - Рабочее чтение/запись идёт в локальный SQLite (мгновенно, без блокировки UI).
  - Если PostgreSQL настроен, запись дублируется в PG асинхронно (через PGSyncer).
  - При старте данные подтягиваются из PG в SQLite (DBManager._pull_from_pg).
  - Все ПК колледжа работают с одной общей базой PostgreSQL.

Данные хранятся в таблице kv_store (ключ → JSON):
  students, teachers, groups, config, journal:<группа>__<предмет>

Пароли НЕ хранятся в открытом виде: при записи поле "password" автоматически
превращается в "password_hash" (PBKDF2-HMAC-SHA256, см. security.py).
"""
import json
from typing import Optional

from core import DBManager, _syncer
from security import hash_password, verify_password, encrypt_value, decrypt_value
from styles import DEFAULT_GROUPS

# Логин администратора не секрет (секрет — пароль). Дефолтного ПАРОЛЯ больше нет:
# раньше тут лежал захардкоженный "vsgutu_admin_online", который принимался при
# первом входе — это был бэкдор. Теперь пароль администратора задаётся вручную
# при первом запуске на хост-ПК (см. setup_admin_password / auth_pages).
DEFAULT_ADMIN_LOGIN = "admin"


class AccountLocked(Exception):
    """Логин временно заблокирован из-за серии неверных попыток (анти-брутфорс)."""
    def __init__(self, seconds_left: int):
        super().__init__(f"Вход заблокирован, осталось {seconds_left} с")
        self.seconds = seconds_left


# ─────────────────────────────────────────────────────────────
#  Низкоуровневый key-value доступ (SQLite + async PG)
# ─────────────────────────────────────────────────────────────
def _ensure_kv(cur):
    cur.execute(
        "CREATE TABLE IF NOT EXISTS kv_store "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def _kv_get(key: str, default):
    conn = DBManager.get_conn()
    cur = conn.cursor()
    _ensure_kv(cur)
    cur.execute("SELECT value FROM kv_store WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    if row:
        try:
            return json.loads(decrypt_value(row[0]))
        except Exception:
            return default
    return default


def _kv_set(key: str, value) -> bool:
    raw = encrypt_value(json.dumps(value, ensure_ascii=False))
    conn = DBManager.get_conn()
    cur = conn.cursor()
    _ensure_kv(cur)
    cur.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", (key, raw))
    conn.commit()
    conn.close()
    if DBManager.use_pg():
        _syncer.push(
            "INSERT INTO kv_store (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, raw),
        )
    return True


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


# ─────────────────────────────────────────────────────────────
#  Высокоуровневый интерфейс (совместим с прежним GitHub-хранилищем)
# ─────────────────────────────────────────────────────────────
class LocalStore:
    """
    API полностью совместим с прежним GradeBookGitHub, поэтому остальной код
    (admin_dashboard, teacher_dashboard и т.д.) не требует переписывания —
    меняется только источник данных: вместо GitHub — PostgreSQL/SQLite.
    """

    # ── Студенты ──────────────────────────────────────────────
    def get_students(self) -> list:
        return _kv_get("students", [])

    def set_students(self, students: list) -> bool:
        return _kv_set("students", [self._hash_record(s) for s in students])

    # ── Преподаватели ─────────────────────────────────────────
    def get_teachers(self) -> dict:
        return _kv_get("teachers", {})

    def set_teachers(self, teachers: dict) -> bool:
        out = {name: self._hash_record(data) for name, data in teachers.items()}
        return _kv_set("teachers", out)

    # ── Группы ────────────────────────────────────────────────
    def get_groups(self) -> list:
        return _kv_get("groups", [])

    def set_groups(self, groups: list) -> bool:
        return _kv_set("groups", groups)

    # ── Журналы ───────────────────────────────────────────────
    def get_journal(self, group: str, subject: str) -> Optional[dict]:
        return _kv_get(f"journal:{_safe_name(group)}__{_safe_name(subject)}", None)

    def set_journal(self, group: str, subject: str, data: dict) -> bool:
        return _kv_set(f"journal:{_safe_name(group)}__{_safe_name(subject)}", data)

    # ── API-ключ и конфиг ─────────────────────────────────────
    def _config(self) -> dict:
        return _kv_get("config", {})

    def get_api_key(self) -> str:
        return self._config().get("openrouter_api_key", "")

    def set_api_key(self, key: str) -> bool:
        cfg = self._config()
        cfg["openrouter_api_key"] = key
        return _kv_set("config", cfg)

    # ── Пароль администратора (хранится только хеш) ───────────
    def get_admin_login(self) -> str:
        return self._config().get("admin_login", DEFAULT_ADMIN_LOGIN)

    def has_admin_password(self) -> bool:
        """True, если пароль администратора уже задан (хеш есть в конфиге).
        На хост-ПК при первом запуске вернёт False → нужен first-run диалог.
        На остальных ПК конфиг приходит из PostgreSQL уже с хешем → True."""
        return bool(self._config().get("admin_password_hash"))

    def set_admin_password(self, pw: str) -> bool:
        cfg = self._config()
        cfg["admin_password_hash"] = hash_password(pw)
        return _kv_set("config", cfg)

    def setup_admin_password(self, pw: str) -> bool:
        """Первичная установка пароля администратора (только если он ещё не задан).
        Защищает от перезаписи уже настроенного пароля на клиентских ПК."""
        if self.has_admin_password():
            return False
        return self.set_admin_password(pw)

    def check_admin_password(self, pw: str) -> bool:
        h = self._config().get("admin_password_hash")
        if not h:
            return False  # пароль ещё не задан — вход только через first-run установку
        return verify_password(pw, h)

    # ── Аутентификация (логин + пароль) ───────────────────────
    def authenticate(self, login: str, password: str) -> Optional[dict]:
        """
        Единая точка входа. Возвращает:
          {"role": "admin"}
          {"role": "teacher", "name": <ФИО>, "data": {...}}
          {"role": "student", "stud": {"f":..,"n":..,"g":..}}
        или None, если логин/пароль неверны.
        Бросает AccountLocked, если логин временно заблокирован за перебор.

        Здесь же — журнал аудита и анти-брутфорс: фиксируем каждый вход и блокируем
        логин после серии неверных попыток (152-ФЗ / приказ ФСТЭК №21).
        """
        from audit import (is_locked, register_failure, register_success,
                            log_event)

        login = (login or "").strip()
        if not login:
            return None

        locked, left = is_locked(login)
        if locked:
            log_event("login_locked", login, f"осталось {left}s")
            raise AccountLocked(left)

        result = self._authenticate_inner(login, password)

        if result is None:
            register_failure(login)
            log_event("login_failed", login)
        else:
            register_success(login)
            log_event("login_success", login, result.get("role", ""))
        return result

    def _authenticate_inner(self, login: str, password: str) -> Optional[dict]:
        """Сама проверка логина/пароля без аудита и блокировок."""
        if login == self.get_admin_login() and self.check_admin_password(password):
            return {"role": "admin"}

        for name, data in self.get_teachers().items():
            if (data.get("login") or "").strip() == login:
                return {"role": "teacher", "name": name, "data": data} \
                    if self._verify(data, password) else None

        for s in self.get_students():
            if (s.get("login") or "").strip() == login:
                if self._verify(s, password):
                    return {"role": "student", "stud": {
                        "f": s.get("surname", ""),
                        "n": s.get("name", ""),
                        "g": s.get("group", ""),
                    }}
                return None
        return None

    # ── Проверка соединения (для админ-панели) ────────────────
    def test_connection(self) -> tuple:
        if DBManager.use_pg():
            try:
                from db_config import test_connection as pg_test
                ok, msg = pg_test()
                return (True, f"✅ PostgreSQL: {str(msg)[:60]}") if ok else (False, str(msg))
            except Exception as e:
                return False, str(e)
        return True, "✅ Локальный SQLite (PostgreSQL не настроен)"

    def init_repo(self) -> tuple:
        # Таблицы создаются в DBManager; здесь просто гарантируем дефолты
        if not self.get_groups():
            self.set_groups([{"name": g, "subjects": []} for g in DEFAULT_GROUPS])
        return True, "✅ Хранилище инициализировано"

    # ── Внутреннее ────────────────────────────────────────────
    @staticmethod
    def _hash_record(rec: dict) -> dict:
        """Если в записи есть открытый пароль — заменяем на хеш."""
        rec = dict(rec)
        pw = rec.pop("password", None)
        if pw:
            rec["password_hash"] = hash_password(pw)
        return rec

    @staticmethod
    def _verify(rec: dict, pw: str) -> bool:
        h = rec.get("password_hash")
        if h:
            return verify_password(pw, h)
        if rec.get("password"):           # старые записи в открытом виде
            return rec["password"] == pw
        return (pw or "") == ""           # пароль не задан → вход без пароля


# ─────────────────────────────────────────────────────────────
#  Singleton
# ─────────────────────────────────────────────────────────────
_store: Optional[LocalStore] = None


def get_store() -> LocalStore:
    """Всегда возвращает рабочее хранилище (SQLite доступен всегда)."""
    global _store
    if _store is None:
        _store = LocalStore()
    return _store


def reset_store():
    global _store
    _store = None


# Совместимость с прежними именами из github_storage
get_gh_store = get_store
reset_gh_store = reset_store


def is_configured() -> bool:
    """Хранилище доступно всегда (локальный SQLite). PG — опционально."""
    return True
