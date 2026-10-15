"""
test_term_grades.py — Итоговые оценки за семестр (промежуточная аттестация) на десктопе:
локальная запись/чтение, round-trip через синк (collect/apply), надгробия, экспорт.
"""
from data.core import DBManager

SUBJ = "Математика"
YEAR, SEM = "2025/2026", 1


def test_set_and_get_term_grade(fresh_db):
    DBManager.set_term_grade("Иванов", "Иван", SUBJ, YEAR, SEM, "5", "экзамен")
    tg = DBManager.get_term_grades(SUBJ, YEAR, SEM)
    assert tg["Иванов|Иван"]["grade"] == "5"
    assert tg["Иванов|Иван"]["form"] == "экзамен"


#⚠️ ЗДЕСЬ БЫЛ `test_vedomost_xlsx_bytes` (удалён 01.09.2026). Он проверял, что ведомость
#собирается в непустой xlsx, — но собирал её МЁРТВОЙ копией `data/exports.py`: полным
#дублем `server/app/xlsx_export.py`, оставшимся от нативного журнала и не имевшим в
#продукте ни одного вызывающего. То есть проверка была, а защиты не было: сломай живой
#модуль — тест остался бы зелёным.
#Живой путь (`GET /web/teacher/vedomost` → `xlsx_export.build_vedomost_xlsx`) покрыт
#`server/tests/test_vedomost.py`. Сам `data/exports.py` удалён вместе с этим тестом.
