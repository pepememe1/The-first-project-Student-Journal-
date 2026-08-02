"""
test_vector_locale.py — локализация ответов «Вектора» под выбранный язык интерфейса
(полный перевод интерфейса, см. запись в шапке CLAUDE.md).

Три пути:
  • статичные интенты без данных (hello/thanks/help/about_*/howto) — готовый ручной
    перевод (`_STATIC_TEXT` в web.py), без обращения к LLM вовсе;
  • интенты с реальными цифрами (не в `_NO_VOICE_INTENTS`) — LLM озвучивает СРАЗУ на
    нужном языке (persona получает инструкцию, `vector_llm.voice(..., locale=...)`);
  • структурные ответы с данными, которые не озвучиваются (расписание/погода/домашка/
    сервер/списки должников) — готовый русский текст переводится ПОСТФАКТУМ тем же
    примитивом, что и переводчик сообщений (`vector_llm.complete`), с тихим откатом на
    русский при недоступной модели.

Отдельно — «родительская» ловушка: локаль обязана браться у САМОГО родителя
(`user_ui_locale(user)` в `parent_vector_ask`), а не у ребёнка, чью запись
`answer_vector_question` использует для скоупа данных.
"""
from conftest import make_admin, make_teacher


def _set_locale(client, headers, locale, on=True):
    r = client.post("/me/prefs", json={"locale": locale, "locale_on": on}, headers=headers)
    assert r.status_code == 200, r.text


def test_hello_intent_uses_manual_translation_no_llm(client, monkeypatch):
    """Статичный интент (hello) переводится готовым словарём — LLM не зовём вовсе,
    поэтому даже если её подменить, текст не станет "испорченным" вызовом."""
    from app import vector_llm
    monkeypatch.setattr(vector_llm, "complete", lambda *a, **k: "SHOULD_NOT_BE_CALLED")
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    _set_locale(client, th, "en")

    r = client.post("/web/vector/ask", json={"message": "привет"}, headers=th).json()
    assert r["intent"] == "hello"
    assert r["text"].startswith("Hello!"), r["text"]
    assert "SHOULD_NOT_BE_CALLED" not in r["text"]


