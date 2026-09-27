"""
test_schedule_disk_cache.py — снимки расписания переживают перезапуск программы
(быстрый старт, замер 27.09.2026).

━━ ЧТО БЫЛО ━━
Полный снимок колледжа собирается 149 с (89 запросов к порталу). Кэш жил только в
памяти, и после КАЖДОГО запуска программы расписание преподавателя столько же отвечало
«собирается», а студент офлайн после перезапуска не видел своего расписания вовсе.

━━ ЧТО ДЕРЖИТСЯ ━━
- снимок с диска отдаётся СРАЗУ и без портала, но свежий всё равно собирается в фоне;
- старше недели — не поднимается (показать месячное расписание хуже, чем «собирается»);
- без подключённого хранилища (бой) поведение прежнее: устаревший индекс — пустой ответ;
- «Взять с ВСГУТУ» стирает и диск: иначе перезапуск вернул бы выброшенное.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: не звать `_persist` после сборки — краснеет «переживает
перезапуск»; не прогревать в фоне восстановленный снимок — краснеет «свежий собирается»;
убрать предел возраста при подъёме — краснеет «старше недели», при выдаче — «неделя
работы без сети»; не стирать диск в `invalidate_all` — краснеет «Взять с ВСГУТУ».
"""
import threading
import time

import pytest

from app import schedule_web as SW
from schedule.model import GroupSchedule, Snapshot


class _FakePortal:
    """Портал без сети: считает обращения и умеет «лежать»."""
    CATEGORIES = {"college": {"label": "Колледж", "dated": False}}
    DEFAULT_CATEGORY = "college"

    def __init__(self):
        self.calls = []
        self.offline = False
        self.done = threading.Event()

    def _hit(self, what):
        self.calls.append(what)
        if self.offline:
            raise OSError("портал недоступен")

    def build_snapshot(self, category):
        self._hit(("full", category))
        snap = Snapshot(updated_at="свежий", groups={"К74/1": GroupSchedule(name="К74/1")})
        self.done.set()
        return snap

    def category_index_url(self, category):
        return f"idx:{category}"

    def fetch_text(self, url):
        self._hit(("fetch", url))
        return "<html/>"

    def list_category_groups_with_course(self, html, category):
        return [("К74/1", "h1", 3)]

    def category_group_url(self, category, href):
        return f"grp:{href}"

    def parse_group_page(self, html, name, href):
        self.done.set()
        return GroupSchedule(name=name)


class _Store:
    """То, что в программе даёт `desktop/temp_cache.py`: имя → объект."""

    def __init__(self):
        self.files = {}

    def load(self, name):
        return self.files.get(name)

    def save(self, name, obj):
        import json
        self.files[name] = json.loads(json.dumps(obj))    #как настоящий JSON-круг
        return True

    def drop(self, name):
        self.files.pop(name, None)


@pytest.fixture
def portal(monkeypatch):
    fake = _FakePortal()
    monkeypatch.setattr(SW, "_parser", lambda: fake)
    _restart(monkeypatch)
    return fake


def _restart(monkeypatch):
    """Как новый запуск программы: память модуля пуста, хранилище не подключено."""
    monkeypatch.setattr(SW, "_index", {})
    monkeypatch.setattr(SW, "_groups", {})
    monkeypatch.setattr(SW, "_full", {})
    monkeypatch.setattr(SW, "_warming", set())
    monkeypatch.setattr(SW, "_group_refreshing", set())
    monkeypatch.setattr(SW, "_disk", None)


def _age(store, hours):
    """Состарить всё, что лежит на диске, на `hours` часов."""
    shift = hours * 3600
    for d in store.files.values():
        data = d["data"]
        if "ts" in data:
            data["ts"] -= shift
        else:
            for g in data.values():
                g["ts"] -= shift


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def _build_and_persist(portal, store):
    SW.use_disk_cache(store.load, store.save, store.drop)
    SW.full_state("college")
    assert _wait(lambda: "schedule-college-full" in store.files), "снимок не лёг на диск"
    SW.groups_by_course("college")
    SW.get_group("К74/1", "college")
    assert "schedule-college-index" in store.files
    assert "schedule-college-groups" in store.files


