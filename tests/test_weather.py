"""
test_weather.py — погода Вектора берётся у метеослужбы, а не выдумывается.

Ключевое требование продукта: Вектор НЕ сочиняет цифры. Погода тут не исключение —
и «не знаю» при отсутствии связи важнее красивого ответа, потому что устаревшая
температура вводит в заблуждение сильнее, чем её отсутствие.

Сеть в тестах не трогаем: подменяем _fetch. Тест, ходящий в интернет, — это тест
чужого сервиса, а не нашего кода.
"""
import pytest

import weather
import vector_nlu


@pytest.fixture(autouse=True)
def clean_cache():
    """Кэш общий на процесс — чистим, иначе тесты влияют друг на друга."""
    weather._cache.update({"at": 0.0, "data": None})
    yield
    weather._cache.update({"at": 0.0, "data": None})


def _fake(monkeypatch, data):
    monkeypatch.setattr(weather, "_fetch", lambda: data)


def test_intent_recognised():
    """Вопросы про погоду не должны утекать в другие интенты."""
    for q in ["какая погода", "погода в улан-удэ", "сколько градусов на улице",
              "что там на улице", "как погода сегодня"]:
        assert vector_nlu.classify(q, [], [])["intent"] == "weather", q


def test_weather_does_not_shadow_study_intents():
    """И наоборот: учебные вопросы не должны попадать в погоду."""
    cases = {"сколько у меня оценок": "grade_count", "средний балл": "average",
             "какие пары в понедельник": "schedule"}
    for q, expect in cases.items():
        assert vector_nlu.classify(q, [], ["Математика"])["intent"] == expect, q


def test_answer_uses_real_numbers(monkeypatch):
    """Числа из ответа службы попадают в текст КАК ЕСТЬ."""
    _fake(monkeypatch, {"temp": -17, "feels": -24, "wind": 12, "code": 71})
    text = weather.answer()
    assert "-17°" in text
    assert "небольшой снег" in text
    assert "12 км/ч" in text


def test_feels_like_shown_only_when_it_differs(monkeypatch):
    """«Ощущается» — только при заметной разнице, иначе это шум в ответе."""
    _fake(monkeypatch, {"temp": 10, "feels": 10, "wind": 1, "code": 0})
    assert "ощущается" not in weather.answer()
    #Кэш чистим вручную: без этого второй набор данных не доедет (и это правильно —
    #ровно так кэш и должен работать).
    weather._cache.update({"at": 0.0, "data": None})
    _fake(monkeypatch, {"temp": -10, "feels": -18, "wind": 1, "code": 0})
    assert "ощущается" in weather.answer()


def test_no_connection_says_honestly(monkeypatch):
    """Нет связи → честное «не могу посмотреть», а НЕ выдуманная погода."""
    def boom():
        raise OSError("сети нет")
    monkeypatch.setattr(weather, "_fetch", boom)
    assert weather.current() is None
    text = weather.answer()
    assert "не могу" in text.lower()
    #в ответе не должно быть ни градусов, ни описания неба
    assert "°" not in text


def test_stale_cache_is_not_served(monkeypatch):
    """Протухший кэш не отдаём: «сейчас −20» вместо оттепели хуже, чем «не знаю»."""
    _fake(monkeypatch, {"temp": -20, "feels": -20, "wind": 0, "code": 0})
    assert weather.current()["temp"] == -20
    #состарим запись и оборвём сеть
    weather._cache["at"] -= weather.CACHE_TTL_S + 1

    def boom():
        raise OSError("сети нет")
    monkeypatch.setattr(weather, "_fetch", boom)
    assert weather.current() is None, "устаревшие данные выдавать нельзя"


def test_cache_prevents_hammering(monkeypatch):
    """Свежий кэш переиспользуется — VPS одноядерный, дёргать API на каждый вопрос
    незачем."""
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return {"temp": 5, "feels": 5, "wind": 0, "code": 0}
    monkeypatch.setattr(weather, "_fetch", counting)
    for _ in range(5):
        weather.current()
    assert calls["n"] == 1


def test_answer_returns_to_studies(monkeypatch):
    """Вектор — помощник по учёбе: поболтали и вернулись к делу."""
    _fake(monkeypatch, {"temp": 20, "feels": 20, "wind": 0, "code": 0})
    text = weather.answer().lower()
    assert any(w in text for w in ("оценк", "расписан", "долг", "учёб", "учеб"))
