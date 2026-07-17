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
    """True, если запущены как собранный .exe (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Папка, где физически лежит программа.

    Важно: при --onefile PyInstaller распаковывает код во временный sys._MEIPASS,
    но нам нужна папка, где лежит САМ .exe — это os.path.dirname(sys.executable),
    иначе пользовательские файлы оказались бы в %TEMP% и пропадали бы.
    """
    if is_frozen():
        return os.path.dirname(sys.executable)
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
