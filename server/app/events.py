"""
events.py — Лёгкий мониторинг сервера для админ-панели: кто сейчас онлайн и
журнал последних действий/ошибок.

Хранение — В ПАМЯТИ ПРОЦЕССА (как throttle.py). Для типового развёртывания
колледжа сервер крутится ОДНИМ процессом (uvicorn, «сервер из админки»), и этого
достаточно. ⚠️ Несколько воркеров (gunicorn -w N) или машин за балансировщиком НЕ
делят эту память — каждый видел бы свою часть; для такого масштаба выносите состояние
в общий слой (Redis/БД). Здесь намеренно просто и без новых зависимостей.

Потокобезопасность: FastAPI выполняет синхронные эндпоинты в пуле потоков, поэтому
к одному состоянию обращаются параллельно — весь доступ под Lock.
"""
import threading
import time
from collections import deque

_lock = threading.Lock()

#Присутствие: login -> {login, role, name, ip, last_seen}. Обновляется на КАЖДОМ
#авторизованном запросе (см. deps.get_current_user) — это и есть «активность».
_presence: dict = {}

#Кольцевой буфер последних событий: новые вытесняют старые, память не растёт.
_MAX_EVENTS = 500
_events = deque(maxlen=_MAX_EVENTS)
_seq = 0   #монотонный id события — чтобы клиент опрашивал дельтой «дай новее N»

#Сколько секунд без активности ещё считаем «онлайн». Клиент синкается ~раз в 30 c,
#поэтому 90 c (≈3 цикла) — щадящее окно, переживающее одиночный пропуск.
ONLINE_WINDOW_SEC = 90


def touch(login: str, role: str = "", name: str = "", ip: str = ""):
    """Отметить активность пользователя (вызывается на каждом авторизованном запросе)."""
    if not login:
        return
    with _lock:
        _presence[login] = {
            "login": login, "role": role or "", "name": name or "",
            "ip": ip or "", "last_seen": time.time(),
        }


def online(window_sec: int = ONLINE_WINDOW_SEC) -> list:
    """Список активных за последние window_sec секунд (свежие сверху, с idle_sec)."""
    now = time.time()
    cutoff = now - window_sec
    with _lock:
        rows = [dict(r) for r in _presence.values() if r["last_seen"] >= cutoff]
    rows.sort(key=lambda r: r["last_seen"], reverse=True)
    for r in rows:
        r["idle_sec"] = int(now - r["last_seen"])
    return rows


#Управляющие символы, которыми в журнал подделывают строку: перевод строки и возврат
#каретки, остальные C0/C1, «разделитель строк» и «разделитель абзацев» Юникода.
_LINE_BREAKERS = {ord("\n"): "\\n", ord("\r"): "\\r", ord("\t"): " ",
                  0x2028: "\\n", 0x2029: "\\n", 0x85: "\\n"}
_LINE_BREAKERS.update({c: "" for c in list(range(0x00, 0x20)) + [0x7f] + list(range(0x80, 0xa0))
                       if c not in _LINE_BREAKERS})


def one_line(value) -> str:
    """Значение для журнала — ОДНОЙ строкой (OWASP ASVS V16.4.1, 07.10.2026).

    В журнал попадает то, что прислал человек: логин при неудачном входе, имя устройства,
    причина действия. С переводом строки внутри одна запись читается как две, и вторая —
    целиком сочинённая: «вход выполнен: admin» под чужим неудачным входом. Вечерняя
    сводка приманок уходит ПИСЬМОМ, то есть текстом, где подделку не отличить от записи.
    Перевод строки не выбрасываем, а показываем (`\\n`): след того, что его пытались
    вставить, сам по себе сигнал. Одна дверь для живого монитора и постоянного журнала."""
    return str(value or "").translate(_LINE_BREAKERS)


def record(level: str, kind: str, message: str, login: str = "", ip: str = ""):
    """Записать событие в журнал. level: info|warn|error; kind — короткая метка типа."""
    global _seq
    with _lock:
        _seq += 1
        _events.append({
            "id": _seq, "ts": time.time(), "level": level or "info",
            "kind": one_line(kind), "message": one_line(message),
            "login": one_line(login), "ip": one_line(ip),
        })


def recent(since_id: int = 0, limit: int = 200) -> dict:
    """События с id > since_id (дельта-опрос). Возвращает {events, last_id}."""
    with _lock:
        evs = [dict(e) for e in _events if e["id"] > since_id]
        last = _events[-1]["id"] if _events else 0
    if len(evs) > limit:
        evs = evs[-limit:]            #при первом опросе отдаём только хвост
    return {"events": evs, "last_id": last}


def reset():
    """Полный сброс состояния — нужен тестам, чтобы прогоны не влияли друг на друга."""
    global _seq
    with _lock:
        _presence.clear()
        _events.clear()
        _seq = 0
