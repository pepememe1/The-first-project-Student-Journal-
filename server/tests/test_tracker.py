"""
test_tracker.py — трекер задач беседы (05.10.2026, просьба Ярослава).

Владелец включает трекер в настройках беседы; в беседе несколько «работ» с задачами;
правки копятся у клиента и уходят ОДНОЙ пачкой по кнопке «Сохранить»; назначенному
приходит ОДНО письмо во вкладку «Уведомления» со всеми его новыми задачами.

🔒 ГЛАВНЫЕ ИНВАРИАНТЫ ФАЙЛА (у каждого обратный ход проверен порчей продукта, см. ниже):
  • `test_one_letter_per_assignee_per_save` — письмо одно на сохранение, сколько бы задач
    человеку ни дали. Ради этого и сделана кнопка «Сохранить»;
  • `test_silenced_member_cannot_write_text_into_tracker` — текст в трекере это такая же
    запись, как сообщение (инвариант §4.27): заглушённый в беседе не пишет и сюда;
  • `test_member_without_rights_cannot_manage` — права проверяет СЕРВЕР, в точке записи;
  • `test_assigning_an_outsider_sends_nothing` — письмо с названием беседы и задачи не
    уходит постороннему.

  • `test_new_work_columns_and_tasks_arrive_in_one_save` — работа, её колонки и задачи
    применяются ОДНОЙ пачкой: так клиент шлёт первое сохранение всегда.

⚠️ Обратные ходы — двенадцать порч продукта, каждая проверена прогоном, а не на глаз:
  • убрать в `_set_assignees` условие `uid != b.user.id` → `test_self_assignment_sends_no_letter`;
  • слать письмо из цикла по задачам, а не по людям → `test_one_letter_per_assignee_per_save`;
  • убрать `_ensure_may_write` из `tracker_save` → оба теста про заглушённых;
  • убрать `_need_manage` из `_op_task_create` → `test_member_without_rights_cannot_manage`;
  • убрать проверку `uid in b.member_ids` → `test_assigning_an_outsider_sends_nothing`
    (проверяет и строку `TrackerAssignee` в базе: одного «письма нет» мало — его
    прикрывали два других слоя, и мутация проходила зелёной);
  • дать исполнителю двигать чужую задачу → `test_assignee_moves_own_task_and_nothing_else`;
  • пустить в настройки не владельца → `test_only_owner_enables_and_everyone_sees_the_button`;
  • отдавать данные выключенного трекера → `test_disabling_hides_data_but_keeps_it`;
  • искать задачу по id без сверки беседы → `test_objects_of_another_conversation_are_out_of_reach`;
  • не сверять `client_id` комментария → `test_retry_of_the_same_batch_changes_nothing`;
  • убрать `db.flush()` после применённой операции → три теста «одной пачкой» (06.10.2026);
  • убрать `seen` у колонок новой работы → `test_duplicate_column_ids_in_one_work_do_not_break_the_save`.

⚔️ ПОЛКОВНИК (06.10.2026) нашёл три правила прав БЕЗ охраняющего теста — мутация каждого
проходила зелёной при 42 тестах — и права, прочитанные ДО замка записи. Ещё четырнадцать
порч, каждая проверена прогоном (06.10.2026, все пойманы):
  • не сверять беседу комментария при удалении → `test_comment_of_another_conversation_cannot_be_deleted`;
  • отдавать комментарии и историю выключенного трекера → `test_details_of_a_switched_off_tracker_are_not_served`;
  • не сверять исполнителя в отметке хода работы → `test_member_cannot_report_progress_on_someone_elses_task`;
  • читать настройки и право вести ДО замка → оба теста «…while_the_save_waits» про
    выключение и про снятое право;
  • не сбрасывать прочитанное до замка (`db.expire_all()`) → `test_member_silenced_while_the_save_waits`;
  • читать строку настроек до замка либо писать настройки вовсе без него (две порчи) →
    `test_two_fast_clicks_on_the_switch_do_not_break_the_first_enable`;
  • не перечитывать роль владельца под замком → `test_ownership_lost_while_the_switch_waits`
    (второй проход Полковника, 07.10.2026);
  • убрать учёт работы пачки (`b.spend`) у смены типа колонки или у меток работы →
    `test_one_save_cannot_rewrite_the_whole_tracker_many_times`;
  • слать письмо прежнему исполнителю → `test_unassigned_and_reassigned_in_one_save_sends_no_second_letter`;
  • пять откатов разбора кривого ввода (позиция, метки, часы, номер комментария
    «бесконечностью» и шире 64 бит) →
    `test_malformed_values_skip_the_operation_not_the_whole_save`; чек-лист числом →
    `test_assignee_progress_with_a_malformed_checklist_is_harmless`.

🔥 УРОК 06.10.2026: первые 39 тестов заводили работу ОТДЕЛЬНЫМ сохранением (`_board`) и
потому были зелены при сломанном главном сценарии — «завёл работу, накидал задач, нажал
„Сохранить“». Нашёл живой прогон в браузере. Вспомогательная функция теста, которая
раскладывает сценарий удобнее, чем это делает клиент, прячет целое измерение: сверяй её
с тем, что реально уходит по сети.
"""
import json
import uuid

import pytest

from conftest import make_admin, make_teacher
from app.security import hash_password
from app.routers.messenger import tracker as T


def _student(client, admin, login, surname, name, group="К-24"):
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": f"{surname} {name}",
        "surname": surname, "name": name, "group_name": group,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    assert r.status_code == 200, r.text
    return f"stud:{login}", {"Authorization": f"Bearer {r.json()['access_token']}"}


def _id(kind):
    return {"p": "trkp:", "c": "trkc:", "t": "trkt:"}[kind] + uuid.uuid4().hex


@pytest.fixture()
def cast(client):
    """Преподаватель-владелец, два студента-участника и посторонний студент."""
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="towner")
    a_id, a = _student(client, admin, "st_a", "Антонова", "Анна")
    b_id, b = _student(client, admin, "st_b", "Борисов", "Борис")
    x_id, x = _student(client, admin, "st_x", "Чужой", "Харитон")
    r = client.post("/web/messenger/chats/group", headers=teacher,
                    json={"title": "Курсовой проект", "member_ids": [a_id, b_id]})
    assert r.status_code == 200, r.text
    return {"admin": admin, "owner": teacher, "owner_id": "teach:towner",
            "a": a, "a_id": a_id, "b": b, "b_id": b_id, "x": x, "x_id": x_id,
            "conv": r.json()["conversation_id"]}


def _url(cast, tail=""):
    return f"/web/messenger/chats/{cast['conv']}/tracker{tail}"


