"""
test_media_cache.py — кэш картинок мессенджера в %TEMP% (17.10.2026, `desktop/media_cache.py`).

Держится:
- картинка лежит ЗАШИФРОВАННОЙ: ни байтов картинки, ни адреса в файле и в его имени;
- файл, переложенный под чужое имя, не читается (подмена одной картинки другой);
- срок — с последнего показа, как «хранить медиа» у Telegram: показ продлевает,
  забытое уходит; сверх потолка уходят самые давние;
- одну картинку грузит один поток, неудачная загрузка доходит до вызывающего;
- локальный сервер отдаёт гифку и аватарку из кэша (вторая загрузка не ходит в сеть),
  отвергает чужие хосты и запросы со сторонних сайтов, размер и очистку — только
  вошедшему; ссылок на аватарки сам не выдаёт.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: писать без шифрования — краснеет «не видно»; убрать
`os.utime` в `get` — краснеет «показ продлевает»; убрать перехват `/media/avatar` в
`install_media_cache` — краснеет раздача аватарки.
"""
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

from desktop import media_cache

GIF = b"GIF89a" + b"\x00gradebook-gif" * 40
URL = "https://static.klipy.com/ii/1a2b/3c4d/secret-cat.gif"


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(media_cache, "cache_dir", lambda: str(tmp_path))
    return tmp_path


def _files(folder):
    return sorted(p for p in os.listdir(folder) if p.endswith(".bin"))


def test_roundtrip(cache_dir):
    assert media_cache.put("gif", URL, "image/gif", GIF)
    assert media_cache.get("gif", URL) == ("image/gif", GIF)
    assert media_cache.get("avatar", URL) is None          #вид — часть ключа


def test_picture_and_address_are_not_readable_on_disk(cache_dir):
    media_cache.put("gif", URL, "image/gif", GIF)
    [name] = _files(cache_dir)
    blob = (cache_dir / name).read_bytes()
    assert b"gradebook-gif" not in blob and b"GIF89a" not in blob
    assert "secret-cat" not in name and b"secret-cat" not in blob


def test_file_moved_under_another_name_is_not_accepted(cache_dir):
    other = "https://static.klipy.com/ii/other.gif"
    media_cache.put("gif", URL, "image/gif", GIF)
    media_cache.put("gif", other, "image/gif", b"GIF89a-other")
    a, b = (cache_dir / n for n in _files(cache_dir))
    data_a = a.read_bytes()
    a.write_bytes(b.read_bytes())
    b.write_bytes(data_a)
    assert media_cache.get("gif", URL) is None
    assert media_cache.get("gif", other) is None


def test_only_pictures_and_only_within_the_limit(cache_dir):
    assert not media_cache.put("gif", URL, "text/html", b"<script>")
    assert not media_cache.put("gif", URL, "image/svg+xml", b"<svg/>")
    big = b"x" * (media_cache.MAX_ITEM_BYTES["avatar"] + 1)
    assert not media_cache.put("avatar", URL, "image/jpeg", big)
    assert _files(cache_dir) == []


def test_showing_extends_the_term_and_forgotten_ones_go(cache_dir):
    now = time.time()
    seen = "https://static.klipy.com/seen.gif"
    forgotten = "https://static.klipy.com/forgotten.gif"
    media_cache.put("gif", seen, "image/gif", GIF)
    media_cache.put("gif", forgotten, "image/gif", GIF)
    old = now - 15 * 86400
    for name in _files(cache_dir):
        os.utime(cache_dir / name, (old, old))
    assert media_cache.get("gif", seen) is not None        #показ продлевает срок
    out = media_cache.sweep(now=now)
    assert out["removed"] == 1
    assert media_cache.get("gif", seen) is not None
    assert media_cache.get("gif", forgotten) is None


def test_avatars_live_longer_than_gifs(cache_dir):
    now = time.time()
    media_cache.put("avatar", URL, "image/jpeg", b"\xff\xd8jpeg")
    media_cache.put("gif", URL, "image/gif", GIF)
    old = now - 20 * 86400
    for name in _files(cache_dir):
        os.utime(cache_dir / name, (old, old))
    media_cache.sweep(now=now)
    assert [n.split("-")[0] for n in _files(cache_dir)] == ["avatar"]


def test_over_the_ceiling_the_oldest_go_first(cache_dir, monkeypatch):
    monkeypatch.setattr(media_cache, "MAX_TOTAL_BYTES", 3 * 1024)
    now = time.time()
    for i in range(5):
        url = f"https://static.klipy.com/{i}.gif"
        media_cache.put("gif", url, "image/gif", b"G" * 1000)
        name = media_cache._name("gif", url)
        os.utime(cache_dir / name, (now - 100 + i, now - 100 + i))
    out = media_cache.sweep(now=now)
    assert out["bytes"] <= 3 * 1024
    assert media_cache.get("gif", "https://static.klipy.com/0.gif") is None
    assert media_cache.get("gif", "https://static.klipy.com/4.gif") is not None


def test_purge_and_stats(cache_dir):
    media_cache.put("gif", URL, "image/gif", GIF)
    media_cache.put("avatar", URL, "image/jpeg", b"\xff\xd8jpeg")
    st = media_cache.stats()
    assert st["files"] == 2 and st["bytes"] > 0 and st["by_kind"]["avatar"] > 0
    assert media_cache.purge() == 2
    assert media_cache.stats()["files"] == 0


