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
    def __init__(self, lid, ltype, number=1, hour=0, subject="Математика"):
        self.id, self.type = lid, ltype
        self.number, self.subject, self.group_name = number, subject, "ИС-21"
        self.hour = hour


def test_late_is_not_an_absence():
    """🔥 Главное: «О» (опоздал) не увеличивает пропущенные часы."""
    lessons = [_L("L1", "Лекция")]
    assert W.absences(lessons, {"L1": "О"})["всего"] == 0


def test_late_is_counted_separately_not_lost():
    """…но и не исчезает: у куратора должна остаться возможность увидеть, что человек
    систематически опаздывает. Молча потерять факт — вторая крайность."""
    res = W.absences([_L("L1", "Лекция")], {"L1": "О"})
    #2, а не 1: лекция заведена ОДНОЙ строкой (так её кладёт живой POST /web/teacher/lesson),
    #значит эта строка и есть вся пара — 2 академических часа.
    assert res["О"] == 2


def test_unexcused_and_sick_still_count_as_missed():
    """Обратная сторона: «Н» и «Б» пропусками быть не перестали."""
    #Две строки с ОДНИМ номером — это старая (десктопная) раскладка одной пары: 2 часа
    #делятся между ними, по часу на строку.
    res = W.absences([_L("L1", "Лекция"), _L("L2", "Лекция")], {"L1": "Н", "L2": "Б"})
    assert (res["Н"], res["Б"], res["всего"]) == (1, 1, 2)
    #А два РАЗНЫХ занятия (разные номера) — это две пары, 4 часа.
    res2 = W.absences([_L("L1", "Лекция", number=1), _L("L2", "Лекция", number=2)],
                      {"L1": "Н", "L2": "Б"})
    assert (res2["Н"], res2["Б"], res2["всего"]) == (2, 2, 4)


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


# ── ПРАКТИКА (31.08.2026) ──────────────────────────────────────────────────────────
# Дефект жил в одной строке `webdata.absences`:
#     elif l.type == "Практика" and v == "Н":
# то есть у практики учитывалась РОВНО ОДНА метка из трёх. «Б» не попадала в пропуски
# вообще, «О» не попадала в свой счётчик, а сама «Н» стоила 1 «час» вместо двух —
# при том что практика и лекция это одна и та же пара по 2 академических часа.
# Цена: студент, проболевший все практики семестра, показан родителю и куратору как
# «пропусков нет», а систематические опоздания на практику невидимы куратору.


def test_sick_on_a_practice_is_a_missed_class():
    """🔥 Главное. «Б» на практике не попадала в пропуски ВООБЩЕ.

    Обратный ход: вернуть в `absences` условие `and v == "Н"` для практики — краснеет."""
    res = W.absences([_L("P1", "Практика")], {"P1": "Б"})
    assert res["Б"] == 2, "«Б» на практике потеряна"
    assert res["всего"] == 2


def test_late_on_a_practice_is_counted_separately():
    """«О» на практике тоже существует: опоздание не пропуск, но и не небытие."""
    res = W.absences([_L("P1", "Практика")], {"P1": "О"})
    assert res["О"] == 2
    assert res["всего"] == 0, "опоздание не пропуск — правило 3.7.6 одно на все типы"


def test_a_missed_practice_costs_the_same_as_a_missed_lecture():
    """🔥 Пара есть пара. Практика лежит ОДНОЙ строкой, лекция ДВУМЯ — но прогулявший
    практику потерял ровно столько же академических часов, сколько прогулявший лекцию.
    До починки практика стоила вдвое меньше, и это уезжало в индекс риска отчисления."""
    lecture = W.absences([_L("L1", "Лекция", hour=1), _L("L2", "Лекция", hour=2)],
                         {"L1": "Н", "L2": "Н"})
    practice = W.absences([_L("P1", "Практика")], {"P1": "Н"})
    single_row_lecture = W.absences([_L("L9", "Лекция")], {"L9": "Н"})
    assert lecture["всего"] == practice["всего"] == single_row_lecture["всего"] == 2


def test_homework_is_still_not_an_absence():
    """Граница, которую починка НЕ имеет права сдвинуть: «Н» на ДЗ значит «не сдал»,
    а не «не был», и в посещаемость не идёт (докстринг `absences`)."""
    assert W.absences([_L("H1", "ДЗ")], {"H1": "Н"})["всего"] == 0


def test_missed_hours_never_exceed_total_hours():
    """🔥 СВОЙСТВО: пропущено не может быть больше, чем было. `attendance_hours` питает
    ДОЛЮ в индексе риска (`absence_hours / total_hours`), и стоит двум величинам
    считаться разными формулами — доля уезжает за 100 %, а объяснить это нечем."""
    lessons = [_L("L1", "Лекция", hour=1), _L("L2", "Лекция", hour=2),
               _L("P1", "Практика", number=2), _L("H1", "ДЗ", number=3)]
    recs = {"L1": "Н", "L2": "Б", "P1": "Н", "H1": "Н"}
    missed, total, unexcused = W.attendance_hours(lessons, recs)
    assert missed <= total
    #Лекция (пара из двух строк) 2 ч + практика 2 ч = 4; ДЗ часов не несёт вовсе.
    assert (missed, total, unexcused) == (4, 4, 3)


