"""
appupdate.py — OTA-обновления мобильного приложения (Capgo self-hosted).

Отдаёт манифест последнего веб-бандла и сами zip-бандлы. Приложение (autoUpdate)
на старте дёргает /app/updates и, если версия новее текущей, качает бандл с
/app/bundles/<file> и подменяет веб-часть БЕЗ переустановки APK.

Бандлы и манифест latest.json лежат в каталоге GRADEBOOK_OTA_DIR (по умолчанию
server/ota_bundles/). Формат latest.json:
    {"version": "1.0.1", "file": "1.0.1.zip", "checksum": "<sha256-hex>"}
URL бандла подставляется от адреса текущего запроса — работает и на проде, и локально.

━━ ПОФАЙЛОВОЕ (ДЕЛЬТА) ОБНОВЛЕНИЕ, 12.08.2026 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Живая история: обновления не доезжали до телефона МЕСЯЦ. Журнал на устройстве показал
`finish_download_fail` и `Software caused connection abort` — закачка обрывалась, не
дойдя до конца. Причина оказалась не в коде, а в весе: бандл тянул 8.7 МБ, из которых
7 МБ — картинки маскота, не менявшиеся месяцами. Пережатие спрайтов в WebP убрало почти
четыре мегабайта, но природа осталась: КАЖДОЕ обновление качало интерфейс целиком.

Плагин умеет иначе: если в ответе `/app/updates` есть поле `manifest` — список файлов с
их SHA-256 и ссылкой на каждый, — он берёт файл ИЗ ВСТРОЕННОГО В APK бандла или из
своего кэша, когда хеш совпадает, и качает по сети только то, чего у него нет
(`DownloadService.downloadManifest`). Обычная правка меняет один js-файл, то есть вместо
пяти мегабайт по сети идут сотни килобайт — обрываться там нечему.

Хеши и раздачу берём ПРЯМО ИЗ ZIP, а не из распакованной копии рядом: на боевой машине
диск занят на три четверти, и держать каждый бандл в двух видах — верный способ однажды
упереться в место. Посчитанный манифест кэшируется файлом `<версия>.manifest.json` рядом
с архивом: считать SHA-256 семидесяти файлов на каждый запрос телефона незачем.

⚠️ Полная закачка НИКУДА НЕ ДЕЛАСЬ: `url` с целым zip остаётся в ответе всегда. Манифест
для плагина — это ускорение, а не замена; старые сборки приложения поля просто не видят
и работают как раньше.
"""
import hashlib
import json
import os
import zipfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

router = APIRouter(prefix="/app", tags=["app-update"])

_SERVER_DIR = Path(__file__).resolve().parents[2]   # .../server
OTA_DIR = Path(os.environ.get("GRADEBOOK_OTA_DIR", _SERVER_DIR / "ota_bundles"))

#Расширение → тип содержимого. Список короткий намеренно: это ровно то, из чего состоит
#собранный фронтенд. Неизвестное отдаём как поток байтов — телефон файл всё равно только
#сохраняет, а не показывает, и угадывать тип за него незачем.
_MIME = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
    ".woff2": "font/woff2", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8",
}


