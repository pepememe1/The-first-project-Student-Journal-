"""
connect.py — Барьер подтверждения подключения устройств (device approval).

Зачем. Раньше любой ПК, знающий адрес сервера и валидные логин/пароль из БД, мог
синхронизироваться без какого-либо одобрения. Теперь новый ПК сначала ЗАПРАШИВАЕТ
доступ, администратор на хосте видит запрос (с IP) и принимает (выдаёт 6-значный код,
который сообщает пользователю по телефону) или отклоняет. Пока устройство не одобрено —
сервер не пускает его ни во вход, ни в синхронизацию (см. device_allowed).

Что где хранится:
  • ОЖИДАЮЩИЕ запросы и выданные коды — В ПАМЯТИ ПРОЦЕССА (как throttle.py/events.py).
    Они транзиентны: если сервер перезапустится, пользователь просто запросит снова.
  • ОДОБРЕННЫЕ устройства — в БД (таблица approved_devices), потому что одобрение должно
    переживать перезапуск сервера (иначе после каждого рестарта хоста все ПК пришлось
    бы одобрять заново).

Потокобезопасность: FastAPI выполняет синхронные эндпоинты в пуле потоков, поэтому к
состоянию в памяти обращаются параллельно — весь доступ под Lock.
"""
import os
import time
import secrets
import threading
from datetime import datetime, timezone

from .models import ApprovedDevice

_lock = threading.Lock()

#Ожидающие запросы: device_id -> запись. Статусы:
#  pending      — запрос пришёл, ждём решения админа;
#  code_issued  — админ принял, выдан код, ждём ввода кода пользователем;
#  rejected     — админ отклонил (держим недолго, чтобы клиент успел увидеть статус);
#  approved     — код подтверждён (одобрение уже записано в БД).
_pending: dict = {}

#Сколько живёт выданный код и сколько неверных попыток ввода терпим (анти-брутфорс
#6-значного кода: 1e6 вариантов, но лимит попыток + TTL делают перебор бессмысленным).
CODE_TTL_SEC = 10 * 60
MAX_CODE_ATTEMPTS = 5

#Сколько держим завершённые записи (rejected/approved), чтобы клиент успел опросить
#статус, после чего их подчищаем, не давая памяти расти.
_DONE_TTL_SEC = 5 * 60


def _now_iso() -> str:
    #UTC + смещение — единый формат меток с остальным сервером/клиентом.
    return datetime.now(timezone.utc).isoformat()


def host_device_id() -> str:
    """device_id ПК-хоста. server_control выставляет его в окружение
    GRADEBOOK_HOST_DEVICE_ID ПЕРЕД импортом сервера, чтобы хост (на нём админ
    поднимает сервер и одобряет остальных) всегда проходил барьер сам — иначе
    получился бы замкнутый круг (одобрить себя было бы некому). На IP не полагаемся:
    через serveo все клиенты выглядят как 127.0.0.1, и blanket-bypass по loopback
    открыл бы барьер всем. Поэтому опознаём хост строго по этому device_id."""
    return (os.environ.get("GRADEBOOK_HOST_DEVICE_ID", "") or "").strip()


def _prune(now: float):
    """Подчистить просроченные завершённые записи. Зовётся под _lock."""
    dead = [d for d, r in _pending.items()
            if r["status"] in ("rejected", "approved")
            and now - r.get("done_at", now) > _DONE_TTL_SEC]
    for d in dead:
        _pending.pop(d, None)


#Запрос на подключение (вызывает новый ПК, без авторизации)
def submit(device_id: str, ip: str = "", hostname: str = "") -> str:
    """Регистрирует/обновляет ожидающий запрос. Возвращает текущий статус.
    Повторный запрос с тем же device_id обновляет IP/имя и не плодит дублей. Уже
    отклонённый запрос при повторе снова становится pending (пользователь решил
    попробовать ещё раз — пусть админ снова увидит его в списке)."""
    device_id = (device_id or "").strip()
    if not device_id:
        return "none"
    now = time.time()
    with _lock:
        _prune(now)
        rec = _pending.get(device_id)
        if rec and rec["status"] == "code_issued":
            #Код уже выдан — не сбрасываем его, только освежим контактные данные.
            rec["ip"] = ip or rec.get("ip", "")
            rec["hostname"] = hostname or rec.get("hostname", "")
            return rec["status"]
        _pending[device_id] = {
            "device_id": device_id, "ip": ip or "", "hostname": hostname or "",
            "status": "pending", "code": "", "code_expires": 0.0,
            "attempts": 0, "ts": now,
        }
        return "pending"


