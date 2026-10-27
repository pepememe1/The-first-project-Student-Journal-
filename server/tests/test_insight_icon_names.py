"""
test_insight_icon_names.py — значок карточки подсказок называется именем из общего словаря.

Интерфейс рисует значок карточки по `icon_name` из `web/src/config/icons.js`; имени,
которого там нет, соответствует запасной знак вопроса. Поэтому имена сверяются с тем же
файлом, который читает сборка сайта, а не со своей копией списка. Эмодзи в `icon` сервер
отдаёт и дальше: его рисуют сборки до 27.10.2026.
"""
import os
import re

from conftest import make_admin
from app.routers.web import student as student_router

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICONS_JS = os.path.join(ROOT, "web", "src", "config", "icons.js")
GROUP = "ИС-21"


def _icon_names():
    text = open(ICONS_JS, encoding="utf-8").read()
    body = text.split("export const ICONS = Object.freeze({", 1)[1].split("})", 1)[0]
    return set(re.findall(r"^\s*(\w+):", body, re.M))


def _student(client, admin):
    r = client.post("/web/admin/groups", json={"name": GROUP, "subjects": ["Математика"]},
                    headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/web/admin/students", json={
        "login": "petrova", "surname": "Петрова", "name": "Анна", "group": GROUP,
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text
    tok = client.post("/auth/login", json={"login": "petrova", "password": "studpass1"})
    assert tok.status_code == 200, tok.text
    return {"Authorization": f"Bearer {tok.json()['access_token']}", "X-Client": "web"}


def test_every_card_icon_name_exists_in_the_web_icon_dictionary():
    known = _icon_names()
    assert "ok" in known and "warn" in known, "разбор icons.js сломался"
    missing = set(student_router._CARD_ICON_NAMES.values()) - known
    assert not missing, f"нет в web/src/config/icons.js: {sorted(missing)}"


def test_student_insights_carry_icon_name_next_to_the_old_emoji(client):
    admin = make_admin(client)
    stud = _student(client, admin)
    cards = client.get("/web/student/insights", headers=stud).json()["cards"]
    assert cards, "у студента без оценок должна быть хотя бы карточка «всё в порядке»"
    known = _icon_names()
    for c in cards:
        assert c.get("icon"), c
        assert c.get("icon_name") in known, c
