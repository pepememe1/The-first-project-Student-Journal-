"""
test_teacher_assignments.py — §ролей: явное назначение преподаватель↔предмет↔группа.

Баг 3.3.1: препод с 5 предметами (A,B,C,D,E), которые встречаются у 3 групп, видел в
журнале/статистике ВСЕ ЭТИ ГРУППЫ, а не только реально назначенные ему — webdata.
teacher_groups() строил список объединением «моё занятие есть» ∪ «мой предмет числится
у группы», без привязки конкретного препода к конкретной группе. Теперь единственный
источник правды — SubjectHours.teacher_id (webdata.teacher_assignments), назначается
через POST /web/admin/group-hours (payload.teachers), тот же редактор, где и часы.
"""
from conftest import make_admin, make_teacher, assign_teacher


def _push_lesson(client, admin, group, subject, lesson_id="L1"):
    r = client.post("/sync/push", json={"changes": {"lessons": [
        {"id": lesson_id, "group_name": group, "subject": subject, "type": "Практика",
         "number": 1, "topic": "т", "date": "01.09.2025"}]}}, headers=admin)
    assert r.status_code == 200, r.text


def test_without_assignment_journal_falls_back_instead_of_going_blank(client):
    """ПЕРЕСМОТРЕНО 30.07.2026 (решение тимлида). Раньше здесь проверялось «0 групп без
    назначения». На бою это дало простой: teacher_id был пуст во ВСЕХ строках часов —
    заполнять его было нечем до появления редактора назначений, — и нагрузка обнулилась
    сразу у всех восьми преподавателей, на сайте и в программе.
    Теперь до расстановки назначений работает прежнее правило. Точный скоуп при этом жив:
    как только назначение появилось, видно ТОЛЬКО его (соседний тест), а выгрузка данных
    на чужой компьютер остаётся строгой всегда (test_sync_pull_... ниже)."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["A", "B", "C", "D", "E"])
    for i, subj in enumerate(["A", "B", "C", "D", "E"]):
        _push_lesson(client, admin, f"G{i}", subj, lesson_id=f"L{i}")

    data = client.get("/web/teacher/overview", headers=th).json()
    assert data["groups"], "без назначений журнал не должен быть пустым"
    assert set(data["subjects"]) <= {"A", "B", "C", "D", "E"}, "только свои предметы"


def test_assignment_shows_exactly_that_pair_not_other_groups_with_same_subject(client):
    """Тот же предмет встречается у ДВУХ групп — назначена только ОДНА, видна только она."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])
    _push_lesson(client, admin, "G1", "Математика", "L1")
    _push_lesson(client, admin, "G2", "Математика", "L2")   # тот же предмет, ЧУЖАЯ группа
    assign_teacher(client, admin, "teach:teacher1", "G1", "Математика")

    data = client.get("/web/teacher/overview", headers=th).json()
    assert data["groups"] == ["G1"]
    assert data["assignments"] == [{"group": "G1", "subject": "Математика"}]

    ok = client.get("/web/teacher/journal", params={"group": "G1", "subject": "Математика"},
                    headers=th)
    assert ok.status_code == 200, ok.text
    forbidden = client.get("/web/teacher/journal",
                           params={"group": "G2", "subject": "Математика"}, headers=th)
    assert forbidden.status_code == 403, "чужая группа с тем же предметом — не видна"


def test_teacher_can_teach_different_subjects_to_different_groups(client):
    """Ведёт математику у 74/1 и информатику у 74/2 — каждая группа со СВОИМ предметом."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика", "Информатика"])
    _push_lesson(client, admin, "74/1", "Математика", "L1")
    _push_lesson(client, admin, "74/2", "Информатика", "L2")
    assign_teacher(client, admin, "teach:teacher1", "74/1", "Математика")
    assign_teacher(client, admin, "teach:teacher1", "74/2", "Информатика")

    assert client.get("/web/teacher/journal", params={"group": "74/1", "subject": "Математика"},
                      headers=th).status_code == 200
    assert client.get("/web/teacher/journal", params={"group": "74/2", "subject": "Информатика"},
                      headers=th).status_code == 200
    #Перекрёстно — НЕ назначено, должно быть 403.
    assert client.get("/web/teacher/journal", params={"group": "74/1", "subject": "Информатика"},
                      headers=th).status_code == 403
    assert client.get("/web/teacher/journal", params={"group": "74/2", "subject": "Математика"},
                      headers=th).status_code == 403


def test_journal_of_foreign_subject_is_still_403(client):
    """ПЕРЕСМОТРЕНО вместе с тестом выше: свой предмет без назначения теперь открывается
    (иначе журнал недоступен всем, см. простой 30.07.2026). А ЧУЖОЙ предмет — по-прежнему
    403: мост касается только видимости своего, права он не расширяет."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])
    _push_lesson(client, admin, "G1", "Математика")
    _push_lesson(client, admin, "G1", "Химия", "L9")      # предмета у него НЕТ
    own = client.get("/web/teacher/journal", params={"group": "G1", "subject": "Математика"},
                     headers=th)
    assert own.status_code == 200, own.text
    foreign = client.get("/web/teacher/journal", params={"group": "G1", "subject": "Химия"},
                         headers=th)
    assert foreign.status_code == 403


