"""
test_gif.py — GIF-пикер мессенджера (Klipy).

Klipy не дёргаем — тест чужого API не наш тест (см. тот же принцип в test_translate.py).
Проверяется своё:
  • ОТВЕТ KLIPY УРЕЗАЕТСЯ до {id, slug, title, thumb_url, url, width, height} — тяжёлые
    поля (5 форматов × 5 размеров, blur_preview-base64) до клиента не доезжают.
  • БЕЛЫЙ СПИСОК ХОСТА: ссылка в Message.body обязана вести на CDN Klipy — иначе кто
    угодно мог бы прислать «GIF-сообщение» с произвольным URL (SSRF/подмена).
  • Нет ключа/сеть недоступна → пустые списки, а не исключение — пикер не мешает чату.
  • GIF-сообщение не проходит через цензуру/слэш-команды/упоминания (это URL, не текст).
  • «Избранное» в prefs — те же проверки хоста, что при отправке.
"""
import json
import urllib.error

import pytest

from conftest import make_admin
from test_conversation_roles import _group
from test_messenger import _setup

from app import config, gif_service


# ── gif_service.py — юнит-тесты с подменённой сетью ─────────────────────────────────

class _FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _klipy_key(monkeypatch):
    """Ключ настроен (иначе _get() даже не попробует сходить в сеть) — сама сеть
    подменяется отдельно в тестах, которым это нужно."""
    monkeypatch.setattr(config, "KLIPY_API_KEY", "test-key")
    gif_service.invalidate_categories_cache()
    yield
    gif_service.invalidate_categories_cache()


def _fake_urlopen(payload):
    def _fn(req, timeout=8):
        return _FakeResponse(payload)
    return _fn


_SAMPLE_GIF = {
    "id": 42, "slug": "hello-world", "title": "Hello World",
    "type": "gif", "tags": [], "blur_preview": "data:image/jpeg;base64,AAAA",
    "file": {
        "xs": {"webp": {"url": "https://static.klipy.com/x/thumb.webp", "width": 90, "height": 90}},
        "md": {"gif": {"url": "https://static.klipy.com/x/full.gif", "width": 300, "height": 300}},
    },
}


def test_no_key_returns_empty_without_network(monkeypatch):
    monkeypatch.setattr(config, "KLIPY_API_KEY", "")
    assert gif_service.trending() == {"items": [], "has_next": False}
    assert gif_service.categories() == []


def test_trending_simplifies_the_heavy_klipy_object(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen(
        {"result": True, "data": {"data": [_SAMPLE_GIF], "has_next": True}}))
    out = gif_service.trending(per_page=1)
    assert out == {"items": [{
        "id": 42, "slug": "hello-world", "title": "Hello World",
        "thumb_url": "https://static.klipy.com/x/thumb.webp",
        "url": "https://static.klipy.com/x/full.gif",
        "width": 300, "height": 300,
    }], "has_next": True}
    #Тяжёлые поля не просочились наружу.
    assert "blur_preview" not in out["items"][0] and "file" not in out["items"][0]


def test_search_empty_query_is_a_noop_no_network(monkeypatch):
    calls = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: calls.append(1))
    assert gif_service.search("   ") == {"items": [], "has_next": False}
    assert calls == []


def test_network_failure_returns_empty_not_an_exception(monkeypatch):
    def _boom(req, timeout=8):
        raise urllib.error.URLError("нет сети")
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    assert gif_service.trending() == {"items": [], "has_next": False}
    assert gif_service.categories() == []


def test_categories_are_cached_between_calls(monkeypatch):
    calls = []

    def _fn(req, timeout=8):
        calls.append(1)
        return _FakeResponse({"result": True, "data": {"categories": [
            {"category": "hello", "query": "hello", "preview_url": "https://static.klipy.com/p.gif"},
        ]}})
    monkeypatch.setattr("urllib.request.urlopen", _fn)
    first = gif_service.categories()
    second = gif_service.categories()
    assert first == second == [{"label": "hello", "query": "hello",
                                "preview_url": "https://static.klipy.com/p.gif"}]
    assert len(calls) == 1, "второй вызов обязан взять кэш, а не сходить в сеть снова"


def test_allowed_url_checks_the_cdn_host():
    assert gif_service.is_allowed_url("https://static.klipy.com/ii/x/y.gif")
    assert not gif_service.is_allowed_url("https://evil.example.com/x.gif")
    assert not gif_service.is_allowed_url("")
    assert not gif_service.is_allowed_url(None)


def test_mark_shared_failure_does_not_raise(monkeypatch):
    def _boom(req, timeout=8):
        raise urllib.error.URLError("нет сети")
    monkeypatch.setattr("urllib.request.urlopen", _boom)
    gif_service.mark_shared("hello-world")   #не должно бросить исключение


# ── Эндпоинты ────────────────────────────────────────────────────────────────────────

def test_gif_endpoints_require_login(client):
    assert client.get("/web/messenger/gifs/categories").status_code == 401
    assert client.get("/web/messenger/gifs/trending").status_code == 401
    assert client.get("/web/messenger/gifs/search", params={"q": "cat"}).status_code == 401


