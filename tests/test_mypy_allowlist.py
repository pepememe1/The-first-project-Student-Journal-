"""Список файлов mypy (`pyproject.toml [tool.mypy] files`) не ссылается на удалённое.

`data/exports.py` удалили 01.09.2026, а из списка — нет. mypy при этом падает на «Cannot
read file» ДО проверки: целый месяц типы не проверялись вообще, а запуск выглядел как
«одна ошибка конфигурации», которую легко отложить. Найдено 02.10.2026.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mypy_files(text: str) -> list:
    section = text.split("[tool.mypy]", 1)[1].split("\n[", 1)[0]
    m = re.search(r"^files\s*=\s*\[(.*?)\]", section, re.S | re.M)
    assert m, "в [tool.mypy] нет списка files"
    return re.findall(r'"([^"]+)"', m.group(1))


def _missing(text: str) -> list:
    return [p for p in _mypy_files(text) if not os.path.isfile(os.path.join(ROOT, p))]


def test_every_mypy_file_exists():
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
        text = f.read()
    files = _mypy_files(text)
    assert len(files) >= 5, files
    assert _missing(text) == [], "mypy упадёт на чтении файла и не проверит ничего"


def test_reverse_a_deleted_file_is_noticed():
    fake = '[tool.mypy]\nfiles = ["grading.py", "data/exports.py"]\n\n[tool.other]\n'
    assert _missing(fake) == ["data/exports.py"]
