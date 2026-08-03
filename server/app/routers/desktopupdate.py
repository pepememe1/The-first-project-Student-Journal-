"""
desktopupdate.py — манифест автообновлений ДЕСКТОПА (аналог /app/updates для Android).

Сам .exe и патчи раздаёт уже существующий `/downloads/*` (см. main.py) — второго
механизма отдачи файлов не заводим. Здесь только манифест: что сейчас последнее, каким
патчем можно доехать с предыдущей версии и какими хешами всё проверяется.

Формат манифеста и правила сравнения версий — в корневом `desktop_update.py`, общем с
клиентом и со сборщиком патчей (`tools/make_desktop_patch.py`).

Манифест лежит файлом `downloads/updates/manifest.json` и создаётся при выкладке новой
сборки. Файла нет → отвечаем «обновлений нет», а не ошибкой: пустой сервер — штатное
состояние, пока не выложили ни одной сборки.
"""
import json
import os
import sys

from fastapi import APIRouter
from fastapi.responses import JSONResponse

#Корень репозитория в sys.path — тем же приёмом, что для grading/vector_nlu.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import desktop_update as DU        # noqa: E402

router = APIRouter(prefix="/desktop", tags=["desktop-update"])

_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOWNLOADS_DIR = os.environ.get(
    "GRADEBOOK_DOWNLOADS", os.path.join(os.path.dirname(_SERVER_DIR), "downloads"))


def _manifest_path() -> str:
    return os.path.join(DOWNLOADS_DIR, DU.UPDATES_DIR_NAME, DU.MANIFEST_NAME)


def load_manifest() -> dict:
    path = _manifest_path()
    if not os.path.isfile(path):
        return {}
    try:
        #utf-8-sig — терпимо к BOM (PowerShell пишет его при Out-File), как в appupdate.py.
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:                                        # noqa: BLE001
        return {}


@router.get("/updates")
def desktop_updates():
    """Манифест последней сборки десктопа.

    Ссылки на файлы намеренно ОТНОСИТЕЛЬНЫЕ (`/downloads/updates/<файл>`): программа
    ходит на тот же адрес, с которого уже синхронизируется, и абсолютный URL здесь
    означал бы вторую копию правды об адресе сервера — на переезде она разъедется.
    """
    man = load_manifest()
    if not man.get("version"):
        return JSONResponse({"message": "no update available"})
    return JSONResponse(man)
