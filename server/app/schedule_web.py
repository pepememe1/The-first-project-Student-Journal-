"""
schedule_web.py — Серверная выдача расписания ВСГУТУ для веб-версии.

Переиспользует ДЕСКТОПНЫЙ парсер портала (schedule/parser.py, только stdlib+requests,
без Qt) — формулу разбора не дублируем. В отличие от десктопа (там каждый клиент сам
тянет портал), для сайта портал дёргает СЕРВЕР и кэширует снимок в памяти (TTL 3ч) —
чтобы не бомбить portal.esstu.ru на каждый заход браузера. Данные публичные, ПДн не
участвуют (152-ФЗ не задет).

Парсим по ОДНОЙ группе (быстро), а не весь колледж: браузеру нужна только его группа.
Любая сетевая ошибка/оффлайн → пустой снимок (эндпоинт отдаёт 200 с пустыми днями).
"""
import os
import sys
import time
import math
import threading
from datetime import date

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_lock = threading.Lock()
_TTL = 3 * 3600                      # как автo-обновление в десктопе (кэш старше 3ч → рефреш)
_index = {"ts": 0.0, "pairs": []}    # [(name, href)]
_groups = {}                         # name -> {"ts": float, "data": dict}


def _parser():
    """Ленивый импорт парсера (изолирует возможные сбои импорта от старта сервера)."""
    from schedule import parser  # noqa: E402  (schedule/__init__ импортит только math/datetime/model)
    return parser


def current_week_parity(d: date | None = None) -> int:
    """1 (I неделя) / 2 (II неделя) — тот же расчёт, что в schedule/store.py."""
    d = d or date.today()
    days = (d - date(d.year, 1, 1)).days
    js_getday = (d.weekday() + 1) % 7
    result = math.ceil((js_getday + 1 + days) / 7)
    return 2 if result % 2 == 0 else 1


def _load_index(force: bool = False):
    with _lock:
        fresh = _index["pairs"] and (time.time() - _index["ts"] < _TTL)
    if fresh and not force:
        return _index["pairs"]
    p = _parser()
    html = p.fetch_text(p.COLLEGE_INDEX)
    pairs = p.list_college_groups(html)
    with _lock:
        _index["ts"] = time.time()
        _index["pairs"] = pairs
    return pairs


def list_groups() -> list:
    """Имена групп колледжа (на «К»). Пустой список при оффлайне/ошибке."""
    try:
        return [name for name, _ in _load_index()]
    except Exception:
        return []


def _href_for(name: str) -> str:
    for n, href in _load_index():
        if n == name:
            return href
    return ""


def get_group(name: str) -> dict | None:
    """Снимок расписания одной группы (dict как GroupSchedule.to_dict) или None."""
    name = (name or "").strip()
    if not name:
        return None
    with _lock:
        c = _groups.get(name)
        if c and time.time() - c["ts"] < _TTL:
            return c["data"]
    try:
        href = _href_for(name)
        if not href:
            return None
        p = _parser()
        html = p.fetch_text(p.BASE_URL + p.COLLEGE_DIR + href)
        data = p.parse_group_page(html, name=name, href=href).to_dict()
        with _lock:
            _groups[name] = {"ts": time.time(), "data": data}
        return data
    except Exception:
        return None
