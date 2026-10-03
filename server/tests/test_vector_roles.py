"""
test_vector_roles.py — Вектор отвечает ПО РОЛИ, а не «как студенту» (28.09.2026).

━━ ЗАЧЕМ ━━
Жалоба Ярослава с живого бота (роль admin, GigaChat):
  «Студенты»           → «конкретный список студентов мне недоступен»;
  «Студенты к74/1»     → «о группе К74/1 у меня данных нет»;
  «Сводка группы»      → «в твоей группе 26 студентов» — у администратора группы нет.
Причин было три, и каждая здесь под своим тестом:
  • разбор не знал слов «студенты»/«группы» и не извлекал группу из вопроса;
  • у администратора не было веток «состав группы», «сводка», «пропуски», «расписание
    группы», «студент по фамилии» — всё проваливалось в общий счётчик колледжа;
  • этот счётчик уходил в модель, и модель переписывала «в колледже 26» как «в вашей
    группе 26». Поэтому админские ответы теперь НЕ озвучиваются вовсе.
Плюс находки живого прогона граней: долги без названия предмета выглядели дублями,
куратор без нагрузки «не имел групп», модератор получал ответы студента, зона риска у
ролей считалась по-разному, преподаватели с портала ВСГУТУ Вектору были неизвестны.
"""
import types

import pytest

from conftest import make_admin, assign_teacher
from app.security import hash_password

G1, G2 = "К74/1", "К64/2"          # слэш в имени — ловушка Starlette, проверяем на нём


def _lessons(ty, ts):
    out = []
    for i in range(1, 5):
        out.append({"id": f"m1-{i}", "group_name": G1, "subject": "Математика",
                    "type": "Практика", "number": i, "topic": "т", "date": f"0{i}.09.2026",
                    "year": ty, "semester": ts})
    for i in range(1, 3):
        out.append({"id": f"f1-{i}", "group_name": G1, "subject": "Физика",
                    "type": "Практика", "number": i, "topic": "т", "date": f"1{i}.09.2026",
                    "year": ty, "semester": ts})
        out.append({"id": f"m2-{i}", "group_name": G2, "subject": "Математика",
                    "type": "Практика", "number": i, "topic": "т", "date": f"1{i}.09.2026",
                    "year": ty, "semester": ts})
    return out


MARKS = {  # студент → {занятие: отметка}
    "stud:a1": {"m1-1": "5", "m1-2": "5", "m1-3": "4", "m1-4": "5", "f1-1": "5", "f1-2": "4"},
    "stud:a2": {"m1-1": "2", "m1-2": "Н", "m1-3": "2", "m1-4": "2", "f1-1": "2", "f1-2": "Н"},
    "stud:a3": {"m1-1": "4", "m1-2": "4", "f1-1": "4"},
    "stud:b1": {"m2-1": "3", "m2-2": "3"},
}
STUDENTS = [  # id, фамилия, имя, группа
    ("stud:a1", "Цыдыпов", "Батор Баирович", G1),
    ("stud:a2", "Жамбалов", "Эрдэм Саянович", G1),
    ("stud:a3", "Очиров", "Саян Олегович", G1),
    ("stud:b1", "Цыдыпов", "Батор Баирович", G2),    # полный тёзка из другой группы
]


@pytest.fixture()
def world(client):
    from app.db import default_term
    ty, ts = default_term()
    admin = make_admin(client)
    users = [{"id": sid, "role": "student", "login": sid.split(":")[1], "surname": f,
              "name": n, "full_name": f"{f} {n}", "group_name": g, "password_hash": ""}
             for sid, f, n, g in STUDENTS]
    users[0]["password_hash"] = hash_password("studpass1")
    users.append({"id": "teach:t1", "role": "teacher", "login": "t1",
                  "password_hash": hash_password("teachpass1"), "surname": "Орлова",
                  "name": "Анна Петровна", "patronymic": "Петровна",
                  "full_name": "Орлова Анна Петровна", "subjects": ["Математика"],
                  "curated_groups": [G1]})
    users.append({"id": "moder1", "role": "moderator", "login": "moder1",
                  "password_hash": hash_password("moderpass1"), "surname": "Модеров",
                  "name": "Матвей Олегович", "full_name": "Модеров Матвей Олегович"})
    grades = [{"id": f"{sid}|{lid}", "student_id": sid,
               "student_f": next(s[1] for s in STUDENTS if s[0] == sid),
               "student_n": next(s[2] for s in STUDENTS if s[0] == sid),
               "lesson_id": lid, "grade": v}
              for sid, marks in MARKS.items() for lid, v in marks.items()]
    r = client.post("/sync/push", json={"changes": {
        "groups": [{"id": "grp:1", "name": G1, "subjects": ["Математика", "Физика"]},
                   {"id": "grp:2", "name": G2, "subjects": ["Математика"]},
                   {"id": "grp:3", "name": "К99/9", "subjects": ["Математика"]}],
        "users": users, "lessons": _lessons(ty, ts), "grades": grades}}, headers=admin)
    assert r.status_code == 200, r.text
    #Преподаватель ВЕДЁТ только К64/2, а К74/1 лишь КУРИРУЕТ — ровно случай находки.
    assign_teacher(client, admin, "teach:t1", G2, "Математика", year=ty, semester=ts)
    return {"client": client, "admin": admin,
            "teacher": _login(client, "t1", "teachpass1"),
            "student": _login(client, "a1", "studpass1"),
            "moder": _login(client, "moder1", "moderpass1")}


