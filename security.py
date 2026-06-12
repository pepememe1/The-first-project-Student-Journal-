"""
security.py — Переносимое шифрование ВСГУТУ Журнала
====================================================
Данные шифруются случайным мастер-ключом.
Мастер-ключ защищён паролем администратора (PBKDF2).
secure_data.enc можно скопировать на ЛЮБОЙ ПК —
программа расшифрует его тем же паролем администратора.
"""

import os
import json
import base64
import hashlib
import secrets

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

SECURE_FILE      = "secure_data.enc"
MASTER_KEY_FIELD = "__master_key__"
# Пароль администратора — обфусцирован, не читается как строка в exe
import base64 as _b64
def _get_default_pw() -> str:
    """Восстанавливает встроенный пароль из обфусцированного вида."""
    _k = __import__("hashlib").sha256(b"VSGUTU_GRADEBOOK_SALT_2024").digest()
    _p = _b64.b64decode("U2bHG1yH" + "fhiDZJyA" + "OisYpdtI" + "8Q==")
    return bytes(b ^ _k[i % len(_k)] for i, b in enumerate(_p)).decode()


#Криптографические примитивы

def _derive_key(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256: пароль → 32-байтный ключ."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000, dklen=32)


def _xor_crypt(data: bytes, key: bytes) -> bytes:
    key_len = len(key)
    return bytes(b ^ key[i % key_len] for i, b in enumerate(data))


def _encrypt_bytes(plaintext: bytes, key32: bytes) -> bytes:
    if CRYPTO_AVAILABLE:
        return Fernet(base64.urlsafe_b64encode(key32)).encrypt(plaintext)
    ct  = _xor_crypt(plaintext, key32)
    mac = hashlib.sha256(key32 + ct).digest()[:8]
    return mac + ct


def _decrypt_bytes(ciphertext: bytes, key32: bytes) -> bytes:
    if CRYPTO_AVAILABLE:
        try:
            return Fernet(base64.urlsafe_b64encode(key32)).decrypt(ciphertext)
        except Exception:
            return b""
    if len(ciphertext) < 8:
        return b""
    mac_stored, body = ciphertext[:8], ciphertext[8:]
    if hashlib.sha256(key32 + body).digest()[:8] != mac_stored:
        return b""
    return _xor_crypt(body, key32)


def _lock_master_key(master_key: bytes, admin_password: str) -> str:
    """Шифрует мастер-ключ паролем администратора."""
    salt    = secrets.token_bytes(16)
    derived = _derive_key(admin_password, salt)
    enc     = _encrypt_bytes(master_key, derived)
    return base64.urlsafe_b64encode(salt + enc).decode()


def _unlock_master_key(locked: str, admin_password: str) -> bytes:
    """Расшифровывает мастер-ключ паролем администратора."""
    try:
        payload  = base64.urlsafe_b64decode(locked.encode())
        salt, enc = payload[:16], payload[16:]
        derived  = _derive_key(admin_password, salt)
        return _decrypt_bytes(enc, derived)
    except Exception:
        return b""


#Хранилище

class SecureStorage:
    """
    Переносимое зашифрованное хранилище.
    Файл secure_data.enc работает на любом ПК — привязки к машине нет.
    Для переноса: скопируйте файл и импортируйте через «📦 Перенос данных».
    """

    def __init__(self, filepath: str = SECURE_FILE):
        self.filepath    = filepath
        self._data: dict = {}
        self._master_key: bytes = b""
        self._admin_pw   = _get_default_pw()
        self._load()

    #Инициализация

    def _load(self):
        if not os.path.exists(self.filepath):
            self._init_new()
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        except Exception:
            self._data = {}
            self._init_new()
            return

        self._admin_pw = _get_default_pw()
        locked = self._data.get(MASTER_KEY_FIELD, "")
        if locked:
            # Пробуем текущий пароль
            self._master_key = _unlock_master_key(locked, self._admin_pw)
            # Обратная совместимость: старые файлы с дефолтным паролем
            if not self._master_key:
                self._master_key = _unlock_master_key(locked, _get_default_pw())
                if self._master_key:
                    self._admin_pw = _get_default_pw()
        if not self._master_key:
            # Файл повреждён или от старой версии — создаём новый
            self._init_new()

    def _init_new(self):
        self._master_key = secrets.token_bytes(32)
        self._admin_pw   = _get_default_pw()
        self._data[MASTER_KEY_FIELD]    = _lock_master_key(self._master_key, self._admin_pw)
        self._save()



    def _save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)

    def _relock(self, new_password: str):
        """Перешифровывает мастер-ключ новым паролем. Данные не меняются."""
        self._admin_pw = new_password
        self._data[MASTER_KEY_FIELD]    = _lock_master_key(self._master_key, new_password)
        self._save()

    #Базовые операции

    def set(self, key: str, value: str):
        raw = value.encode("utf-8")
        enc = _encrypt_bytes(raw, self._master_key)
        self._data[key] = base64.urlsafe_b64encode(enc).decode()
        self._save()

    def get(self, key: str, default: str = "") -> str:
        if key not in self._data or key.startswith("__"):
            return default
        try:
            enc = base64.urlsafe_b64decode(self._data[key].encode())
            raw = _decrypt_bytes(enc, self._master_key)
            return raw.decode("utf-8") if raw else default
        except Exception:
            return default

    def delete(self, key: str):
        if key in self._data:
            del self._data[key]
            self._save()

    def has(self, key: str) -> bool:
        return key in self._data and not key.startswith("__")

    #Управление паролем администратора

    def change_admin_password(self, new_password: str):
        self._relock(new_password)

    def set_admin_password(self, password: str):
        self.change_admin_password(password)

    def get_admin_password(self) -> str:
        return self._admin_pw

    #Высокоуровневые методы

    def set_teachers(self, teachers: dict):
        self.set("teachers_data", json.dumps(teachers, ensure_ascii=False))

    def get_teachers(self) -> dict:
        try:
            return json.loads(self.get("teachers_data", "{}"))
        except Exception:
            return {}

    def set_api_key(self, api_key: str):
        self.set("openrouter_api_key", api_key)

    def get_api_key(self) -> str:
        return self.get("openrouter_api_key", "")

    def set_students(self, students: list):
        self.set("students_data", json.dumps(students, ensure_ascii=False))

    def get_students(self) -> list:
        try:
            return json.loads(self.get("students_data", "[]"))
        except Exception:
            return []

    def set_groups(self, groups: list):
        self.set("groups_data", json.dumps(groups, ensure_ascii=False))

    def get_groups(self) -> list:
        try:
            return json.loads(self.get("groups_data", "[]"))
        except Exception:
            return []

    def has_any_data(self) -> bool:
        return bool(self.get_teachers() or self.get_groups() or self.get_students())

    #Перенос данных между ПК

    def export_portable(self, filepath: str) -> tuple:
        """
        Экспортирует secure_data.enc в указанный путь.
        Файл можно перенести на любой ПК и импортировать там.
        """
        try:
            import shutil
            shutil.copy2(self.filepath, filepath)
            return True, f"Данные экспортированы: {os.path.basename(filepath)}"
        except Exception as e:
            return False, str(e)

    def import_portable(self, filepath: str) -> tuple:
        """
        Импортирует данные с другого ПК.
        Заменяет текущий secure_data.enc и перезагружает хранилище.
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                new_data = json.load(f)
        except Exception as e:
            return False, f"Ошибка чтения файла: {e}"

        if MASTER_KEY_FIELD not in new_data:
            return False, (
                "Файл не является экспортом ВСГУТУ Журнала.\n"
                "Убедитесь что файл создан через «📦 Перенос данных → Экспорт»."
            )

        stored_pw = _get_default_pw()
        test_key  = _unlock_master_key(new_data[MASTER_KEY_FIELD], stored_pw)
        if not test_key:
            return False, "Не удалось расшифровать данные. Файл повреждён или изменён."

        try:
            import shutil
            shutil.copy2(filepath, self.filepath)
        except Exception as e:
            return False, f"Ошибка копирования файла: {e}"

        self._data       = new_data
        self._master_key = test_key
        self._admin_pw   = stored_pw

        t = len(self.get_teachers())
        s = len(self.get_students())
        g = len(self.get_groups())
        return True, f"Импортировано: преподавателей {t}, студентов {s}, групп {g}"

    def import_from_json(self, filepath: str) -> tuple:
        """Читает незашифрованный initial_data.json (только первый запуск)."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return False, f"Файл не найден: {filepath}"
        except json.JSONDecodeError as e:
            return False, f"Ошибка формата JSON: {e}"
        except Exception as e:
            return False, f"Ошибка чтения: {e}"

        imported = []
        if data.get("api_key"):
            self.set_api_key(data["api_key"])
            imported.append("API ключ")
        if data.get("admin_password"):
            self.set_admin_password(data["admin_password"])
            imported.append("пароль администратора")
        if data.get("teachers"):
            self.set_teachers(data["teachers"])
            imported.append(f"преподавателей: {len(data['teachers'])}")
        if data.get("students"):
            self.set_students(data["students"])
            imported.append(f"студентов: {len(data['students'])}")
        if data.get("groups"):
            self.set_groups(data["groups"])
            imported.append(f"групп: {len(data['groups'])}")
        if not imported:
            return False, "Файл пустой или не содержит распознанных данных."
        return True, "Импортировано: " + ", ".join(imported) + "."

    def export_template_json(self, filepath: str):
        """Создаёт шаблон initial_data.json."""
        template = {
            "_comment": "Заполните и положите рядом с программой. При первом запуске зашифруется.",
            "api_key": "",
            "admin_password": "задайте_пароль_администратора",
            "teachers": {
                "Иванов Иван": {
                    "password": "пароль_преподавателя",
                    "subjects": ["Компьютерные сети"],
                    "group_assignments": {}
                }
            },
            "students": [{"name": "Имя", "surname": "Фамилия", "group": "к74/1"}],
            "groups":   [{"name": "к74/1", "subjects": ["Компьютерные сети"]}]
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)

    #  ПОЛНЫЙ ЭКСПОРТ / ИМПОРТ (ZIP)

    def export_full(self, filepath: str) -> tuple:
        """Упаковывает secure_data.enc + vsgutu_grades.db + subjects.json в ZIP."""
        try:
            import zipfile
            import shutil
            from subjects import SUBJECTS_FILE
            from core import DB_NAME
            db_path = DB_NAME
            with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as zf:
                if os.path.exists(self.filepath):
                    zf.write(self.filepath, "secure_data.enc")
                if os.path.exists(db_path):
                    zf.write(db_path, "vsgutu_grades.db")
                if os.path.exists(SUBJECTS_FILE):
                    zf.write(SUBJECTS_FILE, "subjects.json")
                zf.writestr("_vsgutu_backup", "VSGUTU_FULL_BACKUP_V1")
            with zipfile.ZipFile(filepath) as zf2:
                count = len([n for n in zf2.namelist() if not n.startswith("_")])
            return True, f"Бэкап сохранён: {os.path.basename(filepath)} ({count} файла)"
        except Exception as e:
            return False, str(e)

    def analyze_import(self, filepath: str) -> tuple:
        """
        Анализирует ZIP перед импортом, возвращает diff без применения.
        Возвращает: (ok, message, diff_dict)
        """
        try:
            import zipfile
            import tempfile
            from subjects import load_subjects
            with zipfile.ZipFile(filepath, "r") as zf:
                if "_vsgutu_backup" not in zf.namelist():
                    return False, "Файл не является резервной копией ВСГУТУ.", {}
                with tempfile.TemporaryDirectory() as tmp:
                    zf.extractall(tmp)
                    tmp_enc  = os.path.join(tmp, "secure_data.enc")
                    tmp_db   = os.path.join(tmp, "vsgutu_grades.db")
                    tmp_subj = os.path.join(tmp, "subjects.json")
                    diff = {}

                    if os.path.exists(tmp_enc):
                        with open(tmp_enc, "r", encoding="utf-8") as f:
                            test_data = json.load(f)
                        if MASTER_KEY_FIELD not in test_data:
                            return False, "Файл secure_data.enc повреждён.", {}
                        stored_pw = _get_default_pw()
                        test_key  = _unlock_master_key(test_data[MASTER_KEY_FIELD], stored_pw)
                        if not test_key:
                            return False, "Не удалось расшифровать данные.", {}

                        tmp_store             = SecureStorage.__new__(SecureStorage)
                        tmp_store.filepath    = tmp_enc
                        tmp_store._data       = test_data
                        tmp_store._master_key = test_key
                        tmp_store._admin_pw   = stored_pw

                        def _norm(s):
                            f = s.get("surname", "").strip().lower()
                            n = s.get("name", "").strip().lower()
                            return tuple(sorted([f, n]))

                        cur_studs  = self.get_students()
                        new_studs  = tmp_store.get_students()
                        cur_keys   = {_norm(s) for s in cur_studs}
                        diff["added_students"] = [s for s in new_studs if _norm(s) not in cur_keys]
                        diff["dup_students"]   = [s for s in new_studs if _norm(s) in cur_keys]

                        cur_t = self.get_teachers()
                        new_t = tmp_store.get_teachers()
                        diff["added_teachers"] = [n for n in new_t if n not in cur_t]
                        diff["dup_teachers"]   = [n for n in new_t if n in cur_t]

                        cur_g  = {g["name"] for g in self.get_groups()}
                        new_g  = tmp_store.get_groups()
                        diff["added_groups"] = [g["name"] for g in new_g if g["name"] not in cur_g]
                        diff["dup_groups"]   = [g["name"] for g in new_g if g["name"] in cur_g]

                        diff["_test_data"] = test_data
                        diff["_test_key"]  = test_key

                    if os.path.exists(tmp_db):
                        import sqlite3 as _sq
                        sc = _sq.connect(tmp_db)
                        diff["db_lessons"] = sc.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
                        diff["db_grades"]  = sc.execute("SELECT COUNT(*) FROM grades").fetchone()[0]
                        diff["db_studs"]   = sc.execute("SELECT COUNT(*) FROM students").fetchone()[0]
                        sc.close()
                        # Сохраняем путь (файл уже в tempdir — копируем рядом с zip)
                        import shutil
                        db_copy = filepath + ".tmpdb"
                        shutil.copy2(tmp_db, db_copy)
                        diff["_tmp_db"] = db_copy
                    else:
                        diff["_tmp_db"] = None

                    if os.path.exists(tmp_subj):
                        with open(tmp_subj, encoding="utf-8") as f:
                            new_subj = json.load(f)
                        cur_subj = load_subjects()
                        diff["added_subjects"] = [s for s in new_subj if s not in cur_subj]
                        diff["dup_subjects"]   = [s for s in new_subj if s in cur_subj]
                        import shutil
                        subj_copy = filepath + ".tmpsubj"
                        shutil.copy2(tmp_subj, subj_copy)
                        diff["_tmp_subj"] = subj_copy
                    else:
                        diff["_tmp_subj"] = None

                    return True, "ok", diff
        except Exception as e:
            return False, str(e), {}

    def apply_import(self, diff: dict, mode: str = "merge") -> tuple:
        """
        Применяет импорт после подтверждения.
        mode: 'merge' — добавить новых, пропустить дубли
              'replace' — полностью заменить
        """
        try:
            import shutil
            from subjects import load_subjects, save_subjects
            restored = []

            if "_test_data" in diff:
                test_data = diff["_test_data"]
                test_key  = diff["_test_key"]
                stored_pw = _get_default_pw()

                tmp_store             = SecureStorage.__new__(SecureStorage)
                tmp_store._data       = test_data
                tmp_store._master_key = test_key
                tmp_store._admin_pw   = stored_pw

                def _norm(s):
                    f = s.get("surname", "").strip().lower()
                    n = s.get("name", "").strip().lower()
                    return tuple(sorted([f, n]))

                if mode == "replace":
                    self._data       = test_data
                    self._master_key = test_key
                    self._admin_pw   = stored_pw
                    self._save()
                    t = len(self.get_teachers())
                    s = len(self.get_students())
                    g = len(self.get_groups())
                    restored.append(f"заменено: препод. {t}, студ. {s}, групп {g}")
                else:
                    cur_s   = self.get_students()
                    cur_k   = {_norm(s) for s in cur_s}
                    added_s = 0
                    for s in tmp_store.get_students():
                        if _norm(s) not in cur_k:
                            cur_s.append(s); cur_k.add(_norm(s)); added_s += 1
                    self.set_students(cur_s)

                    cur_t   = self.get_teachers()
                    added_t = 0
                    for name, data in tmp_store.get_teachers().items():
                        if name not in cur_t:
                            cur_t[name] = data; added_t += 1
                    self.set_teachers(cur_t)

                    cur_g   = self.get_groups()
                    cur_gk  = {g["name"] for g in cur_g}
                    added_g = 0
                    for g in tmp_store.get_groups():
                        if g["name"] not in cur_gk:
                            cur_g.append(g); cur_gk.add(g["name"]); added_g += 1
                    self.set_groups(cur_g)
                    restored.append(f"студ. +{added_s}, препод. +{added_t}, групп +{added_g}")

            if diff.get("_tmp_db") and os.path.exists(diff["_tmp_db"]):
                import sqlite3 as _sq
                from core import DB_NAME
                sc = _sq.connect(diff["_tmp_db"])
                dc = _sq.connect(DB_NAME)
                rows_l = sc.execute(
                    "SELECT id,group_name,subject,type,number,topic,date,retake_date,hour FROM lessons"
                ).fetchall()
                dc.executemany("INSERT OR IGNORE INTO lessons VALUES(?,?,?,?,?,?,?,?,?)", rows_l)
                rows_s = sc.execute("SELECT f,n,group_name FROM students").fetchall()
                dc.executemany("INSERT OR IGNORE INTO students VALUES(?,?,?)", rows_s)
                rows_g = sc.execute(
                    "SELECT student_f,student_n,lesson_id,grade FROM grades"
                ).fetchall()
                dc.executemany(
                    "INSERT OR IGNORE INTO grades(student_f,student_n,lesson_id,grade) VALUES(?,?,?,?)",
                    rows_g
                )
                dc.commit(); sc.close(); dc.close()
                try:
                    os.remove(diff["_tmp_db"])
                except Exception:
                    pass
                restored.append(f"занятий: {len(rows_l)}, оценок: {len(rows_g)}")

            if diff.get("_tmp_subj") and os.path.exists(diff["_tmp_subj"]):
                with open(diff["_tmp_subj"], encoding="utf-8") as f:
                    new_subj = json.load(f)
                cur_subj = load_subjects()
                merged   = sorted(list(set(cur_subj) | set(new_subj)))
                save_subjects(merged)
                try:
                    os.remove(diff["_tmp_subj"])
                except Exception:
                    pass
                restored.append(f"предметов: {len(merged)}")

            return True, "Применено: " + "; ".join(restored) if restored else "Изменений нет."
        except Exception as e:
            return False, str(e)

    def export_subjects_json(self, filepath: str) -> tuple:
        try:
            import shutil
            from subjects import SUBJECTS_FILE
            if not os.path.exists(SUBJECTS_FILE):
                return False, "Файл subjects.json не найден."
            shutil.copy2(SUBJECTS_FILE, filepath)
            with open(filepath, encoding="utf-8") as f:
                count = len(json.load(f))
            return True, f"Экспортировано {count} предметов."
        except Exception as e:
            return False, str(e)

    def import_subjects_json(self, filepath: str) -> tuple:
        """Возвращает (ok, msg, diff) для показа диалога подтверждения."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return False, "Ожидается JSON-массив строк.", {}
            subjects = [str(s).strip() for s in data if str(s).strip()]
            if not subjects:
                return False, "Файл не содержит предметов.", {}
            from subjects import load_subjects
            cur     = load_subjects()
            added   = [s for s in subjects if s not in cur]
            already = [s for s in subjects if s in cur]
            return True, "ok", {"added": added, "already": already, "all": subjects}
        except Exception as e:
            return False, str(e), {}



# Глобальный экземпляр
secure_store = SecureStorage()


# ─────────────────────────────────────────────────────────────
#  Хеширование паролей пользователей (PBKDF2-HMAC-SHA256)
#  Формат строки: pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>
# ─────────────────────────────────────────────────────────────
import hmac as _hmac

_PW_ITERS = 200_000


def hash_password(password: str) -> str:
    """Возвращает безопасный хеш пароля для хранения в БД."""
    if password is None:
        password = ""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PW_ITERS)
    return f"pbkdf2_sha256${_PW_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Проверяет пароль против сохранённого хеша. Защита от timing-атак."""
    if not stored or "$" not in stored:
        return False
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iters)
        return _hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
