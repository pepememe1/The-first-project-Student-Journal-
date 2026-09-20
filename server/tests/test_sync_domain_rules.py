"""
test_sync_domain_rules.py — одна операция получает одно решение, каким бы транспортом
она ни пришла (находка ревью J06, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
Веб-ручка `/web/teacher/grade` проверяет ЧЕТЫРЕ вещи: значение по шкале, назначение на
пару, архив прошлых семестров и замок зачётки (выставлена итоговая — текущие оценки по
предмету закрыты). Через `/sync/push` не проверялось НИ ОДНО, кроме назначения. То есть
офлайн-копия обходила и замок, и запрет правки архива, и проверку значения — молча и с
успешным ответом, а решение продукта зависело от того, откуда пришёл запрос.

⚠️ Отказ не выдаётся за сохранение: он попадает в `rejected` (клиент читает его и
показывает), а сверка «сервер = истина» при непустом `rejected` не стирает локальный
кэш — работа остаётся у человека.

⚠️ Отдельно проверяется, что полный снимок с архивными оценками, СОВПАДАЮЩИМИ с
серверными, не отвергается: иначе `rejected` был бы вечно ненулевым и сверка не
выполнилась бы никогда.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать оба вызова `_domain_refusal` — краснеют первые три
теста. Четвёртый и пятый зелены и стерегут от «починки», которая начала бы отвергать
неизменившийся снимок или ломать администратора.
"""
from conftest import make_admin, make_teacher
from app.security import hash_password

GROUP, SUBJ = "К-61", "Физика"
SID = "stud:dom1"


def _term(db=None):
    from app.db import SessionLocal
    from app.routers.web import _common as C
    s = SessionLocal()
    try:
        return C.W.current_term(C.W.load_config(s))
    finally:
        s.close()


def _setup(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t_dom", subjects=(SUBJ,))
    ty, ts = _term()
    r = client.post("/sync/push", json={"changes": {
        "subject_hours": [{
            "id": f"hrs:{GROUP}|{SUBJ}|{ty}|{ts}", "group_name": GROUP, "subject": SUBJ,
            "year": ty, "semester": ts, "hours_total": 32, "teacher_id": "teach:t_dom",
        }],
        "users": [{
            "id": SID, "role": "student", "login": "dom1",
            "password_hash": hash_password("studpass1"),
            "surname": "Доржиев", "name": "Дамба", "group_name": GROUP,
        }],
    }}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": SUBJ, "type": "Практика", "number": 1,
        "date": "01.09.2026", "topic": "Тема",
    }, headers=teacher)
    assert r.status_code == 200, r.text
    return admin, teacher, r.json()["id"], ty, ts


def _push_grade(client, headers, lesson_id, value, gid=None):
    from app.models import grade_id
    return client.post("/sync/push", json={"changes": {"grades": [{
        "id": gid or grade_id(SID, lesson_id), "student_f": "Доржиев", "student_n": "Дамба",
        "lesson_id": lesson_id, "grade": value, "student_id": SID,
        "updated_at": "2026-09-02T00:00:00Z", "deleted": False,
    }]}}, headers=headers)


def _grade_in_db(lesson_id):
    from app.db import SessionLocal
    from app.models import Grade, grade_id
    db = SessionLocal()
    try:
        row = db.get(Grade, grade_id(SID, lesson_id))
        return None if row is None else (row.grade or "")
    finally:
        db.close()


def test_sync_refuses_a_value_the_web_would_refuse(client):
    _, teacher, lid, _, _ = _setup(client)
    r = _push_grade(client, teacher, lid, "Ништяк")
    assert r.status_code == 200, r.text
    assert (r.json().get("rejected") or {}).get("grades") == 1, \
        f"мусорное значение принято через синк: {r.json()}"
    assert _grade_in_db(lid) is None, "отвергнутая оценка всё равно записалась"
    #И человеку названа ПРИЧИНА, а не только число.
    why = (r.json().get("rejected_reasons") or {}).get("grades") or []
    assert any("значение" in w for w in why), f"причина отказа не названа: {why}"


def test_sync_respects_the_gradebook_lock(client):
    """Итоговая выставлена — текущие оценки закрыты. Через веб это 409, через синк это
    был молчаливый успех."""
    _, teacher, lid, _, _ = _setup(client)
    r = client.post("/web/teacher/term-grade", json={
        "surname": "Доржиев", "name": "Дамба", "subject": SUBJ, "group": GROUP,
        "grade": "5",
    }, headers=teacher)
    assert r.status_code == 200, r.text

    r = _push_grade(client, teacher, lid, "3")
    assert (r.json().get("rejected") or {}).get("grades") == 1, \
        f"замок зачётки обошёлся синком: {r.json()}"
    assert _grade_in_db(lid) is None


def test_sync_respects_the_archive(client):
    """Занятие прошлого семестра — read-only на обоих транспортах."""
    admin, teacher, lid, _, _ = _setup(client)
    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        row = db.get(Lesson, lid)
        row.year, row.semester = "2020/2021", 2      #уводим занятие в архив
        db.commit()
    finally:
        db.close()

    r = _push_grade(client, teacher, lid, "4")
    assert (r.json().get("rejected") or {}).get("grades") == 1, \
        f"оценка записана в архивный семестр: {r.json()}"


def test_an_unchanged_snapshot_is_not_rejected(client):
    """🔑 Главная страховка правки. Полный снимок десктопа везёт и архивные оценки,
    совпадающие с серверными. Отвергать их значило бы держать `rejected` вечно
    ненулевым — а при непустом `rejected` сверка «сервер = истина» не стирает кэш, то
    есть она перестала бы выполняться НАВСЕГДА."""
    admin, teacher, lid, _, _ = _setup(client)
    assert _push_grade(client, teacher, lid, "5").json().get("rejected") is None

    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        row = db.get(Lesson, lid)
        row.year, row.semester = "2020/2021", 2
        db.commit()
    finally:
        db.close()

    #Та же самая оценка тем же снимком: ничего не меняется — отвергать нечего.
    r = _push_grade(client, teacher, lid, "5")
    assert r.status_code == 200, r.text
    assert r.json().get("rejected") is None, \
        f"неизменившийся снимок отвергнут — сверка «сервер = истина» больше не сработает: {r.json()}"


def test_the_admin_push_is_untouched(client):
    """Администратор шлёт весь справочник колледжа; учительские замки к нему не
    применяются — ни в вебе, ни здесь."""
    admin, teacher, lid, _, _ = _setup(client)
    r = client.post("/web/teacher/term-grade", json={
        "surname": "Доржиев", "name": "Дамба", "subject": SUBJ, "group": GROUP,
        "grade": "5",
    }, headers=teacher)
    assert r.status_code == 200, r.text
    r = _push_grade(client, admin, lid, "3")
    assert r.status_code == 200, r.text
    assert r.json().get("rejected") is None, "админский push сломан замком преподавателя"
