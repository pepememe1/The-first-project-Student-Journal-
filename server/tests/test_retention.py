"""test_retention.py — политика хранения: что уходит по сроку, а что НЕ имеет права уйти.

Проверяем не «функция вызвалась», а СВОЙСТВА: свежее остаётся, старое исчезает, живое не
трогается ни при каких обстоятельствах. Иначе тест был бы зелёным и при реализации
«удалять всё» — то есть при худшей из возможных ошибок в этом модуле.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import retention
from app.db import Base, SessionLocal, engine
from app.models import (AuthSession, Grade, Message, MessageEdit, NotifyEvent,
                        Reminder)


@pytest.fixture()
def db_session():
    """Прямая сессия к чистой тестовой базе: политику хранения проверяем на уровне
    таблиц, HTTP тут ничего не добавляет и только замедлил бы прогон."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    retention._last_run = None
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _fresh(db):
    """Сбрасываем метку «уже убирались сегодня» — иначе тесты зависели бы от порядка."""
    retention._last_run = None
    return db


# ── Надгробия ──────────────────────────────────────────────────────────────────────
def test_old_tombstone_is_purged_but_fresh_one_survives(db_session):
    db = _fresh(db_session)
    db.add(Grade(id="g:old", updated_at=_ago(400), deleted=True))
    db.add(Grade(id="g:recent", updated_at=_ago(10), deleted=True))
    db.commit()

    retention.purge_tombstones(db)
    db.commit()

    assert db.query(Grade).filter(Grade.id == "g:old").first() is None
    assert db.query(Grade).filter(Grade.id == "g:recent").first() is not None, (
        "свежее надгробие удалять НЕЛЬЗЯ: ПК, который его ещё не забрал, вернёт строку живой")


def test_live_row_is_never_touched_however_old(db_session):
    """Самое важное свойство модуля. Оценка десятилетней давности — это история
    успеваемости, а не мусор: её удаление стёрло бы диплом человека."""
    db = _fresh(db_session)
    db.add(Grade(id="g:ancient", updated_at=_ago(4000), deleted=False, grade="5"))
    db.commit()

    retention.purge_tombstones(db)
    db.commit()

    row = db.query(Grade).filter(Grade.id == "g:ancient").first()
    assert row is not None and row.grade == "5", (
        "уборка тронула ЖИВУЮ строку — это потеря данных, а не политика хранения")


def test_row_without_timestamp_is_not_purged(db_session):
    """Пустая метка — это «не знаем, когда», а не «очень давно». Строковое сравнение
    поставило бы '' раньше любой даты, и такие строки вымело бы первым же прогоном."""
    db = _fresh(db_session)
    db.add(Grade(id="g:nots", updated_at="", deleted=True))
    db.commit()

    retention.purge_tombstones(db)
    db.commit()

    assert db.query(Grade).filter(Grade.id == "g:nots").first() is not None


def test_purge_is_capped_per_run(db_session, monkeypatch):
    """Первая уборка на копившейся годами базе идёт ВНУТРИ чужого HTTP-запроса —
    потолок обязателен, остаток уедет следующим прогоном."""
    db = _fresh(db_session)
    monkeypatch.setattr(retention, "MAX_ROWS_PER_TABLE", 3)
    for i in range(10):
        db.add(Grade(id=f"g:cap{i}", updated_at=_ago(400), deleted=True))
    db.commit()

    got = retention.purge_tombstones(db)
    db.commit()
    assert got.get("grades") == 3
    assert db.query(Grade).filter(Grade.deleted == True).count() == 7  # noqa: E712


# ── Сессии, уведомления, напоминания ───────────────────────────────────────────────
def test_old_sessions_go_and_recent_stay(db_session):
    db = _fresh(db_session)
    db.add(AuthSession(jti="s:old", login="a", issued_at=_ago(200)))
    db.add(AuthSession(jti="s:new", login="a", issued_at=_ago(1)))
    db.commit()

    retention.purge_sessions(db)
    db.commit()

    assert db.query(AuthSession).filter(AuthSession.jti == "s:old").first() is None
    assert db.query(AuthSession).filter(AuthSession.jti == "s:new").first() is not None


def test_unread_notification_lives_longer_than_read_one(db_session):
    """Прочитанное — история, непрочитанное — ещё не доставленное человеку сообщение.
    Сроки у них разные намеренно."""
    db = _fresh(db_session)
    db.add(NotifyEvent(id="n:read", login="a", created_at=_ago(120), read_at=_ago(119)))
    db.add(NotifyEvent(id="n:unread", login="a", created_at=_ago(120), read_at=""))
    db.commit()

    retention.purge_notifications(db)
    db.commit()

    assert db.query(NotifyEvent).filter(NotifyEvent.id == "n:read").first() is None
    assert db.query(NotifyEvent).filter(NotifyEvent.id == "n:unread").first() is not None


def test_pending_reminder_is_never_purged_by_age(db_session):
    """Напоминание, которое ЕЩЁ НЕ СРАБОТАЛО, — это обещание человеку. Его вполне могли
    поставить на следующий семестр, и «оно старое» тут не аргумент."""
    db = _fresh(db_session)
    db.add(Reminder(login="a", text="сдать отчёт", remind_at=_ago(-200),
                    created_at=_ago(200), fired_at=""))
    db.add(Reminder(login="a", text="уже напомнили", remind_at=_ago(200),
                    created_at=_ago(200), fired_at=_ago(200)))
    db.commit()

    retention.purge_reminders(db)
    db.commit()

    rows = db.query(Reminder).all()
    assert len(rows) == 1 and rows[0].fired_at == "", (
        "сработавшее должно уйти, ожидающее — остаться")


