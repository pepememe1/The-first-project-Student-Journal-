"""test_device_key_reason.py — ПОЧЕМУ локальные базы сейчас не шифруются.

До 15.10.2026 пустой ключ значил для всех одно, и журнал писал «драйвера sqlcipher3
нет» даже когда драйвер был, а под DPAPI не расшифровался сам ключ. Человек работал сеанс
с ФИО открытым текстом на диске, а причина в журнале вела не туда.
"""
import pytest

from data import device_key, security


@pytest.fixture()
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(device_key, "_cache", None)
    monkeypatch.setattr(device_key, "_reason", "")
    path = tmp_path / "local_app.key"
    import app_paths
    monkeypatch.setattr(app_paths, "data_file", lambda name: str(path))
    return path


def test_no_driver_is_named_as_such(fresh, monkeypatch):
    monkeypatch.setattr(device_key, "driver_available", lambda: False)
    assert device_key.db_key() == ""
    assert device_key.encryption_off_reason() == "no-driver"


def test_unreadable_key_is_named_and_the_key_file_is_left_alone(fresh, monkeypatch):
    fresh.write_bytes(b"\x01\x02 not dpapi")
    monkeypatch.setattr(device_key, "driver_available", lambda: True)
    monkeypatch.setattr(security, "os_unprotect", lambda blob: b"")
    assert device_key.db_key() == ""
    assert device_key.encryption_off_reason() == "key-unreadable"
    #Новый ключ поверх старого заводить нельзя — он не подошёл бы к уже зашифрованной базе.
    assert fresh.read_bytes() == b"\x01\x02 not dpapi"


def test_working_key_means_no_reason(fresh, monkeypatch):
    fresh.write_bytes(b"blob")
    monkeypatch.setattr(device_key, "driver_available", lambda: True)
    monkeypatch.setattr(security, "os_unprotect", lambda blob: b"ab" * 32)
    assert device_key.db_key() == "ab" * 32
    assert device_key.encryption_off_reason() == ""
