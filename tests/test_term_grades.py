"""
test_term_grades.py — Итоговые оценки за семестр (промежуточная аттестация) на десктопе:
локальная запись/чтение, round-trip через синк (collect/apply), надгробия, экспорт.
"""
from data.core import DBManager
from sync import sync_engine

SUBJ = "Математика"
YEAR, SEM = "2025/2026", 1


def test_set_and_get_term_grade(fresh_db):
    DBManager.set_term_grade("Иванов", "Иван", SUBJ, YEAR, SEM, "5", "экзамен")
    tg = DBManager.get_term_grades(SUBJ, YEAR, SEM)
    assert tg["Иванов|Иван"]["grade"] == "5"
    assert tg["Иванов|Иван"]["form"] == "экзамен"


def test_empty_grade_is_tombstone(fresh_db):
    """Пустая оценка = снятие (надгробие): в выборке её нет, но в collect она уезжает."""
    DBManager.set_term_grade("Петров", "Пётр", SUBJ, YEAR, SEM, "4", "экзамен")
    DBManager.set_term_grade("Петров", "Пётр", SUBJ, YEAR, SEM, "", "экзамен")
    assert "Петров|Пётр" not in DBManager.get_term_grades(SUBJ, YEAR, SEM)
    tomb = [t for t in sync_engine.collect_local()["term_grades"]
            if t["student_f"] == "Петров" and t["deleted"] is True]
    assert tomb, "надгробие итоговой оценки должно уйти на сервер"


def test_collect_local_includes_term_grades(fresh_db):
    DBManager.set_term_grade("Сидоров", "Сидор", SUBJ, YEAR, SEM, "3", "зачёт")
    snap = sync_engine.collect_local()
    row = [t for t in snap["term_grades"] if t["id"] == "Сидоров|Сидор|Математика|2025/2026|1"]
    assert row and row[0]["grade"] == "3" and row[0]["semester"] == 1


def test_apply_remote_term_grade(fresh_db):
    """Итоговая оценка с сервера (свежая) применяется локально."""
    sync_engine.apply_remote({"term_grades": [{
        "id": "Кузнецов|Анна|Математика|2025/2026|1", "student_f": "Кузнецов",
        "student_n": "Анна", "subject": SUBJ, "year": YEAR, "semester": SEM,
        "grade": "Зачтено", "form": "зачёт",
        "updated_at": "2099-01-01T00:00:00+00:00", "deleted": False}]})
    tg = DBManager.get_term_grades(SUBJ, YEAR, SEM)
    assert tg["Кузнецов|Анна"]["grade"] == "Зачтено"


def test_remote_tombstone_removes_term_grade(fresh_db):
    """Надгробие итоговой оценки с сервера (свежее) снимает локальную оценку."""
    DBManager.set_term_grade("Смирнов", "Олег", SUBJ, YEAR, SEM, "5", "экзамен")
    sync_engine.apply_remote({"term_grades": [{
        "id": "Смирнов|Олег|Математика|2025/2026|1", "student_f": "Смирнов",
        "student_n": "Олег", "subject": SUBJ, "year": YEAR, "semester": SEM,
        "grade": "", "form": "экзамен",
        "updated_at": "2099-01-01T00:00:00+00:00", "deleted": True}]})
    assert "Смирнов|Олег" not in DBManager.get_term_grades(SUBJ, YEAR, SEM)


def test_stale_remote_does_not_override_local(fresh_db):
    """Старая серверная метка НЕ затирает более свежую локальную правку (LWW)."""
    DBManager.set_term_grade("Волков", "Илья", SUBJ, YEAR, SEM, "5", "экзамен")
    sync_engine.apply_remote({"term_grades": [{
        "id": "Волков|Илья|Математика|2025/2026|1", "student_f": "Волков",
        "student_n": "Илья", "subject": SUBJ, "year": YEAR, "semester": SEM,
        "grade": "2", "form": "экзамен",
        "updated_at": "1999-01-01T00:00:00+00:00", "deleted": False}]})
    assert DBManager.get_term_grades(SUBJ, YEAR, SEM)["Волков|Илья"]["grade"] == "5"


def test_vedomost_xlsx_bytes():
    """Экспорт ведомости в xlsx отдаёт непустой файл."""
    from data import exports
    rows = [{"surname": "Иванов", "name": "Иван", "patronymic": "Петрович", "grade": "5"}]
    data = exports.build_vedomost_xlsx("ИС-21", SUBJ, {"year": YEAR, "semester": SEM},
                                       "экзамен", rows, teacher="Тестов Т.Т.")
    assert data[:2] == b"PK" and len(data) > 500   #xlsx — это zip (PK)
