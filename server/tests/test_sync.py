"""
test_sync.py — Синхронизация: push/pull, права ролей, серверные метки, идемпотентность.
"""
import time

from conftest import make_admin, make_teacher, assign_teacher


_LESSON = {"id": "L1", "group_name": "ИС-21", "subject": "Математика",
           "type": "Практика", "number": 1, "topic": "Тест", "date": "01.09.2025"}
_GRADE = {"id": "Иванов|Иван|L1", "student_f": "Иванов", "student_n": "Иван",
          "lesson_id": "L1", "grade": "5"}
_TERM_GRADE = {"id": "Иванов|Иван|Математика|2025/2026|1", "student_f": "Иванов",
               "student_n": "Иван", "subject": "Математика", "year": "2025/2026",
               "semester": 1, "grade": "5", "form": "экзамен"}


def _push(client, headers, **entities):
    return client.post("/sync/push", json={"changes": entities}, headers=headers)


def test_push_and_pull_roundtrip(client):
    h = make_admin(client)
    r = _push(client, h, lessons=[_LESSON], grades=[_GRADE])
    assert r.status_code == 200
    assert r.json()["applied"]["lessons"] == 1

    data = client.get("/sync/pull", headers=h).json()["changes"]
    assert any(l["id"] == "L1" for l in data["lessons"])
    g = [x for x in data["grades"] if x["id"] == _GRADE["id"]]
    assert g and g[0]["updated_at"], "оценка должна вернуться с серверной меткой времени"


def test_push_is_idempotent(client):
    h = make_admin(client)
    _push(client, h, grades=[_GRADE])
    #повторный push тех же данных не меняет ничего — это держит дельта-синк лёгким
    r = _push(client, h, grades=[_GRADE])
    assert r.json()["applied"]["grades"] == 0


def test_server_stamps_timestamp_not_client(client):
    """Метку времени ставит сервер, а не клиент: пришедший updated_at игнорируется,
    иначе LWW зависел бы от часов на машинах преподавателей (clock skew)."""
    h = make_admin(client)
    fake = dict(_GRADE, updated_at="1999-01-01T00:00:00+00:00")
    _push(client, h, grades=[fake])
    g = [x for x in client.get("/sync/pull", headers=h).json()["changes"]["grades"]
         if x["id"] == _GRADE["id"]][0]
    assert not g["updated_at"].startswith("1999"), "клиентская метка не должна сохраняться"


def test_tombstone_roundtrips_through_server(client):
    """Надгробие (deleted=True) переживает push→pull: удаление доезжает до других ПК,
    а не теряется. Без этого удалённое занятие/оценка воскресали бы при синхронизации."""
    h = make_admin(client)
    _push(client, h, lessons=[dict(_LESSON, deleted=True)],
          grades=[dict(_GRADE, deleted=True)])
    ch = client.get("/sync/pull", headers=h).json()["changes"]
    lesson = [x for x in ch["lessons"] if x["id"] == _LESSON["id"]]
    grade = [x for x in ch["grades"] if x["id"] == _GRADE["id"]]
    assert lesson and lesson[0]["deleted"] is True, "надгробие занятия должно вернуться"
    assert grade and grade[0]["deleted"] is True, "надгробие оценки должно вернуться"


def test_pull_requires_auth(client):
    assert client.get("/sync/pull").status_code == 401


