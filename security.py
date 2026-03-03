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
DEFAULT_ADMIN_PW = "vsgutu_admin_online"


# ── Криптографические примитивы ───────────────────────────────

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


# ── Хранилище ─────────────────────────────────────────────────

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
        self._admin_pw   = DEFAULT_ADMIN_PW
        self._load()

    # ── Инициализация ─────────────────────────────────────────

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

        self._admin_pw = self._data.get("__admin_pw_hint__", DEFAULT_ADMIN_PW)
        locked = self._data.get(MASTER_KEY_FIELD, "")
        if locked:
            self._master_key = _unlock_master_key(locked, self._admin_pw)
        if not self._master_key:
            # Файл повреждён или от старой версии — создаём новый
            self._init_new()

    def _init_new(self):
        self._master_key = secrets.token_bytes(32)
        self._admin_pw   = DEFAULT_ADMIN_PW
        self._data[MASTER_KEY_FIELD]    = _lock_master_key(self._master_key, self._admin_pw)
        self._data["__admin_pw_hint__"] = self._admin_pw
        self._save()

    def _save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)

    def _relock(self, new_password: str):
        """Перешифровывает мастер-ключ новым паролем. Данные не меняются."""
        self._admin_pw = new_password
        self._data[MASTER_KEY_FIELD]    = _lock_master_key(self._master_key, new_password)
        self._data["__admin_pw_hint__"] = new_password
        self._save()

    # ── Базовые операции ─────────────────────────────────────

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

    # ── Управление паролем администратора ─────────────────────

    def change_admin_password(self, new_password: str):
        self._relock(new_password)

    def set_admin_password(self, password: str):
        self.change_admin_password(password)

    def get_admin_password(self) -> str:
        return self._admin_pw

    # ── Высокоуровневые методы ────────────────────────────────

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

    # ── Перенос данных между ПК ───────────────────────────────

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

        stored_pw = new_data.get("__admin_pw_hint__", DEFAULT_ADMIN_PW)
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
            "admin_password": "vsgutu_admin_online",
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


# Глобальный экземпляр
secure_store = SecureStorage()
