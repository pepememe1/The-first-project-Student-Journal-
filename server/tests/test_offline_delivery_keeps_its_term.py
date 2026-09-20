"""
test_offline_delivery_keeps_its_term.py — операция исполняется в том периоде, для
которого её задумали (находка ревью J10, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
Итоговая оценка и новое занятие штампуются `current_term` В МОМЕНТ ИСПОЛНЕНИЯ. Онлайн
это одно мгновение с нажатием, а офлайн-очередь (`web/src/api/outbox.js`) доставляет
запись через произвольный срок — ночь, выходные, каникулы. Преподаватель закрывает
первый семестр без сети 30 декабря, очередь уходит 12 января: сервер пишет итоговую во
ВТОРОЙ семестр и запирает ею период, который никто не закрывал (наличие итоговой
закрывает текущие оценки по предмету, `_ensure_term_open`). Ни ошибки, ни следа.

⚠️ Ответ — ОТКАЗ, а не перенос. Куда девать работу, сделанную для закрытого периода,
решает человек: открыть семестр обратно (законное действие админа) или отказаться.
Молчаливый перенос — решение за него, причём невидимое. Отказ виден: очередь кладёт
такие записи в `rejected`, и плашка показывает их с причиной.

⚠️ Период НЕОБЯЗАТЕЛЕН намеренно — его не шлют онлайн-веб, десктоп и старые сборки
приложения. Требовать его значило бы сломать их все ради случая, которого у них нет.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать вызовы `_require_intended_term` — краснеют первый и
четвёртый тесты. Остальные зелены и стерегут от «починки», которая начала бы требовать
период или отвергать законную запись.
"""
from conftest import make_admin, make_teacher
from app.security import hash_password

GROUP, SUBJ = "К-51", "История"
STALE_YEAR, STALE_SEM = "2020/2021", 2      #заведомо не текущий период


def _term(client, admin):
    from app.db import SessionLocal
    from app.routers.web import _common as C
    db = SessionLocal()
    try:
        return C.W.current_term(C.W.load_config(db))
    finally:
        db.close()


def _setup(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t_term10", subjects=(SUBJ,))
    ty, ts = _term(client, admin)
    r = client.post("/sync/push", json={"changes": {
        "subject_hours": [{
            "id": f"hrs:{GROUP}|{SUBJ}|{ty}|{ts}", "group_name": GROUP, "subject": SUBJ,
            "year": ty, "semester": ts, "hours_total": 32, "teacher_id": "teach:t_term10",
        }],
        "users": [{
            "id": "stud:term10", "role": "student", "login": "term10",
            "password_hash": hash_password("studpass1"),
            "surname": "Батоев", "name": "Баир", "group_name": GROUP,
        }],
    }}, headers=admin)
    assert r.status_code == 200, r.text
    return admin, teacher, ty, ts


def _set_term_grade(client, headers, **over):
    body = {"surname": "Батоев", "name": "Баир", "subject": SUBJ, "group": GROUP,
            "grade": "5"}
    body.update(over)
    return client.post("/web/teacher/term-grade", json=body, headers=headers)


def test_a_term_grade_meant_for_a_closed_period_is_refused(client):
    _, teacher, ty, ts = _setup(client)
    r = _set_term_grade(client, teacher, year=STALE_YEAR, semester=STALE_SEM)
    assert r.status_code == 409, \
        f"итоговая за {STALE_YEAR}·{STALE_SEM} записана в текущий период: {r.status_code}"
    detail = r.json().get("detail", "")
    assert STALE_YEAR in detail and ty in detail, \
        f"отказ не называет ОБА периода, человеку нечего понять: {detail!r}"

    #И главное следствие: текущий семестр не заперт чужой итоговой.
    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": SUBJ, "type": "Практика", "number": 1,
        "date": "01.09.2026", "topic": "Тема",
    }, headers=teacher)
    assert r.status_code == 200, r.text
    r = client.post("/web/teacher/grade", json={
        "lesson_id": r.json()["id"], "surname": "Батоев", "name": "Баир", "value": "4",
    }, headers=teacher)
    assert r.status_code == 200, f"чужая итоговая заперла текущий семестр: {r.text}"


def test_a_term_grade_that_names_the_current_period_goes_through(client):
    _, teacher, ty, ts = _setup(client)
    r = _set_term_grade(client, teacher, year=ty, semester=ts)
    assert r.status_code == 200, f"законная запись со своим периодом отвергнута: {r.text}"


def test_a_client_that_does_not_send_a_period_still_works(client):
    """Онлайн-веб, десктоп и старые сборки приложения периода не шлют — и не должны."""
    _, teacher, _, _ = _setup(client)
    assert _set_term_grade(client, teacher).status_code == 200


def test_a_lesson_meant_for_a_closed_period_is_refused(client):
    _, teacher, _, _ = _setup(client)
    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": SUBJ, "type": "Лекция", "number": 1,
        "date": "10.12.2020", "topic": "Прошлый семестр",
        "year": STALE_YEAR, "semester": STALE_SEM,
    }, headers=teacher)
    assert r.status_code == 409, \
        f"занятие прошлого семестра заведено в текущем журнале: {r.status_code} {r.text}"


def test_a_lesson_without_a_period_is_stamped_as_before(client):
    _, teacher, ty, ts = _setup(client)
    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": SUBJ, "type": "Лекция", "number": 1,
        "date": "01.09.2026", "topic": "Обычное занятие",
    }, headers=teacher)
    assert r.status_code == 200, r.text
    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        row = db.get(Lesson, r.json()["id"])
        assert (row.year, row.semester) == (ty, ts), "штамп текущего периода сломан"
    finally:
        db.close()
