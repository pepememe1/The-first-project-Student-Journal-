# -*- coding: utf-8 -*-
"""Сторож состава релизного артефакта (`tools/build_release.py`).

Зачем именно сторож, а не «мы же посмотрели». Частичный деплой ронял прод ДВАЖДЫ,
и оба раза причина была одна: список корневых общих модулей вёлся РУКАМИ. Такой
список — снимок значения; он верен в день, когда его написали, и молча устаревает.
Проверено на этом же заходе: в рукописном списке `CLAUDE.md` §8.1 нет ни `log`,
ни `teacher_match`, хотя оба нужны серверу (`teacher_match` появился 28.08.2026).

⚠️ Тест зовёт ФУНКЦИИ ПРОДУКТА, а не повторяет их логику у себя. Повторённая
формула сверяет копию с копией: правка в сборщике такой тест не тронет.
"""

import ast
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_release as BR  # noqa: E402


def _module_level_local_imports(path, local):
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out & local


def test_every_module_the_server_imports_on_startup_is_in_the_artifact():
    """Ни один модуль, нужный на СТАРТЕ, не должен остаться за бортом."""
    shipped = set(BR.needed_root_modules())
    local = BR._local_module_names()

    missing = {}
    for base, dirs, files in os.walk(BR.SERVER_APP):
        dirs[:] = [d for d in dirs if d not in BR.EXCLUDE_DIRS]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            for mod in _module_level_local_imports(path, local):
                if mod not in shipped and mod != "app":
                    missing.setdefault(mod, []).append(os.path.relpath(path, ROOT))

    assert not missing, (
        "server/app импортирует это НА СТАРТЕ, а в артефакт не попадёт:\n  "
        + "\n  ".join(f"{m} ← {', '.join(v[:3])}" for m, v in missing.items())
    )


def test_the_desktop_half_never_travels_to_the_production_server():
    """🔒 В артефакте не должно быть десктопных пакетов. Это §16, а не гигиена.

    В `desktop/server_admin.py` живёт выполнение произвольных команд по SSH на
    боевой машине. Единственное, что отделяет эту возможность от браузера, —
    то, что НА БОЕВОМ СЕРВЕРЕ ЭТОГО КОДА НЕТ. Роль можно обойти, отсутствующий
    файл — нельзя.

    🔥 Не гипотетическая осторожность: первая версия сборщика обходила импорты
    транзитивно и «всех подряд», и `data/`, `sync/`, `desktop/` попали в список —
    через ЛЕНИВЫЕ импорты в `schedule/overrides.py`, которые на сервере не
    исполняются никогда. Артефакт привёз бы на прод ровно то, чего там быть не
    должно, причём молча и с самыми добрыми намерениями.
    """
    forbidden = {"desktop", "data", "sync", "tests", "tools", "web"}
    shipped = set(BR.needed_root_modules())
    assert not (shipped & forbidden), (
        f"в артефакт попали пакеты, которых на бою быть не должно: "
        f"{sorted(shipped & forbidden)}"
    )


@pytest.mark.parametrize("module", [
    "grading",        # расчёт оценок — общий с десктопом
    "study_hours",    # часы и ЗЕТ
    "vector_nlu",     # разбор вопросов к Вектору
    "voice_command",  # голосовые команды
    "desktop_update", # версия и манифест обновлений
    "schedule",       # парсер портала
    "teacher_match",  # сопоставление ФИО преподавателей (28.08.2026)
    "log",            # его нет в рукописном списке CLAUDE.md §8.1
])
def test_known_shared_modules_are_shipped(module):
    """Обратный ход: если обход сломается, список опустеет и это будет ВИДНО.

    Без такой проверки достаточно опечатки в обходе каталогов, и `needed_root_modules`
    вернёт пустоту — а первый тест на пустом множестве останется зелёным.
    """
    assert module in BR.needed_root_modules()


def test_version_slug_is_safe_for_paths():
    """Версия человекочитаемая («Release 3.8.2») — в имени каталога так нельзя."""
    assert BR.version_slug("Release 3.8.2") == "release-3.8.2"
    assert " " not in BR.version_slug(BR.app_version())


def test_the_artifact_carries_no_state():
    """В артефакте не должно быть ни ключей, ни базы, ни выкладок.

    Артефакт ходит по почте и лежит в хранилище сборок. `.env` внутри означал бы,
    что ключ от базы с ПДн уехал вместе с ним.
    """
    entries = BR.gather(include_web=False)
    bad = [arc for _src, arc in entries
           if arc.endswith((".env", ".db", ".key", ".pem", ".keystore"))
           or "/downloads/" in arc or "/ota_bundles/" in arc or "/gb-backups/" in arc]
    assert not bad, f"в артефакт попало состояние: {bad}"


def test_the_build_refuses_state_that_slipped_into_the_tree(monkeypatch, tmp_path):
    """🔒 F-25 (аудит 22.09.2026): ворота стоят В САМОЙ СБОРКЕ, а не только здесь.

    Тест выше проверяет сегодняшнее дерево, но сборка до 26.09.2026 сама не отказывала:
    база, оставшаяся в `server/app` после запуска из исходников, уехала бы в архив.
    ⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать проверку из `gather` — краснеет."""
    db = tmp_path / "gradebook_server.db"
    db.write_bytes(b"SQLite format 3\x00")
    real = BR._gather
    monkeypatch.setattr(BR, "_gather", lambda include_web=True:
                        real(include_web=False) + [(str(db), "app/gradebook_server.db")])
    with pytest.raises(SystemExit):
        BR.gather(include_web=False)


def test_forbidden_names_and_private_keys_are_recognised(tmp_path):
    key = tmp_path / "notes.txt"
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n", encoding="utf-8")
    plain = tmp_path / "ok.py"
    plain.write_text("KEY_NAME = 'token'  # слова key/token в коде — не секрет\n", encoding="utf-8")
    bad = BR.forbidden_entries([
        (str(key), "app/notes.txt"), (str(plain), "app/ok.py"),
        (str(plain), "root/PILOT.md"), (str(plain), "root/.env.bak-2026-09-05"),
        (str(plain), "webdist/GB_DB_KEY.txt"), (str(plain), "app/x.sqlite3"),
        #Имена, которые люди дают копиям, — их пропускала первая версия ворот (второй
        #заход Полковника, 26.09.2026): проверялось только окончание имени.
        (str(plain), "app/gradebook_server.db.bak"), (str(plain), "app/gradebook_server.db-journal"),
        (str(plain), "app/prod.env.bak"), (str(plain), "app/backup_2026.zip"),
        (str(plain), "app/dump.sql"), (str(plain), "app/gradebook_server.db.20260926"),
        (str(plain), "app/secrets.json"),
        #А это — законный код поставки, ловить его нельзя.
        (str(plain), "app/secrets_source.py"), (str(plain), "root/log.py"),
    ])
    assert "app/ok.py" not in bad, "обычный код с словом key — ложная тревога"
    assert "app/secrets_source.py" not in bad and "root/log.py" not in bad, bad
    assert len(bad) == 12, bad
