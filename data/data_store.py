"""
data_store.py — Локальное хранилище данных GradeBookAI (SQLite).

Никаких обращений в интернет напрямую отсюда нет.

Архитектура (offline-first):
  - Рабочее чтение/запись идёт в локальный SQLite (мгновенно, без блокировки UI).
  - Обмен с общей базой колледжа идёт через REST API-сервер ВСГУТУ отдельным
    фоновым потоком (см. sync_runner) — прямого подключения к серверной БД нет.

Данные хранятся в таблице kv_store (ключ → JSON):
  students, teachers, groups, config

Пароли НЕ хранятся в открытом виде: при записи поле "password" автоматически
превращается в "password_hash" (PBKDF2-HMAC-SHA256, см. security.py).
"""
import json
from typing import Optional

from core import DBManager
from security import hash_password, verify_password, encrypt_value, decrypt_value

#Логин администратора не секрет (секрет — пароль). Дефолтного ПАРОЛЯ больше нет:
#раньше тут лежал захардкоженный "vsgutu_admin_online", который принимался при
#первом входе — это был бэкдор. Теперь пароль администратора задаётся вручную
#при первом запуске на хост-ПК (см. setup_admin_password / auth_pages).
DEFAULT_ADMIN_LOGIN = "admin"

#Старый скомпрометированный дефолтный пароль. Его мог записать в базу старый код.
#Новый код считает такой пароль НЕ заданным: вход с ним запрещён, а при попытке
#войти администратором запускается принудительная установка нового пароля.
#Здесь он нужен ТОЛЬКО чтобы распознать и отвергнуть наследие — это не бэкдор.
_LEGACY_DEFAULT_ADMIN_PASSWORD = "vsgutu_admin_online"


def _is_legacy_default(stored_hash: str) -> bool:
    """True, если сохранённый хеш — это старый дефолтный пароль (его надо отвергнуть)."""
    return bool(stored_hash) and verify_password(_LEGACY_DEFAULT_ADMIN_PASSWORD, stored_hash)


class AccountLocked(Exception):
    """Логин временно заблокирован из-за серии неверных попыток (анти-брутфорс)."""
    def __init__(self, seconds_left: int):
        super().__init__(f"Вход заблокирован, осталось {seconds_left} с")
        self.seconds = seconds_left


