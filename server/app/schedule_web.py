"""
schedule_web.py — Серверная выдача расписания ВСГУТУ для веб-версии.

Переиспользует ДЕСКТОПНЫЙ парсер портала (schedule/parser.py, только stdlib+requests,
без Qt) — формулу разбора не дублируем. В отличие от десктопа (там каждый клиент сам
тянет портал), для сайта портал дёргает СЕРВЕР и кэширует снимок в памяти (TTL 3ч) —
чтобы не бомбить portal.esstu.ru на каждый заход браузера. Данные публичные, ПДн не
участвуют (152-ФЗ не задет).

Парсим по ОДНОЙ группе (быстро), а не весь колледж: браузеру нужна только его группа.
Любая сетевая ошибка/оффлайн → пустой снимок (эндпоинт отдаёт 200 с пустыми днями).

Категории (schedule/parser.py::CATEGORIES) — «колледж» была единственной изначально,
теперь портал читается ещё в трёх разделах (бакалавриат/заочное 1/заочное 2). Кэши
ниже ключуются по категории, дефолт везде — «колледж» (DEFAULT_CATEGORY), поэтому
любой существующий вызов без явной категории продолжает вести себя как раньше.
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
_index: dict = {}                    # category -> {"ts": float, "pairs": [(name, href)]}
_groups: dict = {}                   # category -> {name: {"ts": float, "data": dict}}


def _parser():
    """Ленивый импорт парсера (изолирует возможные сбои импорта от старта сервера)."""
    from schedule import parser  # noqa: E402  (schedule/__init__ импортит только math/datetime/model)
    return parser


def default_category() -> str:
    return _parser().DEFAULT_CATEGORY


def categories() -> list:
    """[{key, label, dated}] — реестр категорий для фронта (ОДИН источник правды,
    список меток не дублируется в JS). dated — сессионный формат (Заочное 1/2):
    дни это календарные даты, а не Пн-Сб, и число «недель» не всегда 2 — фронт
    должен рендерить сетку иначе (см. SchedulePage.vue)."""
    p = _parser()
    return [{"key": k, "label": v["label"], "dated": bool(v["dated"])}
           for k, v in p.CATEGORIES.items()]


def current_week_parity(d: date | None = None) -> int:
    """1 (I неделя) / 2 (II неделя) — тот же расчёт, что в schedule/store.py."""
    d = d or date.today()
    days = (d - date(d.year, 1, 1)).days
    js_getday = (d.weekday() + 1) % 7
    result = math.ceil((js_getday + 1 + days) / 7)
    return 2 if result % 2 == 0 else 1


def _load_index(category: str = "", force: bool = False):
    category = category or default_category()
    with _lock:
        entry = _index.get(category, {"ts": 0.0, "pairs": []})
        fresh = entry["pairs"] and (time.time() - entry["ts"] < _TTL)
    if fresh and not force:
        return entry["pairs"]
    p = _parser()
    html = p.fetch_text(p.category_index_url(category))
    pairs = p.list_category_groups(html, category)
    with _lock:
        _index[category] = {"ts": time.time(), "pairs": pairs}
    return pairs


def list_groups(category: str = "") -> list:
    """Имена групп категории (для college — только «К»). Пустой список при оффлайне/ошибке."""
    category = category or default_category()
    try:
        return [name for name, _ in _load_index(category)]
    except Exception:
        return []


def _href_for(name: str, category: str) -> str:
    for n, href in _load_index(category):
        if n == name:
            return href
    return ""


#Расписание ПРЕПОДАВАТЕЛЯ: нужен ПОЛНЫЙ снимок (teacher_index строится инверсией всех
#групповых страниц категории — десятки-сотни GET). Поэтому ЛЕНИВО и в ФОНЕ: первый
#запрос запускает сборку потоком и сразу отвечает {building: true}; готовый снимок
#живёт _TTL. Ключ — категория (college — единственная с реальными аккаунтами
#преподавателей, остальные — просто просмотр «кто ведёт», без привязки к аккаунту).
_full: dict = {}                     # category -> {"ts", "snap", "building"}


def _full_entry(category: str) -> dict:
    return _full.setdefault(category, {"ts": 0.0, "snap": None, "building": False})


def _build_full_bg(category: str):
    try:
        p = _parser()
        snap = p.build_snapshot(category=category)
        with _lock:
            e = _full_entry(category)
            e["snap"] = snap
            e["ts"] = time.time()
    except Exception as e:
        print(f"[schedule_web] полный снимок ({category}) не собрался: {e}")
    finally:
        with _lock:
            _full_entry(category)["building"] = False


def full_state(category: str = ""):
    """(snapshot | None, building: bool). Устаревший/отсутствующий снимок запускает
    фоновую пересборку; пока она идёт, отдаём прежний снимок (если был)."""
    category = category or default_category()
    with _lock:
        e = _full_entry(category)
        snap = e["snap"]
        fresh = snap is not None and (time.time() - e["ts"] < _TTL)
        if not fresh and not e["building"]:
            e["building"] = True
            threading.Thread(target=_build_full_bg, args=(category,), daemon=True).start()
        return snap, e["building"]


def warm(category: str = ""):
    """Прогрев снимка расписания при СТАРТЕ сервера: запускаем фоновую сборку заранее,
    чтобы к первому входу преподавателя его расписание по ФИО было уже готово (иначе
    первый заход ждёт десятки секунд сборки полного снимка). Ничего не блокирует —
    full_state() лишь стартует фоновый поток. По умолчанию греем только колледж —
    единственную категорию с реальными аккаунтами преподавателей."""
    try:
        full_state(category or default_category())
    except Exception as e:
        print(f"[schedule_web] прогрев не удался: {e}")


def match_teacher(full_name: str, names: list) -> str:
    """Ищет преподавателя портала по ФИО пользователя. На портале — «Иванов И.И.»,
    в аккаунте — «Иванов Иван Иванович»: сравниваем фамилию + инициалы."""
    fn = (full_name or "").strip().lower()
    if not fn:
        return ""
    parts = fn.split()
    surname = parts[0]
    inits = "".join(p[0] for p in parts[1:3] if p)
    for t in names:
        tp = (t or "").lower().replace(".", " ").split()
        if not tp or tp[0] != surname:
            continue
        tinits = "".join(p[0] for p in tp[1:3] if p)
        if not inits or not tinits or tinits == inits[:len(tinits)]:
            return t
    return ""


def teacher_weeks(snap, name: str) -> dict | None:
    """Недели преподавателя из teacher_index в JSON-виде: {week: {day: [пары]}};
    в каждую пару добавляем group — преподавателю важно, у кого он ведёт."""
    weeks = (snap.teacher_index or {}).get(name)
    if not weeks:
        return None
    out = {}
    for w, days in weeks.items():
        out[str(w)] = {}
        for d, entries in days.items():
            #Сортируем пары дня ПО НОМЕРУ. teacher_index строится инверсией страниц групп,
            #поэтому пары одного дня приходят в произвольном порядке (у разных групп) — без
            #сортировки в расписании препода 5-я пара оказывалась выше 4-й.
            ordered = sorted(entries, key=lambda e: getattr(e["lesson"], "pair_no", 0) or 0)
            out[str(w)][d] = [dict(e["lesson"].to_dict(), group=e["group"])
                              for e in ordered]
    return out


def invalidate_all() -> None:
    """Сбросить ВЕСЬ кэш портала (все категории): индекс групп, снимки групп и полный
    снимок.

    Нужен кнопке «Взять с ВСГУТУ» — форс-обновление основы, поверх которой лежат правки
    администратора. Полный снимок помечаем протухшим (ts=0), но НЕ дёргаем сборку здесь:
    её запустит следующий full_state() в фоне (на одноядерном VPS блокировать нельзя)."""
    with _lock:
        _index.clear()
        _groups.clear()
        _full.clear()


def get_group(name: str, category: str = "", force: bool = False) -> dict | None:
    """Снимок расписания одной группы категории (dict как GroupSchedule.to_dict) или None.

    force=True — игнорировать кэш и сходить на портал заново (кнопка «Взять с ВСГУТУ»
    для одной группы). Обычные заходы кэш используют (портал не дёргается на каждый
    просмотр)."""
    category = category or default_category()
    name = (name or "").strip()
    if not name:
        return None
    if not force:
        with _lock:
            c = _groups.get(category, {}).get(name)
            if c and time.time() - c["ts"] < _TTL:
                return c["data"]
    try:
        if force:
            _load_index(category, force=True)   #индекс групп мог устареть — обновляем и его
        href = _href_for(name, category)
        if not href:
            return None
        p = _parser()
        dated = p.CATEGORIES[category]["dated"]
        page_parser = p.parse_group_page_dated if dated else p.parse_group_page
        html = p.fetch_text(p.category_group_url(category, href))
        data = page_parser(html, name=name, href=href).to_dict()
        with _lock:
            _groups.setdefault(category, {})[name] = {"ts": time.time(), "data": data}
        return data
    except Exception:
        return None
