"""
audit.py — Журнал событий безопасности и защита от перебора паролей.

Зачем (152-ФЗ, приказ ФСТЭК России №21):
  • Журнал аудита фиксирует значимые события: входы (успех/неудача), создание и
    смену пароля администратора, экспорт персональных данных. Это требование к
    защите ИСПДн — нужно понимать, кто и когда обращался к данным.
  • Анти-брутфорс ограничивает число неверных попыток входа: после порога логин
    временно блокируется, чтобы пароль нельзя было подобрать перебором.

ГДЕ ХРАНИМ (важно для 152-ФЗ). Раньше журнал лежал ОТКРЫТЫМ файлом audit.log рядом с
базой, а состояние блокировок — login_throttle.json. Открытый файл с логинами/ролями
и метками доступа к ИСПДн — это утечка по форме хранения. Теперь и журнал, и троттлинг
живут ВНУТРИ программы — в её локальном зашифрованном хранилище (data_store, kv_store
под префиксом «_local:», Fernet-шифрование, ключ под Windows DPAPI). Эти ключи НЕ
синхронизируются на сервер (журнал у каждого ПК свой; централизованный сбор в SIEM —
отдельная задача и делается на стороне сервера). Старые файлы при первом запуске
разово переносятся внутрь и удаляются (см. _migrate_once).

Журнал админ видит во вкладке «Мониторинг» (раздел «Локальный журнал безопасности»).
Это и есть мониторинг доступа на конкретном ПК.

Модуль намеренно «не падающий»: любая ошибка ввода-вывода тут не должна ронять вход
в программу, поэтому всё обёрнуто в try/except и логируется молча. data_store
импортируем ЛЕНИВО внутри функций — чтобы импорт audit на раннем старте не тянул БД
и не падал, если хранилище ещё не готово.
"""

import os
import time
from datetime import datetime

import app_paths

#Порог и время блокировки при переборе
MAX_FAILS = 7            #сколько неверных попыток допускаем
LOCK_SECONDS = 300       #на сколько блокируем логин после превышения (5 минут)

#Ключи в локальном (зашифрованном, несинхронизируемом) хранилище.
_AUDIT_KEY = "audit_log"          # список строк «ts\tevent\tactor\tdetail»
_THROTTLE_KEY = "login_throttle"  # словарь login -> {fails, locked_until}

#Кольцевой буфер журнала: держим последние N записей (как консоль мониторинга),
#чтобы зашифрованная запись не росла бесконечно. Полное хранение/SIEM — на сервере.
_AUDIT_CAP = 1000

#Старые файлы (наследие) — переносим внутрь программы и удаляем при первом запуске.
_LEGACY_AUDIT = app_paths.data_file("audit.log")
_LEGACY_THROTTLE = app_paths.data_file("login_throttle.json")

_migrated = False


def _ds():
    """Ленивая ссылка на data_store (см. пояснение в шапке)."""
    import data_store
    return data_store


def _migrate_once():
    """Разовый перенос старых файлов журнала/троттлинга в зашифрованное хранилище.

    Файл удаляем ТОЛЬКО после успешной записи внутрь — если хранилище ещё не готово
    (нет ключа/БД), данные не теряем, попробуем в следующий запуск.
    """
    global _migrated
    if _migrated:
        return
    _migrated = True       # в этой сессии повторно не дёргаем (файл переживёт до успеха)
    try:
        ds = _ds()
        #journal
        if os.path.exists(_LEGACY_AUDIT):
            with open(_LEGACY_AUDIT, "r", encoding="utf-8") as f:
                lines = [ln.rstrip("\n") for ln in f if ln.strip()]
            ok = True
            if lines:
                cur = ds.local_get(_AUDIT_KEY, []) or []
                ok = ds.local_set(_AUDIT_KEY, (cur + lines)[-_AUDIT_CAP:])
            if ok:
                os.remove(_LEGACY_AUDIT)
        #throttle
        if os.path.exists(_LEGACY_THROTTLE):
            import json
            with open(_LEGACY_THROTTLE, "r", encoding="utf-8") as f:
                data = json.load(f)
            ok = True
            if isinstance(data, dict) and data:
                ok = ds.local_set(_THROTTLE_KEY, data)
            if ok:
                os.remove(_LEGACY_THROTTLE)
    except Exception as e:
        #миграция не критична: упадём молча, файл останется до следующего запуска
        print(f"[audit] перенос старого журнала отложен: {e}")


#Журнал аудита
def log_event(event: str, actor: str = "", detail: str = ""):
    """
    Записывает строку в журнал: время | событие | кто | подробность.
    actor/detail НЕ должны содержать паролей или расшифрованных ПДн — пишем
    только логины/роли и обезличенные пометки.
    """
    try:
        _migrate_once()
        ts = datetime.now().isoformat(timespec="seconds")
        #экранируем переводы строк, чтобы одна запись = одна строка
        actor = (actor or "").replace("\n", " ").strip()
        detail = (detail or "").replace("\n", " ").strip()
        line = f"{ts}\t{event}\t{actor}\t{detail}"
        ds = _ds()
        cur = ds.local_get(_AUDIT_KEY, []) or []
        cur.append(line)
        ds.local_set(_AUDIT_KEY, cur[-_AUDIT_CAP:])
    except Exception as e:
        #аудит не должен ломать работу приложения
        print(f"[audit] не удалось записать событие: {e}")


def read_events(limit: int = 200) -> list:
    """Возвращает последние записи журнала (для просмотра в «Мониторинге»)."""
    try:
        _migrate_once()
        items = _ds().local_get(_AUDIT_KEY, []) or []
        return list(items[-limit:])
    except Exception:
        return []


#Анти-брутфорс (лимит попыток + временная блокировка)
def _load_throttle() -> dict:
    try:
        _migrate_once()
        data = _ds().local_get(_THROTTLE_KEY, {})
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_throttle(data: dict):
    try:
        _ds().local_set(_THROTTLE_KEY, data)
    except Exception as e:
        print(f"[audit] не удалось сохранить состояние блокировок: {e}")


def is_locked(login: str) -> tuple:
    """
    Возвращает (locked: bool, seconds_left: int).
    Блокировка хранится в зашифрованной БД программы, поэтому переживает перезапуск —
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
    #locked_until — это Unix-метка (float от time.time()), поэтому инициализируем
    #0.0, а не 0: иначе тип значения словаря выводится как int и присваивание
    #float'а ниже считается ошибкой типов.
    rec = data.get(login, {"fails": 0, "locked_until": 0.0})
    #если прошлая блокировка истекла — счётчик начинается заново
    if rec.get("locked_until", 0) and rec["locked_until"] < time.time():
        rec = {"fails": 0, "locked_until": 0.0}
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