def test_full_snapshot_survives_restart_without_the_portal(portal, monkeypatch):
    store = _Store()
    _build_and_persist(portal, store)
    _restart(monkeypatch)
    portal.calls.clear()
    portal.offline = True
    assert SW.use_disk_cache(store.load, store.save, store.drop) == 3
    snap, _building = SW.full_state("college")
    assert snap is not None and "К74/1" in snap.groups, \
        "после перезапуска расписание снова «собирается» — снимок с диска не поднят"
    #Группа студента — сразу, даже когда портал лежит (офлайн-первый запуск).
    assert SW.get_group("К74/1", "college") is not None
    assert SW.groups_by_course_cached("college") == {3: ["К74/1"]}


def test_restored_stale_snapshot_is_served_and_refreshed_in_background(portal, monkeypatch):
    store = _Store()
    _build_and_persist(portal, store)
    _age(store, 5)                    #старше TTL (3 ч), моложе недели
    _restart(monkeypatch)
    portal.calls.clear()
    portal.done.clear()
    SW.use_disk_cache(store.load, store.save, store.drop)
    snap, building = SW.full_state("college")
    assert snap is not None, "устаревший снимок с диска не отдан — человек ждёт сборку"
    assert building, "свежий снимок не собирается — недельное расписание выдано за свежее"
    assert _wait(lambda: ("full", "college") in portal.calls)
    #Курс — сразу из снимка, индекс — в фоне.
    assert SW.groups_by_course_cached("college") == {3: ["К74/1"]}
    assert _wait(lambda: ("fetch", "idx:college") in portal.calls)


def test_snapshot_older_than_a_week_is_not_restored(portal, monkeypatch):
    store = _Store()
    _build_and_persist(portal, store)
    _age(store, 24 * 8)
    _restart(monkeypatch)
    portal.offline = True
    assert SW.use_disk_cache(store.load, store.save, store.drop) == 0
    snap, _building = SW.full_state("college")
    assert snap is None


def test_without_disk_cache_behaviour_is_exactly_as_before(portal, monkeypatch):
    """Бой хранилище не подключает: устаревший индекс там по-прежнему «промах»."""
    SW.groups_by_course("college")
    with SW._lock:
        SW._index["college"]["ts"] -= 5 * 3600
    assert SW.groups_by_course_cached("college") == {}
    assert SW._disk is None


def test_force_refresh_drops_the_disk_copy(portal, monkeypatch):
    store = _Store()
    _build_and_persist(portal, store)
    SW.invalidate_all()
    assert not store.files, "«Взять с ВСГУТУ» оставило снимок на диске — перезапуск вернёт старое"


def test_garbage_on_disk_is_ignored(portal, monkeypatch):
    store = _Store()
    store.files = {"schedule-college-full": {"v": 1, "data": {"ts": time.time(), "snap": 5}},
                   "schedule-college-index": {"v": 99, "data": {}},
                   "schedule-college-groups": "мусор"}
    assert SW.use_disk_cache(store.load, store.save, store.drop) == 0


def test_restored_snapshot_stops_being_served_after_a_week_of_running(portal, monkeypatch):
    """Программа открыта неделю без сети: снимок, поднятый с диска, стареет и в памяти."""
    store = _Store()
    _build_and_persist(portal, store)
    _restart(monkeypatch)
    portal.offline = True
    SW.use_disk_cache(store.load, store.save, store.drop)
    with SW._lock:
        SW._index["college"]["ts"] -= 8 * 24 * 3600
        for g in SW._groups["college"].values():
            g["ts"] -= 8 * 24 * 3600
    assert SW.groups_by_course_cached("college") == {}
    assert SW.get_group("К74/1", "college", cached_only=True) is None
