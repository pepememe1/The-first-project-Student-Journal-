"""
test_vector_surnames.py — Вектор и фамилия студента: любой падеж, любая роль (01.10.2026).

━━ ЗАЧЕМ ━━
Жалоба Ярослава: «пишем фамилию студента — Вектор не может дать ответ». Живой прогон
граней на большом стенде нашёл, из чего она складывается:
  • фамилия искалась ПОДСТРОКОЙ, и «Алексеева» находила только мужчину Алексеева —
    женщина не находилась вовсе, если в колледже был однофамилец-мужчина;
  • «оценки Хандакова Евгения Николаевича» находили фамилию НИКОЛАЕВ — из отчества;
  • имя не сужало однофамильцев: «Борисов Кирилл» при двух Борисовых в одной группе —
    тупик («уточните группу», а группа одна);
  • вопрос о ЧУЖОМ студенте не опознавался: студент получал СВОИ пропуски так, будто это
    ответ про Егорова, преподаватель — сводку по своим группам или «поболтаем»;
  • родитель в общей двери (команда /vector) считался студентом с пустыми данными:
    «Задолженностей нет — так держать!» — родителю должника.
Схема доступа ролей — docs/security/VECTOR-ACCESS.md.
"""
import pytest

from conftest import make_admin, assign_teacher
from app.security import hash_password

G1, G2 = "К74/1", "К64/2"

STUDENTS = [  # id, фамилия, «Имя Отчество», отчество, группа
    ("stud:alexm", "Алексеев", "Кирилл Сергеевич", "Сергеевич", G1),
    ("stud:alexf", "Алексеева", "Мария Игоревна", "Игоревна", G1),
    ("stud:bor1", "Борисов", "Кирилл Эрдэмович", "Эрдэмович", G1),
    ("stud:bor2", "Борисов", "Илья Павлович", "Павлович", G1),
    ("stud:khan", "Хандаков", "Евгений Николаевич", "Николаевич", G1),
    ("stud:nik", "Николаев", "Олег Игоревич", "Игоревич", G2),
    ("stud:kov", "Ковальская", "Анна Сергеевна", "Сергеевна", G2),
]
MARKS = {"stud:alexm": "5", "stud:alexf": "3", "stud:bor1": "4", "stud:bor2": "2",
         "stud:khan": "4", "stud:nik": "5", "stud:kov": "4"}


@pytest.fixture()
def world(client):
    from app.db import default_term
    ty, ts = default_term()
    admin = make_admin(client)
    users = [{"id": sid, "role": "student", "login": sid.split(":")[1], "surname": f,
              "name": n, "patronymic": p, "full_name": f"{f} {n}", "group_name": g,
              "password_hash": ""} for sid, f, n, p, g in STUDENTS]
    khan = next(u for u in users if u["id"] == "stud:khan")
    khan["password_hash"] = hash_password("studpass1")
    users.append({"id": "teach:t1", "role": "teacher", "login": "t1",
                  "password_hash": hash_password("teachpass1"), "surname": "Орлова",
                  "name": "Анна Петровна", "patronymic": "Петровна",
                  "full_name": "Орлова Анна Петровна", "subjects": ["Математика"]})
    users.append({"id": "teach:c1", "role": "teacher", "login": "c1",
                  "password_hash": hash_password("curatorpass1"), "surname": "Будаева",
                  "name": "Туяна Баировна", "patronymic": "Баировна",
                  "full_name": "Будаева Туяна Баировна", "subjects": [],
                  "curated_groups": [G2]})
    users.append({"id": "moder1", "role": "moderator", "login": "moder1",
                  "password_hash": hash_password("moderpass1"), "surname": "Модеров",
                  "name": "Матвей Олегович", "full_name": "Модеров Матвей Олегович"})
    lessons = [{"id": f"{code}-{i}", "group_name": g, "subject": "Математика",
                "type": "Практика", "number": i, "topic": "т", "date": f"0{i}.09.2026",
                "year": ty, "semester": ts}
               for code, g in (("m1", G1), ("m2", G2)) for i in (1, 2)]
    grades = [{"id": f"{sid}|{('m1' if g == G1 else 'm2')}-1", "student_id": sid,
               "student_f": f, "student_n": n,
               "lesson_id": f"{('m1' if g == G1 else 'm2')}-1", "grade": MARKS[sid]}
              for sid, f, n, _p, g in STUDENTS]
    #Хандакову — долг (пропуск), чтобы «долгов нет» было ложью, а не совпадением.
    grades.append({"id": "stud:khan|m1-2", "student_id": "stud:khan",
                   "student_f": "Хандаков", "student_n": "Евгений Николаевич",
                   "lesson_id": "m1-2", "grade": "Н"})
    r = client.post("/sync/push", json={"changes": {
        "groups": [{"id": "grp:1", "name": G1, "subjects": ["Математика"]},
                   {"id": "grp:2", "name": G2, "subjects": ["Математика"]}],
        "users": users, "lessons": lessons, "grades": grades}}, headers=admin)
    assert r.status_code == 200, r.text
    #t1 ВЕДЁТ К74/1; c1 только КУРИРУЕТ К64/2 (нагрузки нет).
    assign_teacher(client, admin, "teach:t1", G1, "Математика", year=ty, semester=ts)

    r = client.post("/web/admin/parents", json={
        "login": "par1", "surname": "Хандакова", "name": "Ольга", "password": "parentpass1"},
        headers=admin)
    assert r.status_code == 200, r.text
    parent_id = r.json()["id"]
    r = client.post("/web/staff/parent-links",
                    json={"parent_id": parent_id, "student_id": "stud:khan"}, headers=admin)
    assert r.status_code == 200, r.text
    student = _login(client, "khan", "studpass1")
    link_id = client.get("/web/student/parent-links", headers=student).json()["links"][0]["id"]
    r = client.post(f"/web/student/parent-links/{link_id}/decide", json={"approve": True},
                    headers=student)
    assert r.status_code == 200, r.text
    return {"client": client, "admin": admin, "student": student,
            "teacher": _login(client, "t1", "teachpass1"),
            "curator": _login(client, "c1", "curatorpass1"),
            "moder": _login(client, "moder1", "moderpass1"),
            "parent": _login(client, "par1", "parentpass1")}


