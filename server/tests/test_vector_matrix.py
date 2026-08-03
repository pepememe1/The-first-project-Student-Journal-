"""
test_vector_matrix.py — «Вектор» по матрице: каждый интент × каждая роль × живые
формулировки, включая подвохи.

━━ ЗАЧЕМ ИМЕННО МАТРИЦА ━━
Точечные тесты проверяют, что удачная формулировка работает. Ломается же обратное: одна
новая основа в лексиконе перетягивает на себя чужие вопросы, и это видно только когда
проверяешь ВСЕ интенты разом. Так и нашлись дефекты, ради которых написан этот файл:

  • «что задали по физике» отвечало СПИСКОМ ОЦЕНОК. Интента «домашнее задание» не
    существовало, а классификатор при распознанном предмете принудительно превращает
    unknown в subject_grades — то есть Вектор уверенно отвечал не на тот вопрос.
    Неверный ответ хуже честного «не понял»: его читают и уходят с ложным знанием.
  • «что мне пересдавать» уходило в unknown: основа «пересдач» не ловит «пересдавать».
  • «покажи журнал», «помоги», «откуда берётся средний балл» — то же самое.

━━ ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ, А ЧТО НЕТ ━━
Формулировки ответа не проверяем — она меняется. Проверяем ТРИ вещи, каждая из которых
уже ломалась: правильно ли понят вопрос, не утекают ли чужие данные и не отвечает ли
Вектор уверенно не на тот вопрос.
"""
import pytest

from conftest import make_admin, make_teacher, assign_teacher

import vector_nlu


# ═══ ЧАСТЬ 1. Разбор запроса (чистый, без базы) ═══════════════════════════════════
SUBJECTS = ["Математика", "Физика", "Информатика", "История"]
SURNAMES = ["Иванова", "Петров", "Дугаров"]

#(вопрос, ожидаемый интент). Ожидание — то, что человек ИМЕЛ В ВИДУ.
PHRASINGS = [
    # приветствие и служебное
    ("привет", "hello"), ("здравствуйте", "hello"), ("добрый день", "hello"),
    ("спасибо", "thanks"), ("спс большое", "thanks"), ("благодарю", "thanks"),
    ("что ты умеешь", "help"), ("кто ты", "help"), ("помоги", "help"),
    # средний балл
    ("какой у меня средний балл", "average"), ("мой средний", "average"),
    ("как я учусь в среднем", "average"), ("средняя оценка", "average"),
    # ПОДВОХ: процедурный вопрос не должен утекать в average
    ("как считается средний балл", "howto"),
    ("откуда берётся средний балл", "howto"),
    ("что такое долг", "howto"),
    # оценки
    ("покажи мои оценки", "grades"), ("что у меня в журнале", "grades"),
    ("покажи журнал", "grades"), ("какие у меня отметки", "grades"),
    ("какие оценки по физике", "subject_grades"),
    ("что у меня по математике", "subject_grades"),
    # СПИСОК ПРЕДМЕТОВ — раньше интента не было, и вопрос уверенно отвечал списком
    # предметов С ОЦЕНКАМИ (утекал в grades), то есть молча терял всё, что импортировано
    # из учебного плана и ещё не обросло занятиями.
    ("какие у меня предметы", "subjects"), ("мои предметы", "subjects"),
    ("список предметов", "subjects"), ("что я изучаю", "subjects"),
    ("какие дисциплины в этом семестре", "subjects"),
    ("сколько у меня предметов", "subjects"),
    # счёт
    ("сколько у меня оценок", "grade_count"), ("сколько двоек", "grade_count"),
    ("сколько всего оценок", "grade_count"), ("количество оценок", "grade_count"),
    # долги и пропуски
    ("есть ли у меня долги", "debtors"), ("что мне пересдавать", "debtors"),
    ("у кого хвосты", "debtors"), ("что не сдано", "debtors"),
    ("сколько я пропустил", "absences"), ("мои пропуски", "absences"),
    ("сколько прогулов", "absences"),
    # расписание
    ("какое сегодня расписание", "schedule"), ("что завтра", "schedule"),
    ("когда физика", "schedule"), ("во сколько первая пара", "schedule"),
    ("сколько пар сегодня", "schedule"),
    # ДОМАШНЕЕ ЗАДАНИЕ — раньше не существовало вовсе
    ("что задали", "homework"), ("что задали на дом", "homework"),
    ("какое домашнее задание", "homework"), ("есть ли дз", "homework"),
    ("что задали по физике", "homework"), ("сколько дз", "homework"),
    # справочники
    ("какая у меня группа", "groups"), ("какие есть группы", "groups"),
    ("кто в моей группе", "roster"), ("сколько студентов в группе", "roster"),
    ("кто ведет математику", "teachers"), ("сколько преподавателей", "teachers"),
    ("сколько у нас студентов", "group_stats"), ("общая сводка", "group_stats"),
    ("кто в зоне риска", "at_risk"), ("кого могут отчислить", "at_risk"),
    # ЗЕТ, погода, о заведении
    ("сколько у меня зет", "zet"), ("хватит ли зет для перевода", "zet"),
    ("какая погода", "weather"), ("сколько градусов на улице", "weather"),
    ("расскажи про колледж", "about_college"), ("что такое всгуту", "about_vsgutu"),
    # СОСТОЯНИЕ СЕРВЕРА (админское)
    ("сколько места на диске", "server_state"), ("что с сервером", "server_state"),
    ("когда был последний бэкап", "server_state"), ("размер базы", "server_state"),
]


