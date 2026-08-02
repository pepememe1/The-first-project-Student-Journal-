"""
test_vector_debtors_names.py — «у кого долги» называет ФАМИЛИИ (жалоба Ярослава).

Раньше для препода/куратора интент долгов отдавал только СЧЁТЧИК («в зоне риска 2»),
и Вектор честно не мог назвать имена. Преподаватель видит своих студентов в журнале,
поэтому список их долгов — прямой ответ, а не раскрытие ПДн. Имена отдаются ДОСЛОВНО
(no_voice), чтобы LLM их не исказил и не отказался называть.
"""
from conftest import make_admin, assign_teacher
from app.security import hash_password


def _login(client, l, p):
    return {"Authorization": f"Bearer {client.post('/auth/login', json={'login':l,'password':p}).json()['access_token']}"}


def test_debtors_lists_student_names_for_teacher(client, monkeypatch):
    #Отключаем реальную озвучку — не важна, ответ должен быть no_voice в любом случае.
    from app import vector_llm
    monkeypatch.setattr(vector_llm, "voice", lambda cfg, t, r, q, locale="ru": "VOICED:" + t)
    admin = make_admin(client)
    #Студент с несданной практикой (2) → задолженность
    client.post("/sync/push", json={"changes": {
        "lessons": [{"id": "L1", "group_name": "G1", "subject": "Мат", "type": "Практика",
                     "number": 1}],
        "users": [{"id": "stud:s1", "role": "student", "login": "s1", "surname": "Двойкин",
                   "name": "Иван", "group_name": "G1", "password_hash": hash_password("p")}],
        "grades": [{"id": "Двойкин|Иван|L1", "student_f": "Двойкин", "student_n": "Иван",
                    "lesson_id": "L1", "grade": "2"}]}}, headers=admin)
    client.post("/web/admin/teachers", json={"full_name": "Пре Под", "login": "t1",
        "password": "pass1234", "subjects": ["Мат"]}, headers=admin)
    assign_teacher(client, admin, "teach:t1", "G1", "Мат")
    th = _login(client, "t1", "pass1234")

    r = client.post("/web/vector/ask", json={"message": "у кого долги"}, headers=th).json()
    assert "Двойкин" in r["text"], r["text"]          #ФАМИЛИЯ названа
    assert "VOICED:" not in r["text"], "список имён НЕ должен идти через LLM"
    assert r["facts"]["at_risk"] >= 1
    assert "no_voice" not in r                          #внутренний флаг наружу не течёт


def test_no_debtors_message(client, monkeypatch):
    from app import vector_llm
    monkeypatch.setattr(vector_llm, "voice", lambda cfg, t, r, q, locale="ru": t)
    admin = make_admin(client)
    client.post("/sync/push", json={"changes": {
        "lessons": [{"id": "L1", "group_name": "G1", "subject": "Мат", "type": "Практика",
                     "number": 1}],
        "users": [{"id": "stud:s1", "role": "student", "login": "s1", "surname": "Пятёркин",
                   "name": "Пётр", "group_name": "G1", "password_hash": hash_password("p")}],
        "grades": [{"id": "Пятёркин|Пётр|L1", "student_f": "Пятёркин", "student_n": "Пётр",
                    "lesson_id": "L1", "grade": "5"}]}}, headers=admin)
    client.post("/web/admin/teachers", json={"full_name": "Пре Под", "login": "t1",
        "password": "pass1234", "subjects": ["Мат"]}, headers=admin)
    assign_teacher(client, admin, "teach:t1", "G1", "Мат")
    th = _login(client, "t1", "pass1234")
    r = client.post("/web/vector/ask", json={"message": "у кого долги"}, headers=th).json()
    assert "нет" in r["text"].lower()
    assert r["facts"]["at_risk"] == 0
