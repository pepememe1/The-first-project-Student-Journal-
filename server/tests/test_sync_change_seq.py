"""
test_sync_change_seq.py — курсор синка по НОМЕРУ изменения, а не по времени
(26.09.2026, исследование синка W-02/W-03/W-05/W-14/W-15/W-16/W-18/W-20, аудит F-22).

━━ ЧТО ДЕРЖИТСЯ ━━
• номер ставит база (триггеры `app/sync_clock.py`): вставка, правка, удаление; номер,
  присланный клиентом, перебивается свежим;
• строка, чья метка времени «в прошлом», но которая закоммичена ПОЗЖЕ страницы, не
  теряется — ровно та потеря, которую давал курсор по времени (W-02);
• pull страницами: не больше `limit` изменений, `more` и курсор ведут до головы;
• удалённое на бою доезжает ключом — и ТОЛЬКО тому, кому строка была положена;
• курсор негоден — `reset` с причиной (область видимости, горизонт, откат номеров, метка
  базы);
• правка очереди сверяется по номеру и под замком записи (W-14/W-15);
• оценки пересдач доезжают до копии преподавателя (карта занятий искала полный id);
• частые pull упираются в ограничитель (F-22), голова отвечает на долгий опрос (W-20).

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН (см. `rev_seq.py` захода): снять `db.refresh(row)` в
`_ensure_base_version` — краснеет тест гонки; убрать `W.base_lesson_id` из выдачи
преподавателю — краснеет тест пересдач; убрать фильтр области у удалений — краснеет тест
чужого ключа; вернуть пагинацию «всё за раз» — краснеет тест страниц; отключить
ограничитель — краснеет тест 429.
"""
import threading
import time

from conftest import make_admin, make_teacher, assign_teacher