# Минимизация выгрузки по роли (152-ФЗ) ───────────────────────────────────────────
def _mk_student(client, admin, login, surname, name, group, pw="studpass1"):
    """Заводит студента через push админа и логинит его — возвращает его заголовок."""
    from app.security import hash_password
    client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password(pw), "surname": surname, "name": name,
        "group_name": group}]}}, headers=admin)
    r = client.post("/auth/login", json={"login": login, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_pull_teacher_row_scope(client):
    """Преподаватель получает свою строку + студентов СВОИХ групп и занятия СВОИХ
    предметов; чужие группы/предметы/преподавателей и админа — не видит. Свой хеш есть,
    хеши студентов и секреты config — вырезаны."""
    admin = make_admin(client)
    th = make_teacher(client, admin, login="teacher1", subjects=["Математика"])
    assign_teacher(client, admin, "teach:teacher1", "ИС-21", "Математика")
    _push(client, admin,
          groups=[{"id": "grp:ИС-21", "name": "ИС-21", "subjects": ["Математика"]},
                  {"id": "grp:ИС-22", "name": "ИС-22", "subjects": ["Физика"]}],
          config=[{"key": "gigachat_credentials", "value": "SECRET", "deleted": False},
                  {"key": "vector_llm", "value": "gigachat", "deleted": False}])
    _mk_student(client, admin, "sa", "Иванов", "Иван", "ИС-21")
    _mk_student(client, admin, "sb", "Петров", "Пётр", "ИС-22")
    _push(client, admin, lessons=[
        dict(_LESSON, id="L1", group_name="ИС-21", subject="Математика"),
        dict(_LESSON, id="L2", group_name="ИС-22", subject="Физика")])

    ch = client.get("/sync/pull", headers=th).json()["changes"]
    logins = {u.get("login") for u in ch["users"]}
    assert "teacher1" in logins and "sa" in logins
    assert "sb" not in logins and "admin" not in logins, "чужая группа/админ не видны"
    assert {l["id"] for l in ch["lessons"]} == {"L1"}, "только занятия своего предмета"
    users = {u["login"]: u for u in ch["users"] if u.get("login")}
    assert users["teacher1"]["password_hash"], "свой хеш есть (офлайн-вход)"
    assert users["sa"]["password_hash"] == "", "хеш студента вырезан"
    cfg = {c["key"]: c.get("value") for c in ch["config"]}
    assert "gigachat_credentials" not in cfg and cfg.get("vector_llm") == "gigachat"


def test_pull_student_row_scope(client):
    """Студент получает ТОЛЬКО себя: свою строку, свои оценки, занятия своей группы.
    Чужих студентов (ПДн) и их оценки — не видит вовсе."""
    admin = make_admin(client)
    make_teacher(client, admin, login="teacher1", subjects=["Математика"])
    sa = _mk_student(client, admin, "sa", "Иванов", "Иван", "ИС-21")
    _mk_student(client, admin, "sb", "Петров", "Пётр", "ИС-21")
    _push(client, admin,
          lessons=[dict(_LESSON, id="L1", group_name="ИС-21", subject="Математика"),
                   dict(_LESSON, id="L2", group_name="ИС-22", subject="Физика")],
          grades=[dict(_GRADE, id="Иванов|Иван|L1", lesson_id="L1"),
                  {"id": "Петров|Пётр|L1", "student_f": "Петров", "student_n": "Пётр",
                   "lesson_id": "L1", "grade": "3"}])

    ch = client.get("/sync/pull", headers=sa).json()["changes"]
    assert {u.get("login") for u in ch["users"]} == {"sa"}, "видит только себя"
    assert {l["id"] for l in ch["lessons"]} == {"L1"}, "только занятия своей группы ИС-21"
    assert {(g["student_f"], g["student_n"]) for g in ch["grades"]} == {("Иванов", "Иван")}, \
        "только свои оценки, не Петрова"


def test_pull_admin_gets_everything(client):
    """Админ получает полный дамп (хеши всех + секреты) — нужно для правки юзеров и ИИ."""
    admin = make_admin(client)
    make_teacher(client, admin, login="teacher1")
    _push(client, admin, config=[
        {"key": "gigachat_credentials", "value": "SECRET_TOKEN", "deleted": False}])

    ch = client.get("/sync/pull", headers=admin).json()["changes"]
    hashes = [u["password_hash"] for u in ch["users"] if u.get("login")]
    assert all(hashes), "у админа все хеши на месте"
    cfg = {c["key"]: c.get("value") for c in ch["config"]}
    assert cfg.get("gigachat_credentials") == "SECRET_TOKEN", "админ видит секреты ИИ"


def test_vector_voice_offline_echoes_facts(client):
    """/vector/voice в оффлайн-режиме (нет провайдера) возвращает факты как есть —
    десктоп получает озвучку через сервер, не держа токен у себя. Пустые факты → ''."""
    admin = make_admin(client)
    th = make_teacher(client, admin, login="teacher1")
    r = client.post("/vector/voice",
                    json={"facts": "Средний балл 4.5, долгов нет.", "question": "как дела"},
                    headers=th)
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Средний балл 4.5, долгов нет."
    assert client.post("/vector/voice", json={"facts": ""}, headers=th).json()["text"] == ""


def test_vector_voice_requires_auth(client):
    assert client.post("/vector/voice", json={"facts": "x"}).status_code == 401


def test_teacher_can_push_own_subject_but_not_foreign(client):
    """Преподаватель математики вправе пушить занятия по математике, но не по физике —
    построчная авторизация по предмету (row-level scope)."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])

    r = _push(client, th, lessons=[dict(_LESSON, subject="Математика")])
    assert r.json()["applied"].get("lessons") == 1

    r = _push(client, th, lessons=[dict(_LESSON, id="L2", subject="Физика")])
    assert r.json()["applied"].get("lessons", 0) == 0
    assert r.json().get("rejected", {}).get("lessons") == 1


def test_teacher_grade_scoped_by_lesson_subject(client):
    """Оценку можно поставить только к занятию своего предмета. К чужому занятию
    (его предмет вне subjects преподавателя) оценка отвергается."""
    admin = make_admin(client)
    #чужое занятие по физике кладёт админ
    _push(client, admin, lessons=[dict(_LESSON, id="PHYS", subject="Физика")])
    th = make_teacher(client, admin, subjects=["Математика"])
    #своё занятие по математике + оценка к нему — проходит
    r = _push(client, th,
              lessons=[dict(_LESSON, id="MATH", subject="Математика")],
              grades=[dict(_GRADE, id="Иванов|Иван|MATH", lesson_id="MATH")])
    assert r.json()["applied"].get("grades") == 1
    #оценка к чужому (физика) занятию — отвергается
    r = _push(client, th, grades=[dict(_GRADE, id="Иванов|Иван|PHYS", lesson_id="PHYS")])
    assert r.json()["applied"].get("grades", 0) == 0
    assert r.json().get("rejected", {}).get("grades") == 1


def test_term_grade_roundtrip(client):
    """Итоговая оценка за семестр (аттестация) переживает push→pull: десктоп и веб
    делят одни данные ведомостей через синк (term_grades в SYNC_MODELS)."""
    h = make_admin(client)
    r = _push(client, h, term_grades=[_TERM_GRADE])
    assert r.json()["applied"]["term_grades"] == 1
    ch = client.get("/sync/pull", headers=h).json()["changes"]
    tg = [x for x in ch["term_grades"] if x["id"] == _TERM_GRADE["id"]]
    assert tg and tg[0]["grade"] == "5" and tg[0]["updated_at"]


def test_teacher_term_grade_scoped_by_subject(client):
    """Преподаватель вправе выставить итоговую оценку только по СВОЕМУ предмету."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Математика"])
    r = _push(client, th, term_grades=[_TERM_GRADE])
    assert r.json()["applied"].get("term_grades") == 1
    foreign = dict(_TERM_GRADE, id="Иванов|Иван|Физика|2025/2026|1", subject="Физика")
    r = _push(client, th, term_grades=[foreign])
    assert r.json()["applied"].get("term_grades", 0) == 0
    assert r.json().get("rejected", {}).get("term_grades") == 1


