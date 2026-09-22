"""
test_no_dist_notice.py — запуск БЕЗ собранного сайта объясняет себя (3.6).

Поймано вживую: программа, запущенная из исходников в свежей папке (без
`npm run build`), открывала окно на /login и показывала человеку голое
`{"detail":"Not Found"}`. Ни причины, ни что делать — выглядит как «сломалось».
"""
import importlib


def _reload_app_without_dist(monkeypatch, tmp_path):
    """Поднять приложение так, будто собранного фронтенда рядом нет вовсе."""
    from app import main as app_main
    monkeypatch.setenv("GRADEBOOK_WEB_DIST", str(tmp_path / "нет-такой-папки"))
    reloaded = importlib.reload(app_main)
    assert reloaded.WEB_DIST == "", "для теста нужен именно случай «dist не найден»"
    return reloaded


def test_missing_dist_explains_itself_instead_of_bare_404(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    app_main = _reload_app_without_dist(monkeypatch, tmp_path)
    try:
        with TestClient(app_main.app) as client:
            r = client.get("/login")
            #503, а НЕ 404: сервер исправен, не хватает только собранного интерфейса.
            assert r.status_code == 503, r.status_code
            body = r.text
            assert "npm run build" in body, "человеку нужна команда, а не диагноз"
            assert "не собран" in body.lower()
            #Здоровье сервера при этом отвечает как обычно — иначе непонятно,
            #поднялся он вообще или нет.
            assert client.get("/health").json() == {"status": "ok"}
    finally:
        _restore_app(monkeypatch, app_main)


def _restore_app(monkeypatch, app_main):
    """Возвращаем модуль в обычное состояние, иначе следующие тесты увидят «нет сайта».
    ⚠️ Переменную ВОЗВРАЩАЕМ к значению до теста (её задаёт conftest — заглушка
    собранного сайта), а не удаляем: удалённая, она увела бы модуль в CI в режим «сайта
    нет», и все следующие тесты страниц получили бы 503 (21.09.2026)."""
    monkeypatch.undo()
    importlib.reload(app_main)


def test_unknown_api_address_without_dist_is_still_404(monkeypatch, tmp_path):
    """Без собранного сайта адрес API обязан отвечать тем же JSON-404, что и с ним.
    До 21.09.2026 заглушка «интерфейс не собран» отвечала 503 и HTML ВСЕМ адресам,
    включая опечатанные адреса API: клиент получал страницу там, где ждёт JSON."""
    from fastapi.testclient import TestClient

    app_main = _reload_app_without_dist(monkeypatch, tmp_path)
    try:
        with TestClient(app_main.app) as client:
            r = client.get("/web/student/nothing-here")
            assert r.status_code == 404, r.status_code
            assert "text/html" not in r.headers.get("content-type", "")
            #Адрес СТРАНИЦЫ по-прежнему объясняет, что интерфейс не собран.
            assert client.get("/login").status_code == 503
    finally:
        _restore_app(monkeypatch, app_main)