def _push(client, headers, **entities):
    r = client.post("/sync/push", json={"changes": entities}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _term():
    from app.db import SessionLocal
    from app import webdata as W
    with SessionLocal() as db:
        return W.current_term(W.load_config(db))


def _student(client, admin, login, surname, name, group, pw="studpass1"):
    from app.security import hash_password
    _push(client, admin, users=[{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password(pw), "surname": surname, "name": name,
        "group_name": group}])
    r = client.post("/auth/login", json={"login": login, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _world(client):
    """Два преподавателя на двух группах, по студенту в каждой, по занятию у каждой."""
    ty, ts = _term()
    admin = make_admin(client)
    t1 = make_teacher(client, admin, "t1", subjects=("Математика",))
    t2 = make_teacher(client, admin, "t2", subjects=("Математика",))
    assign_teacher(client, admin, "teach:t1", "ИС-21", "Математика")
    assign_teacher(client, admin, "teach:t2", "ИС-22", "Математика")
    s1 = _student(client, admin, "s1", "Иванов", "Иван", "ИС-21")
    s2 = _student(client, admin, "s2", "Петров", "Пётр", "ИС-22")
    _push(client, admin, lessons=[
        {"id": "L21", "group_name": "ИС-21", "subject": "Математика", "type": "Практика",
         "number": 1, "year": ty, "semester": ts},
        {"id": "L22", "group_name": "ИС-22", "subject": "Математика", "type": "Практика",
         "number": 1, "year": ty, "semester": ts}])
    return admin, t1, t2, s1, s2


def _page(client, h, cursor=0, **kw):
    params = {"cursor": cursor, **kw}
    r = client.get("/sync/pull", params=params, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _drain(client, h, cursor=0, scope="", epoch="", limit=2000):
    """Все страницы до головы. Возвращает (строки по таблицам, удаления, последняя стр.)."""
    rows, removed, last = {}, {}, None
    for _ in range(1000):
        p = _page(client, h, cursor, limit=limit, scope=scope, epoch=epoch)
        assert not p.get("reset"), p
        if cursor == 0:
            scope, epoch = p["scope"], p["epoch"]
        for name, items in p["changes"].items():
            rows.setdefault(name, {}).update({(it.get("id") or it.get("key")): it
                                              for it in items})
        for name, keys in p["removed"].items():
            removed.setdefault(name, set()).update(keys)
        cursor, last = p["cursor"], p
        if not p["more"]:
            return rows, removed, last
    raise AssertionError("страницы не кончились")


def _grade(lesson, sid, value):
    return {"id": f"{sid}|{lesson}", "student_id": sid, "lesson_id": lesson, "grade": value}


# ── триггеры ─────────────────────────────────────────────────────────────────────────
def test_database_numbers_every_insert_update_and_delete(client):
    admin = make_admin(client)
    from app.db import SessionLocal
    from app.models import Subject
    from app import sync_clock
    with SessionLocal() as db:
        before = sync_clock.read(db)["seq"]
        db.add(Subject(id="subj:A", name="A"))
        db.commit()
        s1 = db.get(Subject, "subj:A").change_seq
        db.get(Subject, "subj:A").name = "A2"
        db.commit()
        s2 = db.get(Subject, "subj:A").change_seq
        db.delete(db.get(Subject, "subj:A"))
        db.commit()
        after = sync_clock.read(db)["seq"]
        from sqlalchemy import text
        log = db.execute(text("SELECT tbl, pk FROM sync_deletes WHERE seq = :s"),
                         {"s": after}).fetchall()
    assert before < s1 < s2 < after, (before, s1, s2, after)
    assert log == [("subjects", "subj:A")], "удаление не попало в журнал удалений"
    assert admin


def test_client_supplied_number_is_overwritten(client):
    """Старый клиент или подменённый пакет не может поставить строке свой номер: такая
    строка выпала бы из курсоров копий (номер «из прошлого»)."""
    admin = make_admin(client)
    _push(client, admin, groups=[{"id": "grp:B", "name": "B", "change_seq": 1}])
    from app.db import SessionLocal
    from app.models import Group
    from app import sync_clock
    with SessionLocal() as db:
        row = db.get(Group, "grp:B")
        head = sync_clock.read(db)["seq"]
        assert row.change_seq == head and row.change_seq > 1
        row.change_seq = 1                 #прямо в обход приёма — триггер обязан перебить
        db.commit()
        assert db.get(Group, "grp:B").change_seq > head


def test_existing_rows_are_numbered_once_in_time_order(client):
    """Строки, лежавшие до миграции (номер 0), нумеруются по `updated_at` ОДИН раз."""
    make_admin(client)
    from sqlalchemy import text
    from app.db import SessionLocal, engine
    from app import sync_clock
    with SessionLocal() as db:
        for sid, ts in (("subj:late", "2026-09-02"), ("subj:early", "2026-01-01")):
            db.execute(text("INSERT INTO subjects (id, name, updated_at, deleted) "
                            "VALUES (:i, :i, :t, 0)"), {"i": sid, "t": ts})
        db.commit()
        #Имитация базы до миграции: номера стёрты, триггеров нет.
        for trg in sync_clock._our_triggers(db.connection()):
            db.execute(text(f"DROP TRIGGER {trg}"))
        db.execute(text("UPDATE subjects SET change_seq = 0"))
        db.commit()
    assert sync_clock.ensure(engine)["numbered"] >= 2
    with SessionLocal() as db:
        seq = dict(db.execute(text("SELECT id, change_seq FROM subjects")).fetchall())
    assert 0 < seq["subj:early"] < seq["subj:late"], seq
    assert sync_clock.ensure(engine)["numbered"] == 0, "повторный старт нумерует заново"


# ── курсор и страницы ────────────────────────────────────────────────────────────────
def test_row_committed_after_the_page_is_not_lost_even_with_an_old_timestamp(client):
    """W-02: метка времени ставится ДО коммита. Строка с меткой «в прошлом», закоммиченная
    после того, как клиент получил страницу, по времени не пришла бы никогда."""
    admin, t1, *_ = _world(client)
    _rows, _rm, last = _drain(client, t1)
    from app.db import SessionLocal
    from app.models import Grade
    with SessionLocal() as db:
        db.add(Grade(id="stud:s1|L21", student_id="stud:s1", student_f="Иванов",
                     student_n="Иван", lesson_id="L21", grade="4",
                     updated_at="2020-01-01T00:00:00+00:00"))
        db.commit()
    rows, _rm, _last = _drain(client, t1, last["cursor"], last["scope"], last["epoch"])
    assert "stud:s1|L21" in rows.get("grades", {}), "строку «из прошлого» потеряли"
    #Та же строка по времени: курсор-время из прошлого ответа её не отдаёт.
    legacy = client.get("/sync/pull", params={"since": last["server_time"]}, headers=t1)
    assert "stud:s1|L21" not in {g["id"] for g in legacy.json()["changes"]["grades"]}, \
        "предпосылка теста: курсор по времени эту строку теряет"


def test_pages_are_bounded_and_lead_to_the_head(client):
    admin = make_admin(client)
    #Справочник предметов админ с программы не пушит (он только на сайте) — берём группы.
    _push(client, admin, groups=[{"id": f"grp:{i}", "name": f"G{i}"} for i in range(25)])
    first = _page(client, admin, 0, limit=10)
    total = sum(len(v) for v in first["changes"].values())
    assert total <= 10 and first["more"], first["cursor"]
    rows, _rm, last = _drain(client, admin, limit=10)
    assert len(rows["groups"]) == 25
    assert last["cursor"] == last["head"] and not last["more"]


def test_teacher_page_holds_only_his_pairs_and_gets_retake_grades(client):
    """Пересдача живёт строкой `<занятие>_retake`; карта занятий искала ПОЛНЫЙ id, и оценки
    пересдач до копии преподавателя не доезжали вовсе."""
    admin, t1, *_ = _world(client)
    _push(client, admin, grades=[_grade("L21", "stud:s1", "2"),
                                 _grade("L21_retake", "stud:s1", "4"),
                                 _grade("L22", "stud:s2", "5")])
    rows, _rm, _last = _drain(client, t1)
    assert set(rows["grades"]) == {"stud:s1|L21", "stud:s1|L21_retake"}, rows["grades"].keys()
    assert set(rows["lessons"]) == {"L21"}


# ── удаления ─────────────────────────────────────────────────────────────────────────
def test_hard_delete_reaches_only_those_who_could_see_the_row(client):
    admin, t1, t2, s1, s2 = _world(client)
    _push(client, admin, grades=[_grade("L21", "stud:s1", "3")])
    marks = {}
    for who, h in (("t1", t1), ("t2", t2), ("s1", s1), ("s2", s2)):
        _r, _rm, marks[who] = _drain(client, h)
    from app.db import SessionLocal
    from app.models import Grade
    with SessionLocal() as db:
        db.delete(db.get(Grade, "stud:s1|L21"))
        db.commit()
    got = {}
    for who, h in (("t1", t1), ("t2", t2), ("s1", s1), ("s2", s2)):
        m = marks[who]
        _r, got[who], _l = _drain(client, h, m["cursor"], m["scope"], m["epoch"])
    assert got["t1"].get("grades") == {"stud:s1|L21"}
    assert got["s1"].get("grades") == {"stud:s1|L21"}
    assert "grades" not in got["t2"], "ключ чужой оценки (с id студента) ушёл чужому преподавателю"
    assert "grades" not in got["s2"], "ключ чужой оценки ушёл другому студенту"


# ── сброс курсора ────────────────────────────────────────────────────────────────────
def test_scope_change_asks_for_a_full_resync(client):
    """W-05: сняли назначение — дельта этого не скажет (строки не менялись), а копия
    продолжала бы хранить ПДн снятой группы. Курсор со старой областью — `reset: scope`."""
    admin, t1, *_ = _world(client)
    _r, _rm, last = _drain(client, t1)
    assign_teacher(client, admin, "teach:t1", "ИС-23", "Математика")
    p = _page(client, t1, last["cursor"], scope=last["scope"], epoch=last["epoch"])
    assert p.get("reset") == "scope", p


def test_cursor_below_the_horizon_or_above_the_head_or_other_epoch_resets(client):
    admin = make_admin(client)
    _push(client, admin, subjects=[{"id": "subj:x", "name": "x"}])
    _r, _rm, last = _drain(client, admin)
    sc, ep, cur = last["scope"], last["epoch"], last["cursor"]
    assert _page(client, admin, cur + 1000, scope=sc, epoch=ep).get("reset") == "ahead"
    assert _page(client, admin, cur, scope=sc, epoch="чужая").get("reset") == "epoch"
    from sqlalchemy import text
    from app.db import SessionLocal
    with SessionLocal() as db:
        db.execute(text("UPDATE sync_clock SET horizon = :h WHERE id = 1"), {"h": cur + 1})
        db.commit()
    _push(client, admin, subjects=[{"id": "subj:y", "name": "y"}])
    assert _page(client, admin, cur, scope=sc, epoch=ep).get("reset") == "horizon"


def test_purging_the_delete_log_moves_the_horizon(client):
    make_admin(client)
    from sqlalchemy import text
    from app.db import SessionLocal
    from app import sync_clock
    with SessionLocal() as db:
        db.execute(text("INSERT INTO sync_deletes (seq, tbl, pk, scope, at) VALUES "
                        "(7, 'subjects', 'subj:old', 'subj:old', '2020-01-01T00:00:00Z')"))
        db.commit()
        assert sync_clock.purge_deletes(db, days=30) == 1
        db.commit()
        assert sync_clock.read(db)["horizon"] >= 7


# ── правка очереди: номер и замок ────────────────────────────────────────────────────
def _set_grade(client, h, value, **extra):
    return client.post("/web/teacher/grade", headers=h, json={
        "lesson_id": "L21", "surname": "Иванов", "name": "Иван", "student_id": "stud:s1",
        "grade": value, **extra})


def test_queued_edit_is_checked_by_number(client):
    admin, t1, *_ = _world(client)
    first = _set_grade(client, t1, "4")
    assert first.status_code == 200, first.text
    seq = first.json()["change_seq"]
    assert seq > 0
    #Правка на свежей версии проходит, на устаревшей — конфликт с номером сервера.
    ok = _set_grade(client, t1, "5", base_seq=seq)
    assert ok.status_code == 200, ok.text
    stale = _set_grade(client, t1, "3", base_seq=seq)
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["server_seq"] == ok.json()["change_seq"]


def test_concurrent_write_between_read_and_check_is_caught(client, monkeypatch):
    """W-15: строку прочитали, а до записи её поменял другой запрос. Проверка обязана
    судить по строке, перечитанной ПОД ЗАМКОМ, а не по снимку до него."""
    admin, t1, *_ = _world(client)
    base = _set_grade(client, t1, "4").json()["change_seq"]
    from app.routers.web import write as W
    from app.db import SessionLocal
    from app.models import Grade
    real = W._seq_of

    def racing(row):
        with SessionLocal() as other:          #чужой запрос успел между чтением и записью
            g = other.get(Grade, "stud:s1|L21")
            g.grade = "2"
            other.commit()
        return real(row)

    monkeypatch.setattr(W, "_seq_of", racing)
    r = _set_grade(client, t1, "5", base_seq=base)
    assert r.status_code == 409, "правка затёрла изменение, сделанное между чтением и записью"


def test_base_number_of_a_row_is_unknown_when_the_copy_has_none():
    """В копии программы до 4.1 строка есть, а номера нет: это «неизвестно» (None), а не
    «строки не было» (0) — иначе бой счёл бы правку конфликтом с самой собой."""
    from types import SimpleNamespace
    from app.routers.web._common import _seq_of
    assert _seq_of(None) == 0
    assert _seq_of(SimpleNamespace(change_seq=0)) is None
    assert _seq_of(SimpleNamespace(change_seq=7)) == 7


def test_null_base_number_falls_back_to_time(client):
    admin, t1, *_ = _world(client)
    first = _set_grade(client, t1, "4").json()
    r = _set_grade(client, t1, "5", base_seq=None, base_updated_at=first["updated_at"])
    assert r.status_code == 200, r.text


# ── побочные эффекты копии ───────────────────────────────────────────────────────────
def test_local_copy_never_sends_pushes(monkeypatch):
    """W-18: правка журнала исполняется в копии программы, а потом ещё раз на бою —
    пуш обязан уйти один раз, с боя. В копии выключатель гасит все восемь мест разом."""
    from app import config
    monkeypatch.setattr(config, "RUSTORE_PROJECT_ID", "p")
    monkeypatch.setattr(config, "RUSTORE_SERVICE_TOKEN", "t")
    assert config.push_enabled()
    monkeypatch.setenv("GRADEBOOK_LOCAL_COPY", "1")
    assert not config.push_enabled()


# ── ограничитель и голова ────────────────────────────────────────────────────────────
def test_too_frequent_pulls_are_refused(client, monkeypatch):
    from app.routers import sync as S
    monkeypatch.setattr(S, "PULL_LIMIT", (3, 300.0))
    admin = make_admin(client)
    for _ in range(3):
        assert client.get("/sync/pull", params={"cursor": 0}, headers=admin).status_code == 200
    r = client.get("/sync/pull", params={"cursor": 0}, headers=admin)
    assert r.status_code == 429 and r.headers.get("Retry-After")


def test_head_answers_immediately_and_long_poll_wakes_on_commit(client, monkeypatch):
    #Страховочное перечитывание отодвигаем далеко: проверяется будильник на коммите, а
    #не опрос базы раз в пару секунд (с ним тест был бы зелёным и без будильника).
    from app import sync_notify
    monkeypatch.setattr(sync_notify, "RECHECK_S", 30.0)
    admin = make_admin(client)
    head = client.get("/sync/head", headers=admin).json()["head"]
    from app.db import SessionLocal
    from app.models import Subject

    def later():
        time.sleep(0.6)
        with SessionLocal() as db:
            db.add(Subject(id="subj:wake", name="wake"))
            db.commit()

    threading.Thread(target=later, daemon=True).start()
    t0 = time.monotonic()
    r = client.get("/sync/head", params={"after": head, "wait": 10}, headers=admin)
    took = time.monotonic() - t0
    assert r.status_code == 200 and r.json()["head"] > head
    assert took < 5, f"долгий опрос проспал правку: {took:.1f} с"


def test_web_client_gets_no_head(client):
    admin = make_admin(client)
    r = client.get("/sync/head", headers={**admin, "X-Client": "web"})
    assert r.status_code == 403


# ── Сверщик ──────────────────────────────────────────────────────────────────────────
def test_digest_matches_what_the_pull_delivered(client):
    """Отпечаток бьётся с тем, что копия получила полным проходом, — иначе Сверщик
    поднимал бы тревогу на исправной копии."""
    from app.routers.sync import table_digest
    admin, t1, *_ = _world(client)
    _push(client, admin, grades=[_grade("L21", "stud:s1", "5"), _grade("L22", "stud:s2", "4")])
    rows, _rm, _last = _drain(client, t1)
    dig = client.get("/sync/digest", headers=t1).json()
    for name in ("grades", "lessons", "users", "groups"):
        mine = table_digest(list(rows.get(name, {}).values()), "id")
        assert dig["tables"][name]["hash"] == mine["hash"], name
        assert dig["tables"][name]["count"] == mine["count"], name


def test_journal_gives_the_number_of_every_cell_including_cleared(client):
    """W-13б: телефон досылает оценку с номером клетки, который видел. Номер нужен и у
    снятой оценки: пустая клетка на экране — это и «строки нет» (0), и надгробие со своим
    номером, и перепутай их — повторная простановка получила бы ложный конфликт."""
    admin, t1, *_ = _world(client)
    ty, ts = _term()
    first = _set_grade(client, t1, "4").json()
    cleared = _set_grade(client, t1, "").json()
    r = client.get("/web/teacher/journal", headers={**t1, "X-Client": "web"},
                   params={"group": "ИС-21", "subject": "Математика"})
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["students"] if x["student_id"] == "stud:s1")
    assert row["seqs"]["L21"] == cleared["change_seq"] > first["change_seq"]
    #Поставить заново с этим номером — не конфликт.
    again = _set_grade(client, t1, "5", base_seq=row["seqs"]["L21"])
    assert again.status_code == 200, again.text


def test_rollback_survives_the_sync_notify_listener(client):
    """Слушатель отката (`sync_notify.install`) обязан принимать сигнатуру SQLAlchemy.

    Полный прогон 27.09.2026: слушатель с одним параметром ронял TypeError на КАЖДОМ
    `db.rollback()` — обработчики ошибок по всему серверу отвечали бы 500. Проверяем
    именно продуктовую фабрику сессий, на которую слушатель вешается при старте."""
    from app import sync_notify
    from app.db import SessionLocal
    from app.models import Group
    sync_notify.install(SessionLocal)
    db = SessionLocal()
    try:
        db.add(Group(id="grp:откат", name="откат"))
        db.flush()
        assert db.info.get("_sync_dirty") is True
        db.rollback()
        assert "_sync_dirty" not in db.info, "признак правки пережил откат — будильник сработает зря"
    finally:
        db.close()