def _enable(client, cast, **extra):
    r = client.put(_url(cast, "/settings"), headers=cast["owner"],
                   json={"enabled": True, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _save(client, cast, who, ops, expect=200):
    r = client.post(_url(cast, "/save"), headers=cast[who], json={"ops": ops})
    assert r.status_code == expect, r.text
    return r.json()


def _board(client, cast, title="Курсовая работа"):
    """Включённый трекер с одной работой. Возвращает (id работы, колонки по типу)."""
    _enable(client, cast)
    pid = _id("p")
    res = _save(client, cast, "owner", [{"op": "project.create", "id": pid, "title": title}])
    assert res["applied"] == 1 and res["skipped"] == []
    project = next(p for p in res["state"]["projects"] if p["id"] == pid)
    return pid, {c["kind"]: c["id"] for c in project["columns"]}


def _events(client, headers, kind="tracker"):
    r = client.get("/me/events", params={"filter": "all", "limit": 100}, headers=headers)
    assert r.status_code == 200, r.text
    return [e for e in r.json()["items"] if e["kind"] == kind]


def _state(client, cast, who="owner"):
    r = client.get(_url(cast), headers=cast[who])
    assert r.status_code == 200, r.text
    return r.json()


def _task(state, tid):
    return next(t for t in state["tasks"] if t["id"] == tid)


# ── включение ─────────────────────────────────────────────────────────────────────────

def test_tracker_is_off_until_owner_enables_it(client, cast):
    st = _state(client, cast)
    assert st["enabled"] is False and st["projects"] == [] and st["tasks"] == []
    info = client.get(f"/web/messenger/chats/{cast['conv']}", headers=cast["a"]).json()
    assert info["tracker_enabled"] is False
    # Выключенный трекер не принимает и записей.
    _save(client, cast, "owner", [{"op": "project.create", "id": _id("p"), "title": "Х"}],
          expect=409)


def test_only_owner_enables_and_everyone_sees_the_button(client, cast):
    # Участник — не владелец: ни включить, ни сменить режим он не может.
    r = client.put(_url(cast, "/settings"), headers=cast["a"], json={"enabled": True})
    assert r.status_code == 403, r.text
    assert _state(client, cast)["enabled"] is False
    st = _enable(client, cast)
    assert st["enabled"] is True and st["can_configure"] is True and st["can_manage"] is True
    # Кнопка в шапке рисуется по этому полю — у ВСЕХ участников, не только у владельца.
    for who in ("a", "b"):
        info = client.get(f"/web/messenger/chats/{cast['conv']}", headers=cast[who]).json()
        assert info["tracker_enabled"] is True
    member = _state(client, cast, "a")
    assert member["enabled"] is True
    assert member["can_configure"] is False and member["can_manage"] is False


def test_enabling_is_announced_in_the_chat(client, cast):
    _enable(client, cast)
    msgs = client.get(f"/web/messenger/chats/{cast['conv']}/messages",
                      headers=cast["a"]).json()["messages"]
    assert any(m.get("kind") == "system" and (m.get("body") or "").startswith("tracker_on")
               for m in msgs), "участники не узнают, откуда взялась кнопка трекера"


def test_disabling_hides_data_but_keeps_it(client, cast):
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["todo"],
                                   "title": "Введение"}])
    client.put(_url(cast, "/settings"), headers=cast["owner"], json={"enabled": False})
    off = _state(client, cast, "a")
    assert off["enabled"] is False and off["tasks"] == [] and off["projects"] == []
    # Включили обратно — распределение за семестр на месте.
    back = _enable(client, cast)
    assert [t["id"] for t in back["tasks"]] == [tid]


def test_tracker_exists_only_in_groups_and_channels(client, cast):
    r = client.post("/web/messenger/chats/direct", headers=cast["a"],
                    json={"user_id": cast["b_id"]})
    if r.status_code != 200:            #ручка личного чата названа иначе — берём «Избранное»
        r = client.post("/web/messenger/chats/saved", headers=cast["a"])
    assert r.status_code == 200, r.text
    direct = r.json()["conversation_id"]
    assert client.get(f"/web/messenger/chats/{direct}/tracker",
                      headers=cast["a"]).status_code == 400
    assert client.put(f"/web/messenger/chats/{direct}/tracker/settings", headers=cast["a"],
                      json={"enabled": True}).status_code == 400


def test_outsider_sees_nothing(client, cast):
    _board(client, cast)
    assert client.get(_url(cast), headers=cast["x"]).status_code == 403
    r = client.post(_url(cast, "/save"), headers=cast["x"],
                    json={"ops": [{"op": "project.create", "id": _id("p"), "title": "Х"}]})
    assert r.status_code == 403, r.text


# ── работы, ключи, номера ─────────────────────────────────────────────────────────────

def test_work_gets_a_key_and_tasks_get_numbers(client, cast):
    pid, cols = _board(client, cast, "Курсовая работа")
    st = _state(client, cast)
    project = st["projects"][0]
    assert project["key"] == "KR", "ключ работы выводится из названия: «Курсовая работа» → KR"
    assert [c["kind"] for c in project["columns"]] == ["todo", "doing", "review", "done"]
    t1, t2 = _id("t"), _id("t")
    res = _save(client, cast, "owner", [
        {"op": "task.create", "id": t1, "column_id": cols["todo"], "title": "Введение"},
        {"op": "task.create", "id": t2, "column_id": cols["todo"], "title": "Глава 1"},
    ])
    assert [_task(res["state"], t)["key"] for t in (t1, t2)] == ["KR-1", "KR-2"]
    # Номер удалённой задачи не переиспользуется: «KR-2» в старом сообщении не должен
    # вдруг начать значить другую задачу.
    t3 = _id("t")
    res = _save(client, cast, "owner", [
        {"op": "task.delete", "id": t2},
        {"op": "task.create", "id": t3, "column_id": cols["todo"], "title": "Глава 2"},
    ])
    assert _task(res["state"], t3)["key"] == "KR-3"


def test_key_is_unique_within_conversation(client, cast):
    _board(client, cast, "Курсовая работа")
    p2 = _id("p")
    res = _save(client, cast, "owner", [{"op": "project.create", "id": p2,
                                         "title": "Контрольная работа"}])
    keys = sorted(p["key"] for p in res["state"]["projects"])
    assert keys == ["KR", "KR2"], f"две работы с одним ключом дали бы две задачи «KR-1»: {keys}"


def test_make_key():
    assert T.make_key("Курсовая работа", set()) == "KR"
    assert T.make_key("Диплом", set()) == "DIPLO"
    assert T.make_key("Web-проект 2026", set()) == "WP2"
    assert T.make_key("!!!", set()) == "TASK"
    assert T.make_key("Курсовая работа", {"KR", "KR2"}) == "KR3"


def test_several_works_in_one_conversation(client, cast):
    """Требование дословно: «в одной беседе можно сделать несколько работ»."""
    _board(client, cast, "Курсовая работа")
    p2 = _id("p")
    res = _save(client, cast, "owner", [{"op": "project.create", "id": p2, "title": "Диплом"}])
    assert len(res["state"]["projects"]) == 2
    cols2 = {c["kind"]: c["id"] for c in
             next(p for p in res["state"]["projects"] if p["id"] == p2)["columns"]}
    tid = _id("t")
    res = _save(client, cast, "owner", [{"op": "task.create", "id": tid,
                                         "column_id": cols2["todo"], "title": "Тема"}])
    assert _task(res["state"], tid)["project_id"] == p2
    assert _task(res["state"], tid)["key"] == "DIPLO-1"


# ── первое «Сохранить»: работа, её колонки и задачи одной пачкой ──────────────────────

