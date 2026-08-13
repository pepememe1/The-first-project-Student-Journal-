"""test_data_key_recovery.py — что происходит, когда файл ключа шифрования НЕ ПОДОШЁЛ.

Почему это отдельный файл и почему вообще тест. Ключ шифрования ПДн создаётся сам при
первом запуске — это штатно. Но ровно тот же код выполняется и когда ключ БЫЛ, а
прочитать его не удалось: битый файл, или профиль перенесли на другую машину (защита
DPAPI привязана к учётной записи Windows). Тогда создаётся НОВЫЙ ключ, и всё, что было
зашифровано прежним, больше не расшифруется — навсегда.

Раньше обе ветки молчали одинаково (`except Exception: pass`), и отличить катастрофу от
обычного первого запуска было нельзя ни человеку, ни по логу. Поведение мы не меняли
(отказываться запускаться из-за битого файла у того, кто ещё ничего не шифровал, — хуже),
но след обязан остаться. Эти тесты проверяют именно НАЛИЧИЕ следа и его отсутствие там,
где следа быть не должно, — иначе предупреждение либо пропадёт при следующей правке, либо
начнёт кричать на каждом чистом запуске и его перестанут читать.
"""
import base64
import logging

import pytest

from data import security


class _Collector(logging.Handler):
    """Собирает записи логгера в список.

    ⚠️ Почему НЕ `caplog`. Логгеры проекта (`log.get`) заводят свой обработчик и ставят
    `propagate = False`, а `caplog` слушает КОРНЕВОЙ логгер — сообщение исправно уходит в
    stderr, но тест его не видит. Погасить это фикстурой не выйдет: `log.get()` зовётся
    ВНУТРИ проверяемой функции, то есть уже после фикстуры, и снова выставляет
    `propagate = False`. Первая версия теста из-за этого проходила в общем прогоне (там
    логгер успевал настроиться раньше) и падала в одиночку — то есть была зависимой от
    порядка, а такой тест не доказывает ничего. Свой обработчик от порядка не зависит."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(autouse=True)
def _isolated_key(tmp_path, monkeypatch):
    """Свой файл ключа на каждый тест + сброшенный кэш модуля.

    Без сброса `_DATA_KEY_CACHE` второй тест получил бы ключ первого и не дошёл бы до
    разбираемой ветки вовсе — то есть был бы зелёным, ничего не проверив."""
    key_file = tmp_path / "data.key"
    monkeypatch.setattr(security, "_data_key_path", lambda: str(key_file))
    monkeypatch.setattr(security, "_legacy_data_key_path", lambda: str(key_file))
    monkeypatch.setattr(security, "_DATA_KEY_CACHE", None)
    yield key_file
    monkeypatch.setattr(security, "_DATA_KEY_CACHE", None)


@pytest.fixture
def sec_log():
    """Записи логгера безопасности за время теста."""
    collector = _Collector()
    logger = logging.getLogger("gradebook.security")
    logger.addHandler(collector)
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    yield collector
    logger.removeHandler(collector)
    logger.setLevel(old_level)


def _errors(collector: _Collector) -> list:
    return [r.getMessage() for r in collector.records if r.levelno >= logging.ERROR]


def test_unreadable_key_file_is_reported_loudly(_isolated_key, sec_log):
    """Ключ БЫЛ и не подошёл → создаётся новый, но в логе обязана быть ошибка.

    Это самый дорогой отказ в модуле: данные не пропадают физически, но становятся
    нечитаемыми, и без сообщения человек узнает об этом только по пустым экранам."""
    #Мусор: не 32 байта под DPAPI и не base64 длиной 32. Литерал ASCII — в bytes-строку
    #кириллица не кладётся (SyntaxError), а смысл здесь несёт длина, а не текст.
    _isolated_key.write_bytes(b"\x00\x01\x02 not-a-key-and-not-valid-base64")

    key = security.get_data_key()

    assert len(key) == 32, "новый ключ всё равно обязан быть выдан — журнал должен открыться"
    assert _errors(sec_log), (
        "файл ключа не подошёл, а в логе НИ ОДНОЙ ошибки — ровно тот тихий отказ, "
        "из-за которого потерю данных нельзя было объяснить")


def test_first_run_does_not_cry_wolf(_isolated_key, sec_log):
    """ОБРАТНЫЙ тест: файла ключа нет вовсе — это штатный первый запуск, и ошибки быть
    НЕ ДОЛЖНО.

    Без этой проверки предыдущая зелёная при реализации «ругаться всегда», а сторож,
    срабатывающий на каждом чистом запуске, перестают читать — и он пропустит настоящий
    случай, ради которого заводился."""
    assert not _isolated_key.exists()

    key = security.get_data_key()

    assert len(key) == 32
    assert not _errors(sec_log), (
        f"чистый первый запуск не должен давать ошибок в логе: {_errors(sec_log)}")


def test_legacy_plaintext_key_is_migrated_without_alarm(_isolated_key, sec_log):
    """Старый формат (ключ base64 открытым текстом) обязан МИГРИРОВАТЬ, а не считаться
    негодным: иначе у всех, кто обновился со старой версии, данные «пропали бы» разом."""
    legacy = b"K" * 32
    _isolated_key.write_bytes(base64.urlsafe_b64encode(legacy))

    key = security.get_data_key()

    assert key == legacy, "прежний ключ обязан быть подхвачен, а не заменён новым"
    assert not _errors(sec_log)
