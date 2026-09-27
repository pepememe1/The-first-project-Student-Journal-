"""
test_sync_namesakes.py — полные тёзки в синке (исследование синка, находка W-04).

━━ ЧТО БЫЛО ━━
Миграция §12 свела в одно место СБОРКУ ключа оценки, но не СРАВНЕНИЕ человека.
`/sync/pull` отдавал студенту оценки «с его фамилией и именем», то есть полный тёзка из
ДРУГОЙ группы выкачивал на свой компьютер чужие оценки и итоговые. А у итоговых выдача
преподавателю и проверка прав при приёме держали карту «(фамилия, имя) → группа», и у
тёзок из разных групп словарь молча оставлял одного: итоговая уезжала преподавателю
чужой группы, а свой её не получал и не мог записать.

━━ ПРАВИЛО ━━
Одна дверь (`models.row_student_id` + `sync._Students`): id в строке есть — только по
нему (включая id в ключе, когда колонку не заполнил старый клиент); id нет — по ФИО, и
только если опознание однозначно. «Не узнали» — отказ, а не «первый найденный».

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: вернуть сравнение по ФИО в `_scope_for_student`, карту
«ФИО → группа» в выдаче и приёме, голую колонку в `_domain_refusal` и в
`webdata.student_records` — каждый возврат красит свой тест ниже.
"""

from conftest import make_admin, make_teacher, assign_teacher


def _push(client, headers, **entities):
    return client.post("/sync/push", json={"changes": entities}, headers=headers)


def _student(client, admin, login, surname, name, group, pw="studpass1"):
    from app.security import hash_password
    r = _push(client, admin, users=[{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password(pw), "surname": surname, "name": name,
        "group_name": group}])
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _term():
    from app.db import SessionLocal
    from app import webdata as W
    with SessionLocal() as db:
        return W.current_term(W.load_config(db))


def _insert(*rows):
    """Строки прямо в базу — так, как их оставили прежние версии (без id студента)."""
    from app.db import SessionLocal
    with SessionLocal() as db:
        for r in rows:
            db.add(r)
        db.commit()


def _world(client):
    """Два полных тёзки «Иванов Иван» в РАЗНЫХ группах + по занятию у каждой группы."""
    admin = make_admin(client)
    iv1 = _student(client, admin, "iv1", "Иванов", "Иван", "ИС-21")
    iv2 = _student(client, admin, "iv2", "Иванов", "Иван", "ИС-22")
    r = _push(client, admin, lessons=[
        {"id": "L21", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 1},
        {"id": "L22", "group_name": "ИС-22", "subject": "Математика", "type": "Практика",
         "number": 1}])
    assert r.status_code == 200, r.text
    return admin, iv1, iv2