#  Шифрование данных «на диске» (ФИО, журналы, API-ключ)
#  Ключ хранится в ОТДЕЛЬНОМ файле, а не в базе. Поэтому, если
#  кто-то скопирует только файл базы — данные останутся нечитаемы.
#
#  ВАЖНО: при работе нескольких ПК с общим PostgreSQL файл ключа
#  (data.key) должен быть ОДИНАКОВЫМ на всех ПК колледжа.
# ─────────────────────────────────────────────────────────────
import sys as _sys

_ENC_PREFIX = "enc:"
_DATA_KEY_CACHE = None


def _data_key_path() -> str:
    if _sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~")
    d = os.path.join(base, "GradeBookAI")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "data.key")


def get_data_key() -> bytes:
    """32-байтный ключ шифрования. Читается из файла или создаётся при первом запуске."""
    global _DATA_KEY_CACHE
    if _DATA_KEY_CACHE is not None:
        return _DATA_KEY_CACHE
    path = _data_key_path()
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                raw = f.read().strip()
            key = base64.urlsafe_b64decode(raw)
            if len(key) == 32:
                _DATA_KEY_CACHE = key
                return key
        except Exception:
            pass
    key = secrets.token_bytes(32)
    try:
        with open(path, "wb") as f:
            f.write(base64.urlsafe_b64encode(key))
    except Exception as e:
        print(f"[Security] не удалось сохранить ключ: {e}")
    _DATA_KEY_CACHE = key
    return key


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)


def encrypt_value(plaintext: str) -> str:
    """Шифрует строку. Возвращает 'enc:<base64>'."""
    if plaintext is None:
        plaintext = ""
    try:
        ct = _encrypt_bytes(plaintext.encode("utf-8"), get_data_key())
        return _ENC_PREFIX + base64.urlsafe_b64encode(ct).decode("ascii")
    except Exception as e:
        print(f"[Security] ошибка шифрования: {e}")
        return plaintext


def decrypt_value(value: str) -> str:
    """Расшифровывает 'enc:...'. Обычный текст (старые данные) возвращает как есть."""
    if not is_encrypted(value):
        return value
    try:
        ct = base64.urlsafe_b64decode(value[len(_ENC_PREFIX):].encode("ascii"))
        pt = _decrypt_bytes(ct, get_data_key())
        return pt.decode("utf-8")
    except Exception as e:
        print(f"[Security] ошибка расшифровки: {e}")
        return ""