def test_gif_endpoints_return_service_shape(client, monkeypatch):
    admin = make_admin(client)
    monkeypatch.setattr(gif_service, "categories", lambda: [{"label": "hi", "query": "hi",
                                                             "preview_url": "https://static.klipy.com/p.gif"}])
    monkeypatch.setattr(gif_service, "trending", lambda page=1: {"items": [], "has_next": False})
    monkeypatch.setattr(gif_service, "search", lambda q, page=1: {"items": [], "has_next": False})
    assert client.get("/web/messenger/gifs/categories", headers=admin).json()["categories"][0]["label"] == "hi"
    assert client.get("/web/messenger/gifs/trending", headers=admin).json() == {"items": [], "has_next": False}
    r = client.get("/web/messenger/gifs/search", params={"q": "cat"}, headers=admin)
    assert r.status_code == 200, r.text


# ── Отправка GIF-сообщения ───────────────────────────────────────────────────────────

_GIF_URL = "https://static.klipy.com/ii/hash/aa/bb/pic.gif"


def test_send_gif_creates_a_gif_kind_message(client):
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": _GIF_URL, "kind": "gif", "gif_slug": "pic"}, headers=a)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["body"] == _GIF_URL and out["kind"] == "gif"
    hist = client.get(f"/web/messenger/chats/{conv}/messages", headers=b).json()["messages"]
    assert hist[0]["kind"] == "gif" and hist[0]["body"] == _GIF_URL


def test_send_gif_rejects_urls_outside_klipy_cdn(client):
    """Без этого кто угодно мог бы прислать «GIF-сообщение» с произвольным адресом —
    белый список хоста закрывает это архитектурно, не проверкой на глаз."""
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": "https://evil.example.com/x.gif", "kind": "gif"}, headers=a)
    assert r.status_code == 400


def test_gif_message_body_is_not_censored(client):
    """URL — не текст, набранный человеком: прогонять его через censor() рискованно
    (случайное совпадение с корнем матерного слова испортило бы саму ссылку)."""
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    #Слог "хуй" не встречается в реальных хешах Klipy, но идея теста — что цензура для
    #kind=gif вообще НЕ вызывается, поэтому даже подставной "опасный" фрагмент прошёл бы.
    tricky = "https://static.klipy.com/ii/hui-hash/aa/bb/pic.gif"
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": tricky, "kind": "gif"}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["body"] == tricky


def test_gif_message_ignores_slash_commands_and_mentions(client):
    """kind=gif пропускает разбор /команд и @упоминаний целиком — тело это ссылка,
    а не текст, который мог бы их случайно содержать."""
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": _GIF_URL, "kind": "gif"}, headers=a)
    assert r.status_code == 200, r.text
    assert r.json()["mentions"] == []


def test_send_gif_calls_mark_shared_after_commit(client, monkeypatch):
    calls = []
    monkeypatch.setattr(gif_service, "mark_shared", lambda slug: calls.append(slug))
    _, (a_id, a), (b_id, b), _ = _setup(client)
    conv = client.post(f"/web/messenger/chats/direct/{b_id}", headers=a).json()["conversation_id"]
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": _GIF_URL, "kind": "gif", "gif_slug": "pic"}, headers=a)
    assert r.status_code == 200, r.text
    assert calls == ["pic"]


def test_muted_participant_cannot_send_gif_either(client):
    """kind=gif обязан проходить те же барьеры доступа, что и обычное сообщение —
    отдельная ветка не должна случайно стать лазейкой мимо /mute (только группы/каналы,
    как и сама команда — см. test_conversation_roles.py)."""
    _, (a_id, a), (b_id, b), (c_id, c) = _setup(client)
    conv = _group(client, a, [b_id, c_id])
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": '/mute "@Боб"'}, headers=a)
    assert r.status_code == 200 and r.json()["kind"] == "system"
    r = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": _GIF_URL, "kind": "gif"}, headers=b)
    assert r.status_code == 403


# ── «Избранное» в prefs ──────────────────────────────────────────────────────────────

def test_favorites_keep_only_klipy_cdn_entries(client):
    admin = make_admin(client)
    r = client.post("/me/prefs", json={"gif_favorites": [
        {"id": 1, "slug": "ok", "title": "Ok", "thumb_url": "https://static.klipy.com/t.webp",
         "url": "https://static.klipy.com/f.gif", "width": 100, "height": 100},
        {"id": 2, "slug": "bad", "title": "Bad", "thumb_url": "https://evil.example.com/t.webp",
         "url": "https://evil.example.com/f.gif", "width": 100, "height": 100},
    ]}, headers=admin)
    assert r.status_code == 200, r.text
    favs = r.json()["prefs"]["gif_favorites"]
    assert len(favs) == 1 and favs[0]["slug"] == "ok"


def test_favorites_garbage_input_is_dropped_not_500(client):
    admin = make_admin(client)
    r = client.post("/me/prefs", json={"gif_favorites": "not-a-list"}, headers=admin)
    assert r.status_code == 200, r.text
    assert "gif_favorites" not in r.json()["prefs"]
