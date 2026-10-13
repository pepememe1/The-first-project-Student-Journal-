"""test_validation_text.py — ответ 422 читает человек, а не программист.

Что стережём. Запрос не той формы FastAPI отклоняет с кодом 422 и кладёт в `detail` список
объектов на английском. Страница показывает `detail` как есть (`toast.error(detail)` в ста
с лишним местах), и на экране получалось «[object Object]». Теперь `detail` — строка
по-русски (`app/validation_text.py`).

Обратный ход — `test_the_default_answer_is_the_defect`: то же приложение БЕЗ нашего
обработчика отдаёт список, то есть проверка «detail — строка» видит дефект, а не зелена
сама по себе.
"""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import validation_text
from app.main import app


def _cyrillic(text: str) -> bool:
    return any("а" <= ch.lower() <= "я" for ch in text)


class _Form(BaseModel):
    login: str
    password: str
    trust_token: str = ""
    limit: int = 10


def _toy(install: bool) -> TestClient:
    toy = FastAPI()

    @toy.post("/form")
    def form(body: _Form):
        return {"ok": True}

    @toy.get("/list")
    def listing(limit: int = 10):
        return {"limit": limit}

    if install:
        validation_text.install(toy)
    return TestClient(toy)


def test_the_default_answer_is_the_defect():
    """Обратный ход: без обработчика `detail` — список, и на экране это «[object Object]»."""
    r = _toy(install=False).post("/form", json={})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


def test_missing_field_is_named_the_way_the_screen_names_it():
    r = _toy(install=True).post("/form", json={"password": "x"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, str)
    assert "«Логин»" in detail and "заполнить" in detail
    assert "Field required" not in detail and _cyrillic(detail)


def test_several_fields_are_counted_not_listed():
    detail = _toy(install=True).post("/form", json={}).json()["detail"]
    assert "«Логин»" in detail and "ещё полей с ошибкой: 1" in detail


def test_technical_field_is_not_shown_to_a_person():
    """`trust_token` человек не вводил и исправить не может — ему нужен совет, а не имя поля."""
    detail = _toy(install=True).post(
        "/form", json={"login": "a", "password": "b", "trust_token": {"x": 1}}).json()["detail"]
    assert "trust_token" not in detail
    assert "Обновите страницу" in detail


def test_query_parameter_error_is_not_blamed_on_the_person():
    detail = _toy(install=True).get("/list", params={"limit": "много"}).json()["detail"]
    assert "Обновите страницу" in detail and "limit" not in detail


def test_wrong_type_gets_a_plain_reason():
    detail = _toy(install=True).post(
        "/form", json={"login": "a", "password": "b", "limit": "много"}).json()["detail"]
    #У `limit` подписи нет — значит это служебное поле и совет общий.
    assert "Обновите страницу" in detail
    reason = validation_text._reason({"type": "int_parsing"})
    assert reason == "здесь должно быть число"


def test_the_answer_never_repeats_what_was_sent():
    """🔒 Пароль, оказавшийся не в том поле, не должен вернуться в теле ответа."""
    marker = "ZNACHENIE-KOTOROE-NE-DOLZHNO-VERNUTSYA"
    r = _toy(install=True).post("/form", json={"login": {"oops": marker}, "password": [marker]})
    assert r.status_code == 422
    assert marker not in r.text
    for err in r.json()["errors"]:
        assert set(err) == {"loc", "type", "msg"}


def test_own_russian_reason_survives_and_english_does_not():
    ru = {"type": "value_error", "msg": "Value error, дата не может быть в будущем"}
    en = {"type": "value_error", "msg": "Value error, bad thing happened"}
    assert validation_text._reason(ru) == "дата не может быть в будущем"
    assert validation_text._reason(en) == "значение не подходит"


def test_the_product_app_has_the_handler_and_answers_in_russian():
    """Проводка: обработчик подключён к настоящему приложению, а не только существует."""
    assert RequestValidationError in app.exception_handlers
    with TestClient(app) as client:
        r = client.post("/auth/login", json={"login": "someone"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, str), "страница показала бы «[object Object]»"
    assert "«Пароль»" in detail
