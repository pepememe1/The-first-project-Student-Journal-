"""
audit.py — Журнал событий безопасности и защита от перебора паролей.

Зачем (152-ФЗ, приказ ФСТЭК России №21):
  • Журнал аудита фиксирует значимые события: входы (успех/неудача), создание и
    смену пароля администратора, экспорт персональных данных. Это требование к
    защите ИСПДн — нужно понимать, кто и когда обращался к данным.
  • Анти-брутфорс ограничивает число неверных попыток входа: после порога логин
    временно блокируется, чтобы пароль нельзя было подобрать перебором.

Хранение — локальное, рядом с базой (offline-first): файл append-only audit.log
и небольшой login_throttle.json в профиле пользователя. На каждом ПК свой журнал;
централизованный сбор (в PostgreSQL/SIEM) можно добавить позже без смены API.

Модуль намеренно «не падающий»: любая ошибка ввода-вывода тут не должна ронять
вход в программу, поэтому всё обёрнуто в try/except и логируется молча.
"""

import json
import time
from datetime import datetime

import app_paths

#Порог и время блокировки при переборе
MAX_FAILS = 7            #сколько неверных попыток допускаем
LOCK_SECONDS = 300       #на сколько блокируем логин после превышения (5 минут)


#Папка та же, что у локальной базы (см. app_paths): рядом с .exe или в профиле.
_AUDIT_LOG = app_paths.data_file("audit.log")
_THROTTLE_FILE = app_paths.data_file("login_throttle.json")


#Журнал аудита
def log_event(event: str, actor: str = "", detail: str = ""):
    """
    Записывает строку в журнал: время | событие | кто | подробность.
    actor/detail НЕ должны содержать паролей или расшифрованных ПДн — пишем
    только логины/роли и обезличенные пометки.
    """
    try:
        ts = datetime.now().isoformat(timespec="seconds")
        #экранируем переводы строк, чтобы одна запись = одна строка
        actor = (actor or "").replace("\n", " ").strip()
        detail = (detail or "").replace("\n", " ").strip()
        line = f"{ts}\t{event}\t{actor}\t{detail}\n"
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        #аудит не должен ломать работу приложения
        print(f"[audit] не удалось записать событие: {e}")


def read_events(limit: int = 200) -> list:
    """Возвращает последние записи журнала (для возможного просмотра в админке)."""
    try:
        with open(_AUDIT_LOG, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [ln.rstrip("\n") for ln in lines[-limit:]]
    except FileNotFoundError:
        return []
    except Exception:
        return []


#Анти-брутфорс (лимит попыток + временная блокировка)
def _load_throttle() -> dict:
    try:
        with open(_THROTTLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_throttle(data: dict):
    try:
        with open(_THROTTLE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[audit] не удалось сохранить состояние блокировок: {e}")


def is_locked(login: str) -> tuple:
    """
    Возвращает (locked: bool, seconds_left: int).
    Блокировка хранится на диске, поэтому переживает перезапуск программы —
    иначе перебор обходился бы простым рестартом.
    """
    login = (login or "").strip().lower()
    if not login:
        return False, 0
    data = _load_throttle()
    rec = data.get(login)
    if not rec:
        return False, 0
    locked_until = rec.get("locked_until", 0)
    left = int(locked_until - time.time())
    if left > 0:
        return True, left
    return False, 0


def register_failure(login: str):
    """Фиксирует неудачную попытку. По достижении порога — ставит блокировку."""
    login = (login or "").strip().lower()
    if not login:
        return
    data = _load_throttle()
    rec = data.get(login, {"fails": 0, "locked_until": 0})
    #если прошлая блокировка истекла — счётчик начинается заново
    if rec.get("locked_until", 0) and rec["locked_until"] < time.time():
        rec = {"fails": 0, "locked_until": 0}
    rec["fails"] = rec.get("fails", 0) + 1
    if rec["fails"] >= MAX_FAILS:
        rec["locked_until"] = time.time() + LOCK_SECONDS
        rec["fails"] = 0
    data[login] = rec
    _save_throttle(data)


def register_success(login: str):
    """Сбрасывает счётчик неудач после удачного входа."""
    login = (login or "").strip().lower()
    if not login:
        return
    data = _load_throttle()
    if login in data:
        data.pop(login, None)
        _save_throttle(data)