def test_new_work_columns_and_tasks_arrive_in_one_save(client, cast):
    """🔥 САМЫЙ ЧАСТЫЙ ПЕРВЫЙ СЦЕНАРИЙ, и он был сломан при 39 зелёных тестах (06.10.2026).

    Человек включает трекер, заводит работу, накидывает задачи, раздаёт их и нажимает
    «Сохранить» — ОДИН раз. Клиент шлёт всё одной пачкой: работу со СВОИМИ колонками (их
    id выдаёт он, иначе до ответа сервера в новую работу нельзя положить ни одной задачи),
    задачи в этих колонках, правки и перестановки только что созданного.

    Сервер применял одну работу, а каждую задачу пропускал с причиной «колонка не
    найдена»: сессия без автосброса, и `Session.get` не видел колонку, добавленную
    предыдущей операцией. Найдено живым прогоном. Тесты выше этого не ловили, потому что
    `_board` заводит работу ОТДЕЛЬНЫМ сохранением — то есть не знали про измерение
    «в одной пачке», и были зелены независимо от него.

    Обратный ход: убрать `db.flush()` после применённой операции в `tracker_save` —
    краснеет этот тест (и два соседних ниже)."""
    _enable(client, cast)
    pid, todo, doing, done, later = _id("p"), _id("c"), _id("c"), _id("c"), _id("c")
    t1, t2, t3, t4 = _id("t"), _id("t"), _id("t"), _id("t")
    ops = [
        {"op": "project.create", "id": pid, "title": "Курсовая работа", "key": "KR",
         "columns": [{"id": todo, "title": "К выполнению", "kind": "todo"},
                     {"id": doing, "title": "В работе", "kind": "doing"},
                     {"id": done, "title": "Готово", "kind": "done"}],
         "labels": [{"id": "lab1", "title": "Теория", "color": ""}]},
        {"op": "task.create", "id": t1, "column_id": todo, "title": "Собрать требования",
         "assignees": [cast["a_id"], cast["b_id"]], "deadline": "2026-10-12"},
        {"op": "task.create", "id": t2, "column_id": todo, "title": "Свёрстать главную",
         "assignees": [cast["a_id"]], "position": 1},
        #Без исполнителей и без единого поля сверх названия: у такой задачи внутри операции
        #нет ни одного попутного сброса, и именно она пропускалась первой.
        {"op": "task.create", "id": t3, "column_id": todo, "title": "Презентация", "position": 2},
        #Поля, которые клиент НЕ вливает в создание (ссылаются на другое) — отдельной правкой.
        {"op": "task.update", "id": t2, "labels": ["lab1"], "parent_id": t1},
        {"op": "task.move", "id": t3, "column_id": doing, "position": 0},
        #Колонка, добавленная к только что созданной работе, и задача в неё.
        {"op": "column.create", "id": later, "project_id": pid, "title": "Отложено", "kind": "todo"},
        {"op": "task.create", "id": t4, "column_id": later, "title": "На потом"},
        {"op": "comment.add", "id": "k1", "task_id": t3, "body": "Начинаем с неё"},
        {"op": "project.update", "id": pid, "description": "Сайт колледжа"},
        {"op": "column.update", "id": later, "title": "Когда-нибудь"},
    ]
    res = _save(client, cast, "owner", ops)
    assert res["skipped"] == [], f"операции первой пачки пропущены: {res['skipped']}"
    assert res["applied"] == len(ops)
    state = res["state"]
    assert {t["id"]: t["key"] for t in state["tasks"]} == {
        t1: "KR-1", t2: "KR-2", t3: "KR-3", t4: "KR-4"}
    assert _task(state, t3)["column_id"] == doing
    assert _task(state, t2)["labels"] == ["lab1"] and _task(state, t2)["parent_id"] == t1
    assert _task(state, t3)["comment_count"] == 1
    assert _task(state, t4)["column_id"] == later
    project = next(p for p in state["projects"] if p["id"] == pid)
    assert project["description"] == "Сайт колледжа"
    assert [c["title"] for c in project["columns"]] == [
        "К выполнению", "В работе", "Готово", "Когда-нибудь"]
    #И то, ради чего всё: каждому исполнителю — одно письмо, со всеми его задачами.
    assert res["notified"] == 2
    a_letters, b_letters = _events(client, cast["a"]), _events(client, cast["b"])
    assert len(a_letters) == 1 and len(b_letters) == 1
    #Список писем содержимого не несёт — оно приходит с самим письмом (страница письма).
    def letter_tasks(who, letters):
        full = client.get(f"/me/events/{letters[0]['id']}", headers=cast[who]).json()
        return {t["id"] for t in full["payload"]["tasks"]}
    assert letter_tasks("a", a_letters) == {t1, t2}
    assert letter_tasks("b", b_letters) == {t1}


def test_work_created_and_deleted_in_one_save_leaves_nothing(client, cast):
    """Завёл работу с задачами, передумал и удалил — до «Сохранить». Клиент такую пару не
    сжимает (удаление — граница сжатия), и сервер обязан её пережить: без сброса удаление
    работы не находило её только что созданных задач и колонок."""
    _enable(client, cast)
    pid, col, tid = _id("p"), _id("c"), _id("t")
    res = _save(client, cast, "owner", [
        {"op": "project.create", "id": pid, "title": "Черновик",
         "columns": [{"id": col, "title": "К выполнению", "kind": "todo"}]},
        {"op": "task.create", "id": tid, "column_id": col, "title": "Лишняя",
         "assignees": [cast["a_id"]]},
        {"op": "project.delete", "id": pid},
    ])
    assert res["skipped"] == [] and res["applied"] == 3
    assert res["state"]["projects"] == [] and res["state"]["tasks"] == []
    assert res["notified"] == 0
    assert _events(client, cast["a"]) == [], "письмо о задаче, которой уже нет"
    #Та же колонка и та же задача в базе не остались сиротами: их id снова свободны.
    again = _save(client, cast, "owner", [
        {"op": "project.create", "id": pid, "title": "Черновик",
         "columns": [{"id": col, "title": "К выполнению", "kind": "todo"}]},
        {"op": "task.create", "id": tid, "column_id": col, "title": "Нужная"},
    ])
    assert again["skipped"] == [] and len(again["state"]["tasks"]) == 1


def test_duplicate_column_ids_in_one_work_do_not_break_the_save(client, cast):
    """Две колонки с одним id в одной работе — кривой клиент, а не повод отвечать 500 на
    всю пачку: вторая колонка пропускается, остальное применяется."""
    _enable(client, cast)
    pid, col, tid = _id("p"), _id("c"), _id("t")
    res = _save(client, cast, "owner", [
        {"op": "project.create", "id": pid, "title": "Работа",
         "columns": [{"id": col, "title": "Первая", "kind": "todo"},
                     {"id": col, "title": "Двойник", "kind": "done"}]},
        {"op": "task.create", "id": tid, "column_id": col, "title": "Задача"},
    ])
    assert res["skipped"] == []
    project = next(p for p in res["state"]["projects"] if p["id"] == pid)
    assert [c["title"] for c in project["columns"]] == ["Первая"]
    assert _task(res["state"], tid)["completed_at"] == "", "задача легла в колонку-двойника"


# ── письмо исполнителю ────────────────────────────────────────────────────────────────

def test_one_letter_per_assignee_per_save(client, cast):
    """🔒 Ради этого и сделана кнопка «Сохранить»: три задачи одному человеку за одно
    сохранение — это ОДНО письмо, а не три."""
    pid, cols = _board(client, cast)
    ids = [_id("t") for _ in range(3)]
    res = _save(client, cast, "owner", [
        {"op": "task.create", "id": tid, "column_id": cols["todo"], "title": f"Задача {i}",
         "deadline": "2026-10-20", "assignees": [cast["a_id"]]}
        for i, tid in enumerate(ids, 1)])
    assert res["notified"] == 1
    letters = _events(client, cast["a"])
    assert len(letters) == 1, f"три задачи за одно сохранение дали {len(letters)} писем"
    # Превью — без подробностей (формулировка из требования), подробности — внутри.
    assert letters[0]["title"] == "Вам дали задания в трекере: 3"
    full = client.get(f"/me/events/{letters[0]['id']}", headers=cast["a"]).json()
    tasks = full["payload"]["tasks"]
    assert [t["key"] for t in tasks] == ["KR-1", "KR-2", "KR-3"]
    assert tasks[0]["deadline"] == "2026-10-20" and tasks[0]["project"] == "Курсовая работа"
    assert full["payload"]["conversation_id"] == cast["conv"]
    assert full["payload"]["assigned_by"]
    # Второй участник задач не получал — и письма у него нет.
    assert _events(client, cast["b"]) == []


def test_single_task_letter_uses_the_requested_wording(client, cast):
    pid, cols = _board(client, cast)
    _save(client, cast, "owner", [{"op": "task.create", "id": _id("t"),
                                   "column_id": cols["todo"], "title": "Введение",
                                   "assignees": [cast["a_id"]]}])
    assert _events(client, cast["a"])[0]["title"] == "Вам дали задание в трекере"


def test_resaving_without_new_assignments_sends_nothing(client, cast):
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["todo"],
                                   "title": "Введение", "assignees": [cast["a_id"]]}])
    # Правка названия и тот же состав исполнителей — назначения НЕ случилось.
    res = _save(client, cast, "owner", [{"op": "task.update", "id": tid, "title": "Введение+",
                                         "assignees": [cast["a_id"]]}])
    assert res["notified"] == 0
    assert len(_events(client, cast["a"])) == 1
    # Добавили второго — письмо получает только он.
    res = _save(client, cast, "owner", [{"op": "task.update", "id": tid,
                                         "assignees": [cast["a_id"], cast["b_id"]]}])
    assert res["notified"] == 1
    assert len(_events(client, cast["a"])) == 1 and len(_events(client, cast["b"])) == 1


