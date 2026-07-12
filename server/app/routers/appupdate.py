"""
appupdate.py — OTA-обновления мобильного приложения (Capgo self-hosted).

Отдаёт манифест последнего веб-бандла и сами zip-бандлы. Приложение (autoUpdate)
на старте дёргает /app/updates и, если версия новее текущей, качает бандл с
/app/bundles/<file> и подменяет веб-часть БЕЗ переустановки APK.

Бандлы и манифест latest.json лежат в каталоге GRADEBOOK_OTA_DIR (по умолчанию
server/ota_bundles/). Формат latest.json:
    {"version": "1.0.1", "file": "1.0.1.zip", "checksum": "<sha256-hex>"}
URL бандла подставляется от адреса текущего запроса — работает и на проде, и локально.
"""
import json
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/app", tags=["app-update"])

_SERVER_DIR = Path(__file__).resolve().parents[2]   # .../server
OTA_DIR = Path(os.environ.get("GRADEBOOK_OTA_DIR", _SERVER_DIR / "ota_bundles"))


def _manifest():
    m = OTA_DIR / "latest.json"
    if not m.is_file():
        return None
    try:
        # utf-8-sig: терпимо к BOM (PowerShell Set-Content -Encoding utf8 пишет с BOM).
        return json.loads(m.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


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
    return JSONResponse(out)


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
    """Отдаёт zip-бандл. Только *.zip внутри OTA_DIR (защита от обхода каталога)."""
    if not name.endswith(".zip") or "/" in name or "\\" in name or ".." in name:
        return JSONResponse({"detail": "not found"}, status_code=404)
    p = (OTA_DIR / name).resolve()
    if not str(p).startswith(str(OTA_DIR.resolve())) or not p.is_file():
        return JSONResponse({"detail": "not found"}, status_code=404)
    return FileResponse(p, media_type="application/zip", filename=name)
