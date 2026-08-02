"""
test_schedule_warm.py — schedule_web.warm() (§3.5.5, живой баг).

Раньше warm() без аргумента грел ТОЛЬКО колледж (оба вызывающих места — старт сервера
и вход преподавателя — звали warm() без category) — первый же заход в «Расписание
преподавателя» для бакалавриата/заочного стартовал холодную сборку (~70с на живых
данных) ровно в момент, когда человек уже смотрит на пустой список. Проверяем БЕЗ
сети: подменяем full_state и смотрим, какие категории он реально получил.
"""
from app import schedule_web
from schedule import parser as P


def test_warm_without_category_warms_all_categories(monkeypatch):
    seen = []
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": seen.append(category))
    schedule_web.warm()
    assert set(seen) == set(P.CATEGORIES)


def test_warm_with_explicit_category_warms_only_that_one(monkeypatch):
    seen = []
    monkeypatch.setattr(schedule_web, "full_state", lambda category="": seen.append(category))
    schedule_web.warm("bakalavriat")
    assert seen == ["bakalavriat"]
