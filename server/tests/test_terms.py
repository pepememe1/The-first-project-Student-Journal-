"""
test_terms.py — Учебный период (год/семестр): фильтр журнала, /web/terms, перевод на
курс (rollover) и защита архива (прошлые семестры — только чтение).

Инвариант: year/semester живут на Lesson, оценки наследуют период от занятия — ключ
оценки не меняется. Текущий термин хранится в config.
"""
from conftest import make_admin, make_teacher, assign_teacher


def _push(client, h, **ent):
    return client.post("/sync/push", json={"changes": ent}, headers=h)


def _mk_lesson(client, th, group="G1", subject="Мат", ltype="Практика"):
    r = client.post("/web/teacher/lesson",
                    json={"group": group, "subject": subject, "type": ltype}, headers=th)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_new_lesson_gets_current_term_and_terms_endpoint(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    assign_teacher(client, admin, "teach:teacher1", "G1", "Мат")
    _mk_lesson(client, th)
    terms = client.get("/web/terms", headers=th).json()
    assert terms["current"]["year"] and terms["current"]["semester"] in (1, 2)
    #занятие попало в текущий период → он есть в списке
    assert {"year": terms["current"]["year"], "semester": terms["current"]["semester"]} in terms["terms"]


def test_rollover_archives_old_term_and_blocks_writes(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    assign_teacher(client, admin, "teach:teacher1", "G1", "Мат")
    lid = _mk_lesson(client, th)
    cur = client.get("/web/terms", headers=th).json()["current"]
    old_y, old_s = cur["year"], cur["semester"]

    #журнал по умолчанию (текущий термин) показывает занятие
    jr = client.get("/web/teacher/journal", params={"group": "G1", "subject": "Мат"}, headers=th).json()
    assert any(l["id"] == lid for l in jr["lessons"])

    #перевод на курс
    rr = client.post("/web/admin/term/rollover", json={}, headers=admin)
    assert rr.status_code == 200, rr.text
    new = rr.json()["current"]
    assert (new["year"], new["semester"]) != (old_y, old_s)
    #Назначения — за термин (как и часы): после перевода на курс их нет автоматически,
    #новый семестр админ размечает заново (то же поведение, что уже было у часов).
    assign_teacher(client, admin, "teach:teacher1", "G1", "Мат",
                   year=new["year"], semester=new["semester"])

    #теперь текущий термин НОВЫЙ → старое занятие в журнале по умолчанию не видно
    jr2 = client.get("/web/teacher/journal", params={"group": "G1", "subject": "Мат"}, headers=th).json()
    assert not any(l["id"] == lid for l in jr2["lessons"])
    #но доступно как архив по явному термину
    jr3 = client.get("/web/teacher/journal",
                     params={"group": "G1", "subject": "Мат", "year": old_y, "semester": old_s},
                     headers=th).json()
    assert any(l["id"] == lid for l in jr3["lessons"])

    #запись в архивное занятие запрещена (409)
    g = client.post("/web/teacher/grade",
                    json={"surname": " Х", "name": " Y", "lesson_id": lid, "grade": "5"}, headers=th)
    assert g.status_code == 409, g.text
    #правка/удаление архивного занятия тоже 409
    assert client.put(f"/web/teacher/lesson/{lid}", json={"topic": "x"}, headers=th).status_code == 409
    assert client.delete(f"/web/teacher/lesson/{lid}", headers=th).status_code == 409

    #новое занятие уже в НОВОМ термине и пишется нормально
    lid2 = _mk_lesson(client, th)
    jr4 = client.get("/web/teacher/journal", params={"group": "G1", "subject": "Мат"}, headers=th).json()
    assert any(l["id"] == lid2 for l in jr4["lessons"])


def test_desktop_pushed_lesson_gets_stamped_term(client):
    admin = make_admin(client)
    #админ пушит занятие БЕЗ year/semester (как десктоп) → сервер штампует текущий термин
    L = {"id": "LX", "group_name": "G9", "subject": "Физ", "type": "Практика", "number": 1}
    assert _push(client, admin, lessons=[L]).status_code == 200
    cur = client.get("/web/terms", headers=admin).json()["current"]
    #занятие видно в текущем термине (значит период проставлен)
    assert {"year": cur["year"], "semester": cur["semester"]} in client.get("/web/terms", headers=admin).json()["terms"]
