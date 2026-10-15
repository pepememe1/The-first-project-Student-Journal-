"""Архив 15.10.2026: тесты выведенного sync/sync_engine.py (продукт его не зовёт с
25.09.2026, см. tests/test_legacy_sync_engine_fenced.py). Перенесены ДОСЛОВНО из
tests/test_sync_lesson_extra.py; не исполняются. Инварианты живого пути держат
desktop/local_mirror, desktop/desk_outbox и server/tests/test_sync*.py."""

def _add_lesson(lid: str):
    conn = DBManager.get_conn()
    conn.execute("INSERT OR REPLACE INTO lessons (id,group_name,subject,type,number,topic,"
                 "date,updated_at,deleted) VALUES (?,'К-101','Физика','Практика',1,'Тема',"
                 "'2026-09-01','2026-09-01T00:00:00+00:00',0)", (lid,))
    conn.commit()
    conn.close()


def test_collector_never_sends_a_field_the_desktop_cannot_know(fresh_db):
    _add_lesson("LX1")
    rows = sync_engine._collect_lessons()
    row = next(r for r in rows if r["id"] == "LX1")
    assert "extra" not in row, (
        "снимок занятия снова несёт extra — пустым он затирает даты пересдач, "
        f"заполненные в вебе: {row.get('extra')!r}")


def test_the_fields_the_desktop_does_know_are_still_sent(fresh_db):
    """Обратная сторона: молчание про extra не должно превратиться в молчание про всё."""
    _add_lesson("LX2")
    row = next(r for r in sync_engine._collect_lessons() if r["id"] == "LX2")
    for field in ("group_name", "subject", "type", "number", "topic", "date",
                  "retake_date", "hour", "updated_at", "deleted", "year", "semester"):
        assert field in row, f"сборщик перестал отправлять {field}"


