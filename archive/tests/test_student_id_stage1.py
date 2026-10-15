"""Архив 15.10.2026: тесты выведенного sync/sync_engine.py (продукт его не зовёт с
25.09.2026, см. tests/test_legacy_sync_engine_fenced.py). Перенесены ДОСЛОВНО из
tests/test_student_id_stage1.py; не исполняются. Инварианты живого пути держат
desktop/local_mirror, desktop/desk_outbox и server/tests/test_sync*.py."""

def test_sync_carries_student_id_both_ways(fresh_db):
    """Синк возит id на сервер и принимает обратно — иначе поле осталось бы локальным
    украшением и бэкофилл на сервере не с чем было бы сверять."""
    sid = _seed_student()
    conn = DBManager.get_conn()
    cur = conn.cursor()
    DBManager.upsert_grade(cur, ("Иванова", "Мария", "L1", "5"))
    conn.commit()
    conn.close()

    collected = sync_engine._collect_grades()
    assert collected[0]["student_id"] == sid, "push обязан везти id"

    #приём: строка с сервера с id, которого локально не было
    sync_engine._merge_grades([{
        "student_f": "Иванова", "student_n": "Мария", "lesson_id": "L9",
        "grade": "4", "updated_at": "2030-01-01T00:00:00+00:00", "device": "web",
        "deleted": False, "student_id": sid,
    }])
    got = [r for r in _grade_rows() if r["lesson_id"] == "L9"]
    assert got and got[0]["student_id"] == sid, "pull обязан сохранять id"


def test_old_client_payload_without_id_is_accepted(fresh_db):
    """Обратная совместимость: клиент старой версии шлёт оценку БЕЗ поля — принимаем,
    а не падаем. Иначе обновление сервера положило бы синк всем непроапгрейженным ПК."""
    sync_engine._merge_grades([{
        "student_f": "Сидоров", "student_n": "Пётр", "lesson_id": "L5",
        "grade": "3", "updated_at": "2030-01-01T00:00:00+00:00", "device": "pc-old",
        "deleted": False,
    }])
    got = [r for r in _grade_rows() if r["lesson_id"] == "L5"]
    assert got and got[0]["student_id"] == ""


