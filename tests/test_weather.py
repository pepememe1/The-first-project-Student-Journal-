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


# ── Вопрос про ЧУЖОЙ город (дефект нашёл Влад, 19.08.2026) ────────────────────────────
def test_question_about_another_city_is_not_answered_as_ulan_ude(monkeypatch):
    """🔥 НАСТОЯЩИЙ ДЕФЕКТ: интент срабатывал по слову «погода», а САМ ВОПРОС не читался.

    Живой случай: студент спросил погоду в Саратове — Вектор уверенно ответил, какая
    сейчас в Улан-Удэ. Со стороны это не «я не умею», а неверный ответ с точной цифрой,
    то есть ровно то, чего продукт обещает не делать. Хуже того, ошибка незаметна:
    температура настоящая, просто не того города.

    Обратный ход: вернуть `answer()` без разбора вопроса — тест краснеет."""
    _fake(monkeypatch, {"temp": -30, "feels": -35, "wind": 3, "code": 0})
    out = weather.answer("а какая погода в Саратове?")
    assert "Саратове" in out, "чужой город даже не упомянут — человек не поймёт ответа"
    assert "-30" in out or "−30" in out, "свою-то погоду сказать всё равно надо"


def test_local_question_answers_as_before(monkeypatch):
    """Обратная сторона: обычный вопрос отвечается как раньше, без лишних реплик."""
    _fake(monkeypatch, {"temp": -30, "feels": -35, "wind": 3, "code": 0})
    for q in ("какая погода?", "погода в Улан-Удэ", "погода сегодня", ""):
        out = weather.answer(q)
        assert "переехал" not in out and "теперь в" not in out, f"лишняя реплика на «{q}»"
        assert weather.CITY in out


def test_time_words_are_not_mistaken_for_a_city(monkeypatch):
    """«в понедельник», «в колледже» — не города. Ложное срабатывание здесь читается
    как издевательство («ты что, переехал в понедельник?») и хуже пропуска."""
    _fake(monkeypatch, {"temp": 5, "feels": 4, "wind": 2, "code": 0})
    for q in ("какая погода в понедельник", "погода в колледже", "погода в городе",
              "какая погода в общаге", "погода в среду"):
        assert "теперь в" not in weather.answer(q), f"ложный город в «{q}»"


def test_server_actually_passes_the_question_to_weather():
    """СТРУКТУРНЫЙ сторож против «обещания без вызывающего» — самого частого дефекта в
    этом проекте. Разбор вопроса может быть исправен, а сервер продолжит звать
    `answer()` без аргумента, и всё останется как было при зелёных тестах модуля.

    Обратный ход: заменить в vector.py `_w.answer(msg)` на `_w.answer()` — тест краснеет."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1]
           / "server" / "app" / "routers" / "web" / "vector.py").read_text(encoding="utf-8")
    assert "_w.answer(msg)" in src, "сервер зовёт погоду, не передавая вопрос"
    assert "_w.answer()" not in src, "остался вызов без вопроса"


def test_no_false_city_on_everyday_phrases(monkeypatch):
    """🔥 Ложные срабатывания, найденные Полковником. Первая версия разбора смотрела
    только ПЕРВОЕ слово после «в/во» — и «во второй половине дня», «во втором семестре»,
    «в это воскресенье», «в актовом зале» превращались в чужие города. Ответ «Ты что,
    теперь во второй?» — это ровно тот же неверный ответ с апломбом, ради которого
    правка и делалась, только с другой стороны.

    Обратный ход: убрать требование заглавной буквы / список городов — тест краснеет."""
    _fake(monkeypatch, {"temp": 5, "feels": 4, "wind": 2, "code": 0})
    for q in ("какая погода во второй половине дня", "погода во втором семестре",
              "какая погода в это воскресенье", "погода в актовом зале",
              "погода в 10 классе", "какая погода в течение дня",
              "погода в среду вечером", "какая погода в нашем городе"):
        assert weather.asked_city(q) == "", f"ложный город в «{q}»"


def test_city_is_recognised_in_both_cases(monkeypatch):
    """Настоящий город ловится и с заглавной (как пишет человек и Whisper), и строчными,
    если это известный крупный город."""
    _fake(monkeypatch, {"temp": 5, "feels": 4, "wind": 2, "code": 0})
    assert weather.asked_city("какая погода в Саратове?") == "Саратове"
    assert weather.asked_city("погода в саратове") == "саратове"
    assert weather.asked_city("а в Москве сейчас?") == "Москве"
    assert weather.asked_city("погода в иркутске") == "иркутске"
    #Фраза может НАЧИНАТЬСЯ с предлога, и тогда он написан с заглавной — регулярка
    #была регистрозависимой и такой вопрос пропускала целиком.
    assert weather.asked_city("В Саратове какая погода?") == "Саратове"
