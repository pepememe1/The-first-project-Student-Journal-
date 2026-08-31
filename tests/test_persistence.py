"""
test_persistence.py — Персистентность по действию: выставленная оценка попадает на
диск СРАЗУ и переживает пересоздание соединения (раньше жила только в памяти до
кнопки «Сохранить»).

⚠️ Переписано 31.08.2026 без `core.GradeBook`. Прежняя версия заводила журнал этим
классом и перечитывала его — но класс мёртв в продукте (ни одного вызывающего вне
тестов) и удалён тем же заходом. Проверяемое свойство от него не зависело ни разу:
речь про ХРАНИЛИЩЕ — `upsert_grade` + `commit` обязаны пережить закрытие соединения.
Оценку на живом пути пишет серверный `POST /web/teacher/grade` (внутри программы — на
локальном сервере), а сюда она приезжает синком.
"""
from data.core import DBManager

G, S = "ИС-21", "Математика"


def _persist_grade(student_f, student_n, key, val):
    """Запись оценки «как в продукте»: сразу на диск, отдельной транзакцией."""
    conn = DBManager.get_conn()
    cur = conn.cursor()
    DBManager.upsert_grade(cur, (student_f, student_n, key, val))
    conn.commit()
    conn.close()


def _read_records(student_f, student_n) -> dict:
    """Оценки студента ИЗ БАЗЫ, новым соединением — то есть точно не из памяти."""
    DBManager._init_sqlite_tables()
    conn = DBManager.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT lesson_id, grade FROM grades "
                "WHERE student_f=? AND student_n=? AND COALESCE(deleted,0)=0",
                (student_f, student_n))
    out = {lid: g for lid, g in cur.fetchall()}
    conn.close()
    return out


def test_grade_survives_journal_reload(fresh_db):
    _persist_grade("Иванов", "Иван", "L1", "5")
    assert _read_records("Иванов", "Иван").get("L1") == "5", \
        "оценка должна сохраниться сразу, а не потеряться до «Сохранить»"


def test_retake_key_persists_separately(fresh_db):
    """Пересдача хранится под отдельным ключом lesson_id+'_retake' и не затирает
    основную оценку — обе переживают перечитывание."""
    _persist_grade("Петров", "Пётр", "L1", "2 (Не зачтено)")
    _persist_grade("Петров", "Пётр", "L1_retake", "4 (Зачтено)")

    recs = _read_records("Петров", "Пётр")
    assert recs.get("L1") == "2 (Не зачтено)"
    assert recs.get("L1_retake") == "4 (Зачтено)"