def test_self_assignment_sends_no_letter(client, cast):
    pid, cols = _board(client, cast)
    res = _save(client, cast, "owner", [{"op": "task.create", "id": _id("t"),
                                         "column_id": cols["todo"], "title": "Своё",
                                         "assignees": [cast["owner_id"]]}])
    assert res["notified"] == 0
    assert _events(client, cast["owner"]) == []


def test_assigned_then_unassigned_in_one_save_sends_nothing(client, cast):
    pid, cols = _board(client, cast)
    tid = _id("t")
    res = _save(client, cast, "owner", [
        {"op": "task.create", "id": tid, "column_id": cols["todo"], "title": "Передумал",
         "assignees": [cast["a_id"]]},
        {"op": "task.update", "id": tid, "assignees": []},
    ])
    assert res["notified"] == 0 and _events(client, cast["a"]) == []


def test_assigning_an_outsider_sends_nothing(client, cast):
    """🔒 В письме — название беседы и задачи. Постороннему оно уйти не должно."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    res = _save(client, cast, "owner", [{"op": "task.create", "id": tid,
                                         "column_id": cols["todo"], "title": "Секретное",
                                         "assignees": [cast["x_id"], cast["a_id"]]}])
    assert _task(res["state"], tid)["assignees"] == [cast["a_id"]]
    assert _events(client, cast["x"]) == []
    assert len(_events(client, cast["a"])) == 1
    #⚠️ Смотрим и САМУ СТРОКУ в базе, а не только ответ. Защит здесь три (запись,
    #выдача состояния, рассылка писем), и первая версия теста проверяла две последние:
    #порча первой оставляла его зелёным (поймано обратным ходом 05.10.2026). А строка
    #назначения на постороннего — мина: войдёт он в беседу позже и окажется исполнителем
    #задачи, о которой ему никто не писал.
    from app.db import SessionLocal
    from app.models import TrackerAssignee
    db = SessionLocal()
    try:
        stored = {r.user_id for r in db.query(TrackerAssignee).filter(
            TrackerAssignee.task_id == tid).all()}
    finally:
        db.close()
    assert stored == {cast["a_id"]}, f"в базе записано назначение на постороннего: {stored}"


def test_push_text_carries_no_details():
    """Через посредника доставки уходит только «что-то этого рода пришло»."""
    from app import rustore_push
    title, body = rustore_push.push_text({"type": "tracker"})
    assert "Курсов" not in title + body and title and body
    assert rustore_push.category_of({"type": "tracker"}) == "tracker"
    for role in ("student", "teacher", "parent", "admin", "moderator"):
        assert "tracker" in rustore_push.ROLE_CATEGORIES[role]


def test_muted_conversation_gets_the_letter_but_no_push(client, cast, monkeypatch):
    """Мьют беседы глушит звонок, а не историю: письмо во вкладке остаётся."""
    from app import rustore_push
    pushed = []
    monkeypatch.setattr(rustore_push, "notify_login",
                        lambda db, login, *a, **k: pushed.append(login) or 0)
    pid, cols = _board(client, cast)
    r = client.post(f"/web/messenger/chats/{cast['conv']}/mute", headers=cast["a"],
                    json={"muted": True})
    assert r.status_code == 200, r.text
    _save(client, cast, "owner", [{"op": "task.create", "id": _id("t"),
                                   "column_id": cols["todo"], "title": "Тихо",
                                   "assignees": [cast["a_id"], cast["b_id"]]}])
    assert len(_events(client, cast["a"])) == 1
    assert pushed == ["st_b"], f"пуш ушёл замьютившему беседу: {pushed}"


# ── права ─────────────────────────────────────────────────────────────────────────────

def test_member_without_rights_cannot_manage(client, cast):
    """🔒 Права проверяет сервер: скрытая кнопка — не защита."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    res = _save(client, cast, "a", [
        {"op": "task.create", "id": tid, "column_id": cols["todo"], "title": "Самовольно"},
        {"op": "project.create", "id": _id("p"), "title": "Своя работа"},
        {"op": "column.create", "id": _id("c"), "project_id": pid, "title": "Своя"},
        {"op": "project.delete", "id": pid},
    ])
    assert res["applied"] == 0
    assert {s["reason"] for s in res["skipped"]} == {"нет права вести трекер"}
    st = _state(client, cast)
    assert st["tasks"] == [] and len(st["projects"]) == 1


def test_assignee_moves_own_task_and_nothing_else(client, cast):
    pid, cols = _board(client, cast)
    mine, other = _id("t"), _id("t")
    _save(client, cast, "owner", [
        {"op": "task.create", "id": mine, "column_id": cols["todo"], "title": "Моя",
         "assignees": [cast["a_id"]],
         "checklist": [{"id": "c1", "text": "Собрать источники", "done": False}]},
        {"op": "task.create", "id": other, "column_id": cols["todo"], "title": "Чужая",
         "assignees": [cast["b_id"]]},
    ])
    res = _save(client, cast, "a", [
        {"op": "task.move", "id": mine, "column_id": cols["doing"]},
        {"op": "task.update", "id": mine,
         "checklist": [{"id": "c1", "text": "ПЕРЕПИСАЛ", "done": True}], "spent": 1.5},
        {"op": "task.move", "id": other, "column_id": cols["done"]},
        {"op": "task.update", "id": mine, "title": "Переименовал"},
        {"op": "task.update", "id": mine, "assignees": [cast["b_id"]]},
    ])
    assert res["applied"] == 2 and len(res["skipped"]) == 3
    t = _task(res["state"], mine)
    assert t["column_id"] == cols["doing"] and t["title"] == "Моя"
    assert t["spent"] == 1.5 and t["assignees"] == [cast["a_id"]]
    # Отметка поставлена, а ТЕКСТ пункта исполнитель поменять не смог.
    assert t["checklist"] == [{"id": "c1", "text": "Собрать источники", "done": True}]
    assert _task(res["state"], other)["column_id"] == cols["todo"]


def test_open_edit_lets_every_member_manage(client, cast):
    _enable(client, cast, open_edit=True)
    pid = _id("p")
    res = _save(client, cast, "a", [{"op": "project.create", "id": pid, "title": "Команда"}])
    assert res["applied"] == 1
    assert _state(client, cast, "b")["can_manage"] is True


def test_tracker_permission_can_be_granted_by_role(client, cast):
    pid, cols = _board(client, cast)
    r = client.post(f"/web/messenger/chats/{cast['conv']}/roles", headers=cast["owner"],
                    json={"name": "Староста", "permissions": ["tracker"]})
    assert r.status_code == 200, r.text
    role_id = r.json()["id"]
    r = client.post(f"/web/messenger/chats/{cast['conv']}/members/{cast['a_id']}/role",
                    headers=cast["owner"], json={"custom_role_id": role_id})
    assert r.status_code == 200, r.text
    assert _state(client, cast, "a")["can_manage"] is True
    res = _save(client, cast, "a", [{"op": "task.create", "id": _id("t"),
                                     "column_id": cols["todo"], "title": "От старосты"}])
    assert res["applied"] == 1
    # У второго участника права нет — и это не сломалось.
    assert _state(client, cast, "b")["can_manage"] is False


# ── текст в трекере — такая же запись, как сообщение ──────────────────────────────────

def _silence(client, cast, surname="Антонова"):
    r = client.post(f"/web/messenger/chats/{cast['conv']}/messages", headers=cast["owner"],
                    json={"body": f"/mute @{surname}"})
    assert r.status_code == 200, r.text


