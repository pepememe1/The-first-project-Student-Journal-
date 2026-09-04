"""
serverinfo.py — раздел «Сервер» в кабинете администратора, ТОЛЬКО ПРОСМОТР.

Что здесь есть: состояние машины, на которой работает сервер (диск, память, аптайм,
нагрузка), размер базы, список резервных копий и обзор каталога развёртывания.

⚠️ ЧЕГО ЗДЕСЬ НЕТ И НЕ БУДЕТ — управления. Ни выполнения команд, ни перезапуска служб,
ни SSH. Причина простая: этот роутер подключён и на БОЕВОМ сервере, куда ходят из
браузера. Дырка в веб-админке не должна превращаться в оболочку на машине с
персональными данными всего колледжа.

Управление живёт в `desktop/server_admin.py` — оно подключается ТОЛЬКО к локальному серверу
программы (127.0.0.1) и на боевой машине физически отсутствует. Разделение проходит
именно по этой границе, а не по проверке роли: роль можно обойти, отсутствующий код —
нельзя.
"""
import os

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import hostinfo
from ..db import get_db
from ..deps import require_admin
from ..models import User

router = APIRouter(prefix="/web/admin/server", tags=["server-info"])


def _deploy_root() -> str:
    """Каталог развёртывания — «корень», выше которого обзор не пускает.

    На бою это /root/gb-deploy/server (рабочий каталог службы), в программе — папка
    локального сервера. Берём рабочий каталог процесса, а не путь к исходникам: он
    совпадает с тем, что человек видит на сервере, и не зависит от способа запуска."""
    return os.path.realpath(os.environ.get("GRADEBOOK_DEPLOY_ROOT") or os.getcwd())


def _db_file() -> str:
    """Путь к файлу базы ('' — если URL не файловый).

    ⚠️ Проверку на `sqlite` НЕ убираем, хотя база у продукта теперь одна: сюда приходит
    строка подключения, и при пустом или нестандартном значении (локальный сервер
    десктопа задаёт её сам) разбирать путь нечего. Пустая строка означает «файл не
    определён», а не «файла нет»."""
    from ..db import DATABASE_URL
    if not DATABASE_URL.startswith("sqlite"):
        return ""
    return DATABASE_URL.split("///", 1)[-1] if "///" in DATABASE_URL else ""


@router.get("/metrics")
def server_metrics(_admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    """Состояние машины + размер базы + сводка по данным."""
    root = _deploy_root()
    out = hostinfo.summary(root)

    db_path = _db_file()
    size = 0
    if db_path and os.path.isfile(db_path):
        try:
            size = os.path.getsize(db_path)
        except OSError:
            size = 0
    #Шифрование базы — свойство, о котором админ обязан знать в лицо: без ключа
    #резервная копия бесполезна, и путать эти два состояния нельзя.
    from ..db import DB_KEY
    out["database"] = {"engine": "sqlite" if db_path else "external",
                       "path": db_path, "size": size, "encrypted": bool(DB_KEY)}

    #Сколько людей в системе — самый дешёвый признак «база живая, а не пустая копия».
    try:
        out["counts"] = {
            "users": db.query(User).filter(User.deleted == False).count(),  # noqa: E712
        }
    except Exception:      # noqa: BLE001 — сводка не повод ронять страницу
        out["counts"] = {}
    return out


@router.get("/backups")
def server_backups(_admin: User = Depends(require_admin)):
    """Резервные копии: что есть и насколько свежее.

    Показываем ДАТУ САМОЙ СВЕЖЕЙ отдельным полем — вопрос «а бэкапы вообще делаются?»
    задают именно так, и ответом на него не должен быть список из сорока строк."""
    root = os.environ.get("GRADEBOOK_BACKUP_DIR") or "/root/gb-backups"
    if not os.path.isdir(root):
        return {"dir": root, "exists": False, "items": [], "latest": ""}
    items = sorted(hostinfo.listdir(root, root), key=lambda x: x["mtime"], reverse=True)
    return {"dir": root, "exists": True, "items": items[:50],
            "latest": items[0]["mtime"] if items else "",
            "total_size": sum(i["size"] for i in items)}


@router.get("/tree")
def server_tree(path: str = Query(""), _admin: User = Depends(require_admin)):
    """Обзор каталога развёртывания: что сколько занимает.

    Ради этого раздел и заводился — «на диске 73 %, а что именно его ест?». Отдаём
    только имена и размеры; содержимое файлов не читается никогда, а выход за корень
    закрыт в `hostinfo.listdir`."""
    root = _deploy_root()
    target = os.path.realpath(path) if path else root
    items = hostinfo.listdir(target, root)
    return {"root": root, "path": target, "items": items,
            "parent": os.path.dirname(target) if target != root else ""}
