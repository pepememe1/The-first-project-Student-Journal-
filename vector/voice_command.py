"""
vector/voice_command.py — РЕЭКСПОРТ общего модуля `voice_command.py` из КОРНЯ репозитория.

Разбор голосовых команд преподавателя переехал в корень — туда же, где живут
`grading.py`, `vector_nlu.py` и `study_hours.py`, и по той же причине: он нужен И десктопу,
И серверу (голосовые оценки на сайте и в телефоне). Держать вторую копию нельзя — именно
так на сервере однажды оказался отставший классификатор «Вектора» на 8 интентов вместо 15,
и лексиконы разъехались незаметно.

Этот файл оставлен, чтобы не переписывать десктопные импорты (`from . import
voice_command`, `from .voice_command import stt_context`) и ~90 тестов. Новый код
импортирует НАПРЯМУЮ: `import voice_command`.
"""
#Импорт из корня работает на всех платформах: на десктопе корень в sys.path через
#`_bootstrap.py`, на сервере — через `webdata` (как для `vector_nlu`).
from voice_command import *          # noqa: F401,F403 — сознательный реэкспорт
from voice_command import (          # noqa: F401 — имена с «_» через * не приходят
    ParsedCommand, WriteItem, LessonPlan, BatchResult,
    WRITE_ACTIONS, parse, parse_batch, stt_context,
)
