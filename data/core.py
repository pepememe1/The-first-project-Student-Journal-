"""
core.py — Журнал ВСГУТУ.

Архитектура (offline-first):
  - Все операции чтения/записи идут в локальный SQLite (мгновенно, без блокировки UI).
  - Обмен с общей базой колледжа идёт через REST API-сервер ВСГУТУ — отдельным
    фоновым потоком (см. sync_runner), а не прямым подключением к БД с клиента.
  - Оффлайн: работаем с SQLite, при восстановлении сети — автосинхронизация.
"""
import sqlite3
import uuid
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Dict
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

APP_VERSION = "Pre-release 2.7"

import os as _os
import sys as _sys
import shutil as _shutil
import socket as _socket
import app_paths


#Где лежит локальная база.
#ВАЖНО: SQLite ВСЕГДА на локальном диске машины — никогда на сетевой шаре
#(иначе блокировки и порча файла при работе нескольких ПК). Где именно лежит
#папка — решает app_paths: рядом с .exe (портативно) или в профиле (dev).


def _is_network_path(path: str) -> bool:
    """Эвристика: UNC-путь (\\\\server\\share) или сетевой диск Windows."""
    p = _os.path.abspath(path)
    if p.startswith("\\\\") or p.startswith("//"):
        return True
    if _sys.platform == "win32":
        try:
            import ctypes
            drive = _os.path.splitdrive(p)[0] + "\\"
            return ctypes.windll.kernel32.GetDriveTypeW(drive) == 4  # DRIVE_REMOTE
        except Exception:
            return False
    return False


DATA_DIR = app_paths.data_dir()
LOCAL_DB = _os.path.join(DATA_DIR, "vsgutu_grades.db")
BACKUP_DIR = _os.path.join(DATA_DIR, "backups")
DEVICE_ID = (_socket.gethostname() or "pc")[:64]   #имя ПК — для детекта конфликтов
MAX_BACKUPS = 48                                    #сколько бэкапов держим (~сутки при цикле 30 мин)
AUTO_BACKUP_INTERVAL_SEC = 30 * 60                  #не чаще одного авто-бэкапа в 30 минут

if _is_network_path(LOCAL_DB):
    print("[DBManager] ВНИМАНИЕ: локальная база на сетевом пути — это вызывает "
          "блокировки и порчу. Используйте локальный диск.")


