"""
test_sync.py — Синхронизация: push/pull, права ролей, серверные метки, идемпотентность.
"""
from conftest import make_admin, make_teacher


_LESSON = {"id": "L1", "group_name": "ИС-21", "subject": "Математика",
           "type": "Практика", "number": 1, "topic": "Тест", "date": "01.09.2025"}
_GRADE = {"id": "Иванов|Иван|L1", "student_f": "Иванов", "student_n": "Иван",
          "lesson_id": "L1", "grade": "5"}


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


def test_pull_requires_auth(client):
    assert client.get("/sync/pull").status_code == 401


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


def test_delta_pull_returns_only_newer(client):
    """pull?since=<метка> отдаёт только записи, изменённые позже метки — основа
    дельта-синхронизации (не качать всю базу каждый раз)."""
    h = make_admin(client)
    _push(client, h, lessons=[_LESSON])
    server_time = client.get("/sync/pull", headers=h).json()["server_time"]
    #с момента server_time изменений не было — дельта пуста
    later = client.get("/sync/pull", params={"since": server_time}, headers=h).json()
    assert all(not v for v in later["changes"].values()), "после метки изменений быть не должно"


def test_delta_pull_brings_new_changes_after_watermark(client):
    """Сценарий дельты двух ПК: один ставит метку, второй пушит новое занятие —
    дельта-pull по метке приносит ТОЛЬКО новое занятие, без старых."""
    h = make_admin(client)
    _push(client, h, lessons=[_LESSON])
    server_time = client.get("/sync/pull", headers=h).json()["server_time"]
    #появилось новое занятие уже ПОСЛЕ взятой метки
    _push(client, h, lessons=[dict(_LESSON, id="L2", topic="Новое")])
    delta = client.get("/sync/pull", params={"since": server_time}, headers=h).json()
    ids = [l["id"] for l in delta["changes"]["lessons"]]
    assert ids == ["L2"], f"дельта должна вернуть только новое занятие, а не {ids}"
