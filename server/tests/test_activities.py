"""
test_activities.py — «Активности» в беседах (docs/PLAN-ACTIVITIES.md §11).

Проверяем не «эндпоинт отвечает 200», а инварианты, которые дороже всего сломать:
ключ викторины не уезжает студенту, автор отзыва не виден преподавателю, вторая
активность в беседе не запускается, повторная отправка не сдваивает результат.
"""
from conftest import make_admin, make_teacher
from test_messenger import _make_student

A = "/web/messenger/activities"


def _setup(client):
    admin = make_admin(client)
    t = make_teacher(client, admin)
    b_id, b = _make_student(client, admin, "bob", "Боб Бобов")
    c_id, c = _make_student(client, admin, "carol", "Кэрол Кэрова")
    return admin, ("teach:teacher1", t), (b_id, b), (c_id, c)


def _group(client, headers, member_ids, title="Группа"):
    return client.post("/web/messenger/chats/group",
                       json={"title": title, "member_ids": member_ids},
                       headers=headers).json()["conversation_id"]


def _quiz(client, headers, questions=None, title="Дроби", tags=None):
    body = {"title": title, "tags": tags if tags is not None else ["Математика", " дроби "],
            "questions": questions if questions is not None else [
                {"type": "single", "text": "2+2?", "points": 1,
                 "options": [{"text": "4", "is_correct": True}, {"text": "5"}]},
            ]}
    r = client.post(f"{A}/quizzes", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _start(client, headers, conv, kind, params=None, title=""):
    return client.post(f"{A}/start", headers=headers,
                       json={"conversation_id": conv, "kind": kind,
                             "params": params or {}, "title": title})


# ── Права и границы ──────────────────────────────────────────────────────────────────
def test_teacher_can_start_without_any_conversation_role(client):
    """Преподаватель ведёт занятие, а не администрирует чат: системная роль даёт право
    запуска и в беседе, которую создал кто-то другой."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, admin, [t_id, b_id])       #владелец — админ, преподаватель просто участник
    r = _start(client, t, conv, "timer", {"duration_s": 300})
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "timer"


def test_student_cannot_start(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    assert _start(client, b, conv, "timer", {"duration_s": 60}).status_code == 403


def test_student_with_granted_permission_can_start(client):
    """Владелец беседы вправе выдать право старосте — через уже существующий редактор ролей."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    role = client.post(f"/web/messenger/chats/{conv}/roles",
                       json={"name": "Староста", "permissions": ["activities"]},
                       headers=t).json()["id"]
    client.post(f"/web/messenger/chats/{conv}/members/{b_id}/role",
                json={"custom_role_id": role}, headers=t)
    assert _start(client, b, conv, "timer", {"duration_s": 60}).status_code == 200


def test_no_activities_in_direct_chat(client):
    """В личном чате активность бессмысленна: там один собеседник."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}",
                       headers=t).json()["conversation_id"]
    r = _start(client, t, conv, "timer", {"duration_s": 60})
    assert r.status_code == 403
    assert "групп" in r.json()["detail"].lower()


def test_second_activity_in_same_conversation_is_refused(client):
    """Вторая параллельная — гонка за экран студента и два источника правды «что идёт»."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    assert _start(client, t, conv, "timer", {"duration_s": 60}, "Первая").status_code == 200
    r = _start(client, t, conv, "poll",
               {"question": "Понятно?", "options": ["Да", "Нет"]})
    assert r.status_code == 409
    assert "Первая" in r.json()["detail"]      #называем ТЕКУЩУЮ, иначе отказ непонятен