def test_one_download_for_many_requests_and_errors_reach_the_caller(cache_dir):
    calls = []
    gate = threading.Event()

    def slow():
        calls.append(1)
        gate.wait(2)
        return "image/gif", GIF

    results = []
    threads = [threading.Thread(target=lambda: results.append(
        media_cache.fetch_through("gif", URL, slow))) for _ in range(5)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    gate.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1 and results == [("image/gif", GIF)] * 5

    def broken():
        raise RuntimeError("сети нет")

    with pytest.raises(RuntimeError):
        media_cache.fetch_through("gif", "https://static.klipy.com/none.gif", broken)


# ── Живой локальный сервер ───────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def api():
    from desktop import local_api
    tmp_db = os.path.join(tempfile.mkdtemp(), "local_app_media.db").replace("\\", "/")
    os.environ["GRADEBOOK_DB_URL"] = f"sqlite:///{tmp_db}"
    srv = local_api.LocalAPI()
    if not srv.start():
        pytest.skip(f"серверный пакет недоступен в этом окружении: {srv.error}")
    yield srv
    srv.stop()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, "", b""


#Та же гифка с боевого сервера — так её теперь берёт кэш программы.
MIRROR = "https://prod.invalid/media/klipy/" + URL.split("static.klipy.com/", 1)[1]


@pytest.fixture
def net(monkeypatch, cache_dir):
    """Подменённая сеть: что «скачано» и сколько раз."""
    from desktop import local_api
    calls = []

    def fake(url, limit):
        calls.append(url)
        if "missing" in url:
            raise local_api._MediaMissing()
        if "/media/avatar" in url:
            return "image/jpeg", b"\xff\xd8avatar-bytes"
        return "image/gif", GIF

    monkeypatch.setattr(local_api, "_download_image", fake)
    monkeypatch.setattr(local_api, "_media_base", lambda: "https://prod.invalid")
    return calls


def test_gif_is_served_from_cache_the_second_time(api, net):
    u = api.url("/desk/media?u=" + urllib.parse.quote(URL, safe=""))
    assert _get(u)[:2] == (200, "image/gif")
    status, _, body = _get(u)
    assert status == 200 and body == GIF
    #27.10.2026: файл берётся с НАШЕГО сервера (`/media/klipy/…`) — без VPN CDN Klipy
    #открывается не у всех. И только один раз: вторая гифка — из кэша.
    assert net == [MIRROR], "вторая гифка обязана прийти из кэша, а не из сети"


def test_gif_falls_back_to_the_cdn_when_our_server_has_none(api, net, monkeypatch):
    """Сервер гифку не отдал (Klipy недоступен и ему) — пробуем CDN напрямую: на этой
    машине он может быть открыт. Обратный ход: убрать запасной путь — краснеет."""
    from desktop import local_api
    real = local_api._download_image

    def mirror_down(url, limit):
        if url.startswith("https://prod.invalid/"):
            net.append(url)
            raise local_api._MediaMissing()
        return real(url, limit)

    monkeypatch.setattr(local_api, "_download_image", mirror_down)
    u = api.url("/desk/media?u=" + urllib.parse.quote(URL, safe=""))
    assert _get(u)[:2] == (200, "image/gif")
    assert net == [MIRROR, URL]


def test_only_klipy_cdn_over_https(api, net):
    for bad in ("https://evil.example/cat.gif", "http://static.klipy.com/cat.gif",
                "https://static.klipy.com:8443/cat.gif", "https://x@static.klipy.com/cat.gif"):
        u = api.url("/desk/media?u=" + urllib.parse.quote(bad, safe=""))
        assert _get(u)[0] == 400, bad
    assert net == []


def test_missing_picture_is_404(api, net):
    u = api.url("/desk/media?u=" + urllib.parse.quote(URL + "?missing=1", safe=""))
    assert _get(u)[0] == 404


def test_foreign_site_cannot_probe_the_cache(api, net):
    u = api.url("/desk/media?u=" + urllib.parse.quote(URL, safe=""))
    assert _get(u, {"Sec-Fetch-Site": "cross-site"})[0] == 403


def test_avatar_link_goes_to_prod_once(api, net):
    q = "k=u&i=stud%3Abob&v=0123456789abcdef&s=signature"
    status, mime, body = _get(api.url("/media/avatar?" + q))
    assert (status, mime, body) == (200, "image/jpeg", b"\xff\xd8avatar-bytes")
    _get(api.url("/media/avatar?" + q))
    assert net == ["https://prod.invalid/media/avatar?" + q]


def test_size_and_clear_need_a_signed_in_person(api, net):
    assert _get(api.url("/desk/media/stats"))[0] == 401
    req = urllib.request.Request(api.url("/desk/media/clear"), data=b"", method="POST")
    try:
        code = urllib.request.urlopen(req, timeout=10).status
    except urllib.error.HTTPError as e:
        code = e.code
    assert code == 401


def test_local_server_issues_no_avatar_links(api):
    from app import media_refs
    assert media_refs.ENABLED is False
