"""
test_security_headers.py — базовые заголовки безопасности ставит САМО приложение.

Зачем сторож. На бою `X-Content-Type-Options: nosniff` и `X-Frame-Options: DENY`
проставляет Caddy (server/Caddyfile). Но в ДЕСКТОПНОЙ сборке тот же FastAPI-`app`
поднимается локально на 127.0.0.1 БЕЗ Caddy (desktop/local_api.py) — и там их не
поставит никто, кроме приложения. Поэтому заголовки живут в middleware `app`, а не
только в конфиге прокси. Удалишь middleware — тест обязан покраснеть (обратный ход
проверен: без него оба assert падают).
"""
from fastapi.testclient import TestClient

from app.main import app


def test_local_responses_carry_nosniff_and_frame_deny():
    """Ответ локального приложения (без Caddy) несёт оба заголовка."""
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.headers.get("X-Content-Type-Options") == "nosniff", \
            "без nosniff WebView2 вправе «додумать» тип ответа и исполнить картинку"
        assert r.headers.get("X-Frame-Options") == "DENY", \
            "без X-Frame-Options нашу локальную страницу можно вложить во фрейм"


def test_headers_present_on_error_responses_too():
    """Заголовки идут и на 404 — middleware оборачивает ЛЮБОЙ ответ, не только 200."""
    with TestClient(app) as client:
        r = client.get("/web/admin/overview")   # без токена → 401/403
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
