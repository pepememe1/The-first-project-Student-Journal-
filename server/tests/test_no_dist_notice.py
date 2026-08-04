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
        #Возвращаем модуль в обычное состояние, иначе следующие тесты увидят «нет сайта».
        monkeypatch.delenv("GRADEBOOK_WEB_DIST", raising=False)
        importlib.reload(app_main)
