"""
test_mascot.py — таблица решений эмоции маскота (чистая логика, без GUI/БД).

Проверяем resolveMascotState по приоритетам из mascot_emotion_prompt.md: события
(П1) перекрывают тренд (П2), «удивление» (П3) перекрывает тренд, посещаемость < 70%
перебивает баллы. Плюс маппинг событий и расчёт тренда.
"""
from vector.mascot import (
    resolveMascotState, _grade_event, _trend, _student_key, detect_events,
)


def _data(**kw):
    base = {"average": 0.0, "recent": [], "trend": "flat", "last_grade": None,
            "attendance_pct": None, "exam_soon": False, "retake_scheduled": False,
            "retake_passed": False, "has_data": False}
    base.update(kw)
    return base


#  Приоритет 1 — события и срочные условия
def test_event_grade5_beats_everything():
    st = resolveMascotState(_data(average=2.0, has_data=True), events=["grade_5"])
    assert st == {"emotion": "рад", "pose": "поздрав"}


def test_event_grade2():
    st = resolveMascotState(_data(average=4.8, has_data=True), events=["grade_2"])
    assert st == {"emotion": "груст", "pose": "предупреж"}


def test_event_priority_order_5_over_3():
    #несколько событий разом — побеждает «5» (выше в таблице)
    st = resolveMascotState(_data(has_data=True), events=["grade_3", "grade_5"])
    assert st["emotion"] == "рад" and st["pose"] == "поздрав"


def test_exam_soon():
    st = resolveMascotState(_data(average=4.8, has_data=True, exam_soon=True))
    assert st == {"emotion": "предупреж", "pose": "думает"}


def test_retake_scheduled_and_passed():
    assert resolveMascotState(_data(has_data=True, retake_scheduled=True)) == \
        {"emotion": "груст", "pose": "думает"}
    assert resolveMascotState(_data(has_data=True, retake_passed=True)) == \
        {"emotion": "рад", "pose": "подбадрив"}


#  Приоритет 2 — тренд и посещаемость
def test_high_average():
    st = resolveMascotState(_data(average=4.7, has_data=True, recent=[5, 4, 5]))
    assert st == {"emotion": "рад", "pose": "деф"}


def test_mid_high_trend_up_vs_flat():
    up = resolveMascotState(_data(average=4.0, has_data=True, trend="up"))
    assert up == {"emotion": "рад", "pose": "подбадрив"}
    flat = resolveMascotState(_data(average=4.0, has_data=True, trend="flat"))
    assert flat == {"emotion": "деф", "pose": "деф"}


def test_mid_low_trend():
    up = resolveMascotState(_data(average=3.0, has_data=True, trend="up"))
    assert up == {"emotion": "деф", "pose": "подбадрив"}
    down = resolveMascotState(_data(average=3.0, has_data=True, trend="down"))
    assert down == {"emotion": "предупреж", "pose": "деф"}


def test_low_average():
    st = resolveMascotState(_data(average=2.0, has_data=True, recent=[2, 2, 3]))
    assert st == {"emotion": "груст", "pose": "предупреж"}


def test_attendance_overrides_grades():
    #посещаемость < 70% перебивает даже отличный балл
    st = resolveMascotState(_data(average=4.9, has_data=True, attendance_pct=55.0))
    assert st == {"emotion": "предупреж", "pose": "предупреж"}


def test_no_data_new_student():
    st = resolveMascotState(_data(has_data=False))
    assert st == {"emotion": "удив", "pose": "деф"}


#  Приоритет 3 — резкий скачок (удивление), перекрывает тренд, но не событие
def test_surprise_overrides_trend():
    st = resolveMascotState(_data(average=4.5, has_data=True, last_grade=2,
                                  recent=[5, 5, 5, 2]))
    assert st == {"emotion": "удив", "pose": "думает"}


def test_surprise_not_over_event():
    st = resolveMascotState(_data(average=4.5, has_data=True, last_grade=2),
                            events=["grade_5"])
    assert st["emotion"] == "рад"      # событие важнее удивления


#  Вспомогательное
def test_grade_event_mapping():
    assert _grade_event("5") == "grade_5"
    assert _grade_event("4 (Зачтено)") == "grade_4"
    assert _grade_event("3") == "grade_3"
    assert _grade_event("2") == "grade_2"
    assert _grade_event("Н") == "grade_2"
    assert _grade_event("") == ""


def test_trend_calc():
    assert _trend([2, 2, 4, 5]) == "up"
    assert _trend([5, 5, 2, 2]) == "down"
    assert _trend([4, 4, 4, 4]) == "flat"
    assert _trend([4]) == "flat"


def test_detect_events_first_run_silent(fresh_db):
    """Первый запуск не сыплет событиями: просто запоминает текущее состояние."""
    stud = {"f": "Иванов", "n": "Иван", "g": "К15/1"}
    sig = {"Физика|l1": "5", "Химия|l2": "4"}
    assert detect_events(stud, sig) == []          # первый раз — тихо
    #теперь новая «5» по новому занятию → событие grade_5
    sig2 = dict(sig); sig2["Физика|l3"] = "5"
    assert "grade_5" in detect_events(stud, sig2)


def test_student_key_stable():
    assert _student_key({"f": "Ли", "n": "Ян", "g": "К25"}) == "ли|ян|к25"