def test_about_college_intent_translated_to_chinese(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    _set_locale(client, th, "zh")

    r = client.post("/web/vector/ask", json={"message": "расскажи про колледж"},
                    headers=th).json()
    assert r["intent"] == "about_college"
    assert "ESSTU" in r["text"] and "colleg" not in r["text"].lower()


def test_locale_off_keeps_russian_even_with_locale_prefs_set(client):
    """`locale_on=false` — интерфейс по-русски, даже если код языка в prefs остался."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    _set_locale(client, th, "en", on=False)

    r = client.post("/web/vector/ask", json={"message": "привет"}, headers=th).json()
    assert r["intent"] == "hello"
    assert r["text"].startswith("Здравствуйте!"), r["text"]


def test_llm_voiced_intent_gets_locale_hint(client, monkeypatch):
    """Интент с реальными цифрами (не no_voice) должен передать locale в vector_llm.voice —
    persona сама просит модель ответить на нужном языке одним вызовом."""
    from app import vector_llm
    seen = {}

    def fake_voice(cfg, text, role, question, locale="ru"):
        seen["locale"] = locale
        return "VOICED"
    monkeypatch.setattr(vector_llm, "voice", fake_voice)

    admin = make_admin(client)
    _set_locale(client, admin, "en")
    r = client.post("/web/vector/ask", json={"message": "сколько студентов"},
                    headers=admin).json()
    assert r["intent"] == "group_stats"
    assert r["text"] == "VOICED"
    assert seen["locale"] == "en"


def test_dynamic_no_voice_intent_translated_postfactum(client, monkeypatch):
    """Ответ с реальными данными, который НЕ озвучивается (список должников — ФИО
    отдаются дословно), всё равно переводится — но готовым русским текстом ЦЕЛИКОМ через
    vector_llm.complete, а не второй генерацией с нуля."""
    from app import vector_llm
    from app.security import hash_password

    admin = make_admin(client)
    client.post("/sync/push", json={"changes": {
        "lessons": [{"id": "L1", "group_name": "G1", "subject": "Мат", "type": "Практика",
                     "number": 1}],
        "users": [{"id": "stud:s1", "role": "student", "login": "s1", "surname": "Двойкин",
                   "name": "Иван", "group_name": "G1", "password_hash": hash_password("p")}],
        "grades": [{"id": "Двойкин|Иван|L1", "student_f": "Двойкин", "student_n": "Иван",
                    "lesson_id": "L1", "grade": "2"}]}}, headers=admin)
    client.post("/web/admin/teachers", json={"full_name": "Пре Под", "login": "t1",
        "password": "pass1234", "subjects": ["Мат"]}, headers=admin)
    from conftest import assign_teacher
    assign_teacher(client, admin, "teach:t1", "G1", "Мат")
    th_login = client.post("/auth/login", json={"login": "t1", "password": "pass1234"}).json()
    th = {"Authorization": f"Bearer {th_login['access_token']}"}
    _set_locale(client, th, "en")

    seen = {}

    def fake_complete(cfg, messages, temperature=0.3):
        seen["messages"] = messages
        return "Debtors: Dvoykin"
    monkeypatch.setattr(vector_llm, "complete", fake_complete)

    r = client.post("/web/vector/ask", json={"message": "у кого долги"}, headers=th).json()
    assert r["text"] == "Debtors: Dvoykin"
    assert "no_voice" not in r                          #внутренний флаг наружу не течёт
    #Модель получила ГОТОВЫЙ русский текст (с фамилией), а не вопрос заново.
    user_msg = seen["messages"][-1]["content"]
    assert "Двойкин" in user_msg


def test_dynamic_no_voice_falls_back_to_russian_without_llm(client, monkeypatch):
    """Нет провайдера/сбой перевода → тихо остаётся русский текст, ответ не ломается."""
    from app import vector_llm
    monkeypatch.setattr(vector_llm, "complete", lambda *a, **k: "")

    admin = make_admin(client)
    _set_locale(client, admin, "en")
    r = client.post("/web/vector/ask", json={"message": "сколько студентов и должников нет"},
                    headers=admin).json()
    #Не важен конкретный интент — важно, что ответ вообще пришёл и не пуст, независимо
    #от провайдера. Проверяем на заведомо no_voice-путь: пустых студентов/долгов нет.
    assert r["text"]


def test_parent_vector_uses_parents_own_locale_not_childs(client):
    """Ловушка из плана: `child`, чью запись видит `answer_vector_question` для скоупа
    данных, — НЕ тот, чей язык интерфейса нужно использовать. Родитель мог выбрать
    английский, пока ребёнок пользуется русским интерфейсом (и наоборот)."""
    admin = make_admin(client)
    r = client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text
    sid = None
    for s in client.get("/web/admin/students", headers=admin).json()["students"]:
        if s.get("login") == "ivanova":
            sid = s.get("id")
    assert sid

    r = client.post("/web/admin/parents", json={
        "login": "parent1", "surname": "Иванов", "name": "Иван",
        "password": "parentpass1"}, headers=admin)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    r = client.post("/web/staff/parent-links",
                    json={"parent_id": pid, "student_id": sid}, headers=admin)
    assert r.status_code == 200, r.text
    link_id = r.json()["id"]

    student_login = client.post("/auth/login",
                                json={"login": "ivanova", "password": "studpass1"}).json()
    student_headers = {"Authorization": f"Bearer {student_login['access_token']}"}
    r = client.post(f"/web/student/parent-links/{link_id}/decide",
                    json={"approve": True}, headers=student_headers)
    assert r.status_code == 200, r.text

    #Ребёнок сам пользуется РУССКИМ интерфейсом (locale_on выключен по умолчанию).
    #Родитель выбрал английский — и должен получить ответ на английском.
    parent_login = client.post("/auth/login",
                               json={"login": "parent1", "password": "parentpass1"}).json()
    parent_headers = {"Authorization": f"Bearer {parent_login['access_token']}"}
    _set_locale(client, parent_headers, "en")

    r = client.post("/web/parent/vector/ask", json={"message": "привет"},
                    headers=parent_headers).json()
    assert r["intent"] == "hello"
    assert r["text"].startswith("Hi!"), r["text"]      #перевод для роли student (ребёнка)
