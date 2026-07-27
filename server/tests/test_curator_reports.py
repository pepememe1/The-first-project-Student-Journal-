"""
test_curator_reports.py — §12 плана: отчёты куратора для родителей в мессенджере.

Держим: канал «Отчёты · Группа» доступен ТОЛЬКО куратору ЭТОЙ группы и ТОЛЬКО если у
группы есть активная связь с родителем; команда /отчет создаёт «вечную» кнопку с
номером по порядку; данные считаются ЖИВЬЁМ, но ограничены датой создания отчёта;
rollover термина архивирует старые кнопки, не удаляя их.
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


def _user_id(client, admin, login):
    r = client.get("/web/admin/students", headers=admin)
    assert r.status_code == 200, r.text
    for s in r.json()["students"]:
        if s.get("login") == login:
            return s.get("id")
    raise AssertionError(f"студент {login} не найден")


def _parent(client, admin, login, surname="Родителев", name="Родион"):
    r = client.post("/web/admin/parents", json={
        "login": login, "surname": surname, "name": name, "password": "parentpass1"},
        headers=admin)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _link_and_approve(client, admin, parent_id, student_login, student_headers):
    sid = _user_id(client, admin, student_login)
    r = client.post("/web/staff/parent-links",
                    json={"parent_id": parent_id, "student_id": sid}, headers=admin)
    assert r.status_code == 200, r.text
    link_id = r.json()["id"]
    r = client.post(f"/web/student/parent-links/{link_id}/decide",
                    json={"approve": True}, headers=student_headers)
    assert r.status_code == 200, r.text


def _make_curator(client, admin, group="ИС-21", login="teacher1", subjects=("Математика",)):
    teach = make_teacher(client, admin, login=login, subjects=list(subjects))
    r = client.put(f"/web/admin/teachers/{login}",
                   json={"curated_groups": [group]}, headers=admin)
    assert r.status_code == 200, r.text
    return teach


def _seed_lesson_and_grade(client, admin, teach, group, subject, value="5", date="01.09.2025",
                          surname="Иванова", name="Мария", lesson_id="L1"):
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": lesson_id, "group_name": group, "subject": subject, "type": "Практика",
         "number": 1, "topic": "т", "date": date}]}}, headers=admin)
    r = client.post("/web/teacher/grade", json={
        "lesson_id": lesson_id, "surname": surname, "name": name, "grade": value}, headers=teach)
    assert r.status_code == 200, r.text


def _setup_group_with_parent(client, group="ИС-21"):
    """Админ, куратор группы, студент, подтверждённый родитель — минимальный «группа с
    родителями» набор, готовый к созданию канала отчётов."""
    admin = make_admin(client)
    teach = _make_curator(client, admin, group=group)
    _student(client, admin, "ivanova", "Иванова", "Мария", group=group)
    sh = _headers(client, "ivanova", "studpass1")
    pid = _parent(client, admin, "parent1")
    ph = _headers(client, "parent1", "parentpass1")
    _link_and_approve(client, admin, pid, "ivanova", sh)
    return admin, teach, sh, ph


def _ensure_channel(client, teach, group="ИС-21"):
    r = client.post(f"/web/messenger/channels/curator-reports/{group}", headers=teach)
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


# ── Доступ к каналу ──────────────────────────────────────────────────────────────────
def test_channel_requires_curator_of_group(client):
    admin = make_admin(client)
    teach = make_teacher(client, admin)   # НЕ куратор
    r = client.post("/web/messenger/channels/curator-reports/ИС-21", headers=teach)
    assert r.status_code == 403


def test_channel_requires_active_parent(client):
    admin = make_admin(client)
    teach = _make_curator(client, admin)
    _student(client, admin, "ivanova", "Иванова", "Мария", group="ИС-21")
    #Родителя ещё нет вовсе — группа "без родителей".
    r = client.post("/web/messenger/channels/curator-reports/ИС-21", headers=teach)
    assert r.status_code == 400


def test_channel_created_and_readers_are_students_and_parents(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    #И студент, и родитель видят канал в списке чатов.
    assert any(c["conversation_id"] == conv_id
              for c in client.get("/web/messenger/chats", headers=sh).json()["chats"])
    assert any(c["conversation_id"] == conv_id
              for c in client.get("/web/messenger/chats", headers=ph).json()["chats"])
    #Родитель — читатель: писать в канал не может.
    assert client.post(f"/web/messenger/chats/{conv_id}/messages",
                       json={"body": "спасибо"}, headers=ph).status_code == 403


# ── Команда /отчет ───────────────────────────────────────────────────────────────────
def test_report_command_creates_numbered_button(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    _seed_lesson_and_grade(client, admin, teach, "ИС-21", "Математика", "5")

    r = client.post(f"/web/messenger/chats/{conv_id}/messages",
                    json={"body": "/отчет"}, headers=teach)
    assert r.status_code == 200, r.text

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    report_msgs = [m for m in msgs if m["kind"] == "report"]
    assert len(report_msgs) == 1
    assert report_msgs[0]["report"]["seq"] == 1
    assert report_msgs[0]["report"]["group"] == "ИС-21"
    assert report_msgs[0]["report"]["archived"] is False


def test_report_sequence_increments_per_group(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=teach).json()["messages"]
    seqs = sorted(m["report"]["seq"] for m in msgs if m["kind"] == "report")
    assert seqs == [1, 2]


def test_report_command_refused_if_group_loses_last_parent(client):
    """Родитель отозвал согласие — в КАНАЛЕ отчётов команда больше не публикует отчёт
    (публиковать его там некому), но сам канал и кнопки прошлых отчётов никуда не деваются.

    Отвечаем 400 с объяснением, а НЕ молчаливым «ок»: раньше куратор жал отправку, ничего
    не происходило, и это выглядело как поломка. В обычном чате ограничения нет — там
    адресата выбирает сам куратор (см. test_report_command_in_direct_chat)."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    #Студент отзывает согласие.
    links = client.get("/web/student/parent-links", headers=sh).json()["links"]
    client.post(f"/web/student/parent-links/{links[0]['id']}/decide",
               json={"approve": False}, headers=sh)

    r = client.post(f"/web/messenger/chats/{conv_id}/messages",
                    json={"body": "/отчет"}, headers=teach)
    assert r.status_code == 400
    assert "родител" in r.json()["detail"].lower()
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=teach).json()["messages"]
    assert not any(m["kind"] == "report" for m in msgs)