def test_finishing_frees_the_conversation(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _start(client, t, conv, "timer", {"duration_s": 60}).json()["id"]
    assert client.post(f"{A}/{a}/finish", json={}, headers=t).status_code == 200
    assert _start(client, t, conv, "timer", {"duration_s": 60}).status_code == 200


def test_only_host_can_finish(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _start(client, t, conv, "timer", {"duration_s": 60}).json()["id"]
    assert client.post(f"{A}/{a}/finish", json={}, headers=b).status_code == 403


# ── Ключ викторины ───────────────────────────────────────────────────────────────────
def test_student_never_receives_the_answer_key(client):
    """🔒 ГЛАВНЫЙ тест категории. Получив ключ, студент прочитает его в инструментах
    разработчика до начала. Проверяем не «поле пустое», а что его НЕТ ВООБЩЕ: пустое
    поле в JSON тоже сообщает, где ключ."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _quiz(client, t)
    a = _start(client, t, conv, "quiz", {"quiz_id": quiz}).json()["id"]
    body = client.get(f"{A}/{a}/questions", headers=b).json()
    assert body["questions"], body
    for q in body["questions"]:
        for opt in q["options"]:
            assert "is_correct" not in opt
            assert "correct_position" not in opt
            assert "match_key" not in opt
    #И в сыром тексте ответа тоже — на случай, если ключ протечёт другим полем.
    raw = client.get(f"{A}/{a}/questions", headers=b).text
    assert "is_correct" not in raw


def test_host_also_gets_questions_without_key(client):
    """Ведущему ключ здесь не нужен (он смотрит свою викторину в конструкторе), а ветка
    «а хосту отдадим с ключом» превратилась бы в вопрос «а точно ли это хост» ровно там,
    где ошибиться дороже всего."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _quiz(client, t)
    a = _start(client, t, conv, "quiz", {"quiz_id": quiz}).json()["id"]
    assert "is_correct" not in client.get(f"{A}/{a}/questions", headers=t).text


def test_constructor_does_give_the_key_to_the_author(client):
    """Обратная сторона: без ключа в конструкторе викторину нельзя было бы редактировать.
    Без этой проверки «починка» вида «не отдавать ключ никогда» была бы зелёной."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    quiz = _quiz(client, t)
    out = client.get(f"{A}/quizzes/{quiz}", headers=t).json()
    assert out["questions"][0]["options"][0]["is_correct"] is True


# ── Прохождение ──────────────────────────────────────────────────────────────────────
def _two_question_quiz(client, headers):
    return _quiz(client, headers, questions=[
        {"type": "single", "text": "2+2?", "points": 1,
         "options": [{"text": "4", "is_correct": True}, {"text": "5"}]},
        {"type": "multi", "text": "Чётные?", "points": 2,
         "options": [{"text": "2", "is_correct": True}, {"text": "3"},
                     {"text": "4", "is_correct": True}]},
    ])


def _key_of(client, headers, quiz):
    """Правильные ответы из конструктора — тест не должен угадывать их по порядку."""
    out = client.get(f"{A}/quizzes/{quiz}", headers=headers).json()
    key = {}
    for q in out["questions"]:
        correct = [o["id"] for o in q["options"] if o["is_correct"]]
        key[q["id"]] = correct[0] if q["type"] == "single" else correct
    return key


def test_submit_grades_on_the_server(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _two_question_quiz(client, t)
    a = _start(client, t, conv, "quiz", {"quiz_id": quiz}).json()["id"]
    key = _key_of(client, t, quiz)
    r = client.post(f"{A}/{a}/submit", json={"answers": key}, headers=b)
    assert r.status_code == 200, r.text
    assert r.json()["correct_count"] == 2
    assert r.json()["score"] == 3.0            #1 + 2 очка


def test_partially_correct_multi_is_wrong(client):
    """«Всё или ничего» в multi — осознанный выбор, а не упрощение (§8.4 плана)."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _two_question_quiz(client, t)
    a = _start(client, t, conv, "quiz", {"quiz_id": quiz}).json()["id"]
    key = _key_of(client, t, quiz)
    multi_qid = [k for k, v in key.items() if isinstance(v, list)][0]
    key[multi_qid] = key[multi_qid][:1]        #только половина верных
    r = client.post(f"{A}/{a}/submit", json={"answers": key}, headers=b).json()
    assert r["correct_count"] == 1


def test_submit_is_graded_once_and_cannot_be_farmed(client):
    """🔒 Ответ на отправку содержит РАЗБОР («где верно, где нет»). Если пускать вторую
    отправку, ключ не нужен вовсе: шлём пустой набор, читаем из ответа список неверных,
    исправляем, шлём снова — для вопросов с четырьмя вариантами это ≤4 запроса до ста
    баллов, без всяких инструментов разработчика. Поэтому проверка ОДНА, а повтор
    возвращает уже сохранённое."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _two_question_quiz(client, t)
    a = _start(client, t, conv, "quiz", {"quiz_id": quiz}).json()["id"]
    key = _key_of(client, t, quiz)
    first = client.post(f"{A}/{a}/submit", json={"answers": {}}, headers=b).json()
    assert first["correct_count"] == 0
    #Вторая попытка с ПРАВИЛЬНЫМИ ответами не должна поднять балл.
    second = client.post(f"{A}/{a}/submit", json={"answers": key}, headers=b).json()
    assert second["already_submitted"] is True
    assert second["correct_count"] == 0
    res = client.get(f"{A}/{a}/results", headers=t).json()["results"]
    assert len(res) == 1                       #и строка по-прежнему одна
    assert res[0]["correct_count"] == 0


def test_network_retry_gets_its_own_result_back(client):
    """Обратная сторона: сетевой ретрай шлёт ТЕ ЖЕ ответы и обязан получить свой
    результат, а не отказ. Без этой проверки «починка» вида «второй submit — 409»
    выглядела бы правильной и ломала бы человека с дрогнувшей сетью."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _two_question_quiz(client, t)
    a = _start(client, t, conv, "quiz", {"quiz_id": quiz}).json()["id"]
    key = _key_of(client, t, quiz)
    one = client.post(f"{A}/{a}/submit", json={"answers": key}, headers=b)
    two = client.post(f"{A}/{a}/submit", json={"answers": key}, headers=b)
    assert one.status_code == 200 and two.status_code == 200
    assert two.json()["score"] == one.json()["score"] == 3.0


def test_participant_sees_only_own_result(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _two_question_quiz(client, t)
    a = _start(client, t, conv, "quiz", {"quiz_id": quiz}).json()["id"]
    key = _key_of(client, t, quiz)
    client.post(f"{A}/{a}/submit", json={"answers": key}, headers=b)
    client.post(f"{A}/{a}/submit", json={"answers": {}}, headers=c)
    assert len(client.get(f"{A}/{a}/results", headers=t).json()["results"]) == 2
    mine = client.get(f"{A}/{a}/results", headers=c).json()["results"]
    assert len(mine) == 1 and mine[0]["user_id"] == c_id


# ── Опрос ────────────────────────────────────────────────────────────────────────────
def _poll(client, t, conv):
    return _start(client, t, conv, "poll",
                  {"question": "Понятно?", "options": ["Да", "Нет"]}).json()["id"]


def test_poll_results_only_for_creator(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _poll(client, t, conv)
    client.post(f"{A}/{a}/vote", json={"choice": 0}, headers=b)
    assert client.get(f"{A}/{a}/poll-results", headers=b).status_code == 403
    out = client.get(f"{A}/{a}/poll-results", headers=t).json()
    assert out["counts"] == [1, 0]


def test_poll_results_stay_private_after_finish(client):
    """Обещание «распределение видит только преподаватель» не может истекать по времени."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _poll(client, t, conv)
    client.post(f"{A}/{a}/vote", json={"choice": 1}, headers=b)
    client.post(f"{A}/{a}/finish", json={}, headers=t)
    assert client.get(f"{A}/{a}/poll-results", headers=b).status_code == 403


def test_revote_replaces_and_students_see_only_the_counter(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _poll(client, t, conv)
    client.post(f"{A}/{a}/vote", json={"choice": 0}, headers=b)
    client.post(f"{A}/{a}/vote", json={"choice": 1}, headers=b)   #передумал
    assert client.get(f"{A}/{a}/poll-results", headers=t).json()["counts"] == [0, 1]
    state = client.get(f"{A}/{a}", headers=c).json()["state"]["payload"]
    assert state["voted_count"] == 1
    assert "votes" not in state                #карта голосов наружу не уходит


# ── Срез понимания ───────────────────────────────────────────────────────────────────
def test_host_feedback_never_leaks_authors(client):
    """🔑 Автор отзыва в базе ЕСТЬ (иначе жалоба админу никуда не ведёт), но интерфейс
    преподавателя его не видит никогда. Проверяем сырой текст ответа целиком: утечь мог
    бы не только `user_id`, но и любое поле, по которому автора вычисляют."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _start(client, t, conv, "pulse", {"duration_s": 60}).json()["id"]
    client.post(f"{A}/{a}/feedback",
                json={"score": 3, "reason_code": "tempo", "text": "Слишком быстро"},
                headers=b)
    raw = client.get(f"{A}/{a}/feedback", headers=t)
    assert raw.status_code == 200, raw.text
    assert b_id not in raw.text
    assert "user_id" not in raw.text
    body = raw.json()
    assert body["answers"] == 1 and body["items"][0]["text"] == "Слишком быстро"


def test_feedback_report_gives_the_author_to_the_admin(client):
    """Обратная сторона того же: жалоба обязана вести к человеку, иначе она бессмысленна."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _start(client, t, conv, "pulse", {"duration_s": 60}).json()["id"]
    client.post(f"{A}/{a}/feedback", json={"score": 1, "text": "оскорбление"}, headers=b)
    fid = client.get(f"{A}/{a}/feedback", headers=t).json()["items"][0]["id"]
    r = client.post(f"{A}/feedback/{fid}/report", json={"reason_code": "harassment"},
                    headers=t)
    assert r.status_code == 200, r.text
    reports = client.get("/web/admin/messenger/reports", headers=admin).json()["reports"]
    mine = [x for x in reports if x["id"] == r.json()["report_id"]][0]
    assert mine["reported"]["id"] == b_id     #админ видит автора


def test_feedback_report_is_marked_as_not_a_message(client):
    """⚠️ У такого тикета `message_id` — это id строки отзыва, а НЕ сообщения. Без
    `target_kind` админка предложила бы «удалить сообщение», и удалён был бы посторонний
    текст с совпавшим номером."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _start(client, t, conv, "pulse", {"duration_s": 60}).json()["id"]
    client.post(f"{A}/{a}/feedback", json={"score": 2, "text": "плохо"}, headers=b)
    fid = client.get(f"{A}/{a}/feedback", headers=t).json()["items"][0]["id"]
    rid = client.post(f"{A}/feedback/{fid}/report", json={}, headers=t).json()["report_id"]
    reports = client.get("/web/admin/messenger/reports", headers=admin).json()["reports"]
    mine = [x for x in reports if x["id"] == rid][0]
    assert mine["target_kind"] == "activity_feedback"


def test_ordinary_message_report_stays_a_message(client):
    """Обратный ход: старые тикеты остались тем, чем были (умолчание, а не пустое поле)."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    mid = client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "текст"},
                      headers=b).json()["id"]
    client.post("/web/messenger/reports",
                json={"message_id": mid, "reason_code": "spam"}, headers=t)
    reports = client.get("/web/admin/messenger/reports", headers=admin).json()["reports"]
    assert reports[0]["target_kind"] == "message"


# ── Библиотека викторин ──────────────────────────────────────────────────────────────
def test_foreign_quiz_cannot_be_edited_but_can_be_copied(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    other = make_teacher(client, admin, login="teacher2")
    quiz = _quiz(client, t)
    client.put(f"{A}/quizzes/{quiz}", json={"visibility": "college"}, headers=t)
    assert client.put(f"{A}/quizzes/{quiz}", json={"title": "Моё"},
                      headers=other).status_code == 403
    copy = client.post(f"{A}/quizzes/{quiz}/copy", headers=other)
    assert copy.status_code == 200, copy.text
    assert copy.json()["parent_id"] == quiz


def test_copy_chain_is_hidden_while_it_has_one_author(client):
    """Ветки внутри одного преподавателя — его кухня, а не история заимствований.
    Сворачивание делает СЕРВЕР: «скрытая» в UI цепочка всё равно уезжала бы в ответе."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    quiz = _quiz(client, t)
    mine = client.post(f"{A}/quizzes/{quiz}/copy", headers=t).json()["id"]
    assert client.get(f"{A}/quizzes/{mine}/similar", headers=t).json()["chain"] == []
    other = make_teacher(client, admin, login="teacher2")
    client.put(f"{A}/quizzes/{mine}", json={"visibility": "college"}, headers=t)
    theirs = client.post(f"{A}/quizzes/{mine}/copy", headers=other).json()["id"]
    chain = client.get(f"{A}/quizzes/{theirs}/similar", headers=other).json()["chain"]
    assert len(chain) == 3                     #двое авторов — цепочка показывается


def test_tags_are_normalised_so_search_finds_them(client):
    """«матем» / «Математика» / « математика » должны быть одним тегом, иначе поиск по
    тегу перестаёт находить половину библиотеки."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    _quiz(client, t, tags=["  Математика ", "МАТЕМАТИКА", "Дроби"])
    out = client.get(f"{A}/quizzes", params={"tag": "математика"}, headers=t).json()
    assert len(out["quizzes"]) == 1
    assert out["quizzes"][0]["tags"] == ["математика", "дроби"]     #дубль схлопнут


def test_quiz_search_is_case_insensitive_for_cyrillic(client):
    """SQLite без ICU не умеет регистронезависимый LIKE для кириллицы — поиск идёт в
    Python, и это надо проверять, а не подразумевать."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    _quiz(client, t, title="Логарифмы и Дроби")
    assert client.get(f"{A}/quizzes", params={"q": "логарифмы"},
                      headers=t).json()["quizzes"]


def test_student_has_no_access_to_the_library(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    assert client.get(f"{A}/quizzes", headers=b).status_code == 403


# ── Соревнование ─────────────────────────────────────────────────────────────────────
def test_contest_refuses_order_and_match_questions(client):
    """На общем табло спор о цене частично верного ответа недопустим (§8.5)."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _quiz(client, t, questions=[
        {"type": "order", "text": "По порядку", "options": [
            {"text": "раз", "correct_position": 1}, {"text": "два", "correct_position": 2}]},
    ])
    r = _start(client, t, conv, "contest", {"quiz_id": quiz})
    assert r.status_code == 400
    assert "соревновании" in r.json()["detail"].lower()


def test_contest_hides_questions_until_the_host_shows_them(client):
    """Отдать все вопросы сразу значит отдать и те, что ещё не задавали."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _two_question_quiz(client, t)
    a = _start(client, t, conv, "contest", {"quiz_id": quiz}).json()["id"]
    assert client.get(f"{A}/{a}/questions", headers=b).json()["questions"] == []
    client.post(f"{A}/{a}/next", headers=t)
    shown = client.get(f"{A}/{a}/questions", headers=b).json()
    assert len(shown["questions"]) == 1 and shown["index"] == 0


def test_contest_answer_is_accepted_once(client):
    """Второй ответ был бы способом выбрать наугад, а потом исправиться без потери времени."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _two_question_quiz(client, t)
    a = _start(client, t, conv, "contest", {"quiz_id": quiz}).json()["id"]
    client.post(f"{A}/{a}/next", headers=t)
    q = client.get(f"{A}/{a}/questions", headers=b).json()["questions"][0]
    first = client.post(f"{A}/{a}/answer", json={"answer": q["options"][0]["id"]}, headers=b)
    assert first.status_code == 200
    again = client.post(f"{A}/{a}/answer", json={"answer": q["options"][1]["id"]}, headers=b)
    assert again.status_code == 409


def test_contest_scores_survive_the_finish(client):
    """Баллы живут в памяти, пока идёт соревнование, но журнал беседы обязан пережить
    перезапуск — итог переносится в БД один раз, при завершении."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _two_question_quiz(client, t)
    a = _start(client, t, conv, "contest", {"quiz_id": quiz}).json()["id"]
    client.post(f"{A}/{a}/next", headers=t)
    q = client.get(f"{A}/{a}/questions", headers=b).json()["questions"][0]
    correct = [o for o in q["options"] if o["text"] == "4"][0]["id"]
    client.post(f"{A}/{a}/answer", json={"answer": correct}, headers=b)
    client.post(f"{A}/{a}/finish", json={}, headers=t)
    res = client.get(f"{A}/{a}/results", headers=t).json()["results"]
    assert len(res) == 1 and res[0]["score"] > 0


# ── Доска ────────────────────────────────────────────────────────────────────────────
def test_only_pen_holder_can_draw(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _start(client, t, conv, "board", {"sheet": "grid"}).json()["id"]
    assert client.post(f"{A}/{a}/strokes", json={"strokes": [{"p": [1, 2]}]},
                       headers=b).status_code == 403
    client.post(f"{A}/{a}/pen", json={"user_id": b_id}, headers=t)
    assert client.post(f"{A}/{a}/strokes", json={"strokes": [{"p": [1, 2]}]},
                       headers=b).status_code == 200


def test_board_is_saved_only_when_asked(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _start(client, t, conv, "board", {}).json()["id"]
    client.post(f"{A}/{a}/strokes", json={"strokes": [{"p": [1, 2]}]}, headers=t)
    client.post(f"{A}/{a}/finish", json={"save": False}, headers=t)
    assert client.get(f"{A}/boards", params={"conversation_id": conv},
                      headers=t).json()["boards"] == []


def test_saved_board_can_be_continued_with_its_strokes(client):
    """Продолжить можно ТОЛЬКО штрихами — поверх растра рисуют заново (§8.1)."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _start(client, t, conv, "board", {"sheet": "lined"}).json()["id"]
    client.post(f"{A}/{a}/strokes", json={"strokes": [{"p": [1, 2]}, {"p": [3, 4]}]}, headers=t)
    client.post(f"{A}/{a}/finish", json={"save": True}, headers=t)
    board = client.get(f"{A}/boards", params={"conversation_id": conv},
                       headers=t).json()["boards"][0]
    assert board["strokes_count"] == 2
    again = _start(client, t, conv, "board", {"continue_board_id": board["id"]}).json()
    assert len(again["state"]["payload"]["strokes"]) == 2
    assert again["state"]["payload"]["sheet"] == "lined"


def test_board_from_another_conversation_is_not_picked_up(client):
    """id доски из чужой группы не должен подтягивать её содержимое сюда."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv1 = _group(client, t, [b_id], title="Первая")
    conv2 = _group(client, t, [c_id], title="Вторая")
    a = _start(client, t, conv1, "board", {}).json()["id"]
    client.post(f"{A}/{a}/strokes", json={"strokes": [{"p": [9, 9]}]}, headers=t)
    client.post(f"{A}/{a}/finish", json={"save": True}, headers=t)
    board_id = client.get(f"{A}/boards", params={"conversation_id": conv1},
                          headers=t).json()["boards"][0]["id"]
    out = _start(client, t, conv2, "board", {"continue_board_id": board_id}).json()
    assert out["state"]["payload"]["strokes"] == []


def test_snapshot_does_not_finish_the_board(client):
    """На доске много написано, и снимок не должен закрывать пару."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _start(client, t, conv, "board", {}).json()["id"]
    client.post(f"{A}/{a}/strokes", json={"strokes": [{"p": [1, 1]}]}, headers=t)
    assert client.post(f"{A}/{a}/snapshot", headers=t).status_code == 200
    assert client.get(f"{A}/{a}", headers=t).json()["status"] == "running"


# ── Карточка в ленте и команда ───────────────────────────────────────────────────────
def test_activity_command_leaves_no_literal_in_the_feed(client):
    """`/активность` — команда, а не сообщение: литерал в ленте не оседает."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": "/активность"}, headers=t)
    assert r.status_code == 200, r.text
    assert r.json()["command"] == "open_activity_launcher"
    msgs = client.get(f"/web/messenger/chats/{conv}/messages", headers=t).json()["messages"]
    assert not any("/активность" in (m.get("body") or "") for m in msgs)


def test_activity_command_is_refused_to_students_before_they_choose(client):
    """Иначе студент узнал бы, что ему нельзя, уже ПОСЛЕ выбора категории."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": "/активность"}, headers=b)
    assert r.status_code == 403


def test_feed_card_carries_the_activity_object(client):
    """В теле сообщения лежит только id — объект подмешивает сервер, потому что статус
    меняется ПОСЛЕ отправки."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    a = _start(client, t, conv, "timer", {"duration_s": 60}, "Пятиминутка").json()["id"]
    msgs = client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"]
    card = [m for m in msgs if m["kind"] == "activity"][0]
    assert card["activity"]["id"] == a
    assert card["activity"]["status"] == "running"
    client.post(f"{A}/{a}/finish", json={}, headers=t)
    msgs = client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"]
    card = [m for m in msgs if m["kind"] == "activity"][0]
    assert card["activity"]["status"] == "finished"    #кнопка гаснет по статусу


def test_chat_list_preview_also_resolves_the_card(client):
    """Превью последнего сообщения — то место, куда заглядывают реже всего, и именно там
    сырой `act:9f3…` жил бы дольше всего незамеченным."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    _start(client, t, conv, "timer", {"duration_s": 60}, "Пятиминутка")
    chats = client.get("/web/messenger/chats", headers=b).json()["chats"]
    row = [x for x in chats if x["conversation_id"] == conv][0]
    assert row["last_message"]["activity"]["title"] == "Пятиминутка"


# ── Журнал беседы ────────────────────────────────────────────────────────────────────
def test_journal_full_for_host_and_own_rows_for_participant(client):
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    quiz = _two_question_quiz(client, t)
    a = _start(client, t, conv, "quiz", {"quiz_id": quiz}).json()["id"]
    client.post(f"{A}/{a}/submit", json={"answers": _key_of(client, t, quiz)}, headers=b)
    client.post(f"{A}/{a}/finish", json={}, headers=t)
    full = client.get(f"{A}/journal", params={"conversation_id": conv}, headers=t).json()
    assert full["full"] is True and full["items"][0]["participants"] == 1
    mine = client.get(f"{A}/journal", params={"conversation_id": conv}, headers=b).json()
    assert mine["full"] is False and mine["items"][0]["my_correct"] == 2
    #Кэрол не участвовала — в её журнале этой активности нет вовсе.
    theirs = client.get(f"{A}/journal", params={"conversation_id": conv}, headers=c).json()
    assert theirs["items"] == []


# ── Маршрутизация ────────────────────────────────────────────────────────────────────
def test_single_segment_routes_are_not_shadowed(client):
    """⚠️ `GET /{activity_id}` — параметр без ограничений: объяви его выше, и `/quizzes`,
    `/journal`, `/boards` начнут отвечать «Активность не найдена» при исправном коде и
    зелёных тестах на сами эти эндпоинты. Проверяем именно ЭТО, а не их работу."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    for path, params in ((f"{A}/quizzes", {}),
                         (f"{A}/journal", {"conversation_id": conv}),
                         (f"{A}/boards", {"conversation_id": conv}),
                         (f"{A}/current", {"conversation_id": conv})):
        r = client.get(path, params=params, headers=t)
        assert r.status_code == 200, f"{path} перехвачен чужим обработчиком: {r.text}"
        assert "Активность не найдена" not in r.text


# ── Границы карточки (возражения Полковника, 15.08.2026) ─────────────────────────────
def test_activity_card_cannot_be_forwarded_to_another_conversation(client):
    """Карточка привязана к своей беседе: снаружи она не открывается (403), то есть в
    чужой ленте повисла бы нерабочая кнопка — а вместе с ней уехали бы заголовок и
    статус (заголовок пишет преподаватель, там бывает тема контрольной)."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv1 = _group(client, t, [b_id], title="Первая")
    conv2 = _group(client, t, [c_id], title="Вторая")
    _start(client, t, conv1, "timer", {"duration_s": 60}, "Контрольная по дробям")
    msgs = client.get(f"/web/messenger/chats/{conv1}/messages", headers=t).json()["messages"]
    card = [m for m in msgs if m["kind"] == "activity"][0]
    client.post("/web/messenger/messages/forward",
                json={"message_ids": [card["id"]], "to_conversation_ids": [conv2]}, headers=t)
    there = client.get(f"/web/messenger/chats/{conv2}/messages", headers=t).json()["messages"]
    assert not any(m["kind"] == "activity" for m in there)
    assert not any("Контрольная по дробям" in (m.get("body") or "") for m in there)


def test_card_object_is_not_attached_outside_its_own_conversation(client):
    """Оборона в глубину: даже если строка КАК-ТО оказалась в чужой ленте, объект к ней
    не подмешивается — заголовок и статус наружу не уходят."""
    from app.db import SessionLocal
    from app.models import Message
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv1 = _group(client, t, [b_id], title="Первая")
    conv2 = _group(client, t, [c_id], title="Вторая")
    aid = _start(client, t, conv1, "timer", {"duration_s": 60}, "Тема контрольной").json()["id"]
    db = SessionLocal()
    db.add(Message(conversation_id=conv2, sender_id=t_id, body=aid,
                   created_at="2026-08-15T00:00:00+00:00", kind="activity", body_format="plain"))
    db.commit()
    db.close()
    raw = client.get(f"/web/messenger/chats/{conv2}/messages", headers=c)
    #Сырой текст ответа целиком: заголовок не должен просочиться НИ ОДНИМ полем.
    assert "Тема контрольной" not in raw.text
    card = [m for m in raw.json()["messages"] if m["kind"] == "activity"][0]
    assert card["activity"] is None


def test_pinned_and_search_resolve_the_card_too(client):
    """⚠️ Обёртка `_attach_rich_meta` заведена ради «нельзя забыть место», но звалась не
    отовсюду: закреплённые, поиск, ветка ответов и модерация отдавали сырой `act:…`."""
    admin, (t_id, t), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, t, [b_id, c_id])
    _start(client, t, conv, "timer", {"duration_s": 60}, "Пятиминутка")
    msgs = client.get(f"/web/messenger/chats/{conv}/messages", headers=t).json()["messages"]
    card = [m for m in msgs if m["kind"] == "activity"][0]
    client.post(f"/web/messenger/messages/{card['id']}/pin", json={}, headers=t)
    pinned = client.get(f"/web/messenger/chats/{conv}/pinned", headers=t).json()["pinned"]
    got = [m for m in pinned if m["kind"] == "activity"]
    assert got and got[0]["activity"]["title"] == "Пятиминутка"
    #И модерация читает ту же ленту, что участники.
    mod = client.get(f"/web/admin/messenger/conversations/{conv}/messages", headers=admin).json()
    got2 = [m for m in mod["messages"] if m["kind"] == "activity"]
    assert got2 and got2[0]["activity"]["title"] == "Пятиминутка"