def _manifest():
    m = OTA_DIR / "latest.json"
    if not m.is_file():
        return None
    try:
        # utf-8-sig: терпимо к BOM (PowerShell Set-Content -Encoding utf8 пишет с BOM).
        return json.loads(m.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _bundle_path(name: str) -> Path | None:
    """Путь к zip-бандлу по имени файла. None — имя подозрительное или файла нет.

    Единая проверка для всех трёх мест, где имя приходит СНАРУЖИ (раздача архива,
    манифест, пофайловая раздача): только *.zip и только внутри OTA_DIR. Слэш и «..»
    в имени отвергаем до обращения к диску — дешевле и надёжнее, чем разбираться с
    результатом уже собранного пути.
    """
    if not name.endswith(".zip") or "/" in name or "\\" in name or ".." in name:
        return None
    p = (OTA_DIR / name).resolve()
    if not str(p).startswith(str(OTA_DIR.resolve())) or not p.is_file():
        return None
    return p


def _file_manifest(zip_path: Path, version: str, base: str) -> list | None:
    """Список файлов бандла с SHA-256 — для пофайловой докачки (см. шапку файла).

    Считается ОДИН раз и кладётся рядом с архивом (`<версия>.manifest.json`): SHA-256
    семидесяти файлов — это чтение всего бандла целиком, а телефоны дёргают /app/updates
    при каждом запуске. Кэш привязан к времени изменения архива: перевыложили бандл под
    тем же именем — манифест пересчитается, а не отдаст хеши от прежнего содержимого.
    """
    cache = zip_path.with_suffix(".manifest.json")
    try:
        stamp = int(zip_path.stat().st_mtime)
    except OSError:
        return None
    if cache.is_file():
        try:
            box = json.loads(cache.read_text(encoding="utf-8"))
            if box.get("stamp") == stamp and isinstance(box.get("files"), list):
                return [{"file_name": f["n"], "file_hash": f["h"],
                         "download_url": f"{base}/app/files/{version}/{f['n']}"}
                        for f in box["files"]]
        except (OSError, ValueError, KeyError, TypeError):
            pass                      # битый кэш — просто пересчитаем

    files = []
    try:
        with zipfile.ZipFile(zip_path) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                digest = hashlib.sha256()
                with z.open(info) as fh:
                    for chunk in iter(lambda: fh.read(1024 * 256), b""):
                        digest.update(chunk)
                files.append({"n": info.filename, "h": digest.hexdigest()})
    except (OSError, zipfile.BadZipFile):
        return None
    try:
        cache.write_text(json.dumps({"stamp": stamp, "files": files}), encoding="utf-8")
    except OSError:
        pass                          # не записался кэш — посчитаем в следующий раз
    return [{"file_name": f["n"], "file_hash": f["h"],
             "download_url": f"{base}/app/files/{version}/{f['n']}"} for f in files]


@router.api_route("/updates", methods=["GET", "POST"])
async def updates(request: Request):
    """Манифест последнего бандла для Capgo. Нет бандла → «нечего обновлять»."""
    data = _manifest()
    if not data or not data.get("version") or not data.get("file"):
        return JSONResponse({"message": "no update available"})
    base = str(request.base_url).rstrip("/")
    out = {"version": data["version"], "url": f"{base}/app/bundles/{data['file']}"}
    if data.get("checksum"):
        out["checksum"] = data["checksum"]
    #Пофайловый список — ускорение поверх обычной закачки (см. шапку). Не собрался
    #(битый архив, нет места под кэш) — молча отдаём ответ без него: телефон тогда
    #качает бандл целиком, как раньше, а не остаётся вовсе без обновления.
    zip_path = _bundle_path(str(data["file"]))
    if zip_path is not None:
        files = _file_manifest(zip_path, str(data["version"]), base)
        if files:
            out["manifest"] = files
    return JSONResponse(out)


@router.get("/files/{version}/{path:path}")
async def bundle_file(version: str, path: str):
    """Один файл из бандла — для пофайловой докачки по манифесту.

    Отдаём ПРЯМО ИЗ zip, без распаковки на диск. Имя файла сверяется со списком внутри
    архива (`z.getinfo`), поэтому «../» в пути никуда не приведёт: такого имени в
    архиве просто нет, и мы ответим 404 — проверка по содержимому надёжнее любой
    фильтрации строки.
    """
    data = _manifest() or {}
    #Версию берём не из пути, а из манифеста: раздаём файлы ТОЛЬКО текущего бандла,
    #иначе адрес превратился бы в способ читать любые прошлые сборки по перебору имён.
    if not data or str(data.get("version")) != version:
        return JSONResponse({"detail": "not found"}, status_code=404)
    zip_path = _bundle_path(str(data.get("file") or ""))
    if zip_path is None:
        return JSONResponse({"detail": "not found"}, status_code=404)
    try:
        with zipfile.ZipFile(zip_path) as z:
            try:
                info = z.getinfo(path)
            except KeyError:
                return JSONResponse({"detail": "not found"}, status_code=404)
            if info.is_dir():
                return JSONResponse({"detail": "not found"}, status_code=404)
            body = z.read(info)
    except (OSError, zipfile.BadZipFile):
        return JSONResponse({"detail": "not found"}, status_code=404)
    media = _MIME.get(Path(path).suffix.lower(), "application/octet-stream")
    #Кэшировать у клиента нечего: файл уникален по содержимому, а плагин и так держит
    #свой кэш по хешу (см. DownloadService: имя в кэше — это хеш файла).
    return Response(content=body, media_type=media,
                    headers={"Cache-Control": "no-store"})


@router.api_route("/apk-info", methods=["GET", "POST"])
async def apk_info(request: Request):
    """Инфо о последнем НАТИВНОМ релизе (APK) для обновления самого приложения.
    Манифест apk-info.json: {"nativeVersion": <int>, "file": "GradeBookAI.apk"}.
    Файл .apk отдаётся через /downloads/<file> (см. main.py). Нет манифеста → «нет APK»."""
    m = OTA_DIR / "apk-info.json"
    if not m.is_file():
        return JSONResponse({"message": "no apk"})
    try:
        data = json.loads(m.read_text(encoding="utf-8-sig"))
    except Exception:
        return JSONResponse({"message": "no apk"})
    if not data.get("nativeVersion") or not data.get("file"):
        return JSONResponse({"message": "no apk"})
    base = str(request.base_url).rstrip("/")
    return JSONResponse({
        "nativeVersion": int(data["nativeVersion"]),
        "versionName": data.get("versionName", ""),
        "url": f"{base}/downloads/{data['file']}",
    })


@router.get("/bundles/{name}")
async def bundle(name: str):
    """Отдаёт zip-бандл целиком. Только *.zip внутри OTA_DIR (см. _bundle_path)."""
    p = _bundle_path(name)
    if p is None:
        return JSONResponse({"detail": "not found"}, status_code=404)
    return FileResponse(p, media_type="application/zip", filename=name)
