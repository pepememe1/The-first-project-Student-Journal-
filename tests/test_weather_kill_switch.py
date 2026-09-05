"""
Сторож выключателя погоды — п. 5.6.1 политики ВСГУТУ.

«Трансграничная передача персональных данных не осуществляется.» Open-Meteo —
иностранный сервис. Наш довод «уходят координаты города, а не ПДн» верен, но
подтвердить его обязан ответственный ВСГУТУ письменно, и на ответ «нельзя» функцию
надо уметь погасить НАСТРОЙКОЙ, а не правкой кода: доступа к их машине у нас по той же
политике не будет.

⚠️ Проверяется СВОЙСТВО «наружу не пошли», а не «функция вернула None»: последнее
зелено и при сломанном интернете, то есть не отличало бы выключатель от отсутствия сети.
Поэтому сеть подменяется перехватчиком, который считает вызовы.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import weather  # noqa: E402


def _no_cache():
    """Кэш обнуляем: иначе тест мерил бы попадание в кэш, а не поход в сеть."""
    with weather._lock:
        weather._cache["at"], weather._cache["data"] = 0, None


def _count_calls(monkeypatch):
    calls = []

    def _fake_fetch():
        calls.append(1)
        return {"current": {"temperature_2m": -30, "weather_code": 0,
                            "wind_speed_10m": 3}}

    monkeypatch.setattr(weather, "_fetch", _fake_fetch)
    return calls


def test_weather_is_on_by_default(monkeypatch):
    """Умолчание — ВКЛЮЧЕНО.

    Умолчание «выключено» тихо отняло бы работающую функцию у каждого, кто просто
    обновился. Гасим только по названной причине, а не на всякий случай."""
    monkeypatch.delenv("GRADEBOOK_WEATHER", raising=False)
    _no_cache()
    calls = _count_calls(monkeypatch)
    assert weather.current() is not None
    assert calls, "погода не пошла в сеть при настройке по умолчанию"
    assert not weather.disabled()


def test_off_stops_the_outbound_call_entirely(monkeypatch):
    """🔒 Главное свойство: при «off» наружу не уходит НИ ОДНОГО запроса.

    Обратный ход: убери проверку `if disabled()` из `current()` — тест краснеет на
    `assert not calls`, потому что запрос уйдёт."""
    _no_cache()
    calls = _count_calls(monkeypatch)
    for value in ("off", "OFF", "0", "false", "no", "нет"):
        monkeypatch.setenv("GRADEBOOK_WEATHER", value)
        _no_cache()
        assert weather.disabled(), "значение %r не выключило погоду" % value
        assert weather.current() is None
    assert not calls, "при выключенной погоде всё равно ушёл запрос наружу"


def test_a_disabled_weather_never_shows_up_in_the_reply(monkeypatch):
    """Выключенная погода не должна оставлять следа в ответе Вектора.

    Иначе получилась бы худшая форма: обращений наружу нет, а реплика про погоду есть —
    то есть продукт говорит о том, чего не знает."""
    monkeypatch.setenv("GRADEBOOK_WEATHER", "off")
    _no_cache()
    _count_calls(monkeypatch)
    assert weather.note() == ""
    #`answer()` отвечает текстом; он обязан быть честным «не знаю», а не выдумкой.
    reply = weather.answer("какая погода")
    assert "°" not in reply and "градус" not in reply.lower(), (
        "при выключенной погоде продукт всё равно назвал температуру: %r" % reply)


def test_switch_is_read_every_time_not_at_import(monkeypatch):
    """Настройка читается при КАЖДОМ обращении.

    Прочитанная один раз при импорте, она потребовала бы перезапуска службы — и человек,
    выключивший погоду и не увидевший эффекта, решил бы, что выключатель не работает.
    Это наш обычный класс дефекта: «настройка есть, но молча не действует»."""
    _no_cache()
    _count_calls(monkeypatch)
    monkeypatch.setenv("GRADEBOOK_WEATHER", "off")
    assert weather.current() is None
    monkeypatch.setenv("GRADEBOOK_WEATHER", "on")
    _no_cache()
    assert weather.current() is not None, "включение обратно не подействовало без рестарта"
