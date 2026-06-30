"""
test_schedule_future.py — тесты ЗАДЕЛОВ под будущее (specialty + reminders).

Заделы в рантайме не вызываются, но это чистая логика — её тестируем, чтобы при
будущем подключении она уже работала и не «сгнила». Без сети и без GUI.
"""
from datetime import datetime

from schedule.specialty import guess_specialty, specialty_label
from schedule.reminders import (
    current_and_next, weekday_code, DEFAULT_LEAD_MIN,
)
from schedule.model import Lesson


#  specialty
def test_guess_specialty_it():
    subs = ["Компьютерные сети ЭВМ", "Основы алгоритмизации и программирования",
            "Физическая культура"]
    assert guess_specialty(subs) == "it"
    assert specialty_label("it")


def test_guess_specialty_law():
    subs = ["Гражданское право", "Трудовое право", "Административный процесс"]
    assert guess_specialty(subs) == "law"


def test_guess_specialty_power():
    subs = ["Электротехника и электроника", "Основы эксплуатации электрооборудования"]
    assert guess_specialty(subs) == "power"


def test_guess_specialty_none():
    assert guess_specialty([]) is None
    assert guess_specialty(["Физическая культура", "Иностранный язык"]) is None


#  reminders
def _lesson(pair_no, time, subject):
    return Lesson(pair_no=pair_no, time=time, subject=subject, raw=subject)


def test_current_and_next_picks_current_and_upcoming():
    lessons = [
        _lesson(1, "09:00-10:35", "Физика"),
        _lesson(2, "10:45-12:20", "Математика"),
        _lesson(3, "13:00-14:35", "Химия"),
    ]
    #10:00 — идёт 1-я пара, следующая 2-я
    now = datetime(2025, 9, 1, 10, 0)
    info = current_and_next(lessons, now)
    assert info.current.subject == "Физика"
    assert info.upcoming.subject == "Математика"


def test_hurry_window():
    lessons = [_lesson(2, "10:45-12:20", "Математика")]
    #10:38 — до пары 7 минут, попадаем в окно (5,10) → пора торопиться
    now = datetime(2025, 9, 1, 10, 38)
    info = current_and_next(lessons, now, lead_min=DEFAULT_LEAD_MIN)
    assert info.upcoming.subject == "Математика"
    assert info.minutes_to_upcoming == 7
    assert info.hurry is True


def test_no_hurry_when_far():
    lessons = [_lesson(2, "10:45-12:20", "Математика")]
    now = datetime(2025, 9, 1, 9, 0)        # за 1ч45м — рано торопиться
    info = current_and_next(lessons, now)
    assert info.hurry is False
    assert info.current is None


def test_weekday_code():
    assert weekday_code(datetime(2025, 9, 1)) == "Пнд"   # 1 сент 2025 — понедельник
    assert weekday_code(datetime(2025, 9, 7)) == "Вск"   # воскресенье
