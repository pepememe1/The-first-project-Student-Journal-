"""
test_grade_value_validation.py — что вообще разрешено класть в поле оценки (3.7.6).

До этого `POST /web/teacher/grade` писал значение КАК ЕСТЬ: проверялись права, группа,
занятие и период — всё, кроме самой оценки. То есть в журнал попадало любое, что
прислал клиент: «Ништяк», пустая строка в 500 символов, HTML. Крашей это не давало
(средний балл просто игнорирует нераспознанное), и потому дефект был незаметен — но
цена у него отложенная: мусор доезжает до отчёта куратора, xlsx-выгрузки и родителя,
а строка, начинающаяся с «Н», ещё и считается ЗАВАЛЕННОЙ работой (`grading.is_failed`),
то есть «Ништяк» превращал студента в должника.
"""
from conftest import make_admin, make_teacher, assign_teacher

A = "/web/teacher/grade"


def _setup(client):
    admin = make_admin(client)
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L1", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    teach = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")
    return teach


def _put(client, teach, value):
    return client.post(A, json={"lesson_id": "L1", "surname": "Иванова",
                                "name": "Мария", "grade": value}, headers=teach)


def test_garbage_grade_is_rejected(client):
    """🔥 Главное: произвольная строка в поле оценки — отказ, а не запись."""
    teach = _setup(client)
    assert _put(client, teach, "Ништяк").status_code == 400


def test_overlong_grade_is_rejected(client):
    """Длина тоже проверяется: поле уезжает в xlsx и в отчёт куратора."""
    teach = _setup(client)
    assert _put(client, teach, "5" * 500).status_code == 400


def test_all_legitimate_values_still_pass(client):
    """Обратная сторона — важнее первой. Проверка НЕ должна отрезать ни одну живую
    шкалу: у преподавателя может стоять 100-балльная, буквенная или зачёт/незачёт,
    а посещаемость — это отдельные метки. Слишком строгая проверка тут хуже, чем её
    отсутствие: она молча ломает работу тому, кто ни в чём не виноват."""
    teach = _setup(client)
    for value in ("5", "2", "87", "A", "F", "Зачтено", "Не зачтено",
                  "Н", "Б", "О", "✓", ""):
        r = _put(client, teach, value)
        assert r.status_code == 200, f"законное значение «{value}» отвергнуто: {r.text}"