def test_attendance_percent_uses_the_same_hours_as_absences():
    """🔥 ТРЕТЬЯ ПРАВДА НА ОДНОМ ЭКРАНЕ. Процент посещаемости в обзоре студента считался
    СВОИМ циклом и только по ЛЕКЦИЯМ — практика не входила в него вовсе. Студент,
    прогулявший все практики и не пропустивший ни одной лекции, видел «посещаемость
    100 %» рядом с честным числом пропущенных часов.

    Обратный ход: вернуть счёт только по лекциям — тест краснеет."""
    lessons = [_L("L1", "Лекция", hour=1), _L("L2", "Лекция", hour=2),
               _L("P1", "Практика", number=2)]
    #Лекция 2 ч + практика 2 ч = 4; прогуляна практика → 2 из 4 → 50 %.
    assert W.attendance_percent(lessons, {"P1": "Н"}) == 50
    assert W.attendance_percent(lessons, {}) == 100
    assert W.attendance_percent([], {}) == 100, "занятий нет — не «0 %», а «нечего пропускать»"


# ── РАЗДЕЛЬНОЕ ОБУЧЕНИЕ И ЗНАМЕНАТЕЛЬ (31.08.2026, второе возражение Полковника) ────
# Числитель починили, а знаменатель — нет. Занятия студенту фильтрует по его подгруппе
# только СТУДЕНЧЕСКИЙ путь; куратор, преподаватель и родитель зовут
# `dropout_risk_for_student` со списком занятий ВСЕЙ группы. После того как подгруппа
# вошла в ключ пары, «Практика №1» двух подгрупп стала ДВУМЯ парами — то есть `total`
# удвоился, а `missed` остался своим. Доля пропусков в индексе риска отчисления вышла
# ровно вдвое заниженной — тем же числом, что и ДО починки, только с другой стороны дроби.


def test_risk_hours_ignore_the_other_subgroup(client):
    """🔥 Знаменатель риска считается по ЗАНЯТИЯМ СТУДЕНТА, а не всей группы.

    Обратный ход: убрать фильтр по подгруппе в `dropout_risk_for_student` — доля
    пропусков падает вдвое и тест краснеет."""
    from conftest import make_admin
    from app import webdata as W
    from app.db import SessionLocal
    from app.models import Lesson, StudentSubgroup, student_subgroup_id

    admin = make_admin(client)
    client.post("/web/admin/students", json={
        "login": "splitguy", "surname": "Раздельнов", "name": "Иван", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)

    db = SessionLocal()
    try:
        cfg = W.load_config(db)
        ty, ts = W.current_term(cfg)
        #По одной практике в каждой подгруппе — у обеих номер №1 (нумерация раздельная).
        for lid, sub in (("P_MY", 1), ("P_OTHER", 2)):
            db.add(Lesson(id=lid, group_name="ИС-21", subject="Математика", type="Практика",
                          number=1, topic="т", date="01.09.2025", subgroup=sub,
                          year=ty, semester=ts))
        stud = W.student_by_name(db, "Раздельнов", "Иван", "ИС-21")
        assert stud is not None, "студент не найден по ФИО — тест проверял бы не то"
        db.add(StudentSubgroup(
            id=student_subgroup_id("ИС-21", "Математика", ty, ts, stud.id),
            group_name="ИС-21", subject="Математика", year=ty, semester=ts,
            student_id=stud.id, subgroup=1))
        db.commit()

        #Студент пропустил ЕДИНСТВЕННУЮ свою практику: пропущено 2 ч из 2 ч своих.
        recs = {"P_MY": "Н"}
        lessons = W.current_term_lessons(db, "ИС-21", W.group_lessons(db, "ИС-21"), cfg)
        #Так же, как это делает `dropout_risk_for_student` (фильтр стоит внутри неё).
        mine = W.filter_lessons_by_student_subgroup(db, lessons, stud.id)
        missed, total, _ = W.attendance_hours(mine, recs)
        assert (missed, total) == (2, 2), (
            "в знаменатель попала практика ЧУЖОЙ подгруппы — доля пропусков занижена вдвое")
        #И сам расчёт риска обязан пользоваться тем же фильтром, а не списком всей группы:
        #в тексте фактора стоит знаменатель, и он обязан быть 2 ч, а не 4.
        risk = W.dropout_risk_for_student(db, "Раздельнов", "Иван", "ИС-21",
                                          cfg=cfg, lessons=lessons, records=recs,
                                          student_id=stud.id)
        txt = " ".join(str(f) for f in risk["factors"])
        assert "из 4 ч" not in txt, f"знаменатель взят по всей группе: {txt}"
    finally:
        db.close()
