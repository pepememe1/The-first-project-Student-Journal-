"""
test_app_update.py — OTA-обновления мобильного приложения (Capgo self-hosted).

Появились после месяца, в течение которого обновления НЕ ДОЕЗЖАЛИ до телефона, а узнали
об этом только по живой жалобе: у эндпоинтов `/app/*` не было ни одного теста. Здесь
проверяется контракт с плагином — то, из-за чего он либо скачает обновление, либо молча
не станет: наличие полей, совпадение хешей с реальным содержимым архива и раздача
отдельных файлов для пофайловой (дельта) докачки.

⚠️ Хеш в манифесте обязан совпадать с SHA-256 РЕАЛЬНОГО файла внутри zip. Плагин
сверяет его и у скачанного файла, и у копии, которую берёт из встроенного в APK
бандла (`DownloadService.downloadManifest`): разойдётся — обновление отвалится, и на
сервере это будет выглядеть как успешная отдача.
"""
import hashlib
import io
import json
import zipfile

from app.routers import appupdate

#Мини-бандл: ровно то, что бывает в собранном фронтенде — корневой index.html и файл
#в подкаталоге (на нём проверяется, что путь со слэшем доезжает до плагина как есть).
FILES = {
    "index.html": b"<!doctype html><title>gb</title>",
    "assets/index-abc123.js": b"console.log('gb')",
    "mascot/happy-idle.webp": b"\x00webp-bytes",
}


def _make_bundle(tmp_path, version="1.260812.0102"):
    """Кладёт zip и latest.json в каталог бандлов и переключает на него роутер."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in FILES.items():
            z.writestr(name, body)
    raw = buf.getvalue()
    (tmp_path / f"{version}.zip").write_bytes(raw)
    (tmp_path / "latest.json").write_text(json.dumps({
        "version": version, "file": f"{version}.zip",
        "checksum": hashlib.sha256(raw).hexdigest(),
    }), encoding="utf-8")
    return version


def test_no_bundle_is_not_an_error(client, tmp_path, monkeypatch):
    """Пустой каталог — штатное состояние до первой выкладки, а не 500."""
    monkeypatch.setattr(appupdate, "OTA_DIR", tmp_path)
    r = client.get("/app/updates")
    assert r.status_code == 200, r.text
    assert r.json() == {"message": "no update available"}


def test_manifest_lists_every_file_with_its_real_hash(client, tmp_path, monkeypatch):
    """Главный контракт дельты: у каждого файла бандла свой SHA-256, и он совпадает с
    содержимым архива. Ошибись здесь — плагин отвергнет всё скачанное."""
    monkeypatch.setattr(appupdate, "OTA_DIR", tmp_path)
    version = _make_bundle(tmp_path)
    body = client.get("/app/updates").json()

    assert body["version"] == version
    assert body["url"].endswith(f"/app/bundles/{version}.zip")   # полная закачка на месте
    got = {e["file_name"]: e for e in body["manifest"]}
    assert set(got) == set(FILES)
    for name, raw in FILES.items():
        assert got[name]["file_hash"] == hashlib.sha256(raw).hexdigest()
        assert got[name]["download_url"].endswith(f"/app/files/{version}/{name}")


def test_manifest_survives_a_rebuild_under_the_same_name(client, tmp_path, monkeypatch):
    """Кэш манифеста привязан ко времени файла, а не только к имени.

    Перевыкладка бандла под тем же именем — обычное дело при повторе релиза. Отдай мы
    тогда прежние хеши, плагин скачал бы НОВЫЕ файлы и забраковал их по СТАРЫМ суммам —
    то есть обновление сломалось бы ровно там, где всё «должно было просто повториться».
    """
    monkeypatch.setattr(appupdate, "OTA_DIR", tmp_path)
    version = _make_bundle(tmp_path)
    first = {e["file_name"]: e["file_hash"] for e in client.get("/app/updates").json()["manifest"]}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("index.html", b"<!doctype html><title>gb v2</title>")
    path = tmp_path / f"{version}.zip"
    path.write_bytes(buf.getvalue())
    import os
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))

    second = {e["file_name"]: e["file_hash"] for e in client.get("/app/updates").json()["manifest"]}
    assert second != first
    assert second["index.html"] == hashlib.sha256(b"<!doctype html><title>gb v2</title>").hexdigest()


def test_single_file_is_served_from_inside_the_zip(client, tmp_path, monkeypatch):
    """Файл отдаётся прямо из архива — без распаковки на диск (место на боевой машине)."""
    monkeypatch.setattr(appupdate, "OTA_DIR", tmp_path)
    version = _make_bundle(tmp_path)
    r = client.get(f"/app/files/{version}/assets/index-abc123.js")
    assert r.status_code == 200, r.text
    assert r.content == FILES["assets/index-abc123.js"]
    assert "javascript" in r.headers["content-type"]


def test_only_the_current_version_is_served(client, tmp_path, monkeypatch):
    """Раздаём файлы ТОЛЬКО текущего бандла: иначе адрес стал бы способом читать любые
    прошлые сборки перебором имён."""
    monkeypatch.setattr(appupdate, "OTA_DIR", tmp_path)
    _make_bundle(tmp_path)
    old = _make_bundle(tmp_path, version="1.260101.0000")   # latest.json теперь на неё
    r = client.get("/app/files/1.260812.0102/index.html")
    assert r.status_code == 404
    assert client.get(f"/app/files/{old}/index.html").status_code == 200


def test_path_traversal_finds_nothing(client, tmp_path, monkeypatch):
    """Обход каталога закрыт по построению: имя сверяется со списком ВНУТРИ архива,
    а такого имени там нет.

    ⚠️ Проверяем ЗАКОДИРОВАННЫМИ «..» (`%2e%2e%2f`). Обычные «../» до сервера просто не
    доходят: и браузер, и http-клиент схлопывают их ещё до отправки, запрос уходит по
    другому адресу и попадает в SPA-заглушку — тест на «404» краснел бы, ничего при этом
    не проверяя. Закодированная последовательность доезжает до обработчика как есть, и
    вот на ней уже видно, что защита работает.
    """
    monkeypatch.setattr(appupdate, "OTA_DIR", tmp_path)
    version = _make_bundle(tmp_path)
    (tmp_path / "secret.txt").write_text("kluchi", encoding="utf-8")
    evils = ("%2e%2e%2fsecret.txt", "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
             "assets%2f%2e%2e%2f%2e%2e%2fsecret.txt")
    for evil in evils:
        r = client.get(f"/app/files/{version}/{evil}")
        assert r.status_code == 404, f"{evil} -> {r.status_code}"
        assert "kluchi" not in r.text


def test_broken_archive_degrades_to_full_download(client, tmp_path, monkeypatch):
    """Манифест не собрался — отвечаем БЕЗ него, но с ссылкой на целый бандл.

    Пофайловая докачка это ускорение, а не единственный путь: остаться из-за неё вовсе
    без обновления хуже, чем скачать лишние мегабайты."""
    monkeypatch.setattr(appupdate, "OTA_DIR", tmp_path)
    version = "1.260812.9999"
    (tmp_path / f"{version}.zip").write_bytes(b"not a zip at all")
    (tmp_path / "latest.json").write_text(json.dumps({
        "version": version, "file": f"{version}.zip", "checksum": "x" * 64,
    }), encoding="utf-8")
    body = client.get("/app/updates").json()
    assert body["version"] == version
    assert "manifest" not in body
    assert body["url"].endswith(f"/app/bundles/{version}.zip")
