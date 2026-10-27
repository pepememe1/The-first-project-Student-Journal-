# -*- coding: utf-8 -*-
"""
test_klipy_media.py — гифки Klipy с нашего домена (27.10.2026, требование Влада).

Без VPN CDN Klipy открывается не у всех: гифки в чатах, аватарки и баннеры были пустыми.
Браузер теперь берёт файл у нас (`/media/klipy/<путь>`), сервер скачивает его с CDN один
раз и держит на диске. Здесь держится:
  • это НЕ открытый прокси: хост зашит, путь — по шаблону, мимо шаблона в сеть не ходим;
  • второй показ — с диска, без похода на CDN;
  • CDN недоступен — честный 404 (клиент покажет первый кадр или значок);
  • промахи кэша — под ограничителем;
  • уборка кэша не трогает аватарки и баннеры профилей (их кадр — запасной вид);
  • сохранение гифки на аватарку ЗОВЁТ «про запас» (проверяется вызов, а не поведение).

⚠️ Сеть в тестах закрыта (`conftest`), поэтому CDN подменяется на `_download`.
Обратный ход проверен: вернуть хост из запроса — краснеет «не открытый прокси»; снять
защиту в `sweep` — краснеет уборка; убрать `pin` из сохранения профиля — краснеет вызов.
"""
import pytest

from conftest import make_admin

GIF = b"GIF89a" + b"\x00frame" * 50
PATH = "ii/8ce8357c78ea940b9c2015daf05ce1a5/77/54/Bdsl9Upy.gif"
URL = "https://static.klipy.com/" + PATH


@pytest.fixture
def cdn(monkeypatch, tmp_path):
    """Кэш во временном каталоге, CDN — подменённый: что скачано и сколько раз."""
    from app import config, klipy_media
    monkeypatch.setenv("GRADEBOOK_KLIPY_CACHE_DIR", str(tmp_path / "klipy"))
    monkeypatch.setattr(config, "KLIPY_API_KEY", "test-key")
    calls = []

    def fake(path):
        calls.append(path)
        if "missing" in path:
            raise OSError("404 на CDN")
        return GIF

    monkeypatch.setattr(klipy_media, "_download", fake)
    return calls


def test_path_check_never_lets_another_host_in():
    from app import klipy_media as K
    assert K.path_of_url(URL) == PATH
    for bad in ("https://evil.example/" + PATH, "http://static.klipy.com/" + PATH,
                "https://static.klipy.com:8443/" + PATH, URL + "?x=1",
                "https://x@static.klipy.com/" + PATH, "https://static.klipy.com/ii/a.svg"):
        assert K.path_of_url(bad) == "", bad
    for bad in ("../etc/passwd.gif", "ii/../../x.gif", "/ii/x.gif", "ii//x.gif", "ii/x y.gif",
                "ii/x.gif/", ""):
        assert not K.path_ok(bad), bad


def test_second_view_comes_from_disk(client, cdn):
    r = client.get("/media/klipy/" + PATH)
    assert r.status_code == 200 and r.content == GIF
    assert r.headers["content-type"].startswith("image/gif")
    assert "immutable" in r.headers["cache-control"]
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert client.get("/media/klipy/" + PATH).status_code == 200
    assert cdn == [PATH], "второй показ обязан прийти с диска, а не с CDN"


def test_path_outside_the_template_never_reaches_the_network(client, cdn):
    for bad in ("ii/x.svg", "ii/x%20y.gif", "ii/%2e%2e/%2e%2e/x.gif"):
        assert client.get("/media/klipy/" + bad).status_code == 404, bad
    assert cdn == []


def test_cdn_failure_is_an_honest_404(client, cdn):
    r = client.get("/media/klipy/ii/missing/x.gif")
    assert r.status_code == 404 and r.headers.get("cache-control") == "no-store"


def test_cache_misses_are_rate_limited(client, cdn, monkeypatch):
    from app import klipy_media
    monkeypatch.setattr(klipy_media, "MISSES_PER_WINDOW", 2)
    codes = [client.get(f"/media/klipy/ii/a{i}/x.gif").status_code for i in range(3)]
    assert codes == [200, 200, 429]
    #Попадание в кэш ограничителем не считается.
    assert client.get("/media/klipy/ii/a0/x.gif").status_code == 200


