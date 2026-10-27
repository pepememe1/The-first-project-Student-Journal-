"""Мягкий рубильник обслуживания: админ включает из админки и сам остаётся в круге сервера."""
import pytest

from conftest import make_admin
from app import maintenance


@pytest.fixture
def admin(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GRADEBOOK_MAINTENANCE_FILE", str(tmp_path / "maint.json"))
    headers = make_admin(client)
    yield headers
    maintenance.set_state(False, "test")


def test_admin_switches_it_on_and_keeps_only_the_server_circle(client, admin):
    assert client.get("/app/maintenance").json()["on"] is False
    r = client.post("/admin/maintenance", json={"on": True, "message": "Обновляем базу"},
                    headers=admin)
    assert r.status_code == 200 and r.json()["on"] is True
    pub = client.get("/app/maintenance").json()
    assert pub["on"] is True and pub["message"] == "Обновляем базу" and "by" not in pub
    #Круг сервера и сам рубильник — открыты.
    assert client.get("/web/admin/server/metrics", headers=admin).status_code != 503
    assert client.get("/admin/maintenance", headers=admin).status_code == 200
    #Остальная админка ждёт конца работ.
    blocked = client.get("/admin/online", headers=admin)
    assert blocked.status_code == 503 and blocked.headers["x-gb-reason"] == "maintenance"
    #Обратный ход: выключили — всё как было.
    client.post("/admin/maintenance", json={"on": False}, headers=admin)
    assert client.get("/admin/online", headers=admin).status_code != 503


def test_everyone_else_sees_maintenance_but_can_still_reach_the_login(client, admin):
    client.post("/admin/maintenance", json={"on": True}, headers=admin)
    anon = client.get("/web/student/home")
    assert anon.status_code == 503 and anon.json()["maintenance"] is True
    #Вход открыт: без него не войдёт и сам администратор.
    assert client.post("/auth/login", json={"login": "nobody", "password": "x"}).status_code != 503
    assert client.get("/health").status_code == 200


def test_only_an_admin_can_pull_the_switch(client, admin):
    r = client.post("/admin/maintenance", json={"on": True})
    assert r.status_code in (401, 403)
    assert client.get("/app/maintenance").json()["on"] is False
