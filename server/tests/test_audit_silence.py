# -*- coding: utf-8 -*-
"""
test_audit_silence.py — 🔒 ОТКАЗ ЖУРНАЛА БЕЗОПАСНОСТИ НЕ ИМЕЕТ ПРАВА БЫТЬ ТИХИМ.

`audit.log` намеренно не бросает исключений: сбой записи следа не должен ронять действие
пользователя. Но до 01.09.2026 он ещё и МОЛЧАЛ — `except Exception: pass`. Следствие:
миграция не доехала, диск полон или база в read-only → продукт работает как ни в чём не
бывало, а следа больше нет. Узнать об этом можно было ровно тогда, когда след
понадобится: при разборе инцидента или при подтверждении аварийного сброса второго
фактора.

Здесь проверяется, что отказ ГРОМКИЙ — и ровно один раз за запуск (иначе при отказавшей
базе строка на каждое действие превратит лог в шум, и его перестанут читать).
"""
import logging

from app import audit


class _BrokenDB:
    """База, которая падает на записи. Ровно тот случай, который прятался."""

    def add(self, *a, **kw):
        raise RuntimeError("no such table: audit_events")

    def commit(self):
        raise RuntimeError("no such table: audit_events")

    def rollback(self):
        pass


def test_audit_failure_is_reported_once(caplog):
    """Обратный ход: вернуть `except Exception: pass` — тест краснеет на пустом логе."""
    audit._audit_write_failed = False
    with caplog.at_level(logging.ERROR, logger="gradebook.audit"):
        audit.log(_BrokenDB(), actor="admin", action="mfa.reset")
    assert any("аудит" in r.message.lower() for r in caplog.records), (
        "журнал безопасности перестал писаться, и об этом никто не узнал")

    #Второй отказ молчит: шум в логе хуже, чем одна внятная строка.
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="gradebook.audit"):
        audit.log(_BrokenDB(), actor="admin", action="mfa.reset")
    assert not caplog.records, "строка на каждое действие — лог перестанут читать"


def test_audit_failure_never_breaks_the_action():
    """Главное свойство не изменилось: сбой журнала не роняет то, что делал человек."""
    audit._audit_write_failed = False
    audit.log(_BrokenDB(), actor="admin", action="grade.set")   # не бросает — и всё