@pytest.mark.parametrize("question,expected", PHRASINGS)
def test_question_is_understood(question, expected):
    got = vector_nlu.classify(question, surnames=SURNAMES, subjects=SUBJECTS)
    assert got["intent"] == expected, (
        f"«{question}»: ждали {expected}, получили {got['intent']}")


def test_homework_about_a_subject_is_not_answered_with_grades():
    """Главный подвох: при распознанном предмете классификатор принудительно превращает
    unknown в subject_grades. Пока интента ДЗ не было, «что задали по физике» отвечало
    списком ОЦЕНОК — уверенно и мимо вопроса."""
    got = vector_nlu.classify("что задали по физике", subjects=SUBJECTS)
    assert got["intent"] == "homework"
    assert got["subject"] == "Физика", "предмет обязан распознаться и здесь"


def test_short_words_do_not_match_inside_other_words():
    """«дз» без границ слова матчится внутри «наДЗор» и «поДЗаголовок». Такие ложные
    срабатывания хуже пропусков: человек получает ответ не на свой вопрос."""
    for word in ("надзор", "подзаголовок", "надзорный орган"):
        assert vector_nlu.classify(word)["intent"] != "homework", word


def test_every_intent_in_lexicon_is_reachable():
    """Каждый интент лексикона обязан набираться хотя бы одной живой формулировкой.
    Недостижимый интент — мёртвый код, который выглядит как работающая фича."""
    covered = {expected for _q, expected in PHRASINGS}
    missing = set(vector_nlu.INTENT_STEMS) - covered
    assert not missing, f"интенты без единой проверенной формулировки: {sorted(missing)}"


