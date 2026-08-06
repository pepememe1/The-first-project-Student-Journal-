"""
app_paths.py — единый источник правды о том, где приложение хранит свои файлы.

Зачем этот модуль. Раньше каждый модуль вычислял «папку данных» сам, и они
разъехались: база и журналы попадали в %LOCALAPPDATA%, а ключ шифрования и
install_key — в %APPDATA% (Roaming). Из-за разнобоя данные растекались по двум
каталогам, а несколько копий программы на одном ПК дрались за ОДНУ общую базу
(одна копия пишет — другая своим синком затирает). Теперь правило одно.

  • Собранный .exe — ПОРТАТИВНЫЙ: все свои файлы (база, ключ шифрования, журналы,
    бэкапы, api_config.json, subjects.json) держит РЯДОМ С СОБОЙ. Папку можно
    скопировать или перенести — это будет отдельная, ни от кого не зависящая
    установка. Две копии в разных папках = два независимых «ПК» (честная
    эмуляция нескольких рабочих мест без общей базы и без гонок).

  • Запуск из исходников (python main.py) — служебные файлы кладём в профиль
    пользователя (%LOCALAPPDATA%/GradeBookAI и аналоги для macOS/Linux), чтобы не
    засорять рабочую копию репозитория временными базами и ключами.

Деление простое:
  app_dir()  — где ЛЕЖИТ программа (рядом с exe / со скриптом). Сюда — файлы,
               которые человек правит руками: api_config.json, subjects.json.
  data_dir() — куда писать служебное (база, ключ, журналы, бэкапы).
               В .exe это та же папка, что и app_dir(); в dev — профиль.
"""
import os
import sys


def is_frozen() -> bool:
    """True, если запущены как собранный .exe.

    🔥 ЖИВОЙ БАГ (найден при разборе «автообновление не работает», Release-3.6.2):
    PyInstaller ставит `sys.frozen`, а **Nuitka — НЕТ** (единственный РЕЛИЗНЫЙ путь,
    §8.1 CLAUDE.md). Старая проверка `getattr(sys, "frozen", False)` под релизным
    .exe всегда возвращала False — `app_dir()`/`data_dir()` уходили в DEV-ветку, а
    `__file__` под Nuitka onefile резолвится во ВРЕМЕННУЮ распаковку
    (`%TEMP%\\onefile_.../app_paths.py`, эмпирически проверено отдельной пробной
    сборкой), а не туда, где лежит настоящий .exe. Тем же путём шёл и
    `updater.py::_exe_path()` — в итоге апдейтер либо подменял файл не там, либо не
    находил, что подменять, и обновление визуально «не работало». Тот же нюанс уже
    был учтён в `ui/webview2_app.py::_is_compiled()` (`"__compiled__" in globals()`) —
    здесь применяем ТОТ ЖЕ приём, а не изобретаем второй."""
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def _nuitka_onefile_dir() -> str:
    """Папка настоящего .exe под Nuitka ONEFILE, или "".

    ⚠️ `sys.executable` под Nuitka onefile указывает НЕ на настоящий .exe, а на
    временный bootstrap-интерпретатор в `%TEMP%\\onefile_<pid>_<ts>_<rnd>\\python.exe`
    (тоже проверено пробной сборкой) — использовать его для app_dir() означало бы
    писать базу/ключ/логи во временную папку, которую Nuitka вправе очистить. Nuitka
    сама кладёт путь к настоящему .exe в переменную окружения `NUITKA_ONEFILE_
    DIRECTORY` (документированный механизм ИМЕННО для этого случая) — читаем её."""
    return os.environ.get("NUITKA_ONEFILE_DIRECTORY", "").strip()


def app_dir() -> str:
    """Папка, где физически лежит программа.

    Важно: при --onefile код распаковывается во временную папку, но нам нужна папка,
    где лежит САМ .exe — иначе пользовательские файлы оказались бы в %TEMP% и
    пропадали бы (PyInstaller — `os.path.dirname(sys.executable)`, Nuitka —
    `NUITKA_ONEFILE_DIRECTORY`, см. is_frozen()/_nuitka_onefile_dir() выше).
    """
    #Переопределение папки — для ТЕСТОВ. Без него прогон клиентского набора писал в
    #subjects.json РЕПОЗИТОРИЯ (reset_synced_local_data чистит предметы) и затирал
    #рабочий список разработчика: тесты «зелёные», а файл в дереве изменён.
    override = os.environ.get("GRADEBOOK_APP_DIR", "").strip()
    if override:
        return override
    if is_frozen():
        return _nuitka_onefile_dir() or os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


#FOLDERID_Downloads — официальный GUID известной папки «Загрузки» Windows.
_FOLDERID_DOWNLOADS = "{374DE290-123F-4565-9164-39C4925E467B}"


