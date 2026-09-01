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


def _advance_calendar(monkeypatch, year: str, semester) -> tuple:
    """Сдвинуть КАЛЕНДАРЬ на следующий учебный период — так, как это делает 1 сентября.

    🔥 Раньше архив в тестах делали переводом термина вперёд (`/admin/term/rollover`).
    Так больше нельзя, и это не каприз: ровно тот ручной сдвиг дважды уводил боевой
    сервер на год вперёд календаря, и у группы оказывались предметы двух курсов сразу.
    Теперь эндпоинт отвечает 400 на попытку уйти в будущее.

    Подменяем сам источник времени (`app.db.default_term`) — тогда прошедший период
    становится архивом ровно по той причине, по которой он им становится в жизни, и
    тест перестаёт зависеть от механизма, который мы намеренно ограничили."""
    if int(semester) == 1:
        nxt = (year, 2)
    else:
        a, b = year.split("/")
        nxt = (f"{int(a) + 1}/{int(b) + 1}", 1)
    from app import db as _db
    monkeypatch.setattr(_db, "default_term", lambda: nxt)
    return nxt


def test_new_lesson_gets_current_term_and_terms_endpoint(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    assign_teacher(client, admin, "teach:teacher1", "G1", "Мат")
    _mk_lesson(client, th)
    terms = client.get("/web/terms", headers=th).json()
    assert terms["current"]["year"] and terms["current"]["semester"] in (1, 2)
    #занятие попало в текущий период → он есть в списке
    assert {"year": terms["current"]["year"], "semester": terms["current"]["semester"]} in terms["terms"]


def test_passing_term_archives_it_and_blocks_writes(client, monkeypatch):
    """Наступил следующий период — прошлый стал архивом: в журнале по умолчанию его нет,
    по явному термину виден, писать в него нельзя (409)."""
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    assign_teacher(client, admin, "teach:teacher1", "G1", "Мат")
    lid = _mk_lesson(client, th)
    cur = client.get("/web/terms", headers=th).json()["current"]
    old_y, old_s = cur["year"], cur["semester"]

    #журнал по умолчанию (текущий термин) показывает занятие
    jr = client.get("/web/teacher/journal", params={"group": "G1", "subject": "Мат"}, headers=th).json()
    assert any(l["id"] == lid for l in jr["lessons"])

    #наступил следующий учебный период (в жизни это делает календарь 1 сентября)
    ny, ns = _advance_calendar(monkeypatch, old_y, old_s)
    new = {"year": ny, "semester": ns}
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


# ── Заслонки против сдвига термина в будущее ──────────────────────────────────────────
# Оба теста написаны потому, что этот баг случался ДВАЖДЫ (3.6.1 и 15.08.2026) и оба
# раза чинился руками в боевой базе: ручной оверрайд уводил продукт на год вперёд
# календаря, от термина считался КУРС студента, импорт учебного плана записывал предметы
# следующего курса — и у группы оказывались предметы двух курсов сразу.

def test_rollover_refuses_to_move_the_term_into_the_future(client):
    """Вперёд период переключается сам 1 сентября. Ручной сдвиг — 400, и термин на месте."""
    admin = make_admin(client)
    before = client.get("/web/terms", headers=admin).json()["current"]

    r = client.post("/web/admin/term/rollover", json={}, headers=admin)
    assert r.status_code == 400, r.text
    assert "не наступил" in r.json()["detail"], r.json()

    after = client.get("/web/terms", headers=admin).json()["current"]
    assert after == before, "отказ обязан быть полным: термин не должен сдвинуться"


def test_rollover_still_works_backwards(client):
    """Обратный тест. Без него «починка» вида «запретить rollover совсем» прошла бы
    незамеченной, а открыть закрытый семестр — законный сценарий."""
    admin = make_admin(client)
    cur = client.get("/web/terms", headers=admin).json()["current"]
    y, s = cur["year"], int(cur["semester"])
    prev = (y, 1) if s == 2 else (f"{int(y.split('/')[0]) - 1}/{int(y.split('/')[1]) - 1}", 2)

    r = client.post("/web/admin/term/rollover",
                    json={"year": prev[0], "semester": prev[1]}, headers=admin)
    assert r.status_code == 200, r.text
    now = client.get("/web/terms", headers=admin).json()["current"]
    assert (now["year"], int(now["semester"])) == prev


def test_current_term_ignores_a_future_override_left_in_the_database(client, monkeypatch):
    """Вторая заслонка: оверрайд из будущего мог УЖЕ лежать в базе с прошлых раз (именно
    так и было на бою). Читатель обязан его игнорировать, а не верить вслепую."""
    from app import webdata as W
    from app.db import SessionLocal, default_term
    from app.models import ConfigKV
    make_admin(client)
    real = default_term()
    future_year = f"{int(real[0].split('/')[0]) + 1}/{int(real[0].split('/')[1]) + 1}"

    db = SessionLocal()
    row = db.get(ConfigKV, "config") or ConfigKV(key="config", value={}, updated_at="")
    row.value = {**(row.value or {}), "current_year": future_year, "current_semester": 1}
    db.add(row)
    db.commit()

    assert W.current_term(W.load_config(db)) == real, "оверрайд из будущего обязан игнорироваться"

    #Обратная половина: оверрайд в ПРОШЛОЕ по-прежнему уважается — иначе тест был бы
    #зелёным и при реализации «игнорировать любой оверрайд», то есть проверял бы не то.
    past_year = f"{int(real[0].split('/')[0]) - 1}/{int(real[0].split('/')[1]) - 1}"
    row.value = {**row.value, "current_year": past_year, "current_semester": 1}
    db.add(row)
    db.commit()
    assert W.current_term(W.load_config(db)) == (past_year, 1), "оверрайд назад — законный сценарий"
    db.close()


# ── ОТСТАВШИЙ ОВЕРРАЙД ТЕРМИНА (01.09.2026) ────────────────────────────────────────
# Оверрайд ВПЕРЁД уже игнорируется и пишет в лог — он дважды уводил продукт на год
# вперёд календаря. Обратный случай был молчаливым, а стоит не меньше: ключ
# `current_year`, оставшийся с весны, 1 сентября НЕ ДАЁТ учебному году начаться.
# Продукт продолжает штамповать занятия прошлым семестром, курс студентов не растёт,
# новые предметы ложатся в закрытый период — и понять это можно только разбором
# боевой базы, как оба прошлых раза.
#
# ⚠️ Само поведение (оверрайд назад работает) НЕ меняем: открыть закрытый семестр —
# законный сценарий, и запретить его значило бы отобрать у админа архив. Меняем
# ровно молчание.


def test_a_stale_term_override_is_reported_but_still_honoured(caplog):
    """Оверрайд, отставший от календаря, ПРИМЕНЯЕТСЯ (архив — законный сценарий), но
    сообщает о себе в лог ровно один раз за запуск.

    Обратный ход: убрать ветку предупреждения — тест краснеет на пустом логе."""
    import logging
    from app import webdata as W

    W._stale_term_warned = False
    past = (f"{int(W.default_term_by_date()[0].split('/')[0]) - 1}/"
            f"{int(W.default_term_by_date()[0].split('/')[1]) - 1}")
    cfg = {"current_year": past, "current_semester": 1}

    with caplog.at_level(logging.WARNING, logger="gradebook.webdata"):
        assert W.current_term(cfg) == (past, 1), "архивный оверрайд обязан применяться"
    assert any("ОТСТАЁТ" in r.message or "отстаёт" in r.message.lower()
               for r in caplog.records), "молчаливое залипание в прошлом семестре"

    #Второй раз — молчим: строка на каждый запрос превратила бы лог в шум.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="gradebook.webdata"):
        W.current_term(cfg)
    assert not caplog.records, "предупреждение повторяется на каждый запрос"


def test_the_current_term_override_is_not_reported():
    """Оверрайд, СОВПАДАЮЩИЙ с календарём, — обычное дело и в лог не идёт."""
    import logging
    from app import webdata as W

    W._stale_term_warned = False
    y, s = W.default_term_by_date()
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    log = logging.getLogger("gradebook.webdata")
    log.addHandler(handler)
    try:
        assert W.current_term({"current_year": y, "current_semester": s}) == (y, s)
    finally:
        log.removeHandler(handler)
    assert not records
