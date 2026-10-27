"""Версия приложения в сессиях и обязательное обновление отставших на пять выпусков."""
import desktop_update
from app import client_app

from conftest import make_admin


def test_the_release_list_ends_with_the_current_version():
    #Забытая строка в RELEASES означала бы: новый выпуск вышел, а счёт отставания стоит.
    assert desktop_update.RELEASES[-1] == desktop_update.release_number()
    keys = [desktop_update.parse_version(r) for r in desktop_update.RELEASES]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)


def test_only_apps_far_behind_are_stopped_and_update_paths_stay_open():
    old = "%s/3.0" % "apk"
    assert client_app.update_required(old, "/web/student/home") >= desktop_update.MAX_RELEASES_BEHIND
    assert client_app.update_required("exe/3.0", "/sync/pull") > 0
    #Сайт, свежая сборка, мусор и сборки без заголовка не блокируются никогда.
    assert client_app.update_required("web/3.0", "/web/student/home") == 0
    assert client_app.update_required("apk/" + desktop_update.release_number(), "/web/x") == 0
    assert client_app.update_required("apk/лишнее", "/web/x") == 0
    assert client_app.update_required(None, "/web/x") == 0
    #Без этих адресов обновиться было бы нечем.
    for path in ("/app/updates", "/app/bundles/1.2.3.zip", "/desktop/updates", "/health"):
        assert client_app.update_required(old, path) == 0, path


def test_a_stale_app_gets_426_with_a_machine_readable_reason(client):
    r = client.get("/web/student/home", headers={"X-Gb-App": "apk/3.0+123"})
    assert r.status_code == 426 and r.headers.get("x-gb-reason") == "update_required"
    assert r.json()["update_required"] is True
    #Обратный ход: та же просьба от свежей сборки до проверки не доходит.
    fresh = client.get("/health", headers={"X-Gb-App": "apk/3.0"})
    assert fresh.status_code == 200


def test_admin_sees_which_app_and_release_each_session_uses(client):
    admin = make_admin(client)
    tag = "exe/" + desktop_update.release_number() + "+42"
    r = client.post("/auth/login", json={"login": "admin", "password": "adminpass1"},
                    headers={"X-Gb-App": tag})
    assert r.status_code == 200, r.text
    rows = client.get("/admin/sessions", headers=admin).json()["sessions"]
    apps = {s["app"] for s in rows}
    assert "exe " + desktop_update.release_number() in apps, apps