def get_status(device_id: str) -> str:
    """Статус запроса для опроса клиентом ('none' — записи нет)."""
    device_id = (device_id or "").strip()
    now = time.time()
    with _lock:
        _prune(now)
        rec = _pending.get(device_id)
        if not rec:
            return "none"
        #Код протух, а пользователь так и не ввёл — возвращаем в pending, пусть админ
        #выдаст заново (иначе человек завис бы на мёртвом коде).
        if rec["status"] == "code_issued" and rec["code_expires"] < now:
            rec["status"] = "pending"
            rec["code"] = ""
            rec["attempts"] = 0
        return rec["status"]


#Действия администратора (require_admin на роутере)
def list_active() -> list:
    """Активные запросы для админ-панели (ожидающие решения и с выданным кодом)."""
    now = time.time()
    with _lock:
        _prune(now)
        rows = [dict(r) for r in _pending.values()
                if r["status"] in ("pending", "code_issued")]
    rows.sort(key=lambda r: r["ts"])
    return rows


def approve(device_id: str) -> str:
    """Админ принял запрос: генерим 6-значный код и переводим в code_issued.
    Возвращает код ('' — если запроса нет)."""
    device_id = (device_id or "").strip()
    with _lock:
        rec = _pending.get(device_id)
        if not rec:
            return ""
        #Криптостойкий 6-значный код (000000..999999), без предсказуемого random.
        code = f"{secrets.randbelow(1_000_000):06d}"
        rec["status"] = "code_issued"
        rec["code"] = code
        rec["code_expires"] = time.time() + CODE_TTL_SEC
        rec["attempts"] = 0
        return code


def reject(device_id: str) -> bool:
    """Админ отклонил: помечаем rejected (клиент увидит это при опросе) и убираем из
    активного списка. Запись подчистится по _DONE_TTL_SEC."""
    device_id = (device_id or "").strip()
    with _lock:
        rec = _pending.get(device_id)
        if not rec:
            return False
        rec["status"] = "rejected"
        rec["code"] = ""
        rec["done_at"] = time.time()
        return True


def verify(device_id: str, code: str) -> tuple:
    """Проверка кода пользователем. Возвращает (ok, reason):
      (True, 'approved')           — код верный, можно записывать одобрение в БД;
      (False, 'no_request')        — запроса нет / не на стадии кода;
      (False, 'expired')           — код просрочен;
      (False, 'too_many')          — исчерпан лимит попыток;
      (False, 'bad_code')          — код неверный (попытка засчитана)."""
    device_id = (device_id or "").strip()
    code = (code or "").strip()
    now = time.time()
    with _lock:
        rec = _pending.get(device_id)
        if not rec or rec["status"] != "code_issued":
            return False, "no_request"
        if rec["code_expires"] < now:
            rec["status"] = "pending"; rec["code"] = ""; rec["attempts"] = 0
            return False, "expired"
        if rec["attempts"] >= MAX_CODE_ATTEMPTS:
            return False, "too_many"
        if code != rec["code"]:
            rec["attempts"] += 1
            return False, "bad_code"
        #Код верный — помечаем approved (саму запись в БД делает роутер, у него Session).
        rec["status"] = "approved"
        rec["code"] = ""
        rec["done_at"] = now
        return True, "approved"


#Одобренные устройства в БД (переживают перезапуск)
def is_approved(db, device_id: str) -> bool:
    """Есть ли устройство в таблице одобренных."""
    device_id = (device_id or "").strip()
    if not device_id:
        return False
    return db.query(ApprovedDevice).filter(
        ApprovedDevice.device_id == device_id).first() is not None


def add_approved(db, device_id: str, ip: str = "", hostname: str = "",
                 approved_by: str = "") -> None:
    """Заносит устройство в одобренные (идемпотентно: повтор обновляет метаданные)."""
    device_id = (device_id or "").strip()
    if not device_id:
        return
    row = db.query(ApprovedDevice).filter(
        ApprovedDevice.device_id == device_id).first()
    if row is None:
        row = ApprovedDevice(device_id=device_id)
        db.add(row)
    row.ip = ip or row.ip or ""
    row.hostname = hostname or row.hostname or ""
    row.approved_at = _now_iso()
    row.approved_by = approved_by or row.approved_by or ""
    db.commit()


#Барьер: пускать ли устройство к защищённым эндпоинтам
def device_allowed(request, db) -> bool:
    """True, если запрос пришёл с одобренного устройства ИЛИ это сам хост.

    Хост опознаём по X-Device-Id == GRADEBOOK_HOST_DEVICE_ID (см. host_device_id):
    на IP не полагаемся (serveo всё показывает как loopback). Остальные — только если
    их device_id лежит в approved_devices."""
    dev = (request.headers.get("x-device-id", "") if request is not None else "").strip()
    if not dev:
        return False
    host = host_device_id()
    if host and dev == host:
        return True
    return is_approved(db, dev)


def reset():
    """Полный сброс ОЖИДАЮЩИХ запросов — для тестов (одобренные в БД не трогаем)."""
    with _lock:
        _pending.clear()