def _known_folder_path(folder_id_guid: str) -> str:
    """Путь известной папки Windows через SHGetKnownFolderPath.

    ⚠️ ЖИВАЯ НАХОДКА: первая версия `_is_risky_run_location` сравнивала с наивной
    склейкой `expanduser("~") + "Downloads"` — и НЕ СРАБОТАЛА на реальном собранном
    .exe (проверено живым прогоном: файлы всё равно легли в Downloads). Причина —
    «Загрузки» НЕ обязана физически сидеть по этому пути: Windows хранит её
    РЕАЛЬНОЕ расположение отдельно (перенос папки, OneDrive Known Folder Move,
    политики), и достать его можно только через настоящий API, а не угадыванием.
    Возвращает "" при любой ошибке (нет API — просто нет и этой защиты, портативное
    поведение как раньше)."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        class _GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                       ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

        ole32, shell32 = ctypes.windll.ole32, ctypes.windll.shell32
        ole32.CLSIDFromString.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_GUID)]
        ole32.CLSIDFromString.restype = ctypes.c_long
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID), ctypes.c_ulong, wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

        rfid = _GUID()
        if ole32.CLSIDFromString(folder_id_guid, ctypes.byref(rfid)) != 0:
            return ""
        buf = ctypes.c_wchar_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(rfid), 0, None, ctypes.byref(buf)) != 0:
            return ""
        path = buf.value or ""
        ole32.CoTaskMemFree(buf)
        return path
    except Exception:
        return ""


def _is_risky_run_location(path: str) -> bool:
    """Папка, откуда программу типично запускают СЛУЧАЙНО, не «установив» её.

    🔥 ЖИВОЙ БАГ: скачали .exe с сайта, запустили СРАЗУ из «Загрузки» — база и ключи
    шифрования легли в ту же папку, вперемешку с другими скачанными файлами (человек
    прислал скриншот — рядом с .exe лежат data.key/vsgutu_grades.db/local_app.key).
    Это НЕ баг портативности как таковой (см. докстрин модуля — «скопировать/
    перенести» работает и работает намеренно, ради независимых тестовых копий), а
    конкретно про одну ОБЩЕИЗВЕСТНУЮ ловушку: «Загрузки» — не то место, где человек
    ДЕРЖИТ программы, туда просто падает браузерная закачка.

    Сверяем ПРЕЖДЕ ВСЕГО с настоящим путём из Windows (_known_folder_path) — наивная
    склейка `~/Downloads` остаётся только запасным вариантом (см. её докстрин: она
    не всегда совпадает с реальным расположением папки)."""
    try:
        norm = os.path.normcase(os.path.normpath(path))
        candidates = []
        known = _known_folder_path(_FOLDERID_DOWNLOADS)
        if known:
            candidates.append(known)
        home = os.path.expanduser("~")
        for name in ("Downloads", "Загрузки"):
            candidates.append(os.path.join(home, name))
        return any(norm == os.path.normcase(os.path.normpath(c)) for c in candidates)
    except Exception:
        return False


def _dev_data_dir() -> str:
    """Папка данных в профиле пользователя — только для запуска из исходников."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") \
            or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") \
            or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "GradeBookAI")


def data_dir() -> str:
    """Папка для служебных файлов (база, ключ, журналы, бэкапы).

    frozen → рядом с .exe (портативно и изолированно) — КРОМЕ «Загрузок» (см.
             _is_risky_run_location, живой баг) — там служебные файлы уходят в
             постоянное системное место, а сам .exe остаётся, где скачался;
    dev    → профиль пользователя (не мусорим в репозитории).
    Папку создаём при первом обращении; если не вышло — откатываемся на CWD.

    ⚠️ `app_dir()` этот редирект НЕ трогает и продолжает отвечать «где реальный
    .exe» как есть — это нужно апдейтеру (переименовать именно ЕГО) и поиску
    бандл-ресурсов (там, где они реально лежат), путать с data_dir() нельзя."""
    d = app_dir() if is_frozen() else _dev_data_dir()
    if is_frozen() and _is_risky_run_location(d):
        safe = os.path.join(os.environ.get("LOCALAPPDATA") or d, "GradeBookAI")
        try:
            os.makedirs(safe, exist_ok=True)
            d = safe
        except Exception:
            pass                #не вышло — остаёмся портативными, как раньше
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        d = os.getcwd()
    return d


def data_file(name: str) -> str:
    """Полный путь к служебному файлу внутри папки данных."""
    return os.path.join(data_dir(), name)


def app_file(name: str) -> str:
    """Полный путь к пользовательскому файлу рядом с программой."""
    return os.path.join(app_dir(), name)
