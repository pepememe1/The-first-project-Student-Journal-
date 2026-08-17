"""
conftest.py — Фикстуры для тестов КЛИЕНТА (логика без GUI: core, sync_engine, data_store).

Главное: подменяем папку данных на временную ДО импорта клиентских модулей. core.py
вычисляет путь к локальной базе на этапе импорта (app_paths.data_dir() читает
LOCALAPPDATA), поэтому переменную окружения задаём в самом верху, пока ни один
модуль приложения ещё не импортирован — тесты не трогают рабочую базу разработчика.

Fixture fresh_db даёт чистую базу на каждый тест: удаляем файл БД и пере-инициализируем
таблицы, плюс сбрасываем сессионный флаг дельта-синка.
"""
import os
import glob
import tempfile

#Временная папка данных — строго до импорта core/data_store/sync_engine.
_DATA = tempfile.mkdtemp(prefix="gbai_client_tests_")
os.environ["LOCALAPPDATA"] = _DATA
#И папку ПРОГРАММЫ тоже: часть путей считается ОТ неё (app_paths.safe_app_file).
#Историческая причина — subjects.json лежал рядом с main.py, и прогон тестов затирал
#рабочий список предметов разработчика. Файла и модуля больше нет (17.08.2026, источник
#правды — портал ВСГУТУ), но подмена папки остаётся правильной: она изолирует прогон от
#дерева репозитория целиком, а не от одного файла.
os.environ["GRADEBOOK_APP_DIR"] = _DATA

import pytest

from data.core import DBManager, LOCAL_DB


@pytest.fixture()
def fresh_db():
    """Чистая локальная база на каждый тест (файл БД + WAL/SHM удаляем, таблицы заново)."""
    for f in glob.glob(LOCAL_DB + "*"):     #.db, -wal, -shm
        try:
            os.remove(f)
        except OSError:
            pass
    DBManager.init()
    #Сбрасываем «первый полный pull сессии», чтобы тесты дельты не влияли друг на друга.
    from sync import sync_engine
    sync_engine.reset_session_state()
    yield
