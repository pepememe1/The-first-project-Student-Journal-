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


# ─────────────────────────────────────────────────────────────────────────────
# Страница и ручка по одному адресу (02.09.2026)
#
# 🔥 Дефект: страница «расписание без входа» была заведена на `/public/schedule` —
# адресе, который на сервере уже занят ЭТОЙ ручкой. Переход по ссылке внутри сайта
# работал (роутинг клиентский, до сервера не идёт), а прямой заход, F5 и присланная
# ссылка отдавали голый JSON. То есть страница была недостижима ровно в том случае,
# ради которого её и завели: человека выбросило из аккаунта, он открывает адрес.
# Освободить адрес нельзя — по нему ходит виджет из ОПУБЛИКОВАННОГО APK.
# ─────────────────────────────────────────────────────────────────────────────

_NAV = {"Sec-Fetch-Mode": "navigate"}


def test_person_opening_the_address_in_a_browser_gets_the_page_not_json(client):
    """Главное свойство задачи: человек, открывший адрес, попадает на страницу."""
    r = client.get("/public/schedule", headers=_NAV, follow_redirects=False)
    assert r.status_code == 302, r.text
    assert r.headers["location"] == "/schedule"


def test_a_shared_link_keeps_the_group_it_was_shared_with(client):
    """Ссылку присылают со СВОЕЙ группой («вот расписание К74/1»). Потеряв её при
    переадресации, страница показала бы группу из памяти открывшего — то есть уверенно
    ответила бы не на тот вопрос."""
    r = client.get("/public/schedule", params={"group": "К74/1"},
                   headers=_NAV, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/schedule?group=%D0%9A74/1"


def test_the_android_widget_still_gets_json(client, monkeypatch):
    """ОБРАТНЫЙ ХОД, и он здесь важнее прямого: виджет живёт в уже опубликованном APK,
    и увести его на страницу значит сломать то, что работает, без возможности починить
    иначе как перезаливом в RuStore.

    ⚠️ Заголовки взяты НАСТОЯЩИЕ, как их шлёт `ScheduleWidgetRefresh.java`, вместе с
    дефолтным `Accept` Java-клиента — он начинается с `text/html`, и проверка «по
    Accept» приняла бы виджет за браузер. Ровно поэтому смотрим `Sec-Fetch-Mode`.
    """
    monkeypatch.setattr(schedule_web, "get_group", lambda g, c="": _SNAP)
    r = client.get("/public/schedule", params={"group": "К74/1"}, headers={
        "Accept": "text/html, image/gif, image/jpeg, *; q=.2, */*; q=.2",
        "X-Client": "android-widget",
    }, follow_redirects=False)
    assert r.status_code == 200, r.text
    assert r.json()["available"] is True


def test_the_spa_fetching_data_is_not_redirected(client, monkeypatch):
    """У fetch/XHR из самой страницы `Sec-Fetch-Mode` равен `cors`/`same-origin`.
    Переадресуй мы и его — страница получила бы HTML вместо данных и показала бы
    «не удалось получить расписание» на исправном сервере."""
    monkeypatch.setattr(schedule_web, "get_group", lambda g, c="": _SNAP)
    for mode in ("cors", "same-origin", "no-cors"):
        r = client.get("/public/schedule", params={"group": "К74/1"},
                       headers={"Sec-Fetch-Mode": mode}, follow_redirects=False)
        assert r.status_code == 200, mode
        assert r.json()["available"] is True, mode


def test_an_unknown_public_address_is_an_honest_404_not_a_page(client):
    """Пока «public» не стоял в списке API-префиксов, ЛЮБОЙ неизвестный `/public/*`
    отвечал страницей с кодом 200. Цена такой дыры не в вежливости ответа: тест,
    стучащийся в опечатанный адрес, зеленеет НЕ ДОЙДЯ до кода — этим уже дважды
    ловились проверки второго фактора (см. CLAUDE.md, 29.08.2026)."""
    r = client.get("/public/net-takogo-adresa")
    assert r.status_code == 404, r.text
    assert "text/html" not in r.headers.get("content-type", "")


def test_the_page_address_is_not_taken_by_any_api_route():
    """Страница и ручка не имеют права делить URL — кто выиграет, решает порядок
    подключения роутеров, а не замысел. Сторож смотрит на ПРОДУКТ: если однажды
    заведут `GET /schedule` на сервере, страница расписания молча исчезнет снова."""
    from app.main import app as real_app
    from app.routers.publicschedule import PAGE_URL

    from test_spa_fallback import _all_paths

    assert PAGE_URL not in set(_all_paths(real_app))
