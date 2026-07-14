"""
log.py — единый файловый логгер приложения (десктоп).

Зачем. В собранном .exe консоли нет, поэтому `print(...)` в блоках `except` уходит
в никуда — диагностика теряется ровно тогда, когда нужна. Этот модуль пишет события
в ФАЙЛ (с ротацией) в папке данных приложения, а в dev-режиме дублирует в stderr.

Использование:
    import log
    log.get("sync").warning("не удалось отправить: %s", err)      # ленивое %-форматирование
    log.get("sync").exception("сбой в цикле")                     # внутри except — со стеком

Модуль намеренно без внешних зависимостей и устойчив к сбоям (не сумели открыть файл —
приложение всё равно работает, лог просто идёт в stderr). Внедряется постепенно:
сначала критичный синк-путь, дальше — остальные подсистемы вместо `except: print(...)`.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

_ROOT = "gradebook"
_configured = False


def _log_path() -> str:
    """Путь к файлу лога: <папка данных>/logs/gradebook.log. Папку данных берём из
    app_paths (рядом с .exe или в профиле); при любой ошибке — домашняя папка."""
    try:
        import app_paths
        base = os.path.join(app_paths.data_dir(), "logs")
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".gradebook", "logs")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "gradebook.log")


def _configure() -> None:
    """Настраивает корневой логгер приложения один раз за процесс (идемпотентно)."""
    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger(_ROOT)
    root.setLevel(logging.INFO)
    root.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    #Файл с ротацией: ~2 МБ × 5 — диагностика последних дней, без разрастания диска.
    try:
        fh = RotatingFileHandler(_log_path(), maxBytes=2_000_000, backupCount=5,
                                 encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass   #не смогли открыть файл — не критично, останется вывод в stderr
    #В dev (есть консоль) дублируем в stderr; в .exe это тоже безвредно.
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)


def get(name: str = "app") -> logging.Logger:
    """Логгер подсистемы (например, «sync», «schedule»). Пишет в общий файл."""
    _configure()
    return logging.getLogger(_ROOT).getChild(name)
