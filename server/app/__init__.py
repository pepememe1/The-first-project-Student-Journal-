"""Бэкенд GradeBookAI — пакет приложения (FastAPI).

Общие корневые модули (`grading.py`, `college_clock.py` и соседи) лежат в корне
репозитория рядом с `server/` — и на бою (`/root/gb-deploy/`), и при запуске из
исходников. Путь к ним кладётся ЗДЕСЬ, один раз: раньше это делали отдельные модули
(`webdata`, `schedule_web`), и модуль, загруженный раньше них (`config`), общий код
импортировать не мог. Условие на наличие файла — для сборки .exe: там общие модули едут
каталогом `gb_shared`, его путь кладёт `desktop/local_api._ensure_shared_path`, а корень
распаковки в путь импорта класть незачем.
"""
import os as _os
import sys as _sys

_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _os.path.isfile(_os.path.join(_ROOT, "college_clock.py")) and _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
