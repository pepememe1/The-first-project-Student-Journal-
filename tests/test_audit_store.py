"""
test_audit_store.py — журнал аудита в зашифрованном хранилище (152-ФЗ).

Проверяем: запись/чтение событий идут через локальный kv (не плейнтекст-файл),
кольцевой буфер ограничивает размер, троттлинг переживает «перезапуск», и разовая
миграция переносит старый audit.log/login_throttle.json внутрь и удаляет файлы.

Используем fresh_db (conftest) — временный профиль и инициализированная БД.
"""
import os
import json

import pytest

import app_paths
from data import audit


@pytest.fixture(autouse=True)
def _reset_migration_flag():
    """Перед каждым тестом сбрасываем флаг миграции — она разовая на процесс."""
    audit._migrated = False
    yield


def test_log_and_read_roundtrip(fresh_db):
    audit.log_event("login_ok", "ivanov", "роль=student")
    audit.log_event("password_change", "admin", "")
    events = audit.read_events()
    assert any("login_ok" in e and "ivanov" in e for e in events)
    assert any("password_change" in e for e in events)
    #формат записи — табличный: ts \t event \t actor \t detail
    assert events[0].count("\t") == 3


def test_no_plaintext_file_created(fresh_db):
    """Новый журнал НЕ должен создавать открытый audit.log на диске (152-ФЗ)."""
    audit.log_event("login_fail", "hacker", "")
    assert not os.path.exists(app_paths.data_file("audit.log"))


def test_ring_buffer_cap(fresh_db, monkeypatch):
    """Журнал не растёт бесконечно — держим последние _AUDIT_CAP записей.

    Cap на время теста понижаем (иначе тысяча Fernet-записей — это медленно)."""
    monkeypatch.setattr(audit, "_AUDIT_CAP", 20)
    for i in range(70):
        audit.log_event("evt", "u", str(i))
    events = audit.read_events(limit=200)
    assert len(events) == 20
    #последняя запись — самая свежая
    assert events[-1].endswith("69")


def test_throttle_persists(fresh_db):
    """Состояние блокировок хранится в БД и читается обратно."""
    login = "bruteforce"
    for _ in range(audit.MAX_FAILS):
        audit.register_failure(login)
    locked, left = audit.is_locked(login)
    assert locked and left > 0
    #успешный вход сбрасывает счётчик
    audit.register_success(login)
    locked2, _ = audit.is_locked(login)
    assert not locked2


def test_migration_imports_and_removes_legacy(fresh_db):
    """Старый audit.log и login_throttle.json переносятся внутрь и удаляются."""
    legacy_audit = app_paths.data_file("audit.log")
    legacy_throttle = app_paths.data_file("login_throttle.json")
    with open(legacy_audit, "w", encoding="utf-8") as f:
        f.write("2025-01-01T10:00:00\tlogin_ok\tlegacy_user\tроль=admin\n")
    with open(legacy_throttle, "w", encoding="utf-8") as f:
        json.dump({"olduser": {"fails": 2, "locked_until": 0.0}}, f)

    audit._migrated = False
    events = audit.read_events()          # первое обращение запускает миграцию

    assert any("legacy_user" in e for e in events)
    assert not os.path.exists(legacy_audit)
    assert not os.path.exists(legacy_throttle)
    #перенесённый троттлинг доступен
    data = audit._load_throttle()
    assert "olduser" in data
