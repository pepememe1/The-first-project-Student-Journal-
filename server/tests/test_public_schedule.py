"""Расписание БЕЗ входа в аккаунт (`/public/schedule/*`).

Эндпоинт открытый — значит проверять надо не «работает ли», а ГРАНИЦУ: что он отдаёт
ровно расписание (публичное у первоисточника) и НИ ОДНОЙ строки из журнала. Соблазн
«тут же рядом отдать средний балл» появится обязательно, и держать его должен тест, а
не комментарий в файле.
"""
import pytest
from fastapi.testclient import TestClient

from app import schedule_web
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


_SNAP = {
    "name": "К74/1", "href": "", "pair_times": [],
    "weeks": {"1": {"Пнд": [{"pair_no": 1, "time": "09:00-10:35", "kind": "лек",
                             "subject": "Математика", "teacher": "Иванов И.И.",
                             "room": "301", "raw": "", "extra": ""}]}},
}


def test_group_schedule_works_without_any_token(client, monkeypatch):
    """Главное свойство: токена нет, а расписание есть. Ради этого всё и делалось —
    виджету на рабочем столе токен взять неоткуда (JWT живёт максимум неделю)."""
    monkeypatch.setattr(schedule_web, "get_group", lambda g, c="": _SNAP)
    r = client.get("/public/schedule", params={"group": "К74/1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["group"] == "К74/1"
    assert body["schedule"]["weeks"]["1"]["Пнд"][0]["subject"] == "Математика"


def test_teacher_schedule_works_without_any_token(client, monkeypatch):
    class _Snap:
        def teachers(self):
            return ["Иванов И.И."]

    monkeypatch.setattr(schedule_web, "full_state", lambda c="": (_Snap(), False))
    monkeypatch.setattr(schedule_web, "teacher_weeks",
                        lambda snap, name: {"1": {"Пнд": []}} if name else None)
    r = client.get("/public/schedule/teacher", params={"name": "Иванов И.И."})
    assert r.status_code == 200
    assert r.json()["teacher"] == "Иванов И.И."


def test_no_group_is_honest_refusal_not_empty_schedule(client):
    """Без параметра `group` подставить «свою» неоткуда — токена нет. Отвечаем честным
    available=false, а не пустым расписанием, которое читалось бы как «пар нет»."""
    r = client.get("/public/schedule")
    assert r.status_code == 200
    assert r.json()["available"] is False
    assert r.json()["schedule"] is None


def test_week_parity_endpoint_returns_date_it_was_computed_for(client):
    """Дату возвращаем вместе с чётностью: без неё при расхождении часовых поясов не
    разобрать, чья «сегодня» имелась в виду."""
    r = client.get("/public/week")
    assert r.status_code == 200
    assert r.json()["week"] in (1, 2)
    assert len(r.json()["date"]) == 10


def test_public_router_exposes_only_schedule(client):
    """🔒 ГРАНИЦА. Под /public не должно быть ничего, кроме расписания и чётности недели.

    Проверяем не текст файла, а РЕАЛЬНО зарегистрированные маршруты приложения — иначе
    достаточно было бы дописать роут в другом файле с тем же префиксом, и тест бы этого
    не заметил."""
    paths = set()
    for r in app.routes:
        p = getattr(r, "path", "")
        if p.startswith("/public"):
            paths.add(p)
        #Подключённые роутеры в этой версии FastAPI лежат обёрткой без .path —
        #настоящие маршруты внутри original_router (тот же приём, что в §16).
        inner = getattr(r, "original_router", None)
        for ir in getattr(inner, "routes", []) or []:
            ip = getattr(ir, "path", "")
            if ip.startswith("/public"):
                paths.add(ip)
    assert paths == {"/public/schedule", "/public/schedule/teacher", "/public/week"}, paths


@pytest.mark.parametrize("path,params", [
    ("/public/schedule", {"group": "К74/1"}),
    ("/public/schedule/teacher", {"name": "Иванов И.И."}),
])
def test_public_answers_never_contain_journal_fields(client, monkeypatch, path, params):
    """🔒 В ответе не должно быть ни одного признака журнала: оценок, посещаемости,
    среднего балла, ЗЕТ, риска отчисления, списков студентов."""
    monkeypatch.setattr(schedule_web, "get_group", lambda g, c="": _SNAP)
    monkeypatch.setattr(schedule_web, "full_state", lambda c="": (None, False))
    body = client.get(path, params=params).text.lower()
    for forbidden in ("average", "средний", "grade", "оценк", "absenc", "пропуск",
                      "zet", "risk", "student_id", "долг"):
        assert forbidden not in body, f"{path}: в публичном ответе оказалось «{forbidden}»"


def test_rate_limit_answers_429_not_403(client, monkeypatch):
    """Превышение частоты — это 429, а не 403: клиенту надо понять, что дело во
    ВРЕМЕНИ и повторить позже, а не решить, что доступ закрыт навсегда."""
    from app.routers import publicschedule

    monkeypatch.setattr(publicschedule, "_too_many", lambda request: True)
    r = client.get("/public/schedule", params={"group": "К74/1"})
    assert r.status_code == 429
