"""
schedule/store.py — локальный кэш расписания, чётность недели и привязка пользователя.

Где лежит. Снимок расписания (model.Snapshot) кладём в локальный зашифрованный
kv_store через data_store.local_* (префикс «_local:»): данные Fernet-шифруются «из
коробки», НЕ синхронизируются с сервером и не будят синк. Это то же место, где
живут адрес сервера и персональный кэш темы. Сетевой парсинг (parser.build_snapshot)
тяжёлый, поэтому в рантайме мы работаем с кэшем, а перепарсиваем только по кнопке
«Обновить» или когда кэш устарел.

Чётность недели (I/II) считаем РОВНО как портальный JS week():
    numberOfDays = (дата − 1 января того же года).days
    js_getday    = (weekday()+1) % 7        # привести Python-нумерацию к JS (Вс=0)
    result       = ceil((js_getday + 1 + numberOfDays) / 7)
    II неделя если result чётное, иначе I.

Привязка пользователя к сущности сайта (какая группа у студента / какое ФИО у
преподавателя) — per-account, тоже в «_local:». На общем ПК выбор одного аккаунта
не утекает другому (ключ включает роль и логин).
"""
from __future__ import annotations
import log

import math
from datetime import date, datetime, timezone

from .model import Snapshot

#Ключи в локальном (зашифрованном, несинхронизируемом) kv-хранилище.
_CACHE_KEY = "schedule_cache"
_IDENTITY_PREFIX = "sched_identity"     # + ":<role>:<login>"


def _cache_key(category: str) -> str:
    """Ключ кэша для категории — «колледж» остаётся БУКВАЛЬНО старым ключом
    (никакой миграции существующих кэшей пользователей при обновлении),
    остальные категории получают свой ключ рядом."""
    from schedule.parser import DEFAULT_CATEGORY
    if category == DEFAULT_CATEGORY:
        return _CACHE_KEY
    return f"{_CACHE_KEY}:{category}"


def _ds():
    """Ленивая ссылка на data_store (модуль из data/, импорты плоские).

    Лениво — чтобы импорт schedule.* не тянул БД на раннем старте и не падал, если
    хранилище ещё не готово (offline-first, «не падающий» модуль)."""
    import data_store
    return data_store


#  Кэш снимка
def save(snapshot: Snapshot, category: str = "college") -> bool:
    """Сохраняет снимок расписания категории в локальный зашифрованный кэш.

    category по умолчанию — «колледж», единственная категория с реальным
    журналом/оценками; остальные (bakalavriat/zo1/zo2) — только просмотр."""
    try:
        return _ds().local_set(_cache_key(category), snapshot.to_dict())
    except Exception as e:
        log.get("store").warning(f"[schedule] не удалось сохранить кэш расписания: {e}")
        return False


def load_cached(category: str = "college") -> Snapshot | None:
    """Возвращает снимок категории из кэша или None, если его ещё нет/он повреждён."""
    try:
        raw = _ds().local_get(_cache_key(category), None)
        if not raw:
            return None
        return Snapshot.from_dict(raw)
    except Exception as e:
        log.get("store").warning(f"[schedule] кэш расписания недоступен/повреждён: {e}")
        return None


def refresh_all(category: str = "college") -> "Snapshot | None":
    """Заново скачать ПОЛНЫЙ снимок расписания категории с портала ВСГУТУ и сохранить в кэш.

    Кнопка «Взять с ВСГУТУ (все группы)». Сетевая операция (десятки-сотни GET,
    зависит от категории) — ВЫЗЫВАТЬ ТОЛЬКО ИЗ ФОНОВОГО ПОТОКА, иначе интерфейс
    замрёт. Правки (overrides) это не трогает — обновляется лишь портальная
    основа, поверх которой они лежат (overrides — только для колледжа)."""
    from schedule import parser
    snap = parser.build_snapshot(category=category)
    save(snap, category=category)
    return snap


def refresh_group(app_group: str, category: str = "college") -> bool:
    """Обновить с портала ОДНУ группу категории и вписать её в кэш (остальные не трогаем).

    Кнопка «Взять с ВСГУТУ» для выбранной группы: быстрее полного снимка (1 GET вместо
    десятков). Тоже сетевая — из фонового потока. teacher_index при этом не пересобирается
    (он нужен расписаниям преподавателей, а не редактору группы)."""
    from schedule import parser
    from schedule.model import Snapshot
    if not app_group:
        return False
    dated = parser.CATEGORIES[category]["dated"]
    page_parser = parser.parse_group_page_dated if dated else parser.parse_group_page
    pairs = parser.list_category_groups(
        parser.fetch_text(parser.category_index_url(category)), category)
    site_name, href = app_group, None
    for name, h in pairs:
        if name == app_group:
            href = h
            break
    if href is None:                       #имя в журнале ≠ имя на портале — подбираем
        site_name = guess_group(app_group, [n for n, _ in pairs]) or app_group
        for name, h in pairs:
            if name == site_name:
                href = h
                break
    if href is None:
        return False
    page = parser.fetch_text(parser.category_group_url(category, href))
    gs = page_parser(page, name=site_name, href=href)
    snap = load_cached(category) or Snapshot()
    snap.groups[site_name] = gs
    save(snap, category=category)
    return True