def test_silenced_member_cannot_write_text_into_tracker(client, cast):
    """🔒 Инвариант §4.27. Без этого трекер — обход `/mute`: пиши не в чат, а в
    комментарий к задаче, его видят те же люди."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["todo"],
                                   "title": "Задача", "assignees": [cast["a_id"]],
                                   "checklist": [{"id": "c1", "text": "Пункт", "done": False}]}])
    _silence(client, cast)
    r = client.post(_url(cast, "/save"), headers=cast["a"],
                    json={"ops": [{"op": "comment.add", "id": "k1", "task_id": tid,
                                   "body": "а я всё равно напишу"}]})
    assert r.status_code == 403, r.text
    assert "заглушены" in r.json()["detail"]
    details = client.get(_url(cast, f"/tasks/{tid}/details"), headers=cast["owner"]).json()
    assert details["comments"] == []


def test_silenced_assignee_can_still_report_progress(client, cast):
    """Глушат слова, а не работу: отметить пункт и сдвинуть свою задачу можно."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["todo"],
                                   "title": "Задача", "assignees": [cast["a_id"]],
                                   "checklist": [{"id": "c1", "text": "Пункт", "done": False}]}])
    _silence(client, cast)
    res = _save(client, cast, "a", [
        {"op": "task.move", "id": tid, "column_id": cols["done"]},
        {"op": "task.update", "id": tid,
         "checklist": [{"id": "c1", "text": "Пункт", "done": True}]},
    ])
    assert res["applied"] == 2
    t = _task(res["state"], tid)
    assert t["column_id"] == cols["done"] and t["checklist"][0]["done"] is True
    assert t["completed_at"], "переход в «Готово» обязан проставить время завершения"


def test_open_edit_does_not_let_a_silenced_member_write(client, cast):
    """`open_edit` даёт право ВЕСТИ трекер, но не отменяет заглушку."""
    _enable(client, cast, open_edit=True)
    _silence(client, cast)
    r = client.post(_url(cast, "/save"), headers=cast["a"],
                    json={"ops": [{"op": "project.create", "id": _id("p"),
                                   "title": "Обход заглушки"}]})
    assert r.status_code == 403, r.text


def test_profanity_is_masked_like_in_messages(client, cast):
    import profanity_filter
    dirty = "Сдать, блядь, отчёт"
    assert profanity_filter.censor(dirty, mask=profanity_filter.MESSENGER_SAFE_MASK) != dirty, (
        "фильтр не узнал слово — тест ослеп, подберите другое")
    pid, cols = _board(client, cast)
    tid = _id("t")
    res = _save(client, cast, "owner", [{"op": "task.create", "id": tid,
                                         "column_id": cols["todo"], "title": dirty}])
    assert _task(res["state"], tid)["title"] != dirty


# ── целостность пачки ─────────────────────────────────────────────────────────────────

def test_retry_of_the_same_batch_changes_nothing(client, cast):
    """Связь оборвалась после записи: клиент не знает, дошло ли, и шлёт пачку снова."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    ops = [
        {"op": "task.create", "id": tid, "column_id": cols["todo"], "title": "Введение",
         "assignees": [cast["a_id"]]},
        {"op": "comment.add", "id": "k1", "task_id": tid, "body": "Начните с обзора"},
    ]
    first = _save(client, cast, "owner", ops)
    assert first["applied"] == 2 and first["notified"] == 1
    second = _save(client, cast, "owner", ops)
    assert second["applied"] == 0 and second["notified"] == 0
    assert {s["reason"] for s in second["skipped"]} == {"уже есть"}
    assert len(second["state"]["tasks"]) == 1
    details = client.get(_url(cast, f"/tasks/{tid}/details"), headers=cast["owner"]).json()
    assert len(details["comments"]) == 1, "повтор пачки удвоил комментарий"
    assert len(_events(client, cast["a"])) == 1, "повтор пачки прислал второе письмо"


def test_bad_operation_is_skipped_and_the_rest_applied(client, cast):
    pid, cols = _board(client, cast)
    good = _id("t")
    res = _save(client, cast, "owner", [
        {"op": "task.create", "id": good, "column_id": cols["todo"], "title": "Хорошая"},
        {"op": "task.create", "id": _id("t"), "column_id": cols["todo"], "title": "   "},
        {"op": "task.create", "id": "не-id", "column_id": cols["todo"], "title": "Плохой id"},
        {"op": "task.create", "id": _id("t"), "column_id": cols["todo"], "title": "Срок",
         "deadline": "завтра"},
        {"op": "task.update", "id": _id("t"), "title": "Нет такой"},
        {"op": "что.это", "id": "x"},
    ])
    assert res["applied"] == 1 and len(res["skipped"]) == 5
    assert [t["id"] for t in res["state"]["tasks"]] == [good]
    # Отклонённые задачи номеров не заняли.
    next_id = _id("t")
    res = _save(client, cast, "owner", [{"op": "task.create", "id": next_id,
                                         "column_id": cols["todo"], "title": "Следующая"}])
    assert _task(res["state"], next_id)["key"] == "KR-2"


def test_rejected_update_changes_no_field_at_all(client, cast):
    """Операция либо применяется целиком, либо не меняет ничего: отказ на одном поле
    не должен оставить записанными остальные."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["todo"],
                                   "title": "Прежнее", "priority": "minor"}])
    res = _save(client, cast, "owner", [{"op": "task.update", "id": tid, "title": "Новое",
                                         "priority": "critical", "deadline": "не дата"}])
    assert res["applied"] == 0
    t = _task(res["state"], tid)
    assert t["title"] == "Прежнее" and t["priority"] == "minor"


def test_objects_of_another_conversation_are_out_of_reach(client, cast):
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["todo"],
                                   "title": "Чужая задача"}])
    # Вторая беседа того же владельца со своим трекером.
    r = client.post("/web/messenger/chats/group", headers=cast["owner"],
                    json={"title": "Другая", "member_ids": [cast["x_id"]]})
    other = {**cast, "conv": r.json()["conversation_id"]}
    _enable(client, other)
    res = _save(client, other, "owner", [
        {"op": "task.update", "id": tid, "title": "Дотянулся"},
        {"op": "task.delete", "id": tid},
        {"op": "task.create", "id": _id("t"), "column_id": cols["todo"], "title": "В чужую колонку"},
        {"op": "project.delete", "id": pid},
    ])
    assert res["applied"] == 0 and len(res["skipped"]) == 4
    assert _task(_state(client, cast), tid)["title"] == "Чужая задача"
    # И прочитать чужую задачу через свою беседу нельзя.
    assert client.get(f"/web/messenger/chats/{other['conv']}/tracker/tasks/{tid}/details",
                      headers=cast["owner"]).status_code == 404


def test_too_many_operations_are_refused(client, cast):
    _enable(client, cast)
    ops = [{"op": "task.move", "id": _id("t")} for _ in range(T._MAX_OPS + 1)]
    r = client.post(_url(cast, "/save"), headers=cast["owner"], json={"ops": ops})
    assert r.status_code == 413, r.text


# ── колонки, подзадачи, связи, история ────────────────────────────────────────────────

def test_column_with_tasks_is_not_deleted_silently(client, cast):
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["review"],
                                   "title": "На проверке"}])
    res = _save(client, cast, "owner", [{"op": "column.delete", "id": cols["review"]}])
    assert res["applied"] == 0, "колонку с задачами удалили без указания, куда их перенести"
    res = _save(client, cast, "owner", [{"op": "column.delete", "id": cols["review"],
                                         "move_to": cols["doing"]}])
    assert res["applied"] == 1
    assert _task(res["state"], tid)["column_id"] == cols["doing"]


def test_deleting_a_work_removes_its_tasks(client, cast):
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [
        {"op": "task.create", "id": tid, "column_id": cols["todo"], "title": "Задача"},
        {"op": "comment.add", "id": "k1", "task_id": tid, "body": "Комментарий"},
    ])
    res = _save(client, cast, "owner", [{"op": "project.delete", "id": pid}])
    assert res["state"]["projects"] == [] and res["state"]["tasks"] == []
    from app.db import SessionLocal
    from app.models import TrackerActivity, TrackerAssignee, TrackerColumn, TrackerComment
    db = SessionLocal()
    try:
        for model in (TrackerColumn, TrackerComment, TrackerActivity, TrackerAssignee):
            assert db.query(model).count() == 0, f"после удаления работы остались строки {model.__name__}"
    finally:
        db.close()