# ── Мессенджер ─────────────────────────────────────────────────────────────────────
def test_deleted_message_keeps_its_row_but_loses_the_text(db_session):
    """Строку-надгробие удалять нельзя: на неё ссылаются ответы и по ней рисуется
    «сообщение удалено». А текст через полгода не нужен уже никому, включая модерацию."""
    db = _fresh(db_session)
    db.add(Message(conversation_id="c1", sender_id="u1", body="старый текст",
                   created_at=_ago(400), deleted_at=_ago(400)))
    db.add(Message(conversation_id="c1", sender_id="u1", body="живое сообщение",
                   created_at=_ago(400), deleted_at=""))
    db.commit()

    retention.blank_deleted_bodies(db)
    db.commit()

    dead = db.query(Message).filter(Message.deleted_at != "").first()
    alive = db.query(Message).filter(Message.deleted_at == "").first()
    assert dead is not None and dead.body == ""
    assert alive.body == "живое сообщение", "живое сообщение трогать нельзя"


def test_old_edit_history_is_purged(db_session):
    db = _fresh(db_session)
    db.add(MessageEdit(message_id=1, body_before="было", edited_at=_ago(400)))
    db.add(MessageEdit(message_id=2, body_before="недавно", edited_at=_ago(5)))
    db.commit()

    retention.purge_message_edits(db)
    db.commit()

    left = db.query(MessageEdit).all()
    assert len(left) == 1 and left[0].body_before == "недавно"


# ── Журнал безопасности и оркестрация ──────────────────────────────────────────────
def test_audit_events_are_never_touched(db_session):
    """Прямой инвариант: журнал безопасности — доказательная база при разборе инцидента,
    а инцидент обнаруживают позже, чем он случился. Модуль не имеет права его знать."""
    import inspect
    src = inspect.getsource(retention)
    assert "AuditEvent" not in src and "audit_events" not in src.replace(
        "`audit_events`", ""), "в политику хранения просочился журнал безопасности"


def test_run_all_survives_a_failing_step(db_session, monkeypatch):
    """Падение одной уборки не отменяет остальные и не роняет запрос — шаги удаляют
    РАЗНЫЕ данные по РАЗНЫМ основаниям, транзакционной связи между ними нет."""
    db = _fresh(db_session)
    db.add(Grade(id="g:x", updated_at=_ago(400), deleted=True))
    db.commit()

    def _boom(_db, **_kw):
        raise RuntimeError("таблица занята")

    monkeypatch.setattr(retention, "purge_sessions", _boom)
    report = retention.run_all(db)

    assert "ошибка" in str(report.get("sessions", "")), report
    assert report.get("tombstones", {}).get("grades") == 1, (
        "упавший шаг утащил за собой уже выполненный")


def test_maybe_run_is_throttled_to_once_a_day(db_session, monkeypatch):
    db = _fresh(db_session)
    calls = []
    monkeypatch.setattr(retention, "run_all", lambda _db: calls.append(1) or {})
    assert retention.maybe_run(db) is not None
    assert retention.maybe_run(db) is None, "уборка пошла по второму кругу в тот же день"
    assert len(calls) == 1


def test_composite_primary_key_is_refused_loudly(db_session):
    """Сегодня составных ключей нет ни у одной таблицы. Появится — выборка по ПЕРВОЙ
    колонке ключа совпала бы с чужими строками, и уборка удалила бы не то, причём молча.
    Лучше громкий отказ одной уборки."""
    import pytest as _pytest
    from sqlalchemy import Column, String
    from app.db import Base

    class _Composite(Base):
        __tablename__ = "retention_composite_probe"
        a = Column(String, primary_key=True)
        b = Column(String, primary_key=True)
        updated_at = Column(String, default="")

    with _pytest.raises(RuntimeError, match="составной"):
        retention._delete_capped(db_session, _Composite, _Composite.updated_at != "")


def test_retention_has_a_caller_in_the_product():
    """🔥 Возражение Полковника, и оно точное: у `reconcile` сегодня сторож на вызывающего
    завели, а у уборки — забыли, хотя дефект ровно тот же и цена та же.

    Удали вызов из `/me/events` (или вынеси эндпоинт в другой роутер при следующем
    разрезе) — все остальные тесты этого файла останутся зелёными, а политика хранения не
    выполнится ни разу. Заметить это можно будет только по размеру базы через полгода.

    Проверяем ФАКТ вызова из рабочего кода, а не поведение `maybe_run` (оно покрыто выше и
    было бы покрыто даже у мёртвого модуля — именно так и выглядит эта ошибка).
    """
    import inspect
    from app.routers import me as me_router

    src = inspect.getsource(me_router)
    assert "retention" in src and "maybe_run(" in src, (
        "политика хранения осиротела: в продукте не осталось ни одного вызывающего")
    #И он обязан стоять на пути ЗАПРОСА, а не в неиспользуемой функции.
    assert "maybe_run(" in inspect.getsource(me_router.list_events)
