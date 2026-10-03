"""Вырезано из tests/test_schedule_future.py 30.09.2026 вместе с schedule/specialty.py.

Архив, не прогон. Вернуть — перенести archive/schedule/specialty.py в schedule/."""
from schedule.specialty import guess_specialty, specialty_label


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
