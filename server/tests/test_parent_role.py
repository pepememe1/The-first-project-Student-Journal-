"""
test_parent_role.py — роль «родитель» (3.1).

Цена ошибки здесь выше, чем в любой другой части релиза: родитель — внешний человек,
получающий доступ к персональным данным другого человека. Поэтому тесты держат в первую
очередь ГРАНИЦЫ, а не удобство:

  • доступ даёт СОГЛАСИЕ СТУДЕНТА, а не привязка сотрудника (152-ФЗ: в колледже учатся и
    совершеннолетние, для них доступ родителя без их согласия — нарушение);
  • студент может отозвать согласие в любой момент, и доступ пропадает сразу;
  • повторная привязка после отзыва снова требует согласия — иначе отзыв обходится
    парой кликов сотрудника;
  • куратор распоряжается только СВОИМИ группами;
  • родитель не видит чужих студентов, не ищет людей и сам невидим для студентов и
    преподавателей — в том числе при прямом запросе карточки по id;
  • переписка родителю доступна только с куратором и родителями своей группы, причём
    проверка стоит на СОЗДАНИИ чата, а не только в поиске.
"""
from conftest import make_admin, make_teacher


def _headers(client, login, password):
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _student(client, admin, login, surname, name, group="ИС-21"):
    r = client.post("/web/admin/students", json={
        "login": login, "surname": surname, "name": name, "group": group,
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text
    return r.json().get("id") or _user_id(client, admin, login)


def _parent(client, admin, login, surname="Иванов", name="Иван"):
    r = client.post("/web/admin/parents", json={
        "login": login, "surname": surname, "name": name, "password": "parentpass1"},
        headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _user_id(client, admin, login):
    """id студента по логину — через админский список (в ответе создания его может не быть)."""
    r = client.get("/web/admin/students", headers=admin)
    assert r.status_code == 200, r.text
    for s in r.json()["students"]:
        if s.get("login") == login:
            return s.get("id")
    raise AssertionError(f"студент {login} не найден")


def _link(client, staff, parent_id, student_id, expect=200):
    r = client.post("/web/staff/parent-links",
                    json={"parent_id": parent_id, "student_id": student_id}, headers=staff)
    assert r.status_code == expect, r.text
    return r.json() if expect == 200 else None


def _approve(client, student_headers, link_id, approve=True):
    r = client.post(f"/web/student/parent-links/{link_id}/decide",
                    json={"approve": approve}, headers=student_headers)
    assert r.status_code == 200, r.text
    return r.json()


def _setup(client):
    """Админ, студент, родитель и связь (ещё не подтверждённая)."""
    admin = make_admin(client)
    _student(client, admin, "ivanova", "Иванова", "Мария")
    sid = _user_id(client, admin, "ivanova")
    pid = _parent(client, admin, "parent1")
    link = _link(client, admin, pid, sid)
    return admin, sid, pid, link["id"]


# ── Согласие студента ───────────────────────────────────────────────────────────────
def test_link_alone_gives_no_access(client):
    """Привязка сотрудника доступа НЕ даёт — только заявку."""
    _admin, _sid, _pid, link_id = _setup(client)
    ph = _headers(client, "parent1", "parentpass1")

    r = client.get("/web/parent/children", headers=ph)
    assert r.status_code == 200, r.text
    assert r.json()["children"] == [] and r.json()["pending"] == 1

    r = client.get("/web/parent/journal", headers=ph)
    assert r.status_code == 403, "журнал не должен открываться без согласия студента"


def test_student_approval_opens_journal(client):
    _admin, _sid, _pid, link_id = _setup(client)
    sh = _headers(client, "ivanova", "studpass1")
    ph = _headers(client, "parent1", "parentpass1")

    links = client.get("/web/student/parent-links", headers=sh).json()["links"]
    assert len(links) == 1 and links[0]["status"] == "pending", links
    _approve(client, sh, link_id)

    r = client.get("/web/parent/children", headers=ph)
    assert [c["full_name"] for c in r.json()["children"]] == ["Иванова Мария"], r.json()

    r = client.get("/web/parent/journal", headers=ph)
    assert r.status_code == 200, r.text
    assert r.json()["student"]["group"] == "ИС-21"


def test_student_can_revoke_consent_later(client):
    """Согласие на обработку своих данных отзывается в любой момент — кнопка у студента."""
    _admin, _sid, _pid, link_id = _setup(client)
    sh = _headers(client, "ivanova", "studpass1")
    ph = _headers(client, "parent1", "parentpass1")
    _approve(client, sh, link_id)
    assert client.get("/web/parent/journal", headers=ph).status_code == 200

    _approve(client, sh, link_id, approve=False)
    assert client.get("/web/parent/journal", headers=ph).status_code == 403
    assert client.get("/web/parent/children", headers=ph).json()["children"] == []


def test_relinking_after_revoke_requires_consent_again(client):
    """Сотрудник не может воскресить отозванный доступ повторной привязкой."""
    admin, sid, pid, link_id = _setup(client)
    sh = _headers(client, "ivanova", "studpass1")
    ph = _headers(client, "parent1", "parentpass1")
    _approve(client, sh, link_id)
    _approve(client, sh, link_id, approve=False)

    _link(client, admin, pid, sid)          #та же пара — заявка создаётся заново
    assert client.get("/web/parent/journal", headers=ph).status_code == 403
    links = client.get("/web/student/parent-links", headers=sh).json()["links"]
    assert links[0]["status"] == "pending", links


def test_student_cannot_decide_someone_elses_link(client):
    """Чужую заявку не подтвердить: иначе согласие можно было бы выдать за другого."""
    admin, _sid, pid, _link_id = _setup(client)
    _student(client, admin, "petrov", "Петров", "Пётр")
    other_id = _user_id(client, admin, "petrov")
    other_link = _link(client, admin, pid, other_id)["id"]

    sh = _headers(client, "ivanova", "studpass1")
    r = client.post(f"/web/student/parent-links/{other_link}/decide",
                    json={"approve": True}, headers=sh)
    assert r.status_code == 404, r.text


# ── Границы куратора ────────────────────────────────────────────────────────────────
def test_curator_may_link_only_own_groups(client):
    admin = make_admin(client)
    _student(client, admin, "ivanova", "Иванова", "Мария", group="ИС-21")
    _student(client, admin, "sidorov", "Сидоров", "Семён", group="ИС-22")
    pid = _parent(client, admin, "parent1")
    teach = make_teacher(client, admin, subjects=["Математика"])
    r = client.put("/web/admin/teachers/teacher1",
                   json={"curated_groups": ["ИС-21"]}, headers=admin)
    assert r.status_code == 200, r.text

    _link(client, teach, pid, _user_id(client, admin, "ivanova"))            #своя группа — ок
    _link(client, teach, pid, _user_id(client, admin, "sidorov"), expect=403)  #чужая — нет


def test_plain_teacher_without_curated_groups_sees_no_parents(client):
    admin = make_admin(client)
    _parent(client, admin, "parent1")
    teach = make_teacher(client, admin, subjects=["Математика"])
    assert client.get("/web/staff/parents", headers=teach).status_code == 403


# ── Изоляция данных родителя ────────────────────────────────────────────────────────
def test_parent_cannot_read_other_students_journal(client):
    admin, sid, pid, link_id = _setup(client)
    _student(client, admin, "petrov", "Петров", "Пётр")
    other_id = _user_id(client, admin, "petrov")
    sh = _headers(client, "ivanova", "studpass1")
    _approve(client, sh, link_id)

    ph = _headers(client, "parent1", "parentpass1")
    r = client.get(f"/web/parent/journal?student_id={other_id}", headers=ph)
    assert r.status_code == 403, r.text


def test_parent_has_no_access_to_student_and_teacher_endpoints(client):
    _setup(client)
    ph = _headers(client, "parent1", "parentpass1")
    for url in ("/web/student/journal", "/web/student/stats",
                "/web/teacher/journal?group=ИС-21&subject=Математика",
                "/web/admin/students"):
        assert client.get(url, headers=ph).status_code == 403, url


def test_parent_vector_answers_about_child_only(client):
    """Вектор родителя работает в скоупе ребёнка; без согласия — молчит (403)."""
    _admin, _sid, _pid, link_id = _setup(client)
    ph = _headers(client, "parent1", "parentpass1")
    assert client.post("/web/parent/vector/ask", json={"message": "средний балл"},
                       headers=ph).status_code == 403

    _approve(client, _headers(client, "ivanova", "studpass1"), link_id)
    r = client.post("/web/parent/vector/ask", json={"message": "средний балл"}, headers=ph)
    assert r.status_code == 200, r.text
    assert r.json()["student_id"], r.json()


# ── Мессенджер ──────────────────────────────────────────────────────────────────────
def test_parent_is_invisible_to_students_and_teachers(client):
    admin, _sid, pid, _link = _setup(client)
    teach = make_teacher(client, admin, subjects=["Математика"])   #без курируемых групп
    sh = _headers(client, "ivanova", "studpass1")

    for headers in (sh, teach):
        r = client.get("/web/messenger/users?role=parent", headers=headers)
        assert r.status_code == 200, r.text
        assert all(u["id"] != pid for u in r.json()["users"]), r.json()
        #и прямой запрос карточки по id тоже не должен раскрывать родителя
        assert client.get(f"/web/messenger/users/{pid}/profile",
                          headers=headers).status_code == 404


def test_student_cannot_open_chat_with_parent(client):
    _admin, _sid, pid, _link = _setup(client)
    sh = _headers(client, "ivanova", "studpass1")
    r = client.post(f"/web/messenger/chats/direct/{pid}", headers=sh)
    assert r.status_code == 403, r.text


def test_parents_of_same_group_may_chat(client):
    admin, sid, pid, link_id = _setup(client)
    sh = _headers(client, "ivanova", "studpass1")
    _approve(client, sh, link_id)

    _student(client, admin, "petrov", "Петров", "Пётр")          #та же группа ИС-21
    pid2 = _parent(client, admin, "parent2", surname="Петров")
    link2 = _link(client, admin, pid2, _user_id(client, admin, "petrov"))["id"]
    _approve(client, _headers(client, "petrov", "studpass1"), link2)

    ph = _headers(client, "parent1", "parentpass1")
    assert client.post(f"/web/messenger/chats/direct/{pid2}", headers=ph).status_code == 200


def test_parents_of_different_groups_may_not_chat(client):
    admin, _sid, pid, link_id = _setup(client)
    _approve(client, _headers(client, "ivanova", "studpass1"), link_id)

    _student(client, admin, "sidorov", "Сидоров", "Семён", group="ИС-22")
    pid2 = _parent(client, admin, "parent2", surname="Сидоров")
    link2 = _link(client, admin, pid2, _user_id(client, admin, "sidorov"))["id"]
    _approve(client, _headers(client, "sidorov", "studpass1"), link2)

    ph = _headers(client, "parent1", "parentpass1")
    r = client.post(f"/web/messenger/chats/direct/{pid2}", headers=ph)
    assert r.status_code == 403, r.text


def test_parent_may_chat_with_curator_but_not_plain_teacher(client):
    admin, sid, pid, link_id = _setup(client)
    _approve(client, _headers(client, "ivanova", "studpass1"), link_id)
    make_teacher(client, admin, subjects=["Математика"])
    client.put("/web/admin/teachers/teacher1",
               json={"curated_groups": ["ИС-21"]}, headers=admin)
    make_teacher(client, admin, login="teacher2", password="teacherpass2",
                 subjects=["Физика"])

    ph = _headers(client, "parent1", "parentpass1")
    assert client.post("/web/messenger/chats/direct/teach:teacher1",
                       headers=ph).status_code == 200
    assert client.post("/web/messenger/chats/direct/teach:teacher2",
                       headers=ph).status_code == 403


def test_parent_cannot_create_groups_or_channels(client):
    """Беседу группы создаёт только куратор — родителю «+» недоступен и на сервере."""
    _setup(client)
    ph = _headers(client, "parent1", "parentpass1")
    for url in ("/web/messenger/chats/group", "/web/messenger/chats/channel"):
        r = client.post(url, json={"title": "Родители ИС-21"}, headers=ph)
        assert r.status_code == 403, (url, r.text)