def _login(client, login, password):
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _ask(world, who, q):
    r = world["client"].post("/web/vector/ask", json={"message": q}, headers=world[who])
    assert r.status_code == 200, (q, r.text)
    return r.json()


@pytest.fixture()
def llm_spy(monkeypatch):
    """Всё, что уходит в озвучку моделью. Сама модель в тестах не нужна."""
    from app import vector_llm
    seen = []

    def _spy(cfg, facts_text, role="student", question="", locale="ru"):
        seen.append(facts_text)
        return facts_text

    monkeypatch.setattr(vector_llm, "voice", _spy)
    return seen


# ── администратор ──────────────────────────────────────────────────────────────────

def test_admin_gets_the_roster_of_the_named_group(world):
    for q in ("студенты к74/1", "список группы К74/1", "кто в группе К74/1"):
        a = _ask(world, "admin", q)
        assert a["intent"] == "roster", (q, a)
        assert "Жамбалов" in a["text"] and "Очиров" in a["text"], (q, a["text"])
    other = _ask(world, "admin", "студенты К64/2")["text"]
    assert "Жамбалов" not in other and "Цыдыпов" in other


def test_admin_summary_speaks_about_the_college_not_his_own_group(world, llm_spy):
    """🔥 Дословный дефект: «сводка группы» → «в вашей группе 26 студентов»."""
    for q in ("сводка группы", "средний балл", "сколько студентов", "студенты"):
        a = _ask(world, "admin", q)
        low = a["text"].lower()
        assert "вашей групп" not in low and "твоей групп" not in low, (q, a["text"])
        assert "колледж" in low, (q, a["text"])
    assert "4" in _ask(world, "admin", "студенты")["text"]   # студентов всего четверо
    one = _ask(world, "admin", "сводка по группе К74/1")
    assert one["text"].startswith("Сводка — К74/1: студентов 3"), one["text"]


def test_admin_answers_never_go_through_the_model(world, llm_spy):
    """Админские ответы НЕ озвучиваются: модель искажала СМЫСЛ сводки («ваша группа»),
    а не только стиль. Проверяем свойство на всём наборе вопросов, а не на одном."""
    for q in ("сводка группы", "студенты", "студенты к74/1", "должники", "зона риска",
              "пропуски", "преподаватели", "группы", "Жамбалов", "сводка по группе К74/1"):
        _ask(world, "admin", q)
    assert llm_spy == [], llm_spy


def test_names_never_reach_the_model_through_translation_or_chat(world, monkeypatch):
    """🔒 Не озвучивается ≠ не уходит наружу (29.09.2026). На английском интерфейсе ответ со
    списком группы переводился моделью ЦЕЛИКОМ, а свободная болтовня получала вопрос с
    чужой фамилией дословно. Проверяем оба пути модели: перевод (`complete`) и болтовню."""
    from app import vector_llm
    sent = []
    monkeypatch.setattr(vector_llm, "complete",
                        lambda cfg, messages, temperature=0.3: sent.append(str(messages)) or "")
    monkeypatch.setattr(vector_llm, "free_chat",
                        lambda cfg, q, role="student", context="", locale="ru": sent.append(q) or "x")
    r = world["client"].post("/me/prefs", json={"locale": "en", "locale_on": True},
                             headers=world["admin"])
    assert r.status_code == 200, r.text
    text = _ask(world, "admin", "студенты к74/1")["text"]
    assert "Жамбалов" in text, text                      # ответ есть — по-русски
    _ask(world, "student", "как там Жамбалов поживает")  # болтовня с чужой фамилией
    leaked = [s for s in sent if "Жамбалов" in s or "Цыдыпов" in s or "Очиров" in s]
    assert not leaked, leaked


