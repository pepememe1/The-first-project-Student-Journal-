"""
test_sync_lesson_extra.py — сборщик не выдаёт пустое `extra` за содержимое занятия
(находка ревью J03, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
`_collect_lessons` подставлял `"extra": {}` каждому занятию. Поле это десктопу
НЕИЗВЕСТНО — колонки `extra` в локальной таблице `lessons` нет вовсе, — а на сервере в
нём лежат даты пересдач №2–5, заполненные в вебе. Полный снимок, который уходит на
старте каждой сессии, объявлял пустой словарь новым содержимым, и сервер их затирал.

⚠️ Проверяется ОТСУТСТВИЕ ключа, а не пустота: отсутствующий ключ сервер не применяет
вовсе (тот же путь, по которому безопасно живёт `subgroup`), а присланная пустота
требует от него догадливости. Молчание честнее пустоты — и не зависит от того, доехала
ли до сервера парная правка `_KEEP_WHEN_BLANK`.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть `"extra": {}` в `sync_engine._collect_lessons` —
краснеет первый тест.
"""
from data.core import DBManager
from sync import sync_engine


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


def test_the_local_table_really_has_no_such_column(fresh_db):
    """Основание правки, а не украшение: появится колонка — сторож напомнит, что теперь
    поле можно возить по-настоящему, а не молчать о нём."""
    conn = DBManager.get_conn()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(lessons)").fetchall()}
    finally:
        conn.close()
    assert "extra" not in cols, (
        "в локальной таблице появилась колонка extra — значит десктоп теперь ЗНАЕТ это "
        "поле, и его надо возить содержимым, а не пропускать")


def test_the_fields_the_desktop_does_know_are_still_sent(fresh_db):
    """Обратная сторона: молчание про extra не должно превратиться в молчание про всё."""
    _add_lesson("LX2")
    row = next(r for r in sync_engine._collect_lessons() if r["id"] == "LX2")
    for field in ("group_name", "subject", "type", "number", "topic", "date",
                  "retake_date", "hour", "updated_at", "deleted", "year", "semester"):
        assert field in row, f"сборщик перестал отправлять {field}"
