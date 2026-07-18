"""
test_student_stable_id.py — id студента НЕИЗМЕНЯЕМ и переживает правку карточки.

Подготовка к переходу оценок на student_id: привязка по id имеет смысл только если сам
id стабилен. Раньше безлогинный студент получал `stud:{фамилия}|{имя}|{группа}`, то есть
id зависел от ФИО — переименование порождало НОВОГО пользователя, а старая строка
оставалась висеть надгробием вместе со всей историей. Тесты закрывают именно это.
"""
from data_store import _server_to_student, _student_id, get_store


def test_existing_id_is_never_recomputed():
    """Присвоенный id возвращается как есть — даже если ФИО и логин изменились."""
    s = {"id": "stud:u:fixed-123", "surname": "Петрова", "name": "Мария",
         "group": "К-102", "login": "newlogin"}
    assert _student_id(s) == "stud:u:fixed-123"


def test_student_without_login_gets_random_id():
    """Безлогинный студент получает случайный id, а НЕ производный от ФИО."""
    s = {"surname": "Иванова", "name": "Мария", "group": "К-101"}
    sid = _student_id(s)
    assert sid.startswith("stud:u:"), "id не должен выводиться из ФИО"
    assert "Иванова" not in sid and "К-101" not in sid
    #и он именно случайный — второй вызов даёт другой id (значит, ФИО ни при чём)
    assert sid != _student_id(dict(s))


def test_login_still_wins_for_new_students():
    """С логином — прежний детерминированный формат (совместимость с сервером/синком)."""
    assert _student_id({"surname": "И", "name": "М", "login": "ivanova"}) == "stud:ivanova"


def test_id_survives_server_to_desktop_form():
    """id обязан доехать до UI-формы: на нём держится сопоставление при сохранении."""
    u = {"id": "stud:u:abc", "surname": "Иванова", "name": "Мария", "group_name": "К-101"}
    assert _server_to_student(u)["id"] == "stud:u:abc"


def test_rename_keeps_same_student_row(fresh_db):
    """Главный сценарий: переименование правит ТУ ЖЕ строку, а не плодит вторую.

    Без стабильного id set_students приняла бы студентку за новую (id пересчитался из
    нового ФИО), а прежнюю запись прикопала надгробием — вместе со связью с оценками."""
    st = get_store()
    st.set_students([{"surname": "Иванова", "name": "Мария", "group": "К-101"}])
    before = st.get_students()
    assert len(before) == 1
    sid = before[0]["id"]

    #правим карточку так же, как это делает диалог админки — поверх старой записи
    card = dict(before[0])
    card["surname"] = "Петрова"
    st.set_students([card])

    after = st.get_students()
    assert len(after) == 1, "переименование не должно создавать второго студента"
    assert after[0]["id"] == sid, "id обязан остаться прежним"
    assert after[0]["surname"] == "Петрова"
