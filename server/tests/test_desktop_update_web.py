"""
test_desktop_update_web.py — эндпоинт манифеста автообновлений десктопа (3.5.6).

Сам .exe и патчи раздаёт уже существующий `/downloads/*`; здесь проверяется только
манифест и то, что его отсутствие — штатное состояние, а не 500.
"""
import json
import os

from app.routers import desktopupdate


def _write_manifest(tmp_path, data):
    d = tmp_path / "updates"
    d.mkdir(exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    return d


def test_no_manifest_is_not_an_error(client, tmp_path, monkeypatch):
    """Сервер без выложенных сборок отвечает «нечего обновлять», а не ошибкой:
    пустой каталог — нормальное состояние до первой выкладки."""
    monkeypatch.setattr(desktopupdate, "DOWNLOADS_DIR", str(tmp_path))
    r = client.get("/desktop/updates")
    assert r.status_code == 200, r.text
    assert r.json() == {"message": "no update available"}


def test_manifest_is_served_as_is(client, tmp_path, monkeypatch):
    man = {"version": "3.5.6",
           "full": {"file": "GradeBookAI-3.5.6.exe", "sha256": "a" * 64, "size": 123},
           "patches": [{"from": "3.5.5", "to": "3.5.6", "file": "3.5.5-3.5.6.patch",
                        "sha256": "b" * 64, "target_sha256": "a" * 64, "size": 12}]}
    _write_manifest(tmp_path, man)
    monkeypatch.setattr(desktopupdate, "DOWNLOADS_DIR", str(tmp_path))

    r = client.get("/desktop/updates")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "3.5.6"
    assert body["patches"][0]["file"] == "3.5.5-3.5.6.patch"
    #Ссылки на файлы ОТНОСИТЕЛЬНЫЕ — абсолютный URL был бы второй копией правды об
    #адресе сервера и разъехался бы при переезде.
    assert "http" not in json.dumps(body)


def test_broken_manifest_does_not_crash_endpoint(client, tmp_path, monkeypatch):
    """Недописанный/побитый файл манифеста не должен ронять сервер пятисоткой."""
    d = tmp_path / "updates"
    d.mkdir(exist_ok=True)
    (d / "manifest.json").write_text("{это не json", encoding="utf-8")
    monkeypatch.setattr(desktopupdate, "DOWNLOADS_DIR", str(tmp_path))

    r = client.get("/desktop/updates")
    assert r.status_code == 200, r.text
    assert r.json() == {"message": "no update available"}


def test_manifest_is_public_no_auth_required(client, tmp_path, monkeypatch):
    """Проверка обновлений идёт ДО входа в аккаунт — эндпоинт обязан быть публичным."""
    _write_manifest(tmp_path, {"version": "3.5.6",
                               "full": {"file": "f.exe", "sha256": "c" * 64, "size": 1},
                               "patches": []})
    monkeypatch.setattr(desktopupdate, "DOWNLOADS_DIR", str(tmp_path))
    r = client.get("/desktop/updates")      #без заголовка Authorization
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "3.5.6"


def test_update_download_refuses_path_traversal(client, tmp_path, monkeypatch):
    """Новый роут /downloads/updates/{fname} обязан держать ту же защиту, что старый.

    Проверяем НА УРОВНЕ ФУНКЦИИ, а не запросом: снаружи `..%2f..%2f.env` до роута вообще
    не доходит (Starlette декодирует %2f ДО роутинга, путь распадается и уезжает в
    SPA-заглушку — проверено на бою). То есть внешний запрос ничего не доказывает про
    саму проверку, а сломать её правкой можно незаметно."""
    from app import main as app_main

    secret = tmp_path / "secret.env"
    secret.write_text("GRADEBOOK_DB_KEY=не-должно-утечь", encoding="utf-8")
    downloads = tmp_path / "downloads"
    (downloads / "updates").mkdir(parents=True)
    monkeypatch.setattr(app_main, "DOWNLOADS_DIR", str(downloads))

    r = app_main.download_update_file("../../secret.env")
    assert getattr(r, "status_code", None) == 404, "выход за пределы downloads запрещён"

    #А обычный файл внутри updates отдаётся как ни в чём не бывало.
    (downloads / "updates" / "ok.patch").write_bytes(b"x")
    assert getattr(app_main.download_update_file("ok.patch"), "status_code", 200) != 404


def test_shared_rules_come_from_root_module():
    """Сервер обязан пользоваться ТЕМ ЖЕ desktop_update.py, что клиент и сборщик —
    иначе имена патчей и сравнение версий разъедутся между сторонами."""
    assert desktopupdate.DU.patch_name("3.5.5", "3.5.6") == "3.5.5-3.5.6.patch"
    assert desktopupdate.DU.MANIFEST_NAME == "manifest.json"
    assert os.path.basename(desktopupdate.DU.__file__) == "desktop_update.py"
