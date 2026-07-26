"""
reminder_parse.py — извлечение даты и времени из текста сообщения («AI-напоминания»).

Живёт в КОРНЕ репозитория рядом с grading.py, vector_nlu.py и study_hours.py: разбор
нужен и серверу (мессенджер), и десктопу, и правило должно быть одно.

⚠️ ЗДЕСЬ НЕТ И НЕ ДОЛЖНО БЫТЬ LLM — несмотря на название фичи в плане. Причины ровно те
же, по которым запись оценок голосом идёт мимо модели (vector/voice_command.py):

  • «завтра в 15:00» разбирается регулярками надёжнее, чем моделью, и не стоит ни рубля;
  • модель ошибается молча. Напоминание, съехавшее на день, хуже, чем ненайденное:
    человек на него положился;
  • это ещё и приватность — текст личной переписки не покидает наш сервер.

Функция намеренно КОНСЕРВАТИВНА: не уверена — возвращает None, и интерфейс просто не
предлагает напоминание. Ложное предложение раздражает сильнее, чем отсутствие подсказки.
"""
import re
from datetime import datetime, timedelta

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "среда": 2, "среду": 2, "четверг": 3,
    "пятница": 4, "пятницу": 4, "суббота": 5, "субботу": 5, "воскресенье": 6,
}

#Время: «в 15:00», «в 15.00», «в 9 часов», «к 18». Минуты необязательны.
_TIME_RE = re.compile(r"\b(?:в|к|до)\s+(\d{1,2})(?:[:.](\d{2}))?\s*(?:час\w*)?\b")
#Дата числом: «12.05», «12.05.2026», «12 мая».
_DATE_NUM_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b")
_DATE_WORD_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b")


def _with_time(day: datetime, hh, mm) -> datetime:
    if hh is None:
        #Без указанного времени напоминаем утром: «сдать отчёт в пятницу» — это про день,
        #а не про полночь, с которой начинается datetime по умолчанию.
        return day.replace(hour=9, minute=0, second=0, microsecond=0)
    return day.replace(hour=hh, minute=mm or 0, second=0, microsecond=0)


def parse_reminder(text: str, now: datetime) -> dict:
    """Найти в тексте дату/время. Возвращает {'when': datetime, 'matched': str} или None.

    `now` передаётся ЯВНО (а не берётся из системных часов) — так функция чистая и её
    можно тестировать без подмены времени."""
    if not text:
        return None
    low = text.lower()

    hh = mm = None
    tm = _TIME_RE.search(low)
    if tm:
        h = int(tm.group(1))
        m = int(tm.group(2)) if tm.group(2) else 0
        #Отсекаем ложные срабатывания: «в 2024 году», «к 5 баллам» дают невозможное время.
        if 0 <= h <= 23 and 0 <= m <= 59:
            hh, mm = h, m

    #«сегодня» / «завтра» / «послезавтра»
    for word, shift in (("послезавтра", 2), ("завтра", 1), ("сегодня", 0)):
        if word in low:
            return {"when": _with_time(now + timedelta(days=shift), hh, mm),
                    "matched": word}

    #День недели: всегда БЛИЖАЙШИЙ будущий. «в пятницу», сказанное в пятницу вечером,
    #почти наверняка про следующую неделю — но угадывать не будем, берём ровно +7 только
    #если день уже прошёл, а сегодняшний оставляем сегодняшним.
    for word, wd in WEEKDAYS.items():
        if re.search(rf"\b{word}\b", low):
            delta = (wd - now.weekday()) % 7
            return {"when": _with_time(now + timedelta(days=delta), hh, mm), "matched": word}

    #«12 мая»
    dw = _DATE_WORD_RE.search(low)
    if dw:
        day, month = int(dw.group(1)), MONTHS[dw.group(2)]
        return _build_date(now, day, month, None, hh, mm, dw.group(0))

    #«12.05» / «12.05.2026»
    dn = _DATE_NUM_RE.search(low)
    if dn:
        day, month = int(dn.group(1)), int(dn.group(2))
        year = int(dn.group(3)) if dn.group(3) else None
        if year is not None and year < 100:
            year += 2000
        return _build_date(now, day, month, year, hh, mm, dn.group(0))

    #Одно только время без дня — про сегодня, и только если оно ещё не наступило.
    if hh is not None:
        when = _with_time(now, hh, mm)
        if when > now:
            return {"when": when, "matched": tm.group(0)}
    return None


def _build_date(now: datetime, day: int, month: int, year, hh, mm, matched: str):
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    try:
        when = datetime(year or now.year, month, day)
    except ValueError:
        return None            #31 февраля и подобное — не дата, а совпадение цифр
    #Год не указан, а дата уже прошла → имеется в виду следующий год.
    if year is None and when.date() < now.date():
        try:
            when = when.replace(year=now.year + 1)
        except ValueError:
            return None
    return {"when": _with_time(when, hh, mm), "matched": matched}