def test_sync_pull_without_assignment_brings_no_groups_or_lessons(client):
    """Офлайн-утечка (десктоп): без назначения /sync/pull не привозит ничего лишнего."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])
    client.post("/sync/push", json={"changes": {
        "groups": [{"id": "grp:G1", "name": "G1", "subjects": ["Математика"]}]}},
        headers=admin)
    _push_lesson(client, admin, "G1", "Математика")

    ch = client.get("/sync/pull", headers=th).json()["changes"]
    assert ch["groups"] == [] and ch["lessons"] == []

    assign_teacher(client, admin, "teach:teacher1", "G1", "Математика")
    ch2 = client.get("/sync/pull", headers=th).json()["changes"]
    assert any(g["name"] == "G1" for g in ch2["groups"])
    assert any(l["id"] == "L1" for l in ch2["lessons"])


def test_group_hours_get_reports_teacher_assignment(client):
    """GET /web/admin/group-hours отдаёт назначенного препода вместе с часами."""
    admin = make_admin(client)
    make_teacher(client, admin, subjects=["Математика"])
    client.post("/web/admin/groups", json={"name": "G1", "subjects": ["Математика"]},
                headers=admin)
    assign_teacher(client, admin, "teach:teacher1", "G1", "Математика")

    r = client.get("/web/admin/group-hours?group=G1", headers=admin)
    assert r.status_code == 200, r.text
    row = next(s for s in r.json()["subjects"] if s["subject"] == "Математика")
    assert row["teacher_id"] == "teach:teacher1"
    assert row["teacher_name"] == "Преподаватель"


def test_group_hours_rejects_teacher_without_that_subject(client):
    """Нельзя назначить препода на предмет, которого у него нет в профиле — 400."""
    admin = make_admin(client)
    make_teacher(client, admin, subjects=["Физика"])   # НЕ Математика
    r = client.post("/web/admin/group-hours",
                    json={"group": "G1", "teachers": {"Математика": "teach:teacher1"}},
                    headers=admin)
    assert r.status_code == 400, r.text


def test_group_hours_rejects_unknown_teacher_id(client):
    admin = make_admin(client)
    r = client.post("/web/admin/group-hours",
                    json={"group": "G1", "teachers": {"Математика": "teach:nobody"}},
                    headers=admin)
    assert r.status_code == 404, r.text


def test_unassign_teacher_by_empty_id(client):
    """Пустая строка снимает назначение (тот же приём, что «0 часов = план снят»)."""
    admin = make_admin(client)
    make_teacher(client, admin, subjects=["Математика"])
    client.post("/web/admin/groups", json={"name": "G1", "subjects": ["Математика"]},
               headers=admin)
    assign_teacher(client, admin, "teach:teacher1", "G1", "Математика")
    r = client.post("/web/admin/group-hours",
                    json={"group": "G1", "teachers": {"Математика": ""}}, headers=admin)
    assert r.status_code == 200, r.text
    row = next(s for s in client.get("/web/admin/group-hours?group=G1", headers=admin)
              .json()["subjects"] if s["subject"] == "Математика")
    assert row["teacher_id"] == "" and row["teacher_name"] == ""


def test_only_admin_can_assign_teacher(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])
    r = client.post("/web/admin/group-hours",
                    json={"group": "G1", "teachers": {"Математика": "teach:teacher1"}},
                    headers=th)
    assert r.status_code == 403


def test_removed_from_plan_subject_disappears_from_current_assignments(client):
    """Живой баг 3.6.1: предмет убрали из плана группы (реимпорт учебного плана заменяет
    Group.subjects, см. admin_import_esstu), а преподаватель продолжал видеть журнал по
    нему — SubjectHours.teacher_id пережил сам предмет. teacher_assignments теперь
    сверяет ТЕКУЩИЙ термин с group_plan_subjects и такие пары отбрасывает."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Компьютерные сети"])
    client.post("/web/admin/groups", json={"name": "К74/1", "subjects": ["Компьютерные сети"]},
                headers=admin)
    assign_teacher(client, admin, "teach:teacher1", "К74/1", "Компьютерные сети")
    assert client.get("/web/teacher/overview", headers=th).json()["groups"] == ["К74/1"]

    #план заменён (как при реимпорте) — строка SubjectHours.teacher_id не трогалась
    r = client.put("/web/admin/groups/К74/1", json={"subjects": ["Физика"]}, headers=admin)
    assert r.status_code == 200, r.text

    data = client.get("/web/teacher/overview", headers=th).json()
    assert data["groups"] == [], f"устаревшее назначение не должно висеть: {data}"
    forbidden = client.get("/web/teacher/journal",
                           params={"group": "К74/1", "subject": "Компьютерные сети"}, headers=th)
    assert forbidden.status_code == 403


