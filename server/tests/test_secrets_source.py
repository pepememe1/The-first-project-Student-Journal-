# -*- coding: utf-8 -*-
"""Секреты читаются ТОЛЬКО через `secrets_source`, и порядок источников не меняется.

Почему это сторож, а не «мы же договорились». Переход на хранилище — это ровно тот
случай, где полумера опаснее бездействия: если хотя бы один секрет продолжает
читаться из окружения, мы считаем, что убрали их с машины, а самый ценный ключ
лежит в `/proc/<pid>/environ` как лежал. Причём выглядит это как успех.

Проверяем СВОЙСТВО по тексту модулей, а не список известных мест: список — снимок
значения, он устаревает в день добавления следующего секрета.
"""

import os
import re

from app import secrets_source

SERVER_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_APP = os.path.join(SERVER_APP, "app")


def _python_files():
    for base, dirs, files in os.walk(SERVER_APP):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(base, name)


def _executable_text(path):
    """Текст файла без докстрингов и комментариев.

    Пояснения ОБЯЗАНЫ упоминать имена секретов — там написано, что это и почему
    так устроено. Сторож, спотыкающийся о собственные пояснения, заставляет
    вычищать именно их, то есть делает код хуже.
    """
    src = open(path, encoding="utf-8").read()
    src = re.sub(r'"""[\s\S]*?"""', '""', src)
    src = re.sub(r"'''[\s\S]*?'''", "''", src)
    return "\n".join(re.sub(r"#.*$", "", line) for line in src.split("\n"))


def _reads_environment_directly(text, name):
    """Читается ли секрет `name` напрямую из окружения в этом тексте.

    ⚠️ ОТДЕЛЬНАЯ функция, а не выражение внутри теста. Первая версия сторожа
    повторяла регулярку ДВАЖДЫ: один раз в проверке, второй — в «обратном ходе».
    Такой обратный ход сверяет копию с копией и не значит ничего: ошибись в
    регулярке — обе половины ошибутся одинаково и обе останутся зелёными. Это
    первая из трёх известных нам форм сторожа, который не может покраснеть.
    """
    return bool(re.search(
        r"(os\.environ(\.get)?\s*[\(\[]|os\.getenv\s*\()\s*['\"]"
        + re.escape(name) + r"['\"]", text))


def test_no_secret_is_read_straight_from_the_environment():
    offenders = []
    for path in _python_files():
        if os.path.basename(path) == "secrets_source.py":
            continue          # он и есть единственное законное место
        text = _executable_text(path)
        for name in secrets_source.SECRET_NAMES:
            if _reads_environment_directly(text, name):
                offenders.append(f"{os.path.relpath(path, SERVER_APP)}: {name}")
    assert not offenders, (
        "секрет читается в обход secrets_source — значит перенос в хранилище его "
        "не затронет, а мы будем считать, что затронул:\n  " + "\n  ".join(offenders)
    )


def test_the_guard_can_actually_fire():
    """Обратный ход: зовём ТУ ЖЕ функцию, которой пользуется проверка."""
    assert _reads_environment_directly('x = os.environ.get("GRADEBOOK_DB_KEY", "")',
                                       "GRADEBOOK_DB_KEY")
    assert _reads_environment_directly('x = os.getenv("GRADEBOOK_JWT_SECRET")',
                                       "GRADEBOOK_JWT_SECRET")
    assert _reads_environment_directly('x = os.environ["GRADEBOOK_S3_KEY"]',
                                       "GRADEBOOK_S3_KEY")
    #И не срабатывает на законном коде — иначе сторож кричал бы всегда.
    assert not _reads_environment_directly('secrets_source.get("GRADEBOOK_DB_KEY")',
                                           "GRADEBOOK_DB_KEY")


def test_storage_wins_over_environment(tmp_path, monkeypatch):
    """Порядок источников: хранилище перебивает переменную, а не наоборот.

    🔥 Обратный порядок был бы худшим из миров: забытая в окружении СТАРАЯ
    переменная тихо отменяла бы переход на хранилище, и сервер работал бы со
    старым ключом, пока мы уверены, что он взят из защищённого места.
    """
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / "gradebook-db-key").write_text("из-хранилища", encoding="utf-8")

    monkeypatch.setenv("GRADEBOOK_DB_KEY", "из-окружения")
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(creds))
    assert secrets_source.get("GRADEBOOK_DB_KEY") == "из-хранилища"
    assert secrets_source.source_of("GRADEBOOK_DB_KEY") == "учётные данные службы"

    monkeypatch.delenv("CREDENTIALS_DIRECTORY")
    assert secrets_source.get("GRADEBOOK_DB_KEY") == "из-окружения"


def test_file_variable_is_honoured(tmp_path, monkeypatch):
    secret = tmp_path / "jwt.txt"
    secret.write_text("  из-файла  \n", encoding="utf-8")
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setenv("GRADEBOOK_JWT_SECRET", "из-окружения")
    monkeypatch.setenv("GRADEBOOK_JWT_SECRET_FILE", str(secret))
    #Пробелы и перевод строки срезаем: файл, набранный редактором, почти всегда
    #заканчивается переводом строки, и ключ «отличался бы» на невидимый символ.
    assert secrets_source.get("GRADEBOOK_JWT_SECRET") == "из-файла"


def test_missing_file_does_not_silently_fall_back_to_nothing(tmp_path, monkeypatch, capsys):
    """Указали файл, а его нет — обязаны сказать вслух."""
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setenv("GRADEBOOK_DB_KEY_FILE", str(tmp_path / "нет-такого"))
    monkeypatch.setenv("GRADEBOOK_DB_KEY", "запасной")
    value = secrets_source.get("GRADEBOOK_DB_KEY")
    out = capsys.readouterr().out
    assert "GRADEBOOK_DB_KEY_FILE" in out, "молчаливый откат — так и теряют шифрование"
    assert value == "запасной"


def test_secret_values_never_appear_in_diagnostics(tmp_path, monkeypatch):
    """`source_of` отвечает про ИСТОЧНИК и не выдаёт значение."""
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setenv("GRADEBOOK_S3_SECRET", "очень-секретное-значение")
    assert "очень-секретное" not in secrets_source.source_of("GRADEBOOK_S3_SECRET")


def test_the_server_page_reports_only_source_labels(monkeypatch):
    """Страница «Сервер» показывает ИСТОЧНИК секрета, и только его.

    Экран безопасности — последнее место, где допустимо «на всякий случай»
    вывести значение. Проверяем, что набор возможных ответов закрытый: любая
    новая ветка в `source_of`, вернувшая что-то похожее на данные, покраснеет.
    """
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    for name in secrets_source.SECRET_NAMES:
        monkeypatch.setenv(name, "секретное-значение-" + name)

    allowed = {"учётные данные службы", "файл", "переменная окружения", "не задан"}
    sources = {name: secrets_source.source_of(name) for name in secrets_source.SECRET_NAMES}
    assert set(sources.values()) <= allowed, f"неожиданная подпись источника: {sources}"
    assert not any("секретное-значение" in v for v in sources.values())