def _pull(client, h):
    r = client.get("/sync/pull", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["changes"]


def test_student_pull_gives_each_namesake_only_his_own_grades(client):
    admin, iv1, iv2 = _world(client)
    r = _push(client, admin, grades=[
        {"id": "stud:iv1|L21", "student_id": "stud:iv1", "student_f": "Иванов",
         "student_n": "Иван", "lesson_id": "L21", "grade": "5"},
        {"id": "stud:iv2|L22", "student_id": "stud:iv2", "student_f": "Иванов",
         "student_n": "Иван", "lesson_id": "L22", "grade": "2"}])
    assert r.status_code == 200, r.text

    assert {g["id"] for g in _pull(client, iv1)["grades"]} == {"stud:iv1|L21"}, \
        "тёзка из другой группы получил чужую оценку"
    assert {g["id"] for g in _pull(client, iv2)["grades"]} == {"stud:iv2|L22"}


def test_owner_is_read_from_the_key_when_an_old_client_left_the_column_empty(client):
    """Старый клиент шлёт ФИО-ключ без id; push приводит ключ к владельцу по занятию, а
    колонку оставляет пустой (простановка бампнула бы метку — §10). Владелец такой
    строки живёт только в ключе, и чужому она уходить не должна."""
    admin, iv1, iv2 = _world(client)
    r = _push(client, admin, grades=[
        {"id": "Иванов|Иван|L21", "student_f": "Иванов", "student_n": "Иван",
         "lesson_id": "L21", "grade": "4"}])
    assert r.status_code == 200, r.text
    from app.db import SessionLocal
    from app.models import Grade
    with SessionLocal() as db:
        row = db.get(Grade, "stud:iv1|L21")
        assert row is not None and not (row.student_id or ""), \
            "предпосылка теста: ключ приведён, колонка пуста"

    assert {g["id"] for g in _pull(client, iv1)["grades"]} == {"stud:iv1|L21"}
    assert _pull(client, iv2)["grades"] == [], "строку с чужим ключом отдали тёзке"


def test_legacy_grade_without_any_id_goes_only_to_the_namesake_of_that_group(client):
    """Совсем старая строка (ФИО-ключ, id нет нигде) — общая по ФИО, но только на
    занятии СВОЕЙ группы: то же правило, что у сайта (`webdata.student_records`)."""
    admin, iv1, iv2 = _world(client)
    from app.models import Grade
    _insert(Grade(id="Иванов|Иван|L22", student_f="Иванов", student_n="Иван",
                  lesson_id="L22", grade="3", updated_at="2026-09-01T00:00:00+00:00"))
    assert {g["id"] for g in _pull(client, iv2)["grades"]} == {"Иванов|Иван|L22"}, \
        "свою старую оценку студент потерял бы"
    assert _pull(client, iv1)["grades"] == [], "старую оценку чужой группы отдали тёзке"


def test_student_term_grades_by_id_and_legacy_only_without_namesakes(client):
    admin, iv1, iv2 = _world(client)
    ty, ts = _term()
    pt = _student(client, admin, "pt1", "Петров", "Пётр", "ИС-21")
    from app.models import TermGrade
    _insert(
        TermGrade(id=f"stud:iv1|Математика|{ty}|{ts}", student_id="stud:iv1",
                  student_f="Иванов", student_n="Иван", subject="Математика",
                  year=ty, semester=ts, grade="5", updated_at="2026-09-01T00:00:00+00:00"),
        #старые итоговые без id: у тёзок строка ничья, у Петрова — его
        TermGrade(id="Иванов|Иван|Физика|2025/2026|1", student_f="Иванов",
                  student_n="Иван", subject="Физика", year="2025/2026", semester=1,
                  grade="4", updated_at="2026-09-01T00:00:00+00:00"),
        TermGrade(id="Петров|Пётр|Физика|2025/2026|1", student_f="Петров",
                  student_n="Пётр", subject="Физика", year="2025/2026", semester=1,
                  grade="3", updated_at="2026-09-01T00:00:00+00:00"))

    assert {t["id"] for t in _pull(client, iv1)["term_grades"]} == \
        {f"stud:iv1|Математика|{ty}|{ts}"}, "ничью итоговую тёзок отдали одному из них"
    assert _pull(client, iv2)["term_grades"] == [], "итоговую тёзки отдали другому"
    assert {t["id"] for t in _pull(client, pt)["term_grades"]} == \
        {"Петров|Пётр|Физика|2025/2026|1"}, "без тёзок старая итоговая обязана доехать"


def test_teacher_pull_term_grades_follow_the_student_not_his_name(client):
    admin, _iv1, _iv2 = _world(client)
    th = make_teacher(client, admin, login="tn1", subjects=["Математика"])
    assign_teacher(client, admin, "teach:tn1", "ИС-21", "Математика")
    ty, ts = _term()
    from app.models import TermGrade
    _insert(
        TermGrade(id=f"stud:iv1|Математика|{ty}|{ts}", student_id="stud:iv1",
                  student_f="Иванов", student_n="Иван", subject="Математика",
                  year=ty, semester=ts, grade="5", updated_at="2026-09-01T00:00:00+00:00"),
        TermGrade(id=f"stud:iv2|Математика|{ty}|{ts}", student_id="stud:iv2",
                  student_f="Иванов", student_n="Иван", subject="Математика",
                  year=ty, semester=ts, grade="2", updated_at="2026-09-01T00:00:00+00:00"),
        TermGrade(id="Иванов|Иван|Математика|2025/2026|1", student_f="Иванов",
                  student_n="Иван", subject="Математика", year="2025/2026", semester=1,
                  grade="4", updated_at="2026-09-01T00:00:00+00:00"))

    got = {t["id"] for t in _pull(client, th)["term_grades"]}
    assert got == {f"stud:iv1|Математика|{ty}|{ts}"}, \
        f"преподаватель ИС-21 получил не то: {got}"


def test_teacher_push_term_grade_is_judged_by_the_student_id(client):
    """Преподаватель ИС-21 пишет итоговую своему Иванову и НЕ может записать её тёзке из
    ИС-22. Прежняя карта «ФИО → группа» у тёзок держала одну группу на двоих, поэтому
    одно из двух утверждений падало при любом порядке строк."""
    admin, _iv1, _iv2 = _world(client)
    th = make_teacher(client, admin, login="tn2", subjects=["Математика"])
    assign_teacher(client, admin, "teach:tn2", "ИС-21", "Математика")
    ty, ts = _term()

    def tg(sid):
        return {"id": f"{sid}|Математика|{ty}|{ts}", "student_id": sid,
                "student_f": "Иванов", "student_n": "Иван", "subject": "Математика",
                "year": ty, "semester": ts, "grade": "5", "form": "экзамен"}

    r = _push(client, th, term_grades=[tg("stud:iv1")])
    assert r.status_code == 200, r.text
    assert r.json()["applied"].get("term_grades") == 1, f"своему не дали записать: {r.json()}"

    r = _push(client, th, term_grades=[tg("stud:iv2")])
    assert r.status_code == 200, r.text
    assert r.json()["applied"].get("term_grades", 0) == 0, "записал итоговую чужой группе"
    assert (r.json().get("rejected") or {}).get("term_grades") == 1


def test_teacher_push_without_id_does_not_guess_between_namesakes(client):
    """Старый клиент без id: итоговая несёт только ФИО, а Ивановых Иванов двое. Угадывать
    нельзя — отказ (в `rejected`, человек его увидит), а не запись «первому найденному»."""
    admin, _iv1, _iv2 = _world(client)
    th = make_teacher(client, admin, login="tn3", subjects=["Математика"])
    assign_teacher(client, admin, "teach:tn3", "ИС-21", "Математика")
    ty, ts = _term()
    r = _push(client, th, term_grades=[{
        "id": f"Иванов|Иван|Математика|{ty}|{ts}", "student_f": "Иванов",
        "student_n": "Иван", "subject": "Математика", "year": ty, "semester": ts,
        "grade": "5", "form": "экзамен"}])
    assert r.status_code == 200, r.text
    assert r.json()["applied"].get("term_grades", 0) == 0, "итоговую записали наугад"
    assert (r.json().get("rejected") or {}).get("term_grades") == 1


def test_grade_lock_follows_the_owner_in_the_key(client):
    """Замок зачётки: у Иванова из ИС-21 выставлена итоговая, значит текущая оценка по
    предмету не пишется. Старый клиент шлёт оценку без колонки id — push приводит ключ к
    владельцу, и замок обязан идти за ключом, а не пропускать строку «без id»."""
    admin, _iv1, _iv2 = _world(client)
    th = make_teacher(client, admin, login="tn4", subjects=["Математика"])
    assign_teacher(client, admin, "teach:tn4", "ИС-21", "Математика")
    ty, ts = _term()
    from app.models import TermGrade
    _insert(TermGrade(id=f"stud:iv1|Математика|{ty}|{ts}", student_id="stud:iv1",
                      student_f="Иванов", student_n="Иван", subject="Математика",
                      year=ty, semester=ts, grade="5",
                      updated_at="2026-09-01T00:00:00+00:00"))
    r = _push(client, th, grades=[{
        "id": "Иванов|Иван|L21", "student_f": "Иванов", "student_n": "Иван",
        "lesson_id": "L21", "grade": "2"}])
    assert r.status_code == 200, r.text
    assert r.json()["applied"].get("grades", 0) == 0, "оценка обошла закрытый семестр"
    assert (r.json().get("rejected") or {}).get("grades") == 1


def test_site_does_not_mix_in_a_namesakes_row_whose_owner_is_in_the_key(client):
    """Сайт читает ту же дверь: строка с владельцем в ключе (колонка пуста) — не общая."""
    admin, _iv1, _iv2 = _world(client)
    _push(client, admin, lessons=[
        {"id": "L21b", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 2}])
    from app.models import Grade
    _insert(Grade(id="stud:iv1|L21b", student_f="Иванов", student_n="Иван",
                  lesson_id="L21b", grade="5", updated_at="2026-09-01T00:00:00+00:00"))
    from app.db import SessionLocal
    from app import webdata as W
    with SessionLocal() as db:
        mine = W.student_records(db, "Иванов", "Иван", student_id="stud:iv1")
        other = W.student_records(db, "Иванов", "Иван", student_id="stud:iv2")
    assert mine.get("L21b") == "5"
    assert "L21b" not in other, "сайт подмешал тёзке строку, чей владелец назван в ключе"
