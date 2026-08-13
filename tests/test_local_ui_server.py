"""
test_local_ui_server.py — ПРИВАТНЫЙ локальный сервер интерфейса (desktop/local_ui_server.py).

Это фундамент перехода десктопа на общий Vue-интерфейс, и у него ровно два обещания
пользователю: «никаких окон» и «снаружи не достучаться». Оба легко потерять при
следующей правке («давай на 0.0.0.0, чтобы с телефона зайти»), поэтому закрепляем
тестами, а не комментариями.
"""
import os
import socket
import threading
import urllib.error
import urllib.request

import pytest

from desktop import local_ui_server as L


@pytest.fixture()
def served(tmp_path, monkeypatch):
    """Поднимает сервер на временном каталоге с «собранным Vue»."""
    (tmp_path / "index.html").write_text("<html>SPA</html>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    #Секрет рядом с каталогом — им проверяем защиту от выхода за пределы раздачи.
    (tmp_path.parent / "secret.txt").write_text("TOP-SECRET-DO-NOT-SERVE", encoding="utf-8")

    monkeypatch.setattr(L, "_dist_dir", lambda: str(tmp_path))
    srv = L.LocalUIServer()
    assert srv.start() is True
    yield srv
    srv.stop()


def _get(srv, path, token=None, host=None, cookie=None):
    req = urllib.request.Request(srv.url(path))
    if token:
        req.add_header(L.TOKEN_HEADER, token)
    if cookie:
        req.add_header("Cookie", cookie)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_listens_only_on_loopback(served):
    """Сокет привязан к 127.0.0.1 — из сети до него не дойти В ПРИНЦИПЕ.

    Самая важная проверка файла: она ловит правку «слушаем 0.0.0.0», которую очень
    соблазнительно сделать «чтобы посмотреть с другого устройства»."""
    host, _port = served._httpd.server_address[:2]
    assert host == "127.0.0.1", f"сервер слушает {host} — это выход наружу"
    assert L.is_loopback_only(host)


def test_port_is_ephemeral(served):
    """Порт выдаёт ОС: угадывать нечего и с чужой программой не столкнёмся."""
    assert served.port > 1024


def test_serves_spa_with_token(served):
    code, body = _get(served, "/", token=served.token)
    assert code == 200 and b"SPA" in body


def test_serves_assets_by_cookie(served):
    """За скриптами браузер ходит сам и наш заголовок не подставит — нужна кука."""
    code, body = _get(served, "/assets/app.js",
                      cookie=f"{L.TOKEN_COOKIE}={served.token}")
    assert code == 200 and b"console.log" in body


def test_without_token_denied(served):
    """Сосед по этому же компьютеру без токена не получает НИЧЕГО."""
    assert _get(served, "/")[0] == 403
    assert _get(served, "/assets/app.js")[0] == 403


def test_wrong_token_denied(served):
    #Токен только ASCII: заголовки HTTP кириллицу не переносят (это ограничение
    #протокола, а не продукта) — подделку изображаем строкой того же алфавита.
    assert _get(served, "/", token="wrong-token-value")[0] == 403
    #И «почти правильный» — на случай, если сравнение однажды заменят на startswith.
    assert _get(served, "/", token=served.token[:-1])[0] == 403


def test_foreign_host_header_denied(served):
    """Защита от DNS-rebinding: чужой сайт может слать браузер на 127.0.0.1, но в
    заголовке Host окажется его домен — такие запросы отклоняем до всякой раздачи."""
    assert _get(served, "/", token=served.token, host="evil.example.com")[0] == 421


def test_path_traversal_blocked(served):
    """За пределы каталога раздачи не выйти — в том числе закодированным «..»."""
    for attack in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        code, body = _get(served, attack, token=served.token)
        assert b"TOP-SECRET-DO-NOT-SERVE" not in body, f"утечка файла через {attack}"


def test_spa_fallback_for_vue_routes(served):
    """Маршрутов Vue (/student/journal) на диске нет — их разбирает роутер в браузере."""
    code, body = _get(served, "/student/journal", token=served.token)
    assert code == 200 and b"SPA" in body


def test_token_is_unique_per_launch():
    """Токен не переживает перезапуск: подсмотренный вчера сегодня бесполезен."""
    a, b = L.LocalUIServer(), L.LocalUIServer()
    a.token, b.token = "", ""
    import secrets
    assert secrets.token_urlsafe(32) != secrets.token_urlsafe(32)


def test_runs_in_thread_not_process(served):
    """«Никаких окон» держится на том, что сервер — ПОТОК: процесс мог бы мигнуть
    консолью, поток не может показать окно в принципе."""
    assert isinstance(served._thread, threading.Thread)
    assert served._thread.daemon, "поток обязан быть демоном — иначе программа не закроется"


def test_start_is_idempotent(served):
    port = served.port
    assert served.start() is True
    assert served.port == port, "повторный старт не должен поднимать второй сервер"


def test_start_without_dist_returns_false(monkeypatch):
    """Нет собранного Vue — честное False, а не падение: десктоп продолжит на нативном."""
    monkeypatch.setattr(L, "_dist_dir", lambda: "")
    srv = L.LocalUIServer()
    assert srv.start() is False
    assert not srv.running