# ═══ ЧАСТЬ 2. Ответы по ролям (с базой) ═══════════════════════════════════════════
def _seed(client, admin):
    """Группа, студент, занятия (практика + ДЗ), преподаватель по предмету."""
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L1", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 1, "topic": "Пределы", "date": "01.09.2025"},
        {"id": "H1", "group_name": "ИС-21", "subject": "Математика", "type": "ДЗ",
         "number": 1, "topic": "Задачи 1-10 из учебника", "date": "02.09.2025"},
    ]}}, headers=admin)
    teach = make_teacher(client, admin, subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")
    return teach


def _student(client):
    r = client.post("/auth/login", json={"login": "ivanova", "password": "studpass1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _ask(client, headers, question):
    r = client.post("/web/vector/ask", json={"message": question}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_student_gets_homework_not_grades(client):
    """Сквозная проверка того же дефекта: студент спрашивает про домашку и получает
    ТЕКСТ ЗАДАНИЯ, а не свои оценки."""
    admin = make_admin(client)
    _seed(client, admin)
    sh = _student(client)
    body = _ask(client, sh, "что задали по математике")
    assert body["intent"] == "homework", body
    assert "Задачи 1-10" in body["text"], body["text"]


def test_homework_text_is_not_rewritten_by_the_model(client):
    """Текст задания написал преподаватель — человек обязан прочитать его дословно.
    Перефразированная домашка это уже другая домашка."""
    from app.routers import web
    assert "homework" in web._NO_VOICE_INTENTS


def test_student_never_sees_server_state(client):
    """Про сервер студенту знать незачем. Важнее другое: без явной ветки этот вопрос
    проваливался бы в средний балл — уверенный ответ не на тот вопрос."""
    admin = make_admin(client)
    _seed(client, admin)
    sh = _student(client)
    body = _ask(client, sh, "сколько места на диске")
    assert body["intent"] != "server_state"
    assert "средний балл" not in body["text"].lower() or "администратор" in body["text"].lower()
    assert body["facts"].get("disk") is None


def test_student_never_sees_other_students(client):
    """Скоуп студента: списки группы, преподаватели и сводки — не его данные."""
    admin = make_admin(client)
    _seed(client, admin)
    sh = _student(client)
    for question in ("кто в зоне риска", "список студентов", "сколько преподавателей",
                     "общая сводка по колледжу"):
        body = _ask(client, sh, question)
        assert body["intent"] in ("help", "groups"), f"{question} → {body['intent']}"
        assert not body["facts"].get("students"), question


def test_teacher_homework_is_scoped_to_own_subjects(client):
    """Преподаватель видит ДЗ, которое задал САМ: чужие предметы в его ответе — утечка
    учебного процесса другой кафедры."""
    admin = make_admin(client)
    teach = _seed(client, admin)
    #Чужой предмет в той же группе — препод его не ведёт.
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "H2", "group_name": "ИС-21", "subject": "История", "type": "ДЗ",
         "number": 1, "topic": "Параграф 5 про Петра", "date": "03.09.2025"}]}},
        headers=admin)
    body = _ask(client, teach, "что я задал")
    assert body["intent"] == "homework", body
    assert "Задачи 1-10" in body["text"]
    assert "Петра" not in body["text"], "в ответ попало ДЗ по чужому предмету"


def test_admin_gets_server_state_with_real_numbers(client):
    """Состояние сервера — такой же факт, как средний балл: берётся у машины, не
    выдумывается. Проверяем, что цифры реальные и приехали в facts."""
    admin = make_admin(client)
    body = _ask(client, admin, "что с сервером")
    assert body["intent"] == "server_state", body
    assert body["facts"]["disk"]["total"] > 0
    assert "db_encrypted" in body["facts"]


def test_admin_asking_about_homework_is_not_given_counters(client):
    """Раньше любой неподходящий вопрос у админа проваливался в счётчики: на «что
    задали» приходило «студентов — 47». Уверенный ответ не на тот вопрос."""
    admin = make_admin(client)
    _seed(client, admin)
    body = _ask(client, admin, "что задали")
    assert body["intent"] == "help", body
    assert "студентов —" not in body["text"]


def test_admin_counts_include_what_requires_action(client):
    """Сводка админа обязана называть заявки на регистрацию: о них иначе узнают, только
    вспомнив зайти на нужную страницу."""
    admin = make_admin(client)
    _seed(client, admin)
    body = _ask(client, admin, "сколько у нас студентов")
    assert body["intent"] == "group_stats", body
    for key in ("students", "teachers", "parents", "groups", "subjects",
                "pending_registrations"):
        assert key in body["facts"], key


def test_admin_risk_uses_the_shared_calculation(client):
    """Долги считаются теми же webdata, что и у преподавателя: своя формула означала бы
    разные списки должников по одному студенту на разных экранах (§4.8)."""
    admin = make_admin(client)
    _seed(client, admin)
    body = _ask(client, admin, "у кого долги")
    assert body["intent"] == "debtors", body
    assert "count" in body["facts"]


def test_no_answer_contains_model_placeholders(client):
    """§5: статичные и структурные интенты в LLM не уходят, иначе модель «озвучивает
    данные» и дописывает «[укажите средние баллы]» — ровно то, что продукт обещает не
    делать."""
    admin = make_admin(client)
    _seed(client, admin)
    sh = _student(client)
    for headers in (sh, admin):
        for question in ("привет", "что ты умеешь", "что задали", "какое расписание",
                         "что с сервером", "расскажи про колледж"):
            text = _ask(client, headers, question)["text"]
            for bad in ("[", "укажите", "ваши данные", "вставьте"):
                assert bad not in text.lower(), f"«{question}» → {text}"