def subjects_all(category: str = "college") -> list:
    """Все уникальные предметы из снимка расписания категории (СПАРСЕНЫ С САЙТА
    ВСГУТУ). По умолчанию — колледж: единственная категория, чьи предметы
    вообще имеют смысл для журнала/каталога.

    Источник правды для списка предметов: вместо «вшитого текстом» перечня берём то,
    что реально стоит в расписании на портале. Пусто — кэша ещё нет (тогда вызывающий
    код откатывается на прежний список). Дедуп + сортировка для стабильного вывода."""
    snap = load_cached(category)
    if not snap:
        return []
    subs = set(snap.subjects or [])
    if not subs:                                   #глобального списка нет — соберём из групп
        for g in snap.groups.values():
            subs.update(g.subjects())
    return sorted({s.strip() for s in subs if s and s.strip()})


def group_schedule(app_group: str, category: str = "college"):
    """Расписание группы категории из кэша портала. Для «колледжа» — С НАЛОЖЕННЫМИ
    админ-правками (overlay), единый источник для предметов и просмотра (как
    web._group_schedule); остальные категории — правок не имеют вовсе (§10
    плана — оверлеи только для боевого журнала колледжа). None — нет данных."""
    snap = load_cached(category)
    g = None
    if snap and app_group:
        site_name = app_group if app_group in snap.groups else guess_group(
            app_group, snap.group_names())
        g = snap.groups.get(site_name)
    if category == "college":
        try:
            from schedule.overrides import apply_to_group, list_overrides
            if g is not None or list_overrides(app_group):
                g = apply_to_group(g, app_group)
        except Exception:
            pass
    return g


def subjects_for_group(app_group: str, category: str = "college") -> list:
    """Предметы КОНКРЕТНОЙ группы из расписания (+ админ-правки для колледжа). Пусто —
    нет кэша или совпадения (вызывающий код откатится на предметы из журнала)."""
    if not app_group:
        return []
    g = group_schedule(app_group, category=category)
    return g.subjects() if g else []


def cache_age_minutes(category: str = "college") -> float | None:
    """Возраст кэша категории в минутах (None — кэша нет)."""
    snap = load_cached(category)
    if not snap or not snap.updated_at:
        return None
    try:
        dt = datetime.fromisoformat(snap.updated_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return delta.total_seconds() / 60.0
    except Exception:
        return None


#  Чётность недели (точная реплика портального week())
def current_week_parity(d: date | None = None) -> int:
    """Возвращает 1 (I неделя) или 2 (II неделя) для даты d (по умолчанию сегодня)."""
    if d is None:
        d = date.today()
    one_jan = date(d.year, 1, 1)
    number_of_days = (d - one_jan).days
    #Python: Пн=0..Вс=6; JS getDay(): Вс=0..Сб=6 → сдвигаем.
    js_getday = (d.weekday() + 1) % 7
    result = math.ceil((js_getday + 1 + number_of_days) / 7)
    return 2 if result % 2 == 0 else 1


def week_label(parity: int) -> str:
    """Человеческая подпись недели: 'I неделя' / 'II неделя'."""
    return "II неделя" if parity == 2 else "I неделя"


#  Привязка пользователя к сущности сайта (per-account, локально)
def _identity_key(role: str, login: str) -> str:
    return f"{_IDENTITY_PREFIX}:{role or ''}:{(login or '').strip().lower()}"


def get_identity(role: str, login: str) -> str:
    """Возвращает сохранённую привязку (имя группы для студента / ФИО на сайте для
    преподавателя) или '' если пользователь ещё не выбирал."""
    try:
        val = _ds().local_get(_identity_key(role, login), "")
        return val if isinstance(val, str) else ""
    except Exception:
        return ""


def set_identity(role: str, login: str, value: str) -> bool:
    """Сохраняет выбор пользователя (какая он группа / какое его ФИО на сайте)."""
    try:
        return _ds().local_set(_identity_key(role, login), value or "")
    except Exception as e:
        log.get("store").warning(f"[schedule] не удалось сохранить привязку расписания: {e}")
        return False


#  Автоподстановка (угадать сущность сайта по данным аккаунта)
def _norm(s: str) -> str:
    """Нормализует строку для нечёткого сравнения имён групп/преподавателей."""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def guess_group(app_group: str, site_groups: list) -> str:
    """Пытается сопоставить группу аккаунта с группой на сайте.

    Сначала точное совпадение, затем нормализованное (без пробелов/регистра).
    Возвращает '' если уверенного совпадения нет — тогда UI попросит выбрать вручную.
    """
    if not app_group:
        return ""
    if app_group in site_groups:
        return app_group
    target = _norm(app_group)
    for g in site_groups:
        if _norm(g) == target:
            return g
    return ""


def guess_teacher(app_full_name: str, site_teachers: list) -> str:
    """Сопоставляет ФИО преподавателя из аккаунта с записью на сайте «ФАМИЛИЯ И.О.».

    На сайте формат «ШАГДУРОВА А.И.»; в аккаунте обычно «Шагдурова Анна Ивановна».
    Сравниваем по фамилии и (если есть) первым буквам имени/отчества.
    """
    if not app_full_name:
        return ""
    parts = [p for p in app_full_name.replace(".", " ").split() if p]
    if not parts:
        return ""
    surname = _norm(parts[0])
    initials = [p[0].lower() for p in parts[1:] if p]

    best = ""
    for t in site_teachers:
        tparts = [p for p in t.replace(".", " ").split() if p]
        if not tparts:
            continue
        if _norm(tparts[0]) != surname:
            continue
        t_inits = [p[0].lower() for p in tparts[1:] if p]
        #фамилия совпала — уже кандидат; если инициалы тоже совпали, это точно он
        if not initials or not t_inits or initials[0] == t_inits[0]:
            return t
        best = best or t
    return best
