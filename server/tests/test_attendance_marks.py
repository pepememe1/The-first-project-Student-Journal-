"""
test_attendance_marks.py — СМЫСЛ меток посещаемости (3.7.6).

Здесь защищается ровно одна вещь, которую невозможно проверить взглядом на экран:
что «О» больше не считается пропуском. Метку переназначили с «уважительной причины»
на «ОПОЗДАЛ» (решение Ярослава 19.08.2026 — так её и понимали преподаватели), а
опоздавший студент НА ЗАНЯТИИ БЫЛ. Пока «О» шло в сумму пропусков, опоздание стоило
человеку столько же, сколько прогул: те же часы в отчёте куратора, тот же вклад в
индекс риска отчисления, тот же «должник» в глазах родителя.
"""
from app import webdata as W


class _L:
    def __init__(self, lid, ltype):
        self.id, self.type = lid, ltype
        self.number, self.subject, self.group_name = 1, "Математика", "ИС-21"


def test_late_is_not_an_absence():
    """🔥 Главное: «О» (опоздал) не увеличивает пропущенные часы."""
    lessons = [_L("L1", "Лекция")]
    assert W.absences(lessons, {"L1": "О"})["всего"] == 0


def test_late_is_counted_separately_not_lost():
    """…но и не исчезает: у куратора должна остаться возможность увидеть, что человек
    систематически опаздывает. Молча потерять факт — вторая крайность."""
    res = W.absences([_L("L1", "Лекция")], {"L1": "О"})
    assert res["О"] == 1


def test_unexcused_and_sick_still_count_as_missed():
    """Обратная сторона: «Н» и «Б» пропусками быть не перестали."""
    lessons = [_L("L1", "Лекция"), _L("L2", "Лекция")]
    res = W.absences(lessons, {"L1": "Н", "L2": "Б"})
    assert (res["Н"], res["Б"], res["всего"]) == (1, 1, 2)


def test_late_does_not_leak_into_risk_hours():
    """`attendance_hours` питает индекс риска отчисления. Опоздание не должно двигать
    человека к отчислению — это разные по смыслу события."""
    lessons = [_L("L1", "Лекция"), _L("L2", "Лекция")]
    missed, total, unexcused = W.attendance_hours(lessons, {"L1": "О", "L2": "Н"})
    assert (missed, unexcused) == (1, 1), "опоздание попало в пропущенные часы"
    assert total == 2


def test_attendance_percent_counts_late_as_present(client):
    """🔥 ВТОРАЯ ПРАВДА НА ОДНОМ ЭКРАНЕ (нашёл Полковник). Процент посещаемости в обзоре
    студента считается ОТДЕЛЬНО от `absences` — своим циклом в `routers/web/student.py`.
    После переназначения «О» первый расчёт перестал считать опоздание пропуском, а
    второй продолжал: у студента с единственной лекцией и меткой «О» обзор показывал
    одновременно «пропусков нет» и «посещаемость 0 %».

    Обратный ход: вернуть «О» в набор непришедших в `student.py` — тест краснеет."""
    from conftest import make_admin

    admin = make_admin(client)
    client.post("/web/admin/students", json={
        "login": "lateguy", "surname": "Опоздалов", "name": "Пётр", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "LEC1", "group_name": "ИС-21", "subject": "Математика", "type": "Лекция",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    client.post("/sync/push", json={"changes": {"grades": [
        {"id": "g1", "student_f": "Опоздалов", "student_n": "Пётр",
         "lesson_id": "LEC1", "grade": "О"}]}}, headers=admin)

    r = client.post("/auth/login", json={"login": "lateguy", "password": "studpass1"})
    sh = {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}
    out = client.get("/web/student/overview", headers=sh).json()
    assert out["attendance"] == 100, (
        "опоздавший студент числится непришедшим — цифра разошлась с «пропусков нет»")
