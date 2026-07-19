"""
test_vector_weather.py — СЕРВЕР: погода Вектора из реальных данных, мимо LLM.

Зеркало клиентского tests/test_weather.py. Проверяем не саму метеослужбу (это был бы
тест чужого сервиса), а наш контракт: интент распознан, числа не искажены, при
отсутствии связи — честное «не знаю», и погода НЕ уходит в озвучку модели.
"""
import pytest

from conftest import make_admin


@pytest.fixture(autouse=True)
def clean_weather_cache():
    import weather
    weather._cache.update({"at": 0.0, "data": None})
    yield
    weather._cache.update({"at": 0.0, "data": None})


def _ask(client, headers, text):
    return client.post("/web/vector/ask", json={"message": text}, headers=headers)


def test_weather_answer_uses_real_numbers(client, monkeypatch):
    import weather
    monkeypatch.setattr(weather, "_fetch",
                        lambda: {"temp": -21, "feels": -28, "wind": 15, "code": 73})
    admin = make_admin(client)
    r = _ask(client, admin, "какая погода")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "weather"
    assert "-21°" in body["text"]
    assert "снег" in body["text"]


def test_weather_without_connection_is_honest(client, monkeypatch):
    """Метеослужба недоступна → говорим прямо, а не выдумываем градусы."""
    import weather

    def boom():
        raise OSError("сети нет")
    monkeypatch.setattr(weather, "_fetch", boom)
    admin = make_admin(client)
    body = _ask(client, admin, "какая погода на улице").json()
    assert body["intent"] == "weather"
    assert "не могу" in body["text"].lower()
    assert "°" not in body["text"], "без данных градусов в ответе быть не должно"


def test_weather_is_not_voiced_by_llm():
    """Погода в _NO_VOICE_INTENTS: модель, «озвучивая данные», меняет числа, а неверная
    температура в продукте, обещающем не врать, дороже красивой формулировки."""
    from app.routers.web import _NO_VOICE_INTENTS
    assert "weather" in _NO_VOICE_INTENTS


def test_weather_returns_user_to_studies(client, monkeypatch):
    """Поболтали — и мягко вернулись к учёбе (Вектор помощник, а не собеседник)."""
    import weather
    monkeypatch.setattr(weather, "_fetch",
                        lambda: {"temp": 18, "feels": 18, "wind": 2, "code": 0})
    admin = make_admin(client)
    text = _ask(client, admin, "погода сегодня").json()["text"].lower()
    assert any(w in text for w in ("оценк", "расписан", "долг", "учёб", "учеб"))


def test_study_questions_still_work(client, monkeypatch):
    """Погодный интент не должен перехватывать учебные вопросы."""
    admin = make_admin(client)
    body = _ask(client, admin, "сколько групп").json()
    assert body["intent"] != "weather"