def test_admin_debtors_are_filtered_by_group_and_name_the_subject(world):
    a = _ask(world, "admin", "должники К74/1")
    assert a["intent"] == "debtors" and "Жамбалов" in a["text"], a["text"]
    #Долг назван вместе с ПРЕДМЕТОМ — без него пять одинаковых «практика №2» читались
    #как глюк (находка живого прогона).
    assert "Математика: " in a["text"] and "Физика: " in a["text"], a["text"]
    assert _ask(world, "admin", "должники К64/2")["text"].startswith("Должников в группе К64/2 нет")


def test_admin_asks_to_clarify_namesakes_instead_of_guessing(world):
    a = _ask(world, "admin", "Цыдыпов")
    assert "несколько" in a["text"] and G1 in a["text"] and G2 in a["text"], a["text"]
    card = _ask(world, "admin", "Цыдыпов К64/2")["text"]
    assert card.startswith("Цыдыпов Батор Баирович (К64/2)"), card
    assert "средний балл 3" in card, card


def test_admin_teachers_include_the_portal_ones(world, monkeypatch):
    """Преподаватели, которых нет в журнале, но которые ведут пары по расписанию портала,
    Вектору теперь известны. Уже заведённый (сопоставленный) не дублируется."""
    from app import schedule_web

    lesson = lambda subject, teacher: types.SimpleNamespace(subject=subject, teacher=teacher)  # noqa: E731
    #Живые формы ячеек портала: хвост предмета прилип к фамилии («ПО ПОРТАЛОВ П.П.») и
    #обрезанное название того же предмета; «Преподаватель» — заглушка, а не человек.
    sched = types.SimpleNamespace(all_lessons=lambda: [
        (1, "Пнд", lesson("Математика", "ОРЛОВА А.П.")),
        (1, "Втр", lesson("Физика", "ПОРТАЛОВ П.П.")),
        (1, "Срд", lesson("Технология разработки", "ПО ПОРТАЛОВ П.П.")),
        (1, "Чтв", lesson("Технология разработки ПО", "ПОРТАЛОВ П.П.")),
        (1, "Птн", lesson("История", "Преподаватель"))])
    snap = types.SimpleNamespace(groups={G1: sched})
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": (snap, False))
    text = _ask(world, "admin", "преподаватели")["text"]
    assert "Орлова Анна Петровна" in text and "ПОРТАЛОВ П.П." in text, text
    assert "ОРЛОВА А.П." not in text and "ПО ПОРТАЛОВ" not in text, text
    assert "без учётной записи: ПОРТАЛОВ П.П.." in text, text     # один, без заглушки
    by_group = _ask(world, "admin", "преподаватели К74/1")["text"]
    assert "ПОРТАЛОВ П.П. — Технология разработки ПО, Физика" in by_group, by_group
    assert "ПРЕПОДАВАТЕЛЬ" not in by_group.upper().replace("ПРЕПОДАВАТЕЛИ", ""), by_group


# ── преподаватель, модератор, студент, родитель ────────────────────────────────────

def test_teacher_is_greeted_by_first_name_and_patronymic(world):
    a = _ask(world, "teacher", "привет")
    assert a["text"].startswith("Здравствуйте, Анна Петровна!"), a["text"]
    #Одно обращение на роль: «вы» без «ты» (находка: «Здравствуйте!… Спрашивай»).
    import re
    assert not re.search(r"\bСпрашивай\b|\bтвоих\b", a["text"]), a["text"]


def test_login_response_carries_the_greeting_name(world):
    r = world["client"].post("/auth/login", json={"login": "t1", "password": "teachpass1"})
    assert r.json()["greet_name"] == "Анна Петровна"
    r = world["client"].post("/auth/login", json={"login": "a1", "password": "studpass1"})
    assert r.json()["greet_name"] == "Батор"


def test_curator_without_load_still_sees_the_curated_group(world):
    """Куратор К74/1 не ведёт там ни одного предмета — раньше Вектор отвечал «за вами нет
    групп», хотя на странице «Курирование» группа видна."""
    a = _ask(world, "teacher", "студенты К74/1")
    assert a["intent"] == "roster" and "Жамбалов" in a["text"], a["text"]
    alien = _ask(world, "teacher", "студенты К99/9")      # группа есть, но чужая
    assert "не ваша" in alien["text"] and "Жамбалов" not in alien["text"], alien["text"]


