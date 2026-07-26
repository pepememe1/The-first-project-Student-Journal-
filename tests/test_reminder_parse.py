"""
test_reminder_parse.py — разбор даты/времени из сообщения («AI-напоминания», §D19).

Разбор ДЕТЕРМИНИРОВАННЫЙ, без LLM. Тесты держат две вещи одинаково крепко: что нужное
находится и что лишнее НЕ находится. Ложное напоминание раздражает сильнее отсутствующего,
а съехавшее на день — хуже обоих, потому что на него уже положились.
"""
from datetime import datetime

from reminder_parse import parse_reminder

#Среда, 15 июля 2026, 10:00 — фиксированная «сейчас» для всех тестов.
NOW = datetime(2026, 7, 15, 10, 0)


def when(text):
    r = parse_reminder(text, NOW)
    return r["when"] if r else None


def test_tomorrow_with_time():
    assert when("Сдать отчёт завтра в 15:00") == datetime(2026, 7, 16, 15, 0)


def test_today_and_day_after_tomorrow():
    assert when("встречаемся сегодня в 18:30") == datetime(2026, 7, 15, 18, 30)
    assert when("послезавтра в 9") == datetime(2026, 7, 17, 9, 0)


def test_day_without_time_defaults_to_morning():
    """«в пятницу» — это про день, а не про полночь: напоминаем утром."""
    assert when("защита проекта в пятницу") == datetime(2026, 7, 17, 9, 0)


def test_weekday_picks_nearest_future():
    #Среда → «во вторник» это следующая неделя (21-е), а не вчерашний день.
    assert when("зачёт во вторник в 12:00") == datetime(2026, 7, 21, 12, 0)


def test_numeric_and_word_dates():
    assert when("экзамен 20.07 в 14:00") == datetime(2026, 7, 20, 14, 0)
    assert when("экзамен 20 июля в 14:00") == datetime(2026, 7, 20, 14, 0)
    assert when("сессия 05.09.2026") == datetime(2026, 9, 5, 9, 0)


def test_past_date_without_year_rolls_to_next_year():
    """«10 января» в июле — это январь СЛЕДУЮЩЕГО года, а не прошедший."""
    assert when("пересдача 10 января") == datetime(2027, 1, 10, 9, 0)


def test_bare_time_only_counts_if_still_ahead():
    assert when("созвон в 17:00") == datetime(2026, 7, 15, 17, 0)
    #08:00 уже прошло — молча переносить на завтра нельзя, это домысел.
    assert when("созвон в 8:00") is None


def test_no_date_returns_none():
    for text in ("привет, как дела?", "скинь конспект по математике", ""):
        assert parse_reminder(text, NOW) is None, text


def test_impossible_values_are_not_dates():
    """Совпадение цифр — ещё не дата. Лучше не предложить, чем предложить чушь."""
    assert when("билет стоит 31.02 рубля") is None
    assert when("это было в 2024 году") is None


def test_matched_fragment_is_reported():
    """Интерфейс подсвечивает найденный кусок — значит, он должен возвращаться."""
    r = parse_reminder("сдать работу завтра в 15:00", NOW)
    assert r and r["matched"] == "завтра"