#Низкоуровневый key-value доступ (SQLite + async PG)
def _ensure_kv(cur):
    cur.execute(
        "CREATE TABLE IF NOT EXISTS kv_store "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


#Модель хранения kv_store (студенты, преподаватели, конфиг, пароль-хеш админа):
#Локально в SQLite значение ЗАШИФРОВАНО ключом этого ПК (DPAPI-привязка к
#учётной записи Windows) — защищает данные на украденном/чужом компьютере,
#при этом ничего не спрашивает у пользователя.
#В общую базу колледжа эти данные попадают через API-сервер ВСГУТУ (см.
#sync_runner); канал защищён TLS, сервер размещается в РФ (152-ФЗ). Пароли
#пользователей в любом случае хранятся только хешами.
def _kv_get(key: str, default):
    conn = DBManager.get_conn()
    cur = conn.cursor()
    _ensure_kv(cur)
    cur.execute("SELECT value FROM kv_store WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    if row:
        try:
            #decrypt_value прозрачно вернёт и открытый текст (на случай миграции).
            return json.loads(decrypt_value(row[0]))
        except Exception:
            return default
    return default


def _kv_set(key: str, value, wake: bool = True) -> bool:
    plain = json.dumps(value, ensure_ascii=False)
    local_blob = encrypt_value(plain)        # локально (SQLite) — шифруем
    conn = DBManager.get_conn()
    cur = conn.cursor()
    _ensure_kv(cur)
    cur.execute("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", (key, local_blob))
    conn.commit()
    conn.close()
    #Разбудить фоновую синхронизацию с сервером (API-режим), чтобы изменение
    #ушло сразу, а не через интервал. Офлайн/нет сервера — это безвредный no-op.
    #wake=False нужен для служебных записей (например, метки last_sync), которые сами
    #по себе НЕ являются данными для отправки — иначе их запись будила бы синк, а тот
    #опять писал бы метку: получился бы бесконечный цикл «синк → метка → синк».
    if wake:
        try:
            from sync_runner import trigger as _sync_trigger
            _sync_trigger()
        except Exception:
            pass
    return True


#Метка последней синхронизации (граница дельта-pull). ЛОКАЛЬНАЯ и устройство-
#зависимая: на сервер НЕ уходит (collect_local не собирает этот ключ) и не будит
#синк (wake=False). Хранит server_time последнего успешного pull — следующий pull
#просит у сервера только изменения позже неё (не качаем всю базу каждый цикл).
_SYNC_WATERMARK_KEY = "_sync_watermark"


def get_sync_watermark() -> str:
    """Метка времени последнего успешного pull ('' — синхронизаций ещё не было)."""
    val = _kv_get(_SYNC_WATERMARK_KEY, "")
    return val if isinstance(val, str) else ""


def set_sync_watermark(server_time: str):
    """Сохраняет границу дельты молча (без пробуждения синка)."""
    _kv_set(_SYNC_WATERMARK_KEY, server_time or "", wake=False)


#Локальные настройки ПК (НЕ синхронизируются): адрес сервера API и т.п.
#Лежат в том же kv_store, но под служебным префиксом "_local:" и пишутся с
#wake=False. collect_local их не собирает (на сервер уходят только
#users/groups/subjects/config/lessons/grades), поэтому на чужие ПК они не
#уезжают и синк не будят. Идея: локальная настройка живёт «в программе» (в её
#БД), а не в отдельном json-файле рядом с exe, который правят руками.
def local_get(key: str, default=None):
    """Читает локальную настройку этого ПК ('' / default — если не задана)."""
    return _kv_get(f"_local:{key}", default)


def local_set(key: str, value) -> bool:
    """Сохраняет локальную настройку этого ПК (молча, без пробуждения синка)."""
    return _kv_set(f"_local:{key}", value, wake=False)


def _now_iso() -> str:
    from datetime import datetime, timezone
    #Время в UTC и с микросекундами. UTC — чтобы метки разных ПК сравнивались
    #честно, без зависимости от часового пояса/перевода часов (LWW по строке).
    #Микросекунды — чтобы создание и удаление в одну секунду различались.
    return datetime.now(timezone.utc).isoformat()


def _stamp_records(new_records, old_records, key_fn):
    """Проставляет updated_at=now только тем записям, что появились или изменились
    (сравнение с прошлой версией по ключу, без учёта самого updated_at). Неизменные
    сохраняют свою метку. Так синхронизация шлёт только реальные изменения, а не
    весь список заново — корректный LWW между ПК без лишнего «шума»."""
    now = _now_iso()
    old_map = {key_fn(r): r for r in old_records}
    for r in new_records:
        prev = old_map.get(key_fn(r))
        changed = (prev is None or
                   {k: v for k, v in r.items() if k != "updated_at"} !=
                   {k: v for k, v in prev.items() if k != "updated_at"})
        if changed:
            r["updated_at"] = now
        elif not r.get("updated_at"):
            r["updated_at"] = prev.get("updated_at", now)
    return new_records


def _student_key(r) -> str:
    return (r.get("login") or
            f"{r.get('surname','')}|{r.get('name','')}|{r.get('group','')}")


def _merge_list_tombstones(new_live, old_raw, key_fn):
    """Возвращает «сырой» список со штампами и надгробиями: записи, которые БЫЛИ,
    а в новом списке исчезли, помечаются deleted=True (а не пропадают) — чтобы
    удаление доехало до других ПК. Существующие надгробия сохраняются."""
    now = _now_iso()
    old_map = {key_fn(r): r for r in old_raw}
    old_live = [r for r in old_raw if not r.get("deleted")]
    _stamp_records(new_live, old_live, key_fn)
    out, new_keys = [], set()
    for r in new_live:
        r["deleted"] = False
        new_keys.add(key_fn(r))
        out.append(r)
    for k, r in old_map.items():
        if k in new_keys:
            continue
        if r.get("deleted"):
            out.append(r)                       # уже надгробие — сохраняем
        else:
            t = dict(r); t["deleted"] = True; t["updated_at"] = now
            out.append(t)                       # было живым, исчезло → надгробие
    return out

#  Высокоуровневый интерфейс к локальному хранилищу
class LocalStore:
    """
    Единая точка доступа к данным приложения (студенты, преподаватели, группы,
    конфиг). Данные лежат в локальном SQLite (kv_store); обмен с общей базой
    колледжа идёт через API-сервер (см. sync_runner).
    """

    #Студенты
    #get_* отдают только ЖИВЫЕ записи (UI не видит надгробий).
    #get_*_raw отдают всё, включая надгробия — нужно синхронизации.
    def get_students(self) -> list:
        return [s for s in _kv_get("students", []) if not s.get("deleted")]

    def get_students_raw(self) -> list:
        return _kv_get("students", [])

    def set_students(self, students: list, stamp: bool = True, wake: bool = True) -> bool:
        records = [self._hash_record(s) for s in students]
        #stamp=True — обычная правка/удаление в UI: исчезнувшие записи становятся
        # надгробиями, изменённые — штампуются.
        #stamp=False — применение данных с сервера (уже слиты, с надгробиями) —
        # сохраняем как есть, чтобы синк не зациклился.
        #wake=False идёт в паре со stamp=False: запись серверных данных НЕ должна
        # будить синк (иначе apply_remote → wake → синк → apply_remote — busy-loop).
        if stamp:
            records = _merge_list_tombstones(records, _kv_get("students", []), _student_key)
        return _kv_set("students", records, wake=wake)

    #Преподаватели
    def get_teachers(self) -> dict:
        return {k: v for k, v in _kv_get("teachers", {}).items() if not v.get("deleted")}

    def get_teachers_raw(self) -> dict:
        return _kv_get("teachers", {})

    def set_teachers(self, teachers: dict, stamp: bool = True, wake: bool = True) -> bool:
        out = {name: self._hash_record(data) for name, data in teachers.items()}
        if stamp:
            old_raw = _kv_get("teachers", {})
            old_live = {k: v for k, v in old_raw.items() if not v.get("deleted")}
            now = _now_iso()
            for name, data in out.items():
                data["deleted"] = False
                prev = old_live.get(name)
                changed = (prev is None or
                           {k: v for k, v in data.items() if k != "updated_at"} !=
                           {k: v for k, v in prev.items() if k != "updated_at"})
                if changed:
                    data["updated_at"] = now
                elif not data.get("updated_at"):
                    data["updated_at"] = prev.get("updated_at", now)
            #надгробия: были, в новом наборе исчезли
            for name, prev in old_raw.items():
                if name in out:
                    continue
                if prev.get("deleted"):
                    out[name] = prev
                else:
                    t = dict(prev); t["deleted"] = True; t["updated_at"] = now
                    out[name] = t
        return _kv_set("teachers", out, wake=wake)

    #Группы
    def get_groups(self) -> list:
        return [g for g in _kv_get("groups", []) if not g.get("deleted")]

    def get_groups_raw(self) -> list:
        return _kv_get("groups", [])

    def set_groups(self, groups: list, stamp: bool = True, wake: bool = True) -> bool:
        if stamp:
            groups = _merge_list_tombstones(groups, _kv_get("groups", []),
                                            lambda r: r.get("name", ""))
        return _kv_set("groups", groups, wake=wake)

    #Конфиг приложения
    def _config(self) -> dict:
        return _kv_get("config", {})

    #Пароль администратора (хранится только хеш)
    def get_admin_login(self) -> str:
        return self._config().get("admin_login", DEFAULT_ADMIN_LOGIN)

    def has_admin_password(self) -> bool:
        """True, если задан ВАЛИДНЫЙ пароль администратора (хеш есть и это не старый
        дефолт). На хост-ПК при первом запуске — False → нужен first-run диалог.
        На остальных ПК конфиг приходит из PostgreSQL уже с хешем → True.
        Старый дефолтный пароль считаем «не заданным», чтобы заставить сменить его."""
        h = self._config().get("admin_password_hash")
        if not h or _is_legacy_default(h):
            return False
        return True

    def set_admin_password(self, pw: str) -> bool:
        #Не даём установить старый скомпрометированный дефолт — иначе бэкдор вернётся.
        if pw == _LEGACY_DEFAULT_ADMIN_PASSWORD:
            return False
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
        if not h or _is_legacy_default(h):
            return False  #пароль не задан или это старый дефолт — вход запрещён
        return verify_password(pw, h)

    #Аутентификация (логин + пароль)
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
            #Запускается фоновая синхронизация с сервером (если задан адрес API).
            #Офлайн / без сервера — внутри просто ничего не делает.
            try:
                from sync_runner import start as _sync_start
                _sync_start(login, password, result.get("role", ""))
            except Exception as e:
                print(f"[sync] не удалось запустить: {e}")
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

    def lookup_session(self, login: str):
        """Находит пользователя ПО ЛОГИНУ без проверки пароля и возвращает (role, payload)
        в том же виде, что ждут экраны/сигналы входа:
          ("admin", None) | ("teacher", (ФИО, data)) | ("student", stud) | None.

        Нужна для ПЕРСИСТЕНТНОГО входа: при старте мы доверяем сохранённой сессии
        (вход уже был выполнен ранее, а доступ к серверу держит сохранённый токен),
        поэтому пароль повторно не спрашиваем — только пересобираем payload дашборда
        из СВЕЖИХ локальных данных (после реконсиляции с сервером)."""
        login = (login or "").strip()
        if not login:
            return None
        if login == self.get_admin_login():
            return ("admin", None)
        for name, data in self.get_teachers().items():
            if (data.get("login") or "").strip() == login:
                return ("teacher", (name, data))
        for s in self.get_students():
            if (s.get("login") or "").strip() == login:
                return ("student", {"f": s.get("surname", ""), "n": s.get("name", ""),
                                    "g": s.get("group", "")})
        return None

    #Внутреннее
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
        if rec.get("password"):           #старые записи в открытом виде
            return rec["password"] == pw
        return (pw or "") == ""           #пароль не задан → вход без пароля


#Singleton
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


def reset_synced_local_data():
    """Стирает СИНХРОНИЗИРУЕМЫЙ кэш этого ПК, сохраняя локальные настройки.

    Зачем. Слияние с сервером аддитивное (sync_engine._merge_by_key): локальная запись
    убирается только по серверному надгробию. Поэтому запись, оставшаяся ТОЛЬКО локально
    (от прежнего аккаунта/сессии или после обновления), «протекала» в следующий аккаунт
    на этом ПК (баг с фантомным студентом). Реконсиляция на границе сессии: стираем кэш и
    затем полным pull приводим локаль в точное соответствие серверу (server wins).

    Стираем: students/teachers/groups (kv), предметы (subjects.json), занятия/оценки/
    конфликты (таблицы), метку дельты. НЕ трогаем:
      • ключи с префиксом `_local:` — адрес сервера, device_id, токен, сохранённая
        сессия, host-флаги, тема, offline_ack (иначе слетели бы подключение и вход);
      • `config` — хеш пароля админа и тема вуза; на полном pull сервер перезапишет свои
        ключи, а лишних «осиротевших» ключей в config практически не бывает.
    """
    #Пустые коллекции пишем без пробуждения синка (это не правка данных, а очистка
    #кэша — будить синхронизацию незачем, да и нечего отправлять).
    _kv_set("students", [], wake=False)
    _kv_set("teachers", {}, wake=False)
    _kv_set("groups", [], wake=False)
    #Метку дельты сбрасываем, чтобы следующий pull был полным и наполнил кэш заново.
    set_sync_watermark("")
    try:
        from subjects import save_subjects
        save_subjects([])
    except Exception as e:
        print(f"[reset] предметы не очищены: {e}")
    try:
        from core import DBManager
        DBManager.clear_synced_tables()
    except Exception as e:
        print(f"[reset] таблицы занятий/оценок не очищены: {e}")
    #Сбрасываем singleton — чтобы в памяти не осталось ссылок на старые данные.
    reset_store()
