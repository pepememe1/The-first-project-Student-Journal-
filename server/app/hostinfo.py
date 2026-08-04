"""
hostinfo.py — сведения о машине, на которой ЭТОТ сервер работает.

Кто это читает. Раздел «Сервер» в кабинете администратора: на сайте — только просмотр,
в программе — то же самое плюс управление по SSH (см. `ui/server_admin.py`, оно живёт
ТОЛЬКО в локальном сервере и на боевой машине не существует).

━━ БЕЗ НОВЫХ ЗАВИСИМОСТЕЙ ━━
Ни psutil, ни чего-либо ещё. Боевой VPS — одно ядро и 960 МБ, каждая лишняя библиотека
там заметна, а всё нужное лежит в `/proc` и в стандартной библиотеке. Заодно тот же код
работает на Windows (программа на компьютере преподавателя) — там читаем через ctypes.

━━ ЧЕГО ЗДЕСЬ НЕТ ━━
Ни одной операции, меняющей систему. Этот модуль умеет только СМОТРЕТЬ: страница
администратора на сайте не должна получать даже теоретической возможности что-то
выполнить на боевом сервере.
"""
import os
import platform
import shutil
import sys
import time


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _linux_memory() -> dict:
    """Память из /proc/meminfo (килобайты). Пусто — значит не Linux."""
    text = _read("/proc/meminfo")
    if not text:
        return {}
    vals = {}
    for line in text.splitlines():
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        num = parts[1].strip().split()
        if num and num[0].isdigit():
            vals[parts[0]] = int(num[0]) * 1024
    total = vals.get("MemTotal", 0)
    #MemAvailable, а не MemFree: ядро отдаёт под кэш почти всю свободную память, и
    #MemFree на живом сервере всегда близок к нулю — по нему кажется, что памяти нет.
    available = vals.get("MemAvailable", vals.get("MemFree", 0))
    swap_total = vals.get("SwapTotal", 0)
    swap_free = vals.get("SwapFree", 0)
    if not total:
        return {}
    return {"total": total, "available": available, "used": total - available,
            "swap_total": swap_total, "swap_used": swap_total - swap_free}


def _windows_memory() -> dict:
    """Память на Windows — через GlobalMemoryStatusEx (ctypes, без зависимостей)."""
    try:
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = _Status()
        st.dwLength = ctypes.sizeof(_Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return {}
        return {"total": st.ullTotalPhys, "available": st.ullAvailPhys,
                "used": st.ullTotalPhys - st.ullAvailPhys,
                "swap_total": 0, "swap_used": 0}
    except Exception:      # noqa: BLE001 — сведения о железе не повод падать
        return {}


def memory() -> dict:
    return _linux_memory() or _windows_memory()


def uptime_seconds() -> float:
    """Сколько машина работает. 0 — узнать не удалось (не Linux и нет счётчика)."""
    text = _read("/proc/uptime")
    if text:
        try:
            return float(text.split()[0])
        except (ValueError, IndexError):
            pass
    try:
        import ctypes
        return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    except Exception:      # noqa: BLE001
        return 0.0


def load_average() -> list:
    """Средняя загрузка за 1/5/15 минут. На Windows такого понятия нет — пусто."""
    try:
        return [round(x, 2) for x in os.getloadavg()]
    except (OSError, AttributeError):
        return []


def cpu_count() -> int:
    return os.cpu_count() or 1


def disk(path: str = "/") -> dict:
    """Место на диске, где лежит сервер."""
    target = path if os.path.exists(path) else os.path.abspath(os.sep)
    try:
        total, used, free = shutil.disk_usage(target)
    except OSError:
        return {}
    return {"path": target, "total": total, "used": used, "free": free}


def dir_size(path: str, max_entries: int = 200_000) -> int:
    """Размер каталога с содержимым.

    Ограничение по числу файлов — не оптимизация, а страховка: каталог с сотнями тысяч
    записей (например, чужой примонтированный диск) заставил бы запрос со страницы
    администратора обходить его целиком, и страница просто зависла бы."""
    total = seen = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
            seen += 1
            if seen >= max_entries:
                return total
    return total


def listdir(path: str, root: str) -> list:
    """Содержимое каталога с размерами. Пусто — путь вне `root` или недоступен.

    ⚠️ ВЫХОД ЗА `root` ЗАПРЕЩЁН. Это единственная защита от того, чтобы страница
    администратора превратилась в файловый менеджер по всей машине: без неё запрос
    `?path=/etc` показал бы содержимое системных каталогов, а `..` увёл бы куда угодно.
    Содержимое файлов не отдаётся никогда — только имена и размеры."""
    try:
        real_root = os.path.realpath(root)
        target = os.path.realpath(path or root)
    except OSError:
        return []
    if target != real_root and not target.startswith(real_root + os.sep):
        return []
    out = []
    try:
        entries = sorted(os.scandir(target), key=lambda e: (not e.is_dir(), e.name.lower()))
    except OSError:
        return []
    for e in entries:
        try:
            is_dir = e.is_dir(follow_symlinks=False)
            size = dir_size(e.path) if is_dir else e.stat(follow_symlinks=False).st_size
            mtime = e.stat(follow_symlinks=False).st_mtime
        except OSError:
            continue
        out.append({"name": e.name, "dir": is_dir, "size": size,
                    "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))})
    return out


#Момент запуска ЭТОГО процесса приложения. Считается один раз при импорте модуля, то
#есть при старте сервера, — ровно то, что нужно: «когда служба последний раз
#перезапускалась». Машинный `uptime` на этот вопрос не отвечает (VPS может работать
#месяцами, а gradebook рестартовали десять минут назад при деплое), и путать эти две
#величины на экране администратора нельзя — из-за такой путаницы «сервер не обновился»
#выглядит как «сервер работает нормально».
_PROCESS_START = time.time()


def process_uptime_seconds() -> float:
    """Сколько работает САМО приложение (не машина)."""
    return max(0.0, time.time() - _PROCESS_START)


def summary(root: str = "") -> dict:
    """Всё сразу — то, что рисует карточка «Сервер» в кабинете администратора."""
    base = root or os.getcwd()
    return {
        "host": platform.node(),
        "system": f"{platform.system()} {platform.release()}",
        "python": sys.version.split()[0],
        "cpu_count": cpu_count(),
        "load": load_average(),
        "uptime": uptime_seconds(),
        "process_uptime": process_uptime_seconds(),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_PROCESS_START)),
        "memory": memory(),
        "disk": disk(base),
        "root": os.path.realpath(base),
        "now": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
