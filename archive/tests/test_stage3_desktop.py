"""Архив 15.10.2026: тесты выведенного sync/sync_engine.py (продукт его не зовёт с
25.09.2026, см. tests/test_legacy_sync_engine_fenced.py). Перенесены ДОСЛОВНО из
tests/test_stage3_desktop.py; не исполняются. Инварианты живого пути держат
desktop/local_mirror, desktop/desk_outbox и server/tests/test_sync*.py."""

def test_push_sends_new_style_grade_key(fresh_db):
    """Оценка за занятие уезжает на сервер уже с ключом по student_id."""
    sid = _seed_student()
    conn = DBManager.get_conn()
    cur = conn.cursor()
    DBManager.upsert_grade(cur, ("Иванова", "Мария", "L1", "5"))
    conn.commit()
    conn.close()

    sent = sync_engine._collect_grades()
    assert sent[0]["id"] == f"{sid}|L1", "push обязан слать ключ по id студента"


def test_push_falls_back_to_name_key_when_student_unknown(fresh_db):
    """Студент не опознан — уезжает СТАРЫЙ ключ, а не пустой/битый. Сервер его
    нормализует сам; терять оценку из-за отсутствия в справочнике нельзя."""
    conn = DBManager.get_conn()
    cur = conn.cursor()
    DBManager.upsert_grade(cur, ("Нет", "Такого", "L1", "4"))
    conn.commit()
    conn.close()

    sent = sync_engine._collect_grades()
    assert sent[0]["id"] == "Нет|Такого|L1"