def _login(client, login, password):
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _ask(world, who, q):
    r = world["client"].post("/web/vector/ask", json={"message": q}, headers=world[who])
    assert r.status_code == 200, (q, r.text)
    return r.json()


def _ask_parent(world, q):
    r = world["client"].post("/web/parent/vector/ask",
                             json={"message": q, "student_id": "stud:khan"},
                             headers=world["parent"])
    assert r.status_code == 200, (q, r.text)
    return r.json()


# ── женская форма рядом с мужской ──────────────────────────────────────────────────

def test_female_surname_is_found_next_to_a_male_namesake(world):
    """🔥 Дословный дефект: «оценки Алексеевой» уходили к мужчине Алексееву (или никуда)."""
    for q in ("оценки Алексеевой", "пропуски у Алексеевой", "Алексеевой"):
        a = _ask(world, "teacher", q)
        assert "Алексеева Мария" in a["text"], (q, a["text"])
        assert "Алексеев Кирилл" not in a["text"], (q, a["text"])


def test_ambiguous_form_lists_both_genders(world):
    """«Алексеева» — и родительный от Алексеев, и женская фамилия: выбирать за человека
    нельзя, в списке обязаны быть ОБА."""
    a = _ask(world, "admin", "Алексеева")
    assert "Алексеев Кирилл" in a["text"] and "Алексеева Мария" in a["text"], a["text"]


def test_name_narrows_namesakes_in_one_group(world):
    """🔥 Два Борисова в ОДНОЙ группе: «уточните группу» было тупиком."""
    for q in ("Борисов Кирилл", "оценки Борисова Кирилла", "Кирилл Борисов"):
        a = _ask(world, "teacher", q)
        assert "Борисов Кирилл" in a["text"] and "Борисов Илья" not in a["text"], (q, a["text"])
    both = _ask(world, "teacher", "Борисов")["text"]
    assert "Борисов Кирилл" in both and "Борисов Илья" in both, both


def test_patronymic_is_not_taken_for_a_surname(world):
    """🔥 «…Евгения Николаевича» находило фамилию Николаев — из отчества."""
    a = _ask(world, "admin", "оценки Хандакова Евгения Николаевича")
    assert "Хандаков" in a["text"] and "Николаев Олег" not in a["text"], a["text"]


# ── чужой студент: честный отказ, а не данные «про себя» ───────────────────────────

def test_teacher_gets_a_refusal_for_a_student_outside_his_groups(world):
    for q in ("пропуски Николаева", "Николаеву", "оценки Ковальской"):
        a = _ask(world, "teacher", q)
        assert "не в ваших группах" in a["text"], (q, a["text"])
        assert "Николаев Олег" not in a["text"] and "Ковальская Анна" not in a["text"]


def test_curator_without_load_sees_his_group_by_surname(world):
    a = _ask(world, "curator", "оценки Николаева")
    assert "Николаев Олег" in a["text"], a["text"]


def test_student_asking_about_another_student_gets_a_refusal_not_his_own_data(world):
    """🔥 «пропуски у Егорова» возвращало студенту ЕГО ЖЕ пропуски — как ответ про Егорова."""
    own = _ask(world, "student", "мои пропуски")["text"]
    for q in ("пропуски у Алексеевой", "оценки Борисова", "Николаев"):
        a = _ask(world, "student", q)
        assert "других" in a["text"] and a["text"] != own, (q, a["text"])


def test_student_own_surname_is_a_question_about_himself(world):
    for q in ("Хандаков", "оценки Хандакова"):
        a = _ask(world, "student", q)
        assert a["intent"] != "unknown", (q, a)
        assert "средний" in a["text"].lower(), (q, a["text"])


def test_moderator_is_told_why_there_is_no_answer(world):
    a = _ask(world, "moder", "оценки Алексеевой")
    assert "модератору не показываю" in a["text"], a["text"]


# ── родитель ───────────────────────────────────────────────────────────────────────

def test_parent_door_answers_about_the_child_in_parent_voice(world):
    a = _ask_parent(world, "Хандаков")
    assert a["intent"] != "unknown", a
    assert "Твой" not in a["text"] and "тебя" not in a["text"], a["text"]
    other = _ask_parent(world, "оценки Алексеевой")
    assert "вашего ребёнка" in other["text"], other["text"]
    assert "Алексеева Мария" not in other["text"]


def test_parent_in_the_general_door_gets_the_child_not_an_empty_student(world):
    """🔥 Команда /vector у родителя: «Задолженностей нет — так держать!» родителю
    должника — его самого считали студентом без оценок."""
    a = _ask(world, "parent", "долги")
    assert "так держать" not in a["text"] and "нет" not in a["text"].lower()[:30], a["text"]
    assert "Математика" in a["text"], a["text"]
    avg = _ask(world, "parent", "средний балл")["text"]
    assert "0.0" not in avg and "Твой" not in avg, avg
