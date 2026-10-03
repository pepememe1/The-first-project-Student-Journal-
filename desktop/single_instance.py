"""single_instance.py — одна копия программы на одну папку данных (28.09.2026).

Находка живого прогона: второй запуск GradeBookAI.exe открывал полноценное второе окно,
и оба процесса работали с ОДНОЙ зашифрованной базой и одной очередью досылки. Каждый
из них поднимал свой локальный сервер, свой фоновый синк и своё зеркало — гонка за
один файл, которую SQLite переживёт, а наша логика «снимок не откатывает принятую
версию» и порядок очереди — нет: два досыльщика одной очереди отправили бы правку дважды.

Замок — именованный mutex Windows, и имя берётся от ПАПКИ ДАННЫХ, а не от программы:
портативная копия в другой папке (своя база, свои ключи) — законный второй экземпляр,
например стенд тестировщика рядом с рабочей программой.
Второй запуск не пугает человека ошибкой, а поднимает уже открытое окно.

⚠️ Сбой самой проверки НЕ мешает запуску: замок — страховка, а не условие работы.
"""
from __future__ import annotations

import hashlib
import os
import sys
import time

_HANDLE = None                     # держим до конца процесса — ОС снимет замок при выходе
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9


def mutex_name(data_dir: str) -> str:
    key = os.path.normcase(os.path.abspath(data_dir or ".")).encode("utf-8")
    return "Local\\GradeBookAI-" + hashlib.sha256(key).hexdigest()[:16]


def acquire(data_dir: str, wait: float = 0.0) -> bool:
    """True — мы единственные (замок взят); False — программа с этой папкой уже открыта.

    `wait` — сколько секунд ждать, пока прежний владелец отпустит замок. Нужен ровно
    одному случаю: перезапуску ПОСЛЕ ОБНОВЛЕНИЯ (`updater.relaunch` ставит
    `GRADEBOOK_AFTER_UPDATE`). Старая копия запускает новую и только потом выходит, и без
    ожидания новая упиралась бы в её замок и молча закрывалась — «после обновления
    программа просто исчезла» (возражение Полковника 29.09.2026)."""
    deadline = time.monotonic() + max(0.0, wait)
    while True:
        got = _try_acquire(data_dir)
        if got or time.monotonic() >= deadline:
            return got
        time.sleep(0.25)


def _try_acquire(data_dir: str) -> bool:
    global _HANDLE
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        handle = k32.CreateMutexW(None, False, mutex_name(data_dir))
        if not handle:
            return True
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            k32.CloseHandle.argtypes = [ctypes.c_void_p]
            k32.CloseHandle(handle)
            return False
        _HANDLE = handle
        return True
    except Exception:              # noqa: BLE001 — страховка, а не условие запуска
        return True


def focus_existing(title_prefix: str = "GradeBookAI") -> bool:
    """Поднять уже открытое окно программы (по началу заголовка). True — нашли."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32")
        found = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _check(hwnd, _lparam):
            n = user32.GetWindowTextLengthW(hwnd)
            if n and user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.startswith(title_prefix + " — ") or buf.value == title_prefix:
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(proto(_check), 0)
        if not found:
            return False
        user32.ShowWindow(found[0], _SW_RESTORE)
        user32.SetForegroundWindow(found[0])
        return True
    except Exception:              # noqa: BLE001
        return False