def test_subtasks_links_and_their_cleanup(client, cast):
    pid, cols = _board(client, cast)
    parent, child, other = _id("t"), _id("t"), _id("t")
    res = _save(client, cast, "owner", [
        {"op": "task.create", "id": parent, "column_id": cols["todo"], "title": "Глава 1",
         "kind": "epic"},
        {"op": "task.create", "id": child, "column_id": cols["todo"], "title": "Параграф 1.1",
         "parent_id": parent},
        {"op": "task.create", "id": other, "column_id": cols["todo"], "title": "Источники",
         "links": [{"type": "blocks", "task_id": parent}]},
    ])
    assert res["applied"] == 3
    assert _task(res["state"], child)["parent_id"] == parent
    assert _task(res["state"], other)["links"] == [{"type": "blocks", "task_id": parent}]
    # Цикл «родитель — подзадача своей подзадачи» отклоняется.
    res = _save(client, cast, "owner", [{"op": "task.update", "id": parent, "parent_id": child}])
    assert res["applied"] == 0
    # Удалили родителя: подзадача осталась обычной задачей, связь на него убрана.
    res = _save(client, cast, "owner", [{"op": "task.delete", "id": parent}])
    assert _task(res["state"], child)["parent_id"] == ""
    assert _task(res["state"], other)["links"] == []


def test_task_fields_of_tracker_level(client, cast):
    """Поля уровня Яндекс Трекера: тип, приоритет, даты, оценка и затраченное время."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    res = _save(client, cast, "owner", [
        {"op": "project.update", "id": pid,
         "labels": [{"id": "l1", "title": "Теория", "color": "blue"}]},
        {"op": "task.create", "id": tid, "column_id": cols["todo"], "title": "Обзор литературы",
         "kind": "improvement", "priority": "critical", "start_date": "2026-10-06",
         "deadline": "2026-10-20T18:00", "estimate": 6, "labels": ["l1", "нет-такой"]},
    ])
    t = _task(res["state"], tid)
    assert (t["kind"], t["priority"]) == ("improvement", "critical")
    assert (t["start_date"], t["deadline"]) == ("2026-10-06", "2026-10-20T18:00")
    assert t["estimate"] == 6.0 and t["labels"] == ["l1"]
    # Неизвестные значения не записываются «как есть».
    res = _save(client, cast, "owner", [{"op": "task.update", "id": tid, "priority": "срочно"}])
    assert res["applied"] == 0
    # Несуществующая дата под шаблон подходит, но датой не является (нашёл клиентский
    # тест: JS молча переносил «2026-13-45» на февраль 2027-го).
    res = _save(client, cast, "owner", [{"op": "task.update", "id": tid,
                                         "deadline": "2026-13-45"}])
    assert res["applied"] == 0 and res["skipped"][0]["reason"] == "такой даты не существует"
    assert _task(res["state"], tid)["deadline"] == "2026-10-20T18:00"
    # Снятая с работы метка уходит и с задач.
    res = _save(client, cast, "owner", [{"op": "project.update", "id": pid, "labels": []}])
    assert _task(res["state"], tid)["labels"] == []


def test_history_tells_who_did_what(client, cast):
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["todo"],
                                   "title": "Введение", "assignees": [cast["a_id"]]}])
    _save(client, cast, "a", [{"op": "task.move", "id": tid, "column_id": cols["doing"]}])
    _save(client, cast, "owner", [{"op": "task.update", "id": tid, "priority": "blocker",
                                   "title": "Введение"}])
    details = client.get(_url(cast, f"/tasks/{tid}/details"), headers=cast["b"]).json()
    kinds = [h["kind"] for h in details["history"]]
    assert kinds == ["created", "assigned", "moved", "changed"], kinds
    moved = details["history"][2]
    assert moved["data"] == {"from": "К выполнению", "to": "В работе"}
    assert moved["actor_id"] == cast["a_id"] and moved["actor_name"] == "Антонова Анна"
    changed = details["history"][3]
    # Название не менялось — в истории только то, что РЕАЛЬНО поменяли.
    assert changed["data"] == {"field": "priority", "old": "normal", "new": "blocker"}


def test_comments_are_added_by_any_member_and_deleted_by_author(client, cast):
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["todo"],
                                   "title": "Задача"}])
    res = _save(client, cast, "b", [{"op": "comment.add", "id": "k1", "task_id": tid,
                                     "body": "Могу помочь"}])
    assert res["applied"] == 1
    assert _task(res["state"], tid)["comment_count"] == 1
    details = client.get(_url(cast, f"/tasks/{tid}/details"), headers=cast["a"]).json()
    cid = details["comments"][0]["id"]
    assert details["comments"][0]["author_name"] == "Борисов Борис"
    # Чужой комментарий участник удалить не может, автор — может.
    assert _save(client, cast, "a", [{"op": "comment.delete", "id": cid}])["applied"] == 0
    assert _save(client, cast, "b", [{"op": "comment.delete", "id": cid}])["applied"] == 1


# ── находки Полковника (06.10.2026): права без охраны, гонка прав, кривой ввод ────────

def _second_conversation(client, cast, **settings):
    """Вторая беседа того же владельца с включённым трекером; участник в ней — «чужой»
    студент, которого нет в первой."""
    r = client.post("/web/messenger/chats/group", headers=cast["owner"],
                    json={"title": "Другая", "member_ids": [cast["x_id"]]})
    assert r.status_code == 200, r.text
    other = {**cast, "conv": r.json()["conversation_id"]}
    _enable(client, other, **settings)
    return other


def test_comment_of_another_conversation_cannot_be_deleted(client, cast):
    """🔒 Номера комментариев сквозные по базе. Без сверки беседы удалить чужой комментарий
    мог бы каждый, кто ведёт трекер ХОТЬ ГДЕ-ТО: владелец соседней беседы, а при «задачи
    ставит каждый» — любой её участник, простым перебором номеров."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["todo"],
                                   "title": "Задача"}])
    _save(client, cast, "b", [{"op": "comment.add", "id": "k1", "task_id": tid,
                               "body": "Важное замечание"}])
    details = client.get(_url(cast, f"/tasks/{tid}/details"), headers=cast["a"]).json()
    cid = details["comments"][0]["id"]
    other = _second_conversation(client, cast, open_edit=True)
    for who in ("owner", "x"):          #владелец соседней беседы и её рядовой участник
        res = _save(client, other, who, [{"op": "comment.delete", "id": cid}])
        assert res["applied"] == 0, f"{who} удалил комментарий чужой беседы"
        assert res["skipped"][0]["reason"] == "комментарий не найден"
    details = client.get(_url(cast, f"/tasks/{tid}/details"), headers=cast["a"]).json()
    assert [c["body"] for c in details["comments"]] == ["Важное замечание"]