def _tick():
    """Пауза, гарантирующая СМЕНУ метки времени сервера. На Windows часы дискретны
    (до ~16 мс), поэтому push и следующий за ним pull могут попасть в ОДИН тик. Тесты
    ниже проверяют семантику дельты, а не поведение на стыке тиков (для стыка есть
    отдельный тест test_delta_pull_does_not_lose_boundary_record)."""
    time.sleep(0.03)


def test_schedule_override_syncs_roundtrip(client):
    """Правки расписания (ScheduleOverride) синхронизируются как обычная сущность — так
    админ-редактор общий для веб и десктопа (правка на одном ПК доезжает на другой)."""
    h = make_admin(client)
    ov = {"id": "sovr:ИС-21|1|Пнд|2", "group_name": "ИС-21", "week": 1, "day": "Пнд",
          "pair_no": 2, "action": "set", "subject": "Математика", "time": "10:45"}
    r = _push(client, h, schedule_overrides=[ov])
    assert r.json()["applied"]["schedule_overrides"] == 1
    ch = client.get("/sync/pull", headers=h).json()["changes"]
    got = [x for x in ch["schedule_overrides"] if x["id"] == ov["id"]]
    assert got and got[0]["subject"] == "Математика" and got[0]["updated_at"]
    #надгробие (удаление правки) тоже доезжает
    _push(client, h, schedule_overrides=[dict(ov, deleted=True)])
    ch2 = client.get("/sync/pull", headers=h).json()["changes"]
    g2 = [x for x in ch2["schedule_overrides"] if x["id"] == ov["id"]]
    assert g2 and g2[0]["deleted"] is True