def test_risk_zone_in_vector_matches_the_curator_dashboard(world):
    """Одно правило «в зоне риска» на дашборд и на Вектора (`W.counts_as_at_risk`).
    Сверяем с НАСТОЯЩИМ ответом дашборда, а не с формулой, повторённой в тесте."""
    board = world["client"].get("/web/teacher/summary", headers=world["teacher"]).json()
    curated = [g for g in board.get("curator_groups", []) if g["group"] == G1]
    assert curated, board
    expected = curated[0]["at_risk"]
    assert expected >= 1, "в данных теста обязан быть студент в зоне риска"
    text = _ask(world, "teacher", "сводка по группе К74/1")["text"]
    assert f"в зоне риска {expected}" in text, (expected, text)
    admin_text = _ask(world, "admin", "сводка по группе К74/1")["text"]
    assert f"в зоне риска {expected}" in admin_text, (expected, admin_text)


def test_moderator_is_not_answered_as_a_student(world):
    a = _ask(world, "moder", "сколько студентов")
    assert "твой средний" not in a["text"].lower() and "для преподавателя" not in a["text"]
    assert _ask(world, "moder", "привет")["text"].startswith("Здравствуйте, Матвей Олегович!")


def test_student_overview_counts_homework_marks_like_the_vector_panel(world):
    """Главная студента считала оценки своим циклом по литералу «Практика» и не видела ДЗ:
    «оценок 25» на главной против 30 в панели Вектора (живой прогон 28.09.2026)."""
    from app.db import default_term
    ty, ts = default_term()
    r = world["client"].post("/sync/push", json={"changes": {
        "lessons": [{"id": "hw1", "group_name": G1, "subject": "Математика", "type": "ДЗ",
                     "number": 1, "topic": "задачи", "date": "20.09.2026", "year": ty,
                     "semester": ts}],
        "grades": [{"id": "stud:a1|hw1", "student_id": "stud:a1", "student_f": "Цыдыпов",
                    "student_n": "Батор Баирович", "lesson_id": "hw1", "grade": "5"}]}},
        headers=world["admin"])
    assert r.status_code == 200, r.text
    body = world["client"].get("/web/student/overview", headers=world["student"]).json()
    math = next(s for s in body["subjects"] if s["subject"] == "Математика")
    assert math["grades"] == 5, math          # 4 практики + ДЗ


def test_admin_overview_separates_active_groups_from_the_catalog(world):
    """«Групп 327» при 26 студентах читалось как ошибка: в справочнике весь каталог
    портала. Панель показывает группы СО СТУДЕНТАМИ, справочник — отдельным числом."""
    body = world["client"].get("/web/admin/overview", headers=world["admin"]).json()
    assert body["groups"] == 3 and body["groups_active"] == 2, body


def test_student_debts_name_the_subject(world):
    a = _ask(world, "student", "привет")
    assert a["text"].startswith("Привет, Батор!"), a["text"]
    assert "для преподавателя" in _ask(world, "student", "кто в группе")["text"]


def test_parent_greeting_addresses_the_parent_not_the_child(world):
    from app.db import SessionLocal
    from app.models import User
    from app.routers.web.vector import answer_vector_question

    parent = types.SimpleNamespace(role="parent", name="Ольга Николаевна",
                                   patronymic="Николаевна",
                                   full_name="Цыдыпова Ольга Николаевна")
    with SessionLocal() as db:
        child = db.get(User, "stud:a1")
        text = answer_vector_question("привет", child, db, voice_role="parent",
                                      addressee=parent)["text"]
    assert text.startswith("Здравствуйте, Ольга Николаевна!"), text
    assert "Батор" not in text, text


def test_curator_without_load_is_answered_about_a_student_by_surname(world):
    """Куратор К74/1 не ведёт там предметов (ревью 30.09.2026): фамилия студента
    курируемой группы не попадала в список опознаваемых, и «пропуски у Жамбалова»
    уходили в общий ответ вместо карточки студента. Предмет курируемой группы, которого
    куратор сам не ведёт («по физике»), обязан опознаваться тем же путём."""
    a = _ask(world, "teacher", "пропуски у Жамбалова")
    assert a["intent"] == "absences", a
    assert a["facts"].get("student", "").startswith("Жамбалов"), a
    assert a["facts"].get("всего") == 4, a
    b = _ask(world, "teacher", "оценки Жамбалова по физике")
    assert b["facts"].get("student", "").startswith("Жамбалов"), b
    assert b["facts"].get("subject") == "Физика", b
