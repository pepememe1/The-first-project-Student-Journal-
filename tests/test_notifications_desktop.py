"""
test_notifications_desktop.py — вкладка «Уведомления» на десктопе.

Уведомления порождает сервер, поэтому читаются они по HTTP, а не через синк. Отсюда
главное, что здесь защищается:

  • обрыв связи НЕ выдаётся за «уведомлений нет» — уже загруженные письма остаются на
    экране, а пользователь видит honest-статус. Пустой список при недоступном сервере
    означал бы, что студент спокойно пропустит уведомление о новой оценке;
  • тексты берутся с сервера как есть и НЕ сочиняются клиентом (иначе десктоп, сайт и
    телефон разъедутся в формулировках);
  • у писем без текста (созданных до появления полей title/body) заголовок всё равно
    осмысленный, а не пустая строка.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def view(qapp, monkeypatch):
    """Вкладка без сети: подменяем клиента, чтобы тест не ходил на сервер."""
    import notifications_view as nv
    monkeypatch.setattr(nv, "_client", lambda: None)
    v = nv.NotificationsView()
    v._workers.clear()          #фоновая загрузка в тесте не нужна
    return v


def letters():
    """Свежие письма на КАЖДЫЙ тест.

    Обязательно функция, а не общий список: вкладка помечает письмо прочитанным прямо
    в переданных словарях, и общий список протекал бы из теста в тест — «непрочитанное»
    во втором тесте оказывалось бы уже прочитанным из первого."""
    return [
        {"id": "e1", "kind": "grade", "title": "Отличная оценка!",
         "body": "Вам поставили 5 по предмету «Математика». Так держать!",
         "created_at": "2026-07-20T10:00:00", "read_at": ""},
        {"id": "e2", "kind": "schedule_changed", "title": "Расписание изменилось",
         "body": "Эй! У тебя поменялось расписание группы ИС-21.",
         "created_at": "2026-07-19T09:00:00", "read_at": "2026-07-19T12:00:00"},
    ]


def test_letters_are_listed_with_server_text(view):
    view._on_loaded({"items": letters(), "unread": 1})
    assert view._list.count() == 2
    #Текст письма именно серверный — клиент его не переписывает.
    view._open(0)
    assert "Так держать" in view._text.toPlainText()


def test_unread_letters_are_bold(view):
    view._on_loaded({"items": letters(), "unread": 1})
    assert view._list.item(0).font().bold() is True, "непрочитанное — жирным"
    assert view._list.item(1).font().bold() is False, "прочитанное — обычным"


def test_opening_letter_marks_it_read(view):
    view._on_loaded({"items": letters(), "unread": 1})
    view._open(0)
    assert view._items[0]["read_at"], "открытое письмо становится прочитанным"
    assert view._list.item(0).font().bold() is False


def test_network_failure_keeps_previous_letters(view):
    """Ключевая гарантия: обрыв связи не превращается в «уведомлений нет»."""
    view._on_loaded({"items": letters(), "unread": 1})
    view._on_failed("connection refused")
    assert view._list.count() == 2, "загруженные письма должны остаться на экране"
    assert "связ" in view._status.text().lower(), "статус обязан сообщить об обрыве"


def test_letter_without_text_still_has_title(view):
    """Письма, созданные до появления полей title/body, не должны выглядеть пустыми."""
    view._on_loaded({"items": [{"id": "old", "kind": "grade", "title": "", "body": "",
                                "created_at": "2026-01-01T00:00:00", "read_at": ""}],
                     "unread": 1})
    assert "Новая оценка" in view._list.item(0).text()
    view._open(0)
    assert view._text.toPlainText().strip(), "тело письма не должно быть пустым"


def test_mark_all_clears_unread_marks(view):
    view._on_loaded({"items": letters(), "unread": 1})
    view._mark_all()
    assert all(i["read_at"] for i in view._items)
    assert view._list.item(0).font().bold() is False