def test_details_of_a_switched_off_tracker_are_not_served(client, cast):
    """Выключенный трекер данных не отдаёт вовсе — и ручка задачи тоже: иначе комментарии
    и история по известному id читались бы и после выключения."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [
        {"op": "task.create", "id": tid, "column_id": cols["todo"], "title": "Задача"},
        {"op": "comment.add", "id": "k1", "task_id": tid, "body": "Черновик замечаний"},
    ])
    assert client.get(_url(cast, f"/tasks/{tid}/details"), headers=cast["a"]).status_code == 200
    r = client.put(_url(cast, "/settings"), headers=cast["owner"], json={"enabled": False})
    assert r.status_code == 200, r.text
    for who in ("a", "owner"):
        r = client.get(_url(cast, f"/tasks/{tid}/details"), headers=cast[who])
        assert r.status_code == 409, f"{who}: {r.status_code} {r.text}"


def test_member_cannot_report_progress_on_someone_elses_task(client, cast):
    """Отметки чек-листа и затраченное время — только в СВОЕЙ задаче. Без сверки
    исполнителя любой участник списывал бы часы и закрывал пункты в чужой работе."""
    pid, cols = _board(client, cast)
    other = _id("t")
    _save(client, cast, "owner", [{
        "op": "task.create", "id": other, "column_id": cols["todo"], "title": "Чужая",
        "assignees": [cast["b_id"]],
        "checklist": [{"id": "c1", "text": "Пункт", "done": False}]}])
    res = _save(client, cast, "a", [
        {"op": "task.update", "id": other, "spent": 7},
        {"op": "task.update", "id": other,
         "checklist": [{"id": "c1", "text": "Пункт", "done": True}]},
    ])
    assert res["applied"] == 0
    assert {s["reason"] for s in res["skipped"]} == {"нет права вести трекер"}
    t = _task(res["state"], other)
    assert t["spent"] == 0 and t["checklist"][0]["done"] is False
    # А сам исполнитель то же самое сделать может: правило режет чужих, а не всех.
    res = _save(client, cast, "b", [{"op": "task.update", "id": other, "spent": 2}])
    assert res["applied"] == 1 and _task(res["state"], other)["spent"] == 2


def _race(monkeypatch, change):
    """Гонка без потоков. `change(db)` выполняется и коммитится ОТДЕЛЬНОЙ сессией в тот
    миг, когда запрос уже прошёл первые чтения и встал за замком записи, — ровно там, где
    на бою вклинивается чужой запрос. Возвращает список: непустой — замок действительно
    брали (иначе тест, ждущий отказа, покраснел бы по другой причине и её не назвал бы)."""
    from app.db import SessionLocal
    from app.routers.web import _common as W
    real, fired = W._lock_for_write, []

    def lock(db):
        if not fired:
            fired.append(True)
            other = SessionLocal()
            try:
                change(other)
                other.commit()
            finally:
                other.close()
        return real(db)

    monkeypatch.setattr(W, "_lock_for_write", lock)
    return fired


def test_tracker_switched_off_while_the_save_waits_is_refused(client, cast, monkeypatch):
    """🔒 Инварианты §4.26 и §4.29 (нашёл Полковник). Настройки и права читались ДО замка
    записи и под ним не перечитывались: владелец выключал трекер, пока чужое сохранение
    ждало очереди, — и пачка всё равно применялась, уже в выключенный трекер."""
    from app.models import TrackerSettings
    _enable(client, cast, open_edit=True)
    fired = _race(monkeypatch, lambda db: db.query(TrackerSettings).filter(
        TrackerSettings.conversation_id == cast["conv"]).update({"enabled": False}))
    _save(client, cast, "a", [{"op": "project.create", "id": _id("p"), "title": "Опоздал"}],
          expect=409)
    assert fired, "сохранение не взяло замок записи — тест ослеп"
    assert _enable(client, cast)["projects"] == []


def test_right_to_manage_revoked_while_the_save_waits(client, cast, monkeypatch):
    """То же с «задачи ставит каждый»: владелец снял режим — пачка участника, уже
    стоявшая в очереди, не применяется по праву, которого больше нет."""
    from app.models import TrackerSettings
    _enable(client, cast, open_edit=True)
    fired = _race(monkeypatch, lambda db: db.query(TrackerSettings).filter(
        TrackerSettings.conversation_id == cast["conv"]).update({"open_edit": False}))
    res = _save(client, cast, "a", [{"op": "project.create", "id": _id("p"),
                                     "title": "По старому праву"}])
    assert fired, "сохранение не взяло замок записи — тест ослеп"
    assert res["applied"] == 0 and res["skipped"][0]["reason"] == "нет права вести трекер"
    assert res["state"]["projects"] == [] and res["state"]["can_manage"] is False


def test_member_silenced_while_the_save_waits(client, cast, monkeypatch):
    """Заглушили (`/mute`), пока пачка с текстом ждала замок, — текст в трекер не попадает.
    Строка участника к этому мигу уже прочитана: без сброса прочитанного (`expire_all`)
    сервер судил бы по снимку, где человек ещё не заглушён."""
    from app.models import ConversationParticipant
    _enable(client, cast, open_edit=True)
    fired = _race(monkeypatch, lambda db: db.query(ConversationParticipant).filter(
        ConversationParticipant.conversation_id == cast["conv"],
        ConversationParticipant.user_id == cast["a_id"]).update({"silenced": True}))
    r = client.post(_url(cast, "/save"), headers=cast["a"],
                    json={"ops": [{"op": "project.create", "id": _id("p"),
                                   "title": "Успел до заглушки"}]})
    assert fired, "сохранение не взяло замок записи — тест ослеп"
    assert r.status_code == 403 and "заглушены" in r.json()["detail"], r.text
    assert _state(client, cast)["projects"] == []


def test_two_fast_clicks_on_the_switch_do_not_break_the_first_enable(client, cast, monkeypatch):
    """Строки настроек нет, пока трекер ни разу не включали. Два быстрых нажатия тумблера
    оба видели «нет» и оба вставляли её: второе падало отказом первичного ключа — ответом
    500 на обычный двойной щелчок. «Первое нажатие» здесь — строка, вставленная отдельной
    сессией в миг, когда второе уже проверило владельца и ждёт замок."""
    from app.models import TrackerSettings
    fired = _race(monkeypatch, lambda db: db.add(TrackerSettings(
        conversation_id=cast["conv"], enabled=True, open_edit=False)))
    st = _enable(client, cast, open_edit=True)
    assert fired, "настройки пишутся без замка записи"
    assert st["enabled"] is True and st["open_edit"] is True


def test_ownership_lost_while_the_switch_waits(client, cast, monkeypatch):
    """Владение передали, пока тумблер прежнего владельца ждал замок, — настройку он уже
    не меняет. Роль читается и до замка (чтобы не владельцу не занимать очередь записи), и
    под ним; второе чтение без этого теста выглядело «дублем», который просится на вынос
    (нашёл Полковник вторым проходом, 07.10.2026)."""
    from app.models import ConversationParticipant
    _enable(client, cast)
    fired = _race(monkeypatch, lambda db: db.query(ConversationParticipant).filter(
        ConversationParticipant.conversation_id == cast["conv"],
        ConversationParticipant.user_id == cast["owner_id"]).update({"role": "member"}))
    r = client.put(_url(cast, "/settings"), headers=cast["owner"], json={"open_edit": True})
    assert fired, "настройки пишутся без замка записи — тест ослеп"
    assert r.status_code == 403, r.text
    assert _state(client, cast, "a")["open_edit"] is False


def test_one_save_cannot_rewrite_the_whole_tracker_many_times(client, cast, monkeypatch):
    """🔒 Пачка идёт под замком записи ВСЕГО сервера. Смена типа колонки переписывает
    признак завершения у каждой её задачи; 500 таких операций над большой колонкой — сотни
    тысяч записей в одной транзакции, и всё это время в колледже нельзя выставить оценку.
    Завести беседу с трекером может и студент. У пачки есть потолок такой работы
    (`_MAX_WORK`); сверх него операция пропускается с причиной и НЕ меняет ничего."""
    pid, cols = _board(client, cast)
    tasks = [_id("t") for _ in range(30)]
    _save(client, cast, "owner", [{"op": "task.create", "id": t, "column_id": cols["todo"],
                                   "title": f"Задача {i}"} for i, t in enumerate(tasks)])
    monkeypatch.setattr(T, "_MAX_WORK", 100)        #30 задач: три смены типа проходят, четвёртая — нет
    #Последняя — «review», а не «done»: колонка после пропуска осталась «done», и смена
    #на тот же тип ничего не переписывает (и потому законно прошла бы).
    kinds = ["done", "todo", "done", "todo", "review"]
    res = _save(client, cast, "owner", [{"op": "column.update", "id": cols["todo"], "kind": k,
                                         "title": f"Колонка {i}"} for i, k in enumerate(kinds)])
    assert res["applied"] == 3 and [s["i"] for s in res["skipped"]] == [3, 4]
    assert {s["reason"] for s in res["skipped"]} == {"слишком большое сохранение — сохраните частями"}
    col = next(c for p in res["state"]["projects"] for c in p["columns"] if c["id"] == cols["todo"])
    # Пропущенная операция не оставила и названия: либо целиком, либо ничего.
    assert col["kind"] == "done" and col["title"] == "Колонка 2"
    assert all(t["completed_at"] for t in res["state"]["tasks"])
    # Тот же потолок у смены меток работы и у удаления: счёт общий на пачку.
    monkeypatch.setattr(T, "_MAX_WORK", 40)
    res = _save(client, cast, "owner", [
        {"op": "project.update", "id": pid, "labels": [{"id": "l1", "title": "Срочно"}]},
        {"op": "project.update", "id": pid, "labels": []},
        {"op": "task.delete", "id": tasks[0]},
    ])
    assert res["applied"] == 2 and [s["op"] for s in res["skipped"]] == ["project.update"]
    assert len(res["state"]["tasks"]) == 29
    # Перенос задач удаляемой колонки и удаление работы с задачами — та же работа.
    monkeypatch.setattr(T, "_MAX_WORK", 5)
    res = _save(client, cast, "owner", [
        {"op": "column.delete", "id": cols["todo"], "move_to": cols["doing"]},
        {"op": "project.delete", "id": pid},
    ])
    assert res["applied"] == 0 and len(res["skipped"]) == 2, res["skipped"]
    assert len(res["state"]["tasks"]) == 29 and len(res["state"]["projects"]) == 1
    # А под настоящим потолком то же самое проходит: он режет размножение, а не работу.
    monkeypatch.undo()
    res = _save(client, cast, "owner", [{"op": "project.delete", "id": pid}])
    assert res["applied"] == 1 and res["state"]["tasks"] == []


def test_deleted_and_recreated_task_is_a_new_assignment(client, cast):
    """Задачу удалили и завели заново с тем же id одной пачкой — прежний исполнитель
    получает письмо: это новое назначение, а не «задача у него и так была»."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    make = {"op": "task.create", "id": tid, "column_id": cols["todo"], "title": "Введение",
            "assignees": [cast["a_id"]]}
    _save(client, cast, "owner", [make])
    res = _save(client, cast, "owner", [
        {"op": "task.update", "id": tid, "assignees": [cast["a_id"]]},
        {"op": "task.delete", "id": tid},
        {**make, "title": "Введение, заново"},
    ])
    assert res["applied"] == 3 and res["notified"] == 1
    assert len(_events(client, cast["a"])) == 2


