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

    frozen → рядом с .exe (портативно и изолированно);
    dev    → профиль пользователя (не мусорим в репозитории).
    Папку создаём при первом обращении; если не вышло — откатываемся на CWD.
    """
    d = app_dir() if is_frozen() else _dev_data_dir()
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