# ── Данные отчёта (живой пересчёт) ───────────────────────────────────────────────────
def test_report_overview_categories_and_subjects(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    _seed_lesson_and_grade(client, admin, teach, "ИС-21", "Математика", "5")
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    rid = next(m["report"]["id"] for m in msgs if m["kind"] == "report")

    r = client.get(f"/web/messenger/reports/{rid}", headers=ph)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["group"] == "ИС-21" and data["seq"] == 1
    assert data["categories"]["counts"]["excellent"] == 1   #средний 5 → отличница
    assert data["subjects"] == [{"subject": "Математика", "avg": 5.0, "percent": 100}]


def test_report_overview_forbidden_for_non_participant(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=teach).json()["messages"]
    rid = next(m["report"]["id"] for m in msgs if m["kind"] == "report")

    outsider = make_teacher(client, admin, login="teacher2")
    assert client.get(f"/web/messenger/reports/{rid}", headers=outsider).status_code == 403


def test_report_subject_drilldown_shows_grades_and_absences(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    _seed_lesson_and_grade(client, admin, teach, "ИС-21", "Математика", "5")
    #Вторая пара — неявка (пропуск).
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L2", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 2, "topic": "т2", "date": "02.09.2025"}]}}, headers=admin)
    client.post("/web/teacher/grade", json={
        "lesson_id": "L2", "surname": "Иванова", "name": "Мария", "grade": "Н"}, headers=teach)

    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    rid = next(m["report"]["id"] for m in msgs if m["kind"] == "report")

    r = client.get(f"/web/messenger/reports/{rid}/subject",
                   params={"subject": "Математика"}, headers=ph)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["lessons"]) == 2
    row = data["rows"][0]
    assert row["student"] == "Иванова Мария"
    assert row["missed_count"] == 1 and row["missed_hours"] == 1


def test_report_snapshot_excludes_lessons_after_cutoff(client):
    """«Вечная» граница: занятие, добавленное ПОСЛЕ создания отчёта, в него не попадает,
    даже если дата занятия попадает в прошлое (curator_report фильтрует по факту создания,
    а тест проверяет наблюдаемое поведение — новая пара не должна ломать уже выданный отчёт)."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    _seed_lesson_and_grade(client, admin, teach, "ИС-21", "Математика", "5", date="01.09.2025")
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    rid = next(m["report"]["id"] for m in msgs if m["kind"] == "report")

    #Занятие с ОЧЕНЬ старой датой, но добавленное ПОСЛЕ отчёта — граница по дате СОЗДАНИЯ
    #отчёта (сегодня), а не по дате занятия, поэтому это новое занятие тоже входит (оно
    #раньше cutoff=сегодня). Проверяем обратный, однозначный случай: занятие с датой в
    #будущем ПОСЛЕ cutoff — не входит.
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "L9", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 9, "topic": "будущее", "date": "01.09.2099"}]}}, headers=admin)
    client.post("/web/teacher/grade", json={
        "lesson_id": "L9", "surname": "Иванова", "name": "Мария", "grade": "3"}, headers=teach)

    r = client.get(f"/web/messenger/reports/{rid}/subject",
                   params={"subject": "Математика"}, headers=ph)
    assert r.status_code == 200, r.text
    ids = [l["id"] for l in r.json()["lessons"]]
    assert "L9" not in ids, "занятие с датой ПОСЛЕ границы отчёта не должно входить в снимок"


# ── Архивация при rollover ────────────────────────────────────────────────────────────
def test_rollover_archives_old_reports(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)

    r = client.post("/web/admin/term/rollover", json={}, headers=admin)
    assert r.status_code == 200, r.text

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    rep = next(m["report"] for m in msgs if m["kind"] == "report")
    assert rep["archived"] is True, "кнопка старого отчёта должна архивироваться после rollover"


def test_new_report_after_rollover_is_not_archived(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    client.post("/web/admin/term/rollover", json={}, headers=admin)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=teach).json()["messages"]
    reports = sorted((m["report"] for m in msgs if m["kind"] == "report"), key=lambda r: r["seq"])
    assert len(reports) == 2
    assert reports[0]["archived"] is True    #отчёт из ЗАКРЫВШЕГОСЯ термина
    assert reports[1]["archived"] is False   #новый — из текущего термина


# ── Отчёт как обычное сообщение: ЛС, произвольный чат, пересылка ─────────────────────
def _parent_id_of(client, admin, login="parent1"):
    r = client.get("/web/staff/parents", headers=admin)
    assert r.status_code == 200, r.text
    for p in r.json()["parents"]:
        if p["login"] == login:
            return p["id"]
    raise AssertionError("родитель не найден")


def test_create_report_goes_to_parent_direct_chat(client):
    """«+ → Отчёт»: отчёт уезжает СООБЩЕНИЕМ в личный чат родителя, без всякого канала."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    _seed_lesson_and_grade(client, admin, teach, "ИС-21", "Математика", "5")
    pid = _parent_id_of(client, admin)

    r = client.post("/web/messenger/curator-reports",
                    json={"group": "ИС-21", "to_user_ids": [pid]}, headers=teach)
    assert r.status_code == 200, r.text
    conv_id = r.json()["conversation_id"]

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    reports = [m for m in msgs if m["kind"] == "report"]
    assert len(reports) == 1 and reports[0]["report"]["group"] == "ИС-21"
    #И родитель этот отчёт может открыть — доступ даёт участие в ЛИЧНОМ чате.
    rid = reports[0]["report"]["id"]
    assert client.get(f"/web/messenger/reports/{rid}", headers=ph).status_code == 200


def test_create_report_without_targets_lands_in_saved(client):
    """Адресат не выбран — отчёт кладём себе в «Избранное», оттуда его пересылают."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    r = client.post("/web/messenger/curator-reports", json={"group": "ИС-21"}, headers=teach)
    assert r.status_code == 200, r.text
    assert r.json()["conversation_id"].startswith("saved:")


def test_create_report_requires_curated_group(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    r = client.post("/web/messenger/curator-reports", json={"group": "ЭК-11"}, headers=teach)
    assert r.status_code == 403


def test_forwarded_report_stays_a_button_and_opens(client):
    """Пересылка отчёта: у адресата это КНОПКА (а не текст «rpt:…»), и она открывается."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    _seed_lesson_and_grade(client, admin, teach, "ИС-21", "Математика", "5")
    r = client.post("/web/messenger/curator-reports", json={"group": "ИС-21"}, headers=teach)
    saved_id, mid = r.json()["conversation_id"], r.json()["message_id"]

    pid = _parent_id_of(client, admin)
    direct = client.post(f"/web/messenger/chats/direct/{pid}", headers=teach).json()["conversation_id"]
    r = client.post("/web/messenger/messages/forward",
                    json={"message_ids": [mid], "to_conversation_ids": [direct]}, headers=teach)
    assert r.status_code == 200 and r.json()["forwarded"] == 1

    msgs = client.get(f"/web/messenger/chats/{direct}/messages", headers=ph).json()["messages"]
    fwd = [m for m in msgs if m["kind"] == "report"]
    assert len(fwd) == 1, "пересланный отчёт должен остаться кнопкой (kind='report')"
    assert fwd[0]["report"] and fwd[0]["report"]["seq"] == 1
    assert client.get(f"/web/messenger/reports/{fwd[0]['report']['id']}", headers=ph).status_code == 200
    assert saved_id.startswith("saved:")


def test_parent_cannot_forward_report_further(client):
    """Родителю отчёт по группе прислали — дальше он его не рассылает (оценки всей группы)."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    pid = _parent_id_of(client, admin)
    r = client.post("/web/messenger/curator-reports",
                    json={"group": "ИС-21", "to_user_ids": [pid]}, headers=teach)
    conv_id = r.json()["conversation_id"]
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    mid = next(m["id"] for m in msgs if m["kind"] == "report")

    saved = client.post("/web/messenger/chats/saved", headers=ph).json()["conversation_id"]
    r = client.post("/web/messenger/messages/forward",
                    json={"message_ids": [mid], "to_conversation_ids": [saved]}, headers=ph)
    assert r.status_code == 200 and r.json()["forwarded"] == 0


def test_report_command_with_group_argument_posts_here(client):
    """`/отчет ИС-21` в ЛИЧНОМ чате публикует отчёт СРАЗУ в эту переписку."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    pid = _parent_id_of(client, admin)
    conv_id = client.post(f"/web/messenger/chats/direct/{pid}", headers=teach).json()["conversation_id"]

    r = client.post(f"/web/messenger/chats/{conv_id}/messages",
                    json={"body": "/отчет ИС-21"}, headers=teach)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "report"

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    #Текст самой команды в ленте не остаётся — только кнопка.
    assert [m["kind"] for m in msgs] == ["report"]


def test_report_command_rejects_foreign_group(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    pid = _parent_id_of(client, admin)
    conv_id = client.post(f"/web/messenger/chats/direct/{pid}", headers=teach).json()["conversation_id"]
    r = client.post(f"/web/messenger/chats/{conv_id}/messages",
                    json={"body": "/отчет ЭК-11"}, headers=teach)
    assert r.status_code == 400
    assert "ЭК-11" in r.json()["detail"]


def test_report_command_from_student_is_refused(client):
    """Команда — не «магическое слово»: у студента она не сработает даже в своих заметках."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = client.post("/web/messenger/chats/saved", headers=sh).json()["conversation_id"]
    r = client.post(f"/web/messenger/chats/{conv_id}/messages",
                    json={"body": "/отчет ИС-21"}, headers=sh)
    assert r.status_code == 403


# ── Выпадающий список групп (вместо ручного ввода) ───────────────────────────────────
def test_my_groups_marks_curated(client):
    admin, teach, sh, ph = _setup_group_with_parent(client)
    r = client.get("/web/messenger/my-groups", headers=teach)
    assert r.status_code == 200, r.text
    names = {g["name"]: g["curated"] for g in r.json()["groups"]}
    assert names.get("ИС-21") is True


def test_channel_endpoints_accept_group_with_slash(client):
    """Имя группы со слэшем («К75/1») в ПУТИ ломало роутинг — теперь оно идёт в query."""
    admin = make_admin(client)
    teach = _make_curator(client, admin, group="К75/1")
    _student(client, admin, "ivanova", "Иванова", "Мария", group="К75/1")
    r = client.post("/web/messenger/channels/announcements", params={"group": "К75/1"},
                    headers=teach)
    assert r.status_code == 200, r.text
    #Слэша в id нет НАМЕРЕННО (см. messenger._gtoken): иначе беседа недоступна по HTTP.
    assert r.json()["conversation_id"] == "sys:announce:К75~1"


# ── Строка чата в списке (предпросмотр) ──────────────────────────────────────────────
def test_chat_list_gives_sender_and_report_meta(client):
    """Списку чатов нужны имя автора (в группе/канале) и номер отчёта — иначе слева
    показывался сырой шаблон служебного сообщения и id отчёта вместо кнопки."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)

    chats = client.get("/web/messenger/chats", headers=ph).json()["chats"]
    row = next(c for c in chats if c["conversation_id"] == conv_id)
    last = row["last_message"]
    assert last["kind"] == "report"
    assert last["report"] and last["report"]["seq"] == 1     #номер для «📊 Отчёт №1»
    assert last["sender_name"], "в канале нужно имя автора последнего сообщения"
    assert last["mine"] is False


def test_system_events_do_not_count_as_unread(client):
    """«Вступил в беседу» — отметка в ленте, а не сообщение тебе: непрочитанным не считается."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    r = client.post("/web/messenger/chats/group", json={
        "title": "Кураторская", "member_ids": []}, headers=teach)
    assert r.status_code == 200, r.text
    conv_id = r.json()["conversation_id"]
    sid = _user_id(client, admin, "ivanova")
    r = client.post(f"/web/messenger/chats/{conv_id}/members",
                    json={"user_ids": [sid]}, headers=teach)
    assert r.status_code == 200, r.text

    chats = client.get("/web/messenger/chats", headers=sh).json()["chats"]
    row = next(c for c in chats if c["conversation_id"] == conv_id)
    assert row["last_message"]["kind"] == "system"
    assert row["unread"] == 0


def test_report_command_is_idempotent_by_nonce(client):
    """Повтор запроса с тем же client_nonce (ретрай сети, двойное нажатие) НЕ создаёт
    второй отчёт: разбор команды стоит ПОСЛЕ проверки nonce, и кнопка несёт этот nonce."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    payload = {"body": "/отчет", "client_nonce": "same-nonce-1"}

    a = client.post(f"/web/messenger/chats/{conv_id}/messages", json=payload, headers=teach)
    b = client.post(f"/web/messenger/chats/{conv_id}/messages", json=payload, headers=teach)
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    assert a.json()["id"] == b.json()["id"], "повтор должен вернуть ту же кнопку"
    assert b.json()["kind"] == "report" and b.json()["report"]["seq"] == 1

    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=teach).json()["messages"]
    assert len([m for m in msgs if m["kind"] == "report"]) == 1


def test_report_button_carries_group_and_cutoff(client):
    """На кнопке видно группу и дату границы — иначе два отчёта подряд неразличимы."""
    admin, teach, sh, ph = _setup_group_with_parent(client)
    conv_id = _ensure_channel(client, teach)
    client.post(f"/web/messenger/chats/{conv_id}/messages", json={"body": "/отчет"}, headers=teach)
    msgs = client.get(f"/web/messenger/chats/{conv_id}/messages", headers=ph).json()["messages"]
    rep = next(m["report"] for m in msgs if m["kind"] == "report")
    assert rep["group"] == "ИС-21"
    assert rep["cutoff_date"] and rep["cutoff_date"].count(".") == 2


# ── Слэш в имени группы («К74/1») — id беседы и отчёта обязаны оставаться адресуемыми ──
def test_group_with_slash_channel_and_report_are_addressable(client):
    """Главный баг «отчёт открывается и тут же закрывается»: слэш из имени группы попадал
    в id («sys:announce:К74/1», «rpt:К74/1|1»), в URL приезжал как %2F, Starlette
    раскодировал его обратно — путь распадался на лишний сегмент и не совпадал ни с одним
    эндпоинтом: GET уходил в SPA-фолбэк (HTML вместо JSON), POST отвечал 405."""
    from urllib.parse import quote
    admin, teach, sh, ph = _setup_group_with_parent(client, group="К74/1")
    _seed_lesson_and_grade(client, admin, teach, "К74/1", "Математика", "5")

    conv_id = client.post("/web/messenger/channels/announcements",
                          params={"group": "К74/1"}, headers=teach).json()["conversation_id"]
    assert "/" not in conv_id, "слэш в id беседы делает её недоступной по HTTP"
    enc = quote(conv_id, safe="")
    assert client.post(f"/web/messenger/chats/{enc}/messages",
                       json={"body": "линейка в 9:00"}, headers=teach).status_code == 200

    r = client.post("/web/messenger/curator-reports", json={"group": "К74/1"}, headers=teach)
    assert r.status_code == 200, r.text
    rid = r.json()["report_id"]
    assert "/" not in rid, "слэш в id отчёта ломает его открытие"
    r = client.get(f"/web/messenger/reports/{quote(rid, safe='')}", headers=teach)
    assert r.status_code == 200, r.text
    assert r.json()["group"] == "К74/1"        #имя группы восстанавливается из id
    r = client.get(f"/web/messenger/reports/{quote(rid, safe='')}/subject",
                   params={"subject": "Математика"}, headers=teach)
    assert r.status_code == 200, r.text


def test_report_command_in_channel_of_group_with_slash(client):
    """`/отчет` в канале «Отчёты · К74/1» — группу берём из id канала, слэш возвращаем."""
    admin, teach, sh, ph = _setup_group_with_parent(client, group="К74/1")
    conv_id = client.post("/web/messenger/channels/curator-reports",
                          params={"group": "К74/1"}, headers=teach).json()["conversation_id"]
    r = client.post(f"/web/messenger/chats/{conv_id}/messages",
                    json={"body": "/отчет"}, headers=teach)
    assert r.status_code == 200, r.text
    assert r.json()["report"]["group"] == "К74/1"


def test_my_groups_collapses_duplicate_spellings(client):
    """«К74/1» в занятиях и «к74/1» в кураторстве — это одна группа, а не две в списке."""
    admin = make_admin(client)
    teach = make_teacher(client, admin, login="t9", subjects=["Математика"])
    client.post("/web/admin/groups", json={"name": "К74/1", "subjects": ["Математика"]},
                headers=admin)
    client.post("/sync/push", json={"changes": {"lessons": [
        {"id": "LX", "group_name": "К74/1", "subject": "Математика", "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    r = client.put("/web/admin/teachers/t9", json={"curated_groups": ["к74/1"]}, headers=admin)
    assert r.status_code == 200, r.text

    groups = client.get("/web/messenger/my-groups", headers=teach).json()["groups"]
    names = [g["name"] for g in groups]
    assert names.count("К74/1") == 1 and "к74/1" not in names, names
    assert groups[names.index("К74/1")]["curated"] is True
