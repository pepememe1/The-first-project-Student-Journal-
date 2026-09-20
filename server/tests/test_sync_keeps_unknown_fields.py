"""
test_sync_keeps_unknown_fields.py — снимок десктопа не стирает поля, которых десктоп
не знает (находка ревью J03, 18.09.2026; починено 20.09.2026).

━━ ЧТО БЫЛО ━━
Даты пересдач №2–5 живут в `Lesson.extra`: их пишет веб (`web/write.py`), читает журнал
преподавателя (`web/teacher.py`). В локальной таблице `lessons` десктопа колонки `extra`
НЕТ ВОВСЕ — а сборщик синхронизации честно подставлял `"extra": {}`. Полный снимок,
который любой ПК шлёт на старте сессии, объявлял пустой словарь новым содержимым, и
сервер затирал им заполненные в вебе даты. Ни ошибки, ни отказа: обычная успешная
синхронизация, после которой колонок пересдач в журнале больше нет.

⚠️ Починка сделана В ДВУХ местах, и это не дублирование. `sync_engine._collect_lessons`
больше не шлёт `extra` вовсе — но эта правка доедет до людей только новой сборкой .exe,
а парк сидит на прежней. Серверная половина (`_KEEP_WHEN_BLANK`) закрывает уже
установленные версии одним деплоем, поэтому проверяется именно она: тест шлёт РОВНО тот
payload, который шлёт старый клиент.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать блок `_KEEP_WHEN_BLANK` в `sync.py` — краснеет первый
тест. Второй и третий остаются зелёными и стерегут от «починки», которая запретила бы
законную правку поля и заведение его с нуля.
"""
from conftest import make_admin, make_teacher

#⚠️ Термин БЕРЁМ ИЗ ПРОДУКТА, а не пишем числом (инвариант «тест, привязанный к
#календарю, протухает сам»): захардкоженный год краснеет ровно 1 сентября, вперемешку с
#настоящими падениями, а написанный «на будущее» — молча начинает проверять другой
#сценарий. Держит `tests/test_no_calendar_bound_tests.py`, он же это и поймал.
def _current_term():
    from app.db import SessionLocal
    from app.routers.web import _common as C
    db = SessionLocal()
    try:
        return C.W.current_term(C.W.load_config(db))
    finally:
        db.close()


YEAR, SEM = _current_term()
GROUP, SUBJ = "К-41", "Физика"


def _setup(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin, login="t_extra", subjects=(SUBJ,))
    r = client.post("/sync/push", json={"changes": {"subject_hours": [{
        "id": f"hrs:{GROUP}|{SUBJ}|{YEAR}|{SEM}", "group_name": GROUP, "subject": SUBJ,
        "year": YEAR, "semester": SEM, "hours_total": 32, "teacher_id": "teach:t_extra",
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": SUBJ, "type": "Практика", "number": 1,
        "date": "01.09.2026", "topic": "Кинематика",
    }, headers=teacher)
    assert r.status_code == 200, r.text
    lid = r.json()["id"]
    #Даты пересдач заполняет ВЕБ — это единственный путь, каким `extra` вообще
    #появляется. Десктоп их не редактирует и не показывает.
    r = client.put(f"/web/teacher/lesson/{lid}", json={"retake_date_2": "15.09.2026"},
                   headers=teacher)
    assert r.status_code == 200, r.text
    return admin, teacher, lid


def _extra_of(lid):
    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        return dict((db.get(Lesson, lid).extra) or {})
    finally:
        db.close()


def _desktop_snapshot(lid, **over):
    """РОВНО то, что шлёт установленная у людей сборка: снимок занятия целиком."""
    item = {"id": lid, "group_name": GROUP, "subject": SUBJ, "type": "Практика",
            "number": 1, "topic": "Кинематика", "date": "01.09.2026",
            "retake_date": "", "hour": 0, "extra": {},
            "updated_at": "2026-09-02T00:00:00Z", "deleted": False,
            "year": YEAR, "semester": SEM}
    item.update(over)
    return {"changes": {"lessons": [item]}}


def test_blank_extra_from_an_old_client_does_not_erase_retake_dates(client):
    _, teacher, lid = _setup(client)
    assert _extra_of(lid).get("retake_date_2") == "15.09.2026", "подготовка не удалась"

    r = client.post("/sync/push", json=_desktop_snapshot(lid, topic="Кинематика и динамика"),
                    headers=teacher)
    assert r.status_code == 200, r.text

    assert _extra_of(lid).get("retake_date_2") == "15.09.2026", \
        "снимок десктопа стёр дату пересдачи пустым extra"

    #И правка, которую человек ДЕЙСТВИТЕЛЬНО сделал, при этом доехала: защита обязана
    #спасать одно поле, а не отменять весь push.
    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        assert db.get(Lesson, lid).topic == "Кинематика и динамика", \
            "защита поля отменила законную правку темы"
    finally:
        db.close()


def test_a_client_that_does_know_the_field_can_still_change_it(client):
    """Непустое значение применяется как обычно — запрет только на СТИРАНИЕ пустотой."""
    _, teacher, lid = _setup(client)
    r = client.post("/sync/push",
                    json=_desktop_snapshot(lid, extra={"retake_date_2": "20.09.2026"}),
                    headers=teacher)
    assert r.status_code == 200, r.text
    assert _extra_of(lid).get("retake_date_2") == "20.09.2026", \
        "осознанная правка поля не доехала"


def test_blank_extra_is_fine_when_the_server_has_nothing_to_lose(client):
    """У занятия без пересдач пустое extra — не потеря, и отказывать тут не в чем."""
    admin, teacher, _ = _setup(client)
    r = client.post("/web/teacher/lesson", json={
        "group": GROUP, "subject": SUBJ, "type": "Практика", "number": 2,
        "date": "08.09.2026", "topic": "Динамика",
    }, headers=teacher)
    assert r.status_code == 200, r.text
    lid2 = r.json()["id"]
    r = client.post("/sync/push", json={"changes": {"lessons": [
        {"id": lid2, "group_name": GROUP, "subject": SUBJ, "type": "Практика",
         "number": 2, "topic": "Динамика и статика", "date": "08.09.2026",
         "retake_date": "", "hour": 0, "extra": {},
         "updated_at": "2026-09-02T00:00:00Z", "deleted": False,
         "year": YEAR, "semester": SEM}]}}, headers=teacher)
    assert r.status_code == 200, r.text
    assert _extra_of(lid2) == {}
    from app.db import SessionLocal
    from app.models import Lesson
    db = SessionLocal()
    try:
        assert db.get(Lesson, lid2).topic == "Динамика и статика"
    finally:
        db.close()