def test_sweep_keeps_profile_gifs(cdn, monkeypatch, tmp_path):
    import os
    import time
    from app import klipy_media as K
    monkeypatch.setenv("GRADEBOOK_KLIPY_CACHE_MB", "16")        #нижний предел
    big = b"x" * (6 * 1024 * 1024)
    old = time.time() - 3600
    for i, name in enumerate(("ii/a/avatar.webp", "ii/b/chat1.gif", "ii/c/chat2.gif",
                              "ii/d/chat3.gif")):
        f = K.local_file(name)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(big)
        os.utime(f, (old + i, old + i))                       #аватарка — самая старая
    removed = K.sweep({"ii/a/avatar.webp"})
    assert removed >= 1
    assert K.cached("ii/a/avatar.webp") is not None, "кадр аватарки вытеснять нельзя"


def test_protected_paths_cover_avatar_still_frame(client):
    from app import klipy_media as K
    from app.db import SessionLocal
    admin = make_admin(client)
    r = client.post("/me/prefs", json={"prefs": {"avatar": URL}}, headers=admin)
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        got = K.protected_paths(db)
    finally:
        db.close()
    stem = PATH[:-4]
    assert {stem + ".webp", stem + ".mp4", PATH} <= got


def test_saving_a_gif_avatar_pins_its_still_frame(client, monkeypatch):
    """Вызов, а не поведение: «про запас», которое никто не зовёт, — обещание без
    вызывающего, наш самый частый дефект."""
    from app import klipy_media
    pinned = []
    monkeypatch.setattr(klipy_media, "pin", lambda url: pinned.append(url))
    admin = make_admin(client)
    r = client.post("/me/prefs", json={"prefs": {"avatar": URL, "profile_banner": URL}},
                   headers=admin)
    assert r.status_code == 200, r.text
    assert pinned.count(URL) == 2
    #Правка другого поля аватарку заново не качает.
    pinned.clear()
    client.post("/me/prefs", json={"prefs": {"bio": "привет"}}, headers=admin)
    assert pinned == []


def test_empty_klipy_key_switches_off_file_downloads_too(client, cdn, monkeypatch):
    """Выключатель Klipy — пустой ключ — гасит и скачивание файлов: на отказ ВСГУТУ по
    п. 5.6.1 наш сервер не должен ходить на CDN вовсе. Уже скачанное отдаётся."""
    from app import config
    assert client.get("/media/klipy/" + PATH).status_code == 200
    monkeypatch.setattr(config, "KLIPY_API_KEY", "")
    assert client.get("/media/klipy/" + PATH).status_code == 200, "скачанное — с диска"
    assert client.get("/media/klipy/ii/new/x.gif").status_code == 404
    assert cdn == [PATH]


def test_a_flood_of_misses_triggers_cleanup_out_of_turn(cdn, monkeypatch):
    """Плановая уборка — раз в 10 минут, но поток промахов успел бы занять диск раньше:
    записано больше пятой части предела — уборка вне очереди (Полковник, 28.10.2026)."""
    from app import klipy_media as K
    from app import shared_state
    monkeypatch.setenv("GRADEBOOK_KLIPY_CACHE_MB", "16")
    shared_state.delete(K._K_SWEEP)              #метка соседнего теста живёт 10 минут
    shared_state.delete(K._K_WRITTEN)
    assert K.sweep_due() is True                 #первая плановая
    assert K.sweep_due() is False                #вторая — рано
    K._count_written(K.cache_limit_bytes() // 5 + 1)
    assert K.sweep_due() is True, "переполнение не ждёт десяти минут"
    assert K.sweep_due() is False


def test_cdn_redirect_to_another_host_is_refused():
    import urllib.request
    from app import klipy_media as K
    h = K._SameHostRedirect()
    req = urllib.request.Request("https://static.klipy.com/ii/a/x.gif")
    assert h.redirect_request(req, None, 302, "Found", {}, "https://evil.example/x.gif") is None
    assert h.redirect_request(req, None, 302, "Found", {}, "http://static.klipy.com/x.gif") is None
    ok = h.redirect_request(req, None, 302, "Found", {}, "https://static.klipy.com/ii/b/x.gif")
    assert ok is not None and ok.full_url.endswith("/ii/b/x.gif")
