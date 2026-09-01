# -*- coding: utf-8 -*-
"""
test_schedule_subgroups.py — 🔥 ПАРА ВТОРОЙ ПОДГРУППЫ НЕ ИМЕЕТ ПРАВА ПРОПАДАТЬ.

━━ ЧЕМ КУПЛЕН (01.09.2026, находка Ярослава на живом расписании) ━━
Портал ВСГУТУ кладёт в ОДНУ ячейку два РАЗНЫХ занятия, если группа делится на подгруппы:

    лаб.Поддержка и тестирование программных модулей- 1 п/г ГЛУШКОВА И.И. а.728-3
    Техн-я разработки и защиты баз- 2 п/г НИКОЛАЕВА Т.В. - а.14-проф1д/кл

GradeBook показывал ТОЛЬКО ПЕРВОЕ — на сайте, в приложении и в виджете. Занятие второй
подгруппы исчезало бесследно: половина группы не видела своей пары вообще и узнавала о
ней, только не придя на неё.

Данные при этом не терялись — `parse_cell` складывал хвост в `Lesson.extra`, и он
доезжал до клиента. Но `extra` не показывал НИКТО: поле существовало как свалка, а не как
занятие. Это наш класс «данные есть, потребителя нет», только с ценой в виде пропущенной
пары.

━━ ЧТО ПРОВЕРЯЕТСЯ ━━
Что из такой ячейки получается ДВА занятия со своими предметом, преподавателем и
аудиторией, и что у каждого проставлена своя подгруппа.
"""
import schedule.parser as P

#Живая ячейка с портала (пятница, первая пара) — из скриншота Ярослава.
TWO_SUBGROUPS = ("лаб.Поддержка и тестирование программных модулей- 1 п/г "
                 "ГЛУШКОВА И.И. а.728-3 Техн-я разработки и защиты баз- 2 п/г "
                 "НИКОЛАЕВА Т.В. - а.14-проф1д/кл")

#Вторая живая ячейка — другой день, другой набор предметов.
TWO_SUBGROUPS_2 = ("аб.Разработка программных модулей- 1 п/г ДАМДИНОВ З.Ш. "
                   "а.14-проф1д/кл Инструмент. средства разработки ПО- 2 п/г "
                   "ЮМАТОВА А.С. - а.15-357-1")


def test_cell_with_two_subgroups_gives_two_lessons():
    """🔥 Главное: занятие второй подгруппы существует, а не пропадает."""
    out = P.parse_cell_all(TWO_SUBGROUPS, pair_no=1, time="09:00-10:35")
    assert len(out) == 2, f"вторая подгруппа потеряна: {[l.subject for l in out]}"

    first, second = out
    assert "Поддержка и тестирование" in first.subject, first.subject
    assert first.teacher == "ГЛУШКОВА И.И.", first.teacher
    assert first.room == "728-3", first.room
    assert first.subgroup == 1, first.subgroup

    assert "разработки и защиты баз" in second.subject, second.subject
    assert second.teacher == "НИКОЛАЕВА Т.В.", second.teacher
    assert "14-проф" in second.room, second.room
    assert second.subgroup == 2, second.subgroup


def test_second_lesson_keeps_time_and_pair_number():
    """Обе подгруппы идут В ОДНО ВРЕМЯ — это одна пара, просто в разных аудиториях.
    Потерять время у второй значило бы показать её в другом месте дня."""
    out = P.parse_cell_all(TWO_SUBGROUPS, pair_no=1, time="09:00-10:35")
    for lesson in out:
        assert lesson.pair_no == 1
        assert lesson.time == "09:00-10:35"


def test_another_real_cell_splits_too():
    """Вторая живая ячейка: тип занятия там написан с опечаткой портала («аб.» вместо
    «лаб.»), и это НЕ повод потерять пару — разбор best-effort."""
    out = P.parse_cell_all(TWO_SUBGROUPS_2, pair_no=2, time="10:45-12:20")
    assert len(out) == 2, f"вторая подгруппа потеряна: {[l.subject for l in out]}"
    assert "Разработка программных модулей" in out[0].subject
    assert out[0].teacher == "ДАМДИНОВ З.Ш."
    assert "Инструмент" in out[1].subject
    assert out[1].teacher == "ЮМАТОВА А.С."


def test_ordinary_cell_still_gives_exactly_one():
    """Обратная сторона: обычная ячейка без подгрупп обязана остаться ОДНИМ занятием.
    Сплит «на всякий случай» размножил бы пары по всему расписанию."""
    out = P.parse_cell_all("лек.Физика ШАГДУРОВА А.И.  а.0310", pair_no=2, time="10:45-12:20")
    assert len(out) == 1
    assert out[0].subject == "Физика"
    assert out[0].subgroup == 0, "у обычной пары подгруппы нет"


def test_empty_cell_gives_nothing():
    """«Окно» остаётся окном — ни одной пары."""
    assert P.parse_cell_all("_", pair_no=1, time="") == []
    assert P.parse_cell_all("", pair_no=1, time="") == []


def test_single_subgroup_cell_keeps_its_number():
    """Бывает и одна подгруппа в ячейке (у второй в это время окно). Пара одна, но
    подгруппу знать надо — иначе студент второй решит, что занятие у него."""
    out = P.parse_cell_all("пр.Матанализ- 1 п/г ИВАНОВ И.И. а.101", pair_no=3, time="")
    assert len(out) == 1
    assert out[0].subgroup == 1