def test_delta_pull_returns_only_newer(client):
    """pull?since=<метка> отдаёт только записи, изменённые позже метки — основа
    дельта-синхронизации (не качать всю базу каждый раз)."""
    h = make_admin(client)
    _push(client, h, lessons=[_LESSON])
    _tick()
    server_time = client.get("/sync/pull", headers=h).json()["server_time"]
    #с момента server_time изменений не было — дельта пуста
    later = client.get("/sync/pull", params={"since": server_time}, headers=h).json()
    assert all(not v for v in later["changes"].values()), "после метки изменений быть не должно"


def test_delta_pull_brings_new_changes_after_watermark(client):
    """Сценарий дельты двух ПК: один ставит метку, второй пушит новое занятие —
    дельта-pull по метке приносит ТОЛЬКО новое занятие, без старых."""
    h = make_admin(client)
    _push(client, h, lessons=[_LESSON])
    _tick()
    server_time = client.get("/sync/pull", headers=h).json()["server_time"]
    #появилось новое занятие уже ПОСЛЕ взятой метки
    _push(client, h, lessons=[dict(_LESSON, id="L2", topic="Новое")])
    delta = client.get("/sync/pull", params={"since": server_time}, headers=h).json()
    ids = [l["id"] for l in delta["changes"]["lessons"]]
    assert ids == ["L2"], f"дельта должна вернуть только новое занятие, а не {ids}"


def test_delta_pull_does_not_lose_boundary_record(client):
    """ПОГРАНИЧНАЯ ЗАПИСЬ НЕ ТЕРЯЕТСЯ (правило: лучше отдать повторно, чем потерять).

    Если метка клиента совпала с меткой записи (push и pull попали в один тик часов —
    на Windows реально), строгий фильтр «updated_at > since» выкидывал такую запись из
    дельты НАВСЕГДА, до её следующего изменения: оценка просто не доезжала до второго ПК.
    Здесь метка берётся РАВНОЙ метке занятия — оно обязано прийти (фильтр «>=»)."""
    h = make_admin(client)
    _push(client, h, lessons=[_LESSON])
    lesson = [x for x in client.get("/sync/pull", headers=h).json()["changes"]["lessons"]
              if x["id"] == _LESSON["id"]][0]
    same_ts = lesson["updated_at"]          #метка клиента = метка самой записи (стык тиков)
    delta = client.get("/sync/pull", params={"since": same_ts}, headers=h).json()
    ids = [x["id"] for x in delta["changes"]["lessons"]]
    assert _LESSON["id"] in ids, ("занятие с меткой, равной метке клиента, обязано прийти "
                                  f"(иначе теряется навсегда), а пришло: {ids}")