def test_unassigned_and_reassigned_in_one_save_sends_no_second_letter(client, cast):
    """Сняли и вернули того же исполнителя двумя операциями ОДНОЙ пачки — назначения не
    случилось: задача у человека была и до сохранения. Письмо получает только тот, кого
    этой пачкой назначили впервые (нашёл Полковник)."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{"op": "task.create", "id": tid, "column_id": cols["todo"],
                                   "title": "Введение", "assignees": [cast["a_id"]]}])
    assert len(_events(client, cast["a"])) == 1
    res = _save(client, cast, "owner", [
        {"op": "task.update", "id": tid, "assignees": []},
        {"op": "task.update", "id": tid, "assignees": [cast["a_id"], cast["b_id"]]},
    ])
    assert res["applied"] == 2 and res["notified"] == 1
    assert len(_events(client, cast["a"])) == 1, "прежнему исполнителю пришло второе письмо"
    assert len(_events(client, cast["b"])) == 1
    assert sorted(_task(res["state"], tid)["assignees"]) == sorted([cast["a_id"], cast["b_id"]])
    # Назначенный, снятый и снова назначенный ВПЕРВЫЕ этой пачкой письмо получает — одно.
    new = _id("t")
    res = _save(client, cast, "owner", [
        {"op": "task.create", "id": new, "column_id": cols["todo"], "title": "Глава 1",
         "assignees": [cast["a_id"]]},
        {"op": "task.update", "id": new, "assignees": []},
        {"op": "task.update", "id": new, "assignees": [cast["a_id"]]},
    ])
    assert res["notified"] == 1 and len(_events(client, cast["a"])) == 2


def test_malformed_values_skip_the_operation_not_the_whole_save(client, cast):
    """Кривое значение в одной операции — пропуск ЭТОЙ операции с причиной. Метка словарём,
    позиция `Infinity`, часы целым в сотни знаков и «бесконечный» номер комментария роняли
    всю пачку отказом сервера: человек терял собранное за минуты.

    Тело шлём СЫРЫМ: `Infinity` и такое целое клиент тестов через `json=` не отправит, а
    чужой клиент — запросто (разбор JSON на сервере их принимает)."""
    pid, cols = _board(client, cast)
    good, junk = _id("t"), _id("t")
    body = json.dumps({"ops": [
        {"op": "task.create", "id": good, "column_id": cols["todo"], "title": "Хорошая"},
        {"op": "task.create", "id": junk, "column_id": cols["todo"], "title": "С мусором",
         "labels": [{"id": "l1"}, 7, ["l1"], None]},
        {"op": "task.update", "id": good, "labels": [{"id": "l1"}]},
        {"op": "task.move", "id": good, "column_id": cols["doing"], "position": "@INF@"},
        {"op": "task.update", "id": good, "spent": "@HUGE@"},
        {"op": "task.update", "id": good, "estimate": "@INF@"},
        {"op": "comment.delete", "id": "@INF@"},
        {"op": "comment.delete", "id": "@HUGE@"},
        {"op": "comment.delete", "id": {"x": 1}},
    ]}, ensure_ascii=False).replace('"@INF@"', "Infinity").replace('"@HUGE@"', "9" * 400)
    assert "Infinity" in body and "9" * 400 in body
    r = client.post(_url(cast, "/save"), content=body.encode("utf-8"),
                    headers={**cast["owner"], "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    res = r.json()
    reasons = {s["i"]: s["reason"] for s in res["skipped"]}
    assert reasons == {3: "позиция не число", 4: "время записано не числом",
                       5: "время вне допустимых границ", 6: "комментарий не найден",
                       7: "комментарий не найден", 8: "комментарий не найден"}, reasons
    assert res["applied"] == 3
    st = res["state"]
    assert _task(st, junk)["labels"] == [] and _task(st, good)["labels"] == []
    assert _task(st, good)["column_id"] == cols["todo"], "пропущенный перенос сдвинул задачу"


def test_assignee_progress_with_a_malformed_checklist_is_harmless(client, cast):
    """Чек-лист числом вместо списка в отметке исполнителя ронял пачку (перебор числа)."""
    pid, cols = _board(client, cast)
    tid = _id("t")
    _save(client, cast, "owner", [{
        "op": "task.create", "id": tid, "column_id": cols["todo"], "title": "Моя",
        "assignees": [cast["a_id"]],
        "checklist": [{"id": "c1", "text": "Пункт", "done": False}]}])
    res = _save(client, cast, "a", [
        {"op": "task.update", "id": tid, "checklist": 5},
        {"op": "task.update", "id": tid,
         "checklist": [7, None, "c1", {"id": "c1", "done": True}]},
    ])
    assert res["applied"] == 2 and res["skipped"] == []
    assert _task(res["state"], tid)["checklist"] == [{"id": "c1", "text": "Пункт", "done": True}]


# ── место трекера в продукте ──────────────────────────────────────────────────────────

def test_tracker_tables_are_not_synced():
    """Трекер — часть мессенджера: онлайн-подсистема, в offline-синк не входит. Окажись
    таблица в SYNC_MODELS — реконсиляция «сервер = истина» вычищала бы её на каждом ПК."""
    from app import models
    synced = {m.__tablename__ if hasattr(m, "__tablename__") else str(k)
              for k, m in models.SYNC_MODELS.items()} | set(models.SYNC_MODELS)
    for name in ("tracker_settings", "tracker_projects", "tracker_columns", "tracker_tasks",
                 "tracker_assignees", "tracker_comments", "tracker_activity"):
        assert name not in synced, f"таблица {name} попала в offline-синк"


def test_tracker_routes_live_under_the_messenger_prefix():
    """В программе `/web/messenger` целиком пересылается на бой (`_PROXY_PREFIXES`).
    Ручка трекера вне этого префикса внутри программы молча отвечала бы пустотой из
    локальной копии — тот самый «раздел на сайте работает, в программе пуст»."""
    paths = [r.path for r in T.router.routes if "tracker" in getattr(r, "path", "")]
    assert len(paths) >= 4, f"маршруты трекера не найдены — тест ослеп: {paths}"
    assert all(p.startswith("/web/messenger/") for p in paths), paths