def test_archived_term_assignment_survives_subject_leaving_todays_plan(client, monkeypatch):
    """Тот же сценарий, но АРХИВНЫЙ (уже закрытый) термин — фильтр по сегодняшнему плану
    на явный просмотр прошлого семестра не распространяется: тогда предмет реально
    велся, и прятать его задним числом было бы переписыванием истории."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Компьютерные сети"])
    client.post("/web/admin/groups", json={"name": "К74/1", "subjects": ["Компьютерные сети"]},
                headers=admin)
    assign_teacher(client, admin, "teach:teacher1", "К74/1", "Компьютерные сети")
    old = client.get("/web/terms", headers=th).json()["current"]

    #Следующий период НАСТУПИЛ (в жизни это делает календарь 1 сентября). Раньше здесь
    #стоял ручной перевод термина вперёд — он теперь запрещён: именно такой сдвиг дважды
    #уводил боевой сервер на год вперёд, и у группы оказывались предметы двух курсов сразу.
    y, s = old["year"], int(old["semester"])
    nxt = (y, 2) if s == 1 else (f"{int(y.split('/')[0]) + 1}/{int(y.split('/')[1]) + 1}", 1)
    from app import db as _db
    monkeypatch.setattr(_db, "default_term", lambda: nxt)

    #план ТЕКУЩЕГО (нового) термина меняется — предмета в нём больше нет
    r = client.put("/web/admin/groups/К74/1", json={"subjects": ["Физика"]}, headers=admin)
    assert r.status_code == 200, r.text

    #явный запрос за СТАРЫЙ (архивный) термин по-прежнему видит назначение
    archived = client.get("/web/teacher/journal",
                          params={"group": "К74/1", "subject": "Компьютерные сети",
                                  "year": old["year"], "semester": old["semester"]}, headers=th)
    assert archived.status_code == 200, archived.text


def test_dropped_subject_hours_row_is_archived_not_left_dangling(client):
    """Живой баг 3.6.1: убранный из плана предмет продолжал считаться «в плане» через
    СВОЮ ЖЕ строку SubjectHours (group_plan_subjects сверяется и по ней, не только по
    Group.subjects) — его ЗЕТ утекал в знаменатель зачёта, а часы висели в редакторе
    рядом со свежим планом. Строка теперь гасится (deleted=True), а не остаётся жить."""
    admin = make_admin(client)
    client.post("/web/admin/groups", json={"name": "G6", "subjects": ["Физика"]}, headers=admin)
    r = client.post("/web/admin/group-hours",
                    json={"group": "G6", "hours": {"Физика": 36}, "zet": {"Физика": 1.0}},
                    headers=admin)
    assert r.status_code == 200, r.text
    before = next(s for s in client.get("/web/admin/group-hours?group=G6", headers=admin)
                 .json()["subjects"] if s["subject"] == "Физика")
    assert before["hours_total"] == 36

    #убираем предмет из плана — его строка часов гасится, а не остаётся висеть
    r = client.put("/web/admin/groups/G6", json={"subjects": []}, headers=admin)
    assert r.status_code == 200, r.text
    after = client.get("/web/admin/group-hours?group=G6", headers=admin).json()
    assert not any(s["subject"] == "Физика" for s in after["subjects"]), after

    #возвращаем предмет в план и пересохраняем часы — находится ТА ЖЕ строка (по
    #составному id), а не плодится дубль с обнулённой историей.
    r = client.put("/web/admin/groups/G6", json={"subjects": ["Физика"]}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/web/admin/group-hours",
                    json={"group": "G6", "hours": {"Физика": 36}}, headers=admin)
    assert r.status_code == 200, r.text
    restored = next(s for s in client.get("/web/admin/group-hours?group=G6", headers=admin)
                    .json()["subjects"] if s["subject"] == "Физика")
    assert restored["hours_total"] == 36


def test_fallback_prefers_real_lessons_over_subject_directory(client):
    """Мост не должен показывать ВЕСЬ колледж.

    «Предмет числится у группы» — слабый признак: предметы вроде «Компьютерные сети» стоят
    у десятков групп, и преподаватель получал в выборе весь колледж вместо своих групп
    (замечено на бою 30.07.2026). Поэтому справочник групп берётся только когда занятий
    нет НИ ОДНОГО — иначе видно ровно те группы, где он действительно ведёт."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Компьютерные сети"])
    _push_lesson(client, admin, "К74/1", "Компьютерные сети", "L1")   # его занятие
    # ещё три группы, где предмет просто числится в справочнике
    client.post("/sync/push", json={"changes": {"groups": [
        {"id": f"grp:X{i}", "name": f"X{i}", "subjects": ["Компьютерные сети"]}
        for i in range(3)]}}, headers=admin)

    data = client.get("/web/teacher/overview", headers=th).json()
    assert data["groups"] == ["К74/1"], f"лишние группы колледжа: {data['groups']}"