#Менеджер подключений
class DBManager:
    @classmethod
    def init(cls):
        """Вызывается при старте: создаёт локальные таблицы SQLite.

        Прямого подключения к серверной БД с клиента НЕТ — обмен с общей базой
        колледжа идёт через REST API-сервер (см. sync_runner). Offline-first
        сохраняется: приложение всегда работает на локальном SQLite, а синхронизация
        подхватывается фоном при наличии сети."""
        cls._init_sqlite_tables()
        print("ℹ️  Локальный SQLite (синхронизация с сервером — через API)")

    @classmethod
    def get_conn(cls):
        """Всегда локальное SQLite соединение. WAL + busy_timeout снижают
        риск блокировок и порчи, если файл всё же оказался общим."""
        conn = sqlite3.connect(LOCAL_DB, timeout=10)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        return conn

    #Авто-бэкапы локальной базы
    @classmethod
    def backup(cls, reason: str = "") -> str:
        """
        Копирует файл базы в DATA_DIR/backups/ с меткой времени.
        Вызывается перед синхронизацией/закрытием. Возвращает путь к бэкапу
        ('' — если бэкапить нечего). Старые бэкапы (свыше MAX_BACKUPS) удаляются.
        """
        try:
            if not _os.path.exists(LOCAL_DB):
                return ""
            _os.makedirs(BACKUP_DIR, exist_ok=True)
            #Микросекунды (%f) в имени — чтобы два бэкапа в одну и ту же секунду
            #(например, авто-бэкап и «перед восстановлением») не затирали друг друга.
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            tag = ("_" + "".join(ch for ch in reason if ch.isalnum())[:16]) if reason else ""
            dst = _os.path.join(BACKUP_DIR, f"vsgutu_grades_{ts}{tag}.db")
            #WAL: гарантируем, что данные на диске, затем копируем
            try:
                c = sqlite3.connect(LOCAL_DB)
                c.execute("PRAGMA wal_checkpoint(FULL)")
                c.close()
            except Exception:
                pass
            _shutil.copy2(LOCAL_DB, dst)
            cls._prune_backups()
            return dst
        except Exception as e:
            print(f"[DBManager] бэкап не удался: {e}")
            return ""

    @classmethod
    def backup_if_due(cls, min_interval_sec: int = AUTO_BACKUP_INTERVAL_SEC,
                      reason: str = "auto") -> str:
        """Бэкап ПО РАСПИСАНИЮ: делает копию, только если с последнего бэкапа прошло
        не меньше min_interval_sec (или бэкапов ещё нет). Вызывается по таймеру из UI,
        поэтому таймер может тикать чаще — лишних копий не наплодим. Защищает от
        потери данных при аварийном завершении (не дождались бэкапа «на выходе»)."""
        try:
            import time as _time
            backups = cls.list_backups()      #свежие первыми, элемент = (имя,путь,размер,mtime)
            if backups and (_time.time() - backups[0][3]) < min_interval_sec:
                return ""                     #ещё рано — последний бэкап свежий
            return cls.backup(reason=reason)
        except Exception as e:
            print(f"[DBManager] backup_if_due: {e}")
            return ""

    @classmethod
    def _prune_backups(cls):
        try:
            files = sorted(
                (f for f in _os.listdir(BACKUP_DIR) if f.endswith(".db")),
                reverse=True,
            )
            for old in files[MAX_BACKUPS:]:
                try:
                    _os.remove(_os.path.join(BACKUP_DIR, old))
                except Exception:
                    pass
        except Exception:
            pass

    @classmethod
    def list_backups(cls) -> list:
        """[(имя, полный_путь, размер_байт, mtime), ...] от свежих к старым."""
        out = []
        try:
            for f in _os.listdir(BACKUP_DIR):
                if not f.endswith(".db"):
                    continue
                p = _os.path.join(BACKUP_DIR, f)
                st = _os.stat(p)
                out.append((f, p, st.st_size, st.st_mtime))
        except Exception:
            pass
        out.sort(key=lambda x: x[3], reverse=True)
        return out

    @classmethod
    def restore(cls, backup_path: str) -> bool:
        """Восстанавливает базу из бэкапа. Перед этим делает бэкап текущей."""
        try:
            if not _os.path.exists(backup_path):
                return False
            cls.backup(reason="before_restore")
            _shutil.copy2(backup_path, LOCAL_DB)
            return True
        except Exception as e:
            print(f"[DBManager] восстановление не удалось: {e}")
            return False

    @classmethod
    def wipe_all_local_data(cls, remove_backups: bool = True) -> dict:
        """ПОЛНЫЙ сброс локальных данных ЭТОГО ПК до состояния «первый запуск».

        Удаляет файл базы (вместе со студентами, преподавателями, оценками, группами,
        конфигом, ХЕШЕМ пароля администратора, адресом сервера, сохранённым токеном и
        кэшем темы — всё это лежит в kv_store одной базы), её WAL/SHM-хвосты и, по
        умолчанию, все резервные копии (иначе восстановление вернуло бы старые данные).

        Что НЕ трогаем сознательно:
          • общую базу колледжа на сервере — это ЛОКАЛЬНЫЙ сброс одного ПК;
          • ключ шифрования data.key — новой пустой базе он не мешает;
          • audit.log и login_throttle.json — журнал безопасности по 152-ФЗ сохраняем.

        Таблицы заново НЕ создаём: при следующем старте их пересоздаст DBManager.init().
        Если файл занят другим процессом и удалить его не вышло — откатываемся на
        очистку содержимого через SQL (DROP всех таблиц), чтобы данные всё равно ушли.

        Возвращает {'removed': [...], 'errors': [...]} — что удалили и где споткнулись.
        """
        removed, errors = [], []

        #Гасим фоновую синхронизацию: иначе её поток может в этот момент держать
        #соединение (файл не удалить) или тут же подтянуть данные обратно с сервера.
        try:
            import sync_runner
            sync_runner.stop()
        except Exception:
            pass

        #Сбрасываем WAL в основной файл и отпускаем соединение — чтобы -wal/-shm не
        #держали данные и файлы освободились для удаления.
        try:
            c = sqlite3.connect(LOCAL_DB)
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            c.close()
        except Exception:
            pass

        file_ok = True
        for suffix in ("-wal", "-shm", "-journal", ""):
            p = LOCAL_DB + suffix
            try:
                if _os.path.exists(p):
                    _os.remove(p)
                    removed.append(_os.path.basename(p))
            except Exception as e:
                file_ok = False
                errors.append(f"{_os.path.basename(p)}: {e}")

        #Файл не удалился (занят) — чистим содержимое через SQL как запасной путь.
        if not file_ok and _os.path.exists(LOCAL_DB):
            try:
                conn = cls.get_conn(); cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                for (t,) in cur.fetchall():
                    if t.startswith("sqlite_"):
                        continue
                    cur.execute(f"DROP TABLE IF EXISTS {t}")
                conn.commit(); conn.close()
                cls._init_sqlite_tables()   #оставляем валидную пустую базу
                removed.append("(содержимое базы очищено через SQL)")
            except Exception as e:
                errors.append(f"sql-wipe: {e}")

        if remove_backups and _os.path.isdir(BACKUP_DIR):
            for f in list(_os.listdir(BACKUP_DIR)):
                if not f.endswith(".db"):
                    continue
                try:
                    _os.remove(_os.path.join(BACKUP_DIR, f))
                    removed.append("backups/" + f)
                except Exception as e:
                    errors.append(f"backups/{f}: {e}")

        #Сбрасываем singleton хранилища, чтобы в памяти не осталось ссылок на старое.
        try:
            import data_store
            data_store.reset_store()
        except Exception:
            pass

        return {"removed": removed, "errors": errors}

    @classmethod
    def clear_synced_tables(cls) -> None:
        """Очищает ТОЛЬКО синхронизируемые таблицы (занятия, оценки, конфликты),
        оставляя саму базу и kv_store с локальными настройками (адрес сервера, токен,
        device_id) на месте. Нужна для «реконсиляции с сервером»: на границе сессии
        стираем локальный кэш данных, чтобы затем полным pull привести его в точное
        соответствие серверу — иначе аддитивное слияние оставляло бы «осиротевшие»
        локальные записи (баг с фантомным студентом). Файл НЕ удаляем (в отличие от
        wipe_all_local_data), поэтому WAL-checkpoint не нужен."""
        conn = cls.get_conn(); cur = conn.cursor()
        try:
            for t in ("grades", "lessons", "sync_conflicts"):
                cur.execute(f"DELETE FROM {t}")
            conn.commit()
        finally:
            conn.close()

    #Конфликты синхронизации (детект вместо тихой перезаписи)
    @classmethod
    def list_conflicts(cls, unresolved_only: bool = True) -> list:
        """Список конфликтов оценок: [dict(...), ...]."""
        out = []
        try:
            conn = cls.get_conn(); cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS sync_conflicts ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                        "student_f TEXT, student_n TEXT, lesson_id TEXT,"
                        "local_grade TEXT, remote_grade TEXT, remote_device TEXT,"
                        "remote_at TEXT, detected_at TEXT, resolved INTEGER DEFAULT 0)")
            q = ("SELECT id,student_f,student_n,lesson_id,local_grade,remote_grade,"
                 "remote_device,remote_at,detected_at,resolved FROM sync_conflicts")
            if unresolved_only:
                q += " WHERE resolved=0"
            q += " ORDER BY detected_at DESC"
            cur.execute(q)
            cols = ["id", "student_f", "student_n", "lesson_id", "local_grade",
                    "remote_grade", "remote_device", "remote_at", "detected_at", "resolved"]
            out = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.close()
        except Exception as e:
            print(f"[DBManager] чтение конфликтов: {e}")
        return out

    @classmethod
    def resolve_conflict(cls, conflict_id: int, chosen_grade: str) -> bool:
        """
        Применяет выбранное преподавателем значение и закрывает конфликт.
        chosen_grade записывается как победитель в SQLite; updated_at обновляется,
        поэтому решение само уедет на сервер при следующей синхронизации (API).
        """
        try:
            conn = cls.get_conn(); cur = conn.cursor()
            cur.execute("SELECT student_f,student_n,lesson_id FROM sync_conflicts "
                        "WHERE id=?", (conflict_id,))
            row = cur.fetchone()
            if not row:
                conn.close(); return False
            f, n, lid = row
            now = datetime.now(timezone.utc).isoformat()
            cur.execute("INSERT OR REPLACE INTO grades "
                        "(student_f,student_n,lesson_id,grade,updated_at,device,deleted) "
                        "VALUES (?,?,?,?,?,?,0)", (f, n, lid, chosen_grade, now, DEVICE_ID))
            cur.execute("UPDATE sync_conflicts SET resolved=1 WHERE id=?", (conflict_id,))
            conn.commit(); conn.close()
            return True
        except Exception as e:
            print(f"[DBManager] resolve_conflict: {e}")
            return False

    @classmethod
    def placeholder(cls) -> str:
        return "?"  #всегда SQLite локально

    @classmethod
    def _init_sqlite_tables(cls):
        conn = sqlite3.connect(LOCAL_DB)
        cur  = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS lessons
            (id TEXT PRIMARY KEY, group_name TEXT, subject TEXT,
             type TEXT, number INTEGER, topic TEXT, date TEXT,
             retake_date TEXT DEFAULT '', hour INTEGER DEFAULT 0)""")
        #deleted — «надгробие»: удалённое занятие НЕ стираем, а помечаем, чтобы
        #удаление доехало до других ПК (иначе занятие воскресало бы при pull).
        for col, default in [("retake_date", "TEXT DEFAULT ''"), ("hour", "INTEGER DEFAULT 0"),
                             ("updated_at", "TEXT DEFAULT ''"), ("deleted", "INTEGER DEFAULT 0")]:
            try:
                cur.execute(f"ALTER TABLE lessons ADD COLUMN {col} {default}")
            except Exception:
                pass
        cur.execute("""CREATE TABLE IF NOT EXISTS students
            (f TEXT, n TEXT, group_name TEXT, PRIMARY KEY(f, n, group_name))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS grades
            (student_f TEXT, student_n TEXT, lesson_id TEXT, grade TEXT,
             updated_at TEXT DEFAULT '', device TEXT DEFAULT '',
             PRIMARY KEY(student_f, student_n, lesson_id))""")
        #миграция старых баз без новых колонок
        for col in ("updated_at", "device"):
            try:
                cur.execute(f"ALTER TABLE grades ADD COLUMN {col} TEXT DEFAULT ''")
            except Exception:
                pass
        #deleted у оценок — то же надгробие (удалённая оценка не должна воскресать).
        try:
            cur.execute("ALTER TABLE grades ADD COLUMN deleted INTEGER DEFAULT 0")
        except Exception:
            pass
        cur.execute("""CREATE TABLE IF NOT EXISTS sync_conflicts
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             student_f TEXT, student_n TEXT, lesson_id TEXT,
             local_grade TEXT, remote_grade TEXT, remote_device TEXT,
             remote_at TEXT, detected_at TEXT, resolved INTEGER DEFAULT 0)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS kv_store
            (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        conn.commit()
        conn.close()

    @classmethod
    def upsert_lesson(cls, cur, vals: tuple):
        """INSERT OR REPLACE для занятия в SQLite.
        Проставляем updated_at — нужно для синхронизации через API (LWW)."""
        now = datetime.now(timezone.utc).isoformat()
        #deleted=0 — это сохранение АКТИВНОГО занятия (в т.ч. «воскрешает» ранее
        #удалённое, если занятие создали заново с тем же id — на практике id новый).
        cur.execute("INSERT OR REPLACE INTO lessons (id,group_name,subject,type,number,topic,date,retake_date,hour,updated_at,deleted) VALUES (?,?,?,?,?,?,?,?,?,?,0)", tuple(vals[:9]) + (now,))

    @classmethod
    def upsert_student(cls, cur, vals: tuple):
        cur.execute("INSERT OR IGNORE INTO students (f,n,group_name) VALUES (?,?,?)", vals)

    @classmethod
    def upsert_grade(cls, cur, vals: tuple):
        """
        vals = (student_f, student_n, lesson_id, grade).
        Проставляем updated_at и device — это делает синхронизацию
        детерминированной (newest-wins по времени, а не «как повезёт»).
        """
        f, n, lid, grade = vals[:4]
        now = datetime.now(timezone.utc).isoformat()
        #deleted=0 — выставление оценки делает запись активной (снимает прежнее
        #надгробие, если оценку ставят заново после удаления).
        cur.execute(
            "INSERT OR REPLACE INTO grades "
            "(student_f,student_n,lesson_id,grade,updated_at,device,deleted) "
            "VALUES (?,?,?,?,?,?,0)", (f, n, lid, grade, now, DEVICE_ID))


#Датаклассы 
@dataclass
class Lesson:
    id: str
    type: str
    number: int
    topic: str
    date: str
    retake_date: str = ""
    hour: int = 0


@dataclass
class Student:
    n: str
    f: str
    group: str
    records: Dict[str, str] = field(default_factory=dict)


#Журнал
class GradeBook:
    def __init__(self, group: str, subject: str):
        self.group   = group
        self.subject = subject
        DBManager._init_sqlite_tables()
        self.lessons: List[Lesson] = []
        self.spisok_stud: List[Student] = []
        self.load_from_db()

    def add_student(self, st: Student):
        self.spisok_stud.append(st)
        self.save_to_db()

    def delete_student(self, surname: str, name: str):
        surname = surname.strip()
        name    = name.strip()
        self.spisok_stud = [
            s for s in self.spisok_stud
            if not (s.f.strip().lower() == surname.lower()
                    and s.n.strip().lower() == name.lower())
        ]
        conn = DBManager.get_conn()
        cur  = conn.cursor()
        #Оценки удаляем НЕ физически, а надгробием (deleted=1 + свежий updated_at):
        #так удаление доедет до других ПК через синхронизацию, а не «воскреснет» при
        #следующем pull. Физическое удаление оставило бы серверную копию живой.
        now = datetime.now(timezone.utc).isoformat()
        cur.execute("UPDATE grades SET deleted=1, updated_at=?, device=? "
                    "WHERE student_f=? AND student_n=?", (now, DEVICE_ID, surname, name))
        cur.execute("DELETE FROM students WHERE f=? AND n=?", (surname, name))
        conn.commit()
        conn.close()

    def delete_lesson(self, lesson_id: str):
        """Удаляет занятие НАДГРОБИЕМ (deleted=1), а не физически — иначе удаление не
        доезжало бы до других ПК и занятие воскресало бы при следующем pull. Раньше
        занятие лишь убиралось из списка в памяти, а строка в SQLite оставалась —
        и при перезагрузке журнала столбец возвращался. Заодно надгробим оценки
        этого занятия, чтобы они не висели «осиротевшими» и тоже удалились везде."""
        self.lessons = [l for l in self.lessons if l.id != lesson_id]
        conn = DBManager.get_conn()
        cur  = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cur.execute("UPDATE lessons SET deleted=1, updated_at=? WHERE id=?", (now, lesson_id))
        cur.execute("UPDATE grades SET deleted=1, updated_at=?, device=? WHERE lesson_id=?",
                    (now, DEVICE_ID, lesson_id))
        conn.commit()
        conn.close()

    def add_lesson(self, lesson_type: str, topic: str = "", date: str = "", hour: int = 0) -> "Lesson":
        nums     = [l.number for l in self.lessons if l.type == lesson_type and getattr(l, 'hour', 0) in (0, 1)]
        next_num = max(nums) + 1 if nums else 1
        dt = date or datetime.now().strftime('%d.%m.%Y')

        if lesson_type == "Лекция" and hour == 0:
            l1 = Lesson(id=str(uuid.uuid4()), type="Лекция", number=next_num, topic=topic, date=dt, retake_date="", hour=1)
            l2 = Lesson(id=str(uuid.uuid4()), type="Лекция", number=next_num, topic=topic, date=dt, retake_date="", hour=2)
            self.lessons.extend([l1, l2])
            self.save_to_db()
            return l1
        else:
            l = Lesson(id=str(uuid.uuid4()), type=lesson_type, number=next_num, topic=topic, date=dt, retake_date="", hour=hour)
            self.lessons.append(l)
            self.save_to_db()
            return l

    def set_retake_date(self, lesson_id: str, retake_date: str, retake_n: int = 1):
        attr = 'retake_date' if retake_n == 1 else f'retake_date_{retake_n}'
        for l in self.lessons:
            if l.id == lesson_id:
                setattr(l, attr, retake_date)
                break
        col = 'retake_date' if retake_n == 1 else f'retake_date_{retake_n}'
        conn = DBManager.get_conn()
        cur  = conn.cursor()
        try:
            cur.execute(f"ALTER TABLE lessons ADD COLUMN {col} TEXT DEFAULT ''")
        except Exception:
            pass
        cur.execute(f"UPDATE lessons SET {col}=? WHERE id=?", (retake_date, lesson_id))
        conn.commit()
        conn.close()

    def save_to_db(self):
        conn = DBManager.get_conn()
        cur  = conn.cursor()
        for l in self.lessons:
            DBManager.upsert_lesson(cur, (
                l.id, self.group, self.subject, l.type,
                l.number, l.topic, l.date,
                getattr(l, 'retake_date', ''),
                getattr(l, 'hour', 0)
            ))
        for s in self.spisok_stud:
            DBManager.upsert_student(cur, (s.f, s.n, s.group))
            for lesson_id, grade in s.records.items():
                DBManager.upsert_grade(cur, (s.f, s.n, lesson_id, grade))
        conn.commit()
        conn.close()

    def load_from_db(self):
        conn = DBManager.get_conn()
        cur  = conn.cursor()

        #deleted=0 — удалённые (надгробия) занятия в журнал не показываем.
        cur.execute(
            "SELECT id, type, number, topic, date, retake_date, hour "
            "FROM lessons WHERE group_name=? AND subject=? AND COALESCE(deleted,0)=0 "
            "ORDER BY type, number, hour",
            (self.group, self.subject)
        )
        self.lessons = []
        for row in cur.fetchall():
            l = Lesson(
                id=row[0], type=row[1], number=row[2],
                topic=row[3], date=row[4],
                retake_date=row[5] if row[5] else "",
                hour=row[6] if row[6] else 0
            )
            self.lessons.append(l)

        #Синхронизация студентов из общего хранилища (data_store)
        #Студентами управляет администратор через data_store (kv_store в SQLite,
        #а общая база — через API-сервер). Здесь мы лишь дозаполняем локальную
        #таблицу students теми, кого ещё нет. ВАЖНО: НЕ удаляем студентов из SQLite —
        #иначе добавленные администратором студенты исчезали бы при каждой
        #перезагрузке журнала.
        try:
            from data_store import get_store
            store = get_store()
            if store:
                known_students = store.get_students()
                existing = set()
                cur.execute("SELECT f, n FROM students WHERE group_name=?", (self.group,))
                for row in cur.fetchall():
                    existing.add((row[0].strip().lower(), row[1].strip().lower()))
                for s in known_students:
                    if s.get("group", "") != self.group:
                        continue
                    surname = s.get("surname", "").strip()
                    name    = s.get("name", "").strip()
                    if surname and name and (surname.lower(), name.lower()) not in existing:
                        DBManager.upsert_student(cur, (surname, name, self.group))
                        existing.add((surname.lower(), name.lower()))
                conn.commit()
        except Exception as e:
            print(f"[GradeBook] синхронизация студентов в load_from_db: {e}")

        cur.execute("SELECT f, n, group_name FROM students WHERE group_name=?", (self.group,))
        self.spisok_stud = []
        for f, n, g in cur.fetchall():
            student = Student(n, f, g)
            #deleted=0 — удалённые (надгробия) оценки в журнал/расчёт не берём.
            cur.execute("SELECT lesson_id, grade FROM grades "
                        "WHERE student_f=? AND student_n=? AND COALESCE(deleted,0)=0", (f, n))
            student.records = {row[0]: row[1] for row in cur.fetchall()}
            self.spisok_stud.append(student)
        conn.close()

    def calculate_average(self, student: Student) -> float:
        """Средний балл через единый модуль grading (та же формула, что у Вектора).
        Методика (Н=вес, учитывать ли пропуск, включать ли экзамены) берётся
        из config, дефолты сохраняют прежнее поведение."""
        import grading
        try:
            from data_store import get_store
            cfg = get_store()._config()
        except Exception:
            cfg = {}
        return grading.practice_average(
            grading.pairs_from_objects(self.lessons), student.records, cfg)

    def export_to_excel(self, file_path: str):
        wb = Workbook()
        ws = wb.active
        title      = f"Успеваемость {self.group}"
        safe_title = re.sub(r'[\[\]:*?/\\]', '_', title)
        ws.title   = safe_title[:31]
        headers = ["Фамилия", "Имя"]
        for l in self.lessons:
            if l.type == "Экзамен":
                headers.append(f"Экзамен №{l.number}\n({l.date})\n{l.topic}")
                if l.retake_date:
                    headers.append(f"Пересдача\n({l.retake_date})")
            else:
                headers.append(f"{l.type} №{l.number}\n({l.date})")
        headers.append("Средний балл")
        ws.append(headers)
        for cell in ws[1]:
            cell.font      = Font(bold=True, color="FFFFFF")
            cell.fill      = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
        for s in self.spisok_stud:
            row = [s.f, s.n]
            for l in self.lessons:
                base = s.records.get(l.id, "")
                row.append(base)
                if l.type == "Экзамен" and l.retake_date:
                    rv = s.records.get(l.id + "_retake", "")
                    if not rv:
                        #пересдача только у заваливших основной экзамен
                        b = (base or "").strip()
                        failed = b.startswith(("2", "Н")) or "Не зачтено" in b
                        rv = "" if failed else "—"
                    row.append(rv)
            row.append(round(self.calculate_average(s), 2))
            ws.append(row)
        wb.save(file_path)
