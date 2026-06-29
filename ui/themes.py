"""
themes.py — Кастомные цветовые палитры (как темы в Google Chrome).

Идея: тема состоит из двух независимых осей.
  • РЕЖИМ (mode): 'light' / 'dark' — выбирает нейтральную базу поверхностей
    (styles.NEUTRALS_LIGHT / NEUTRALS_DARK). Это и есть полноценная тёмная тема.
  • АКЦЕНТ (id / accent): фирменная бирюза или один из 16 цветных пресетов —
    красит интерактив (кнопки, активная навигация, фокус, бейджи). В СВЕТЛОМ
    режиме акцент вдобавок даёт деликатный оттенок поверхностям («цветная тема»);
    в ТЁМНОМ поверхности остаются графитовыми — так читаемо при любом акценте.

Тема описывается «спецификацией» (spec) — это маленький JSON:
    {"id": "<id пресета>"}                          — готовая палитра из PRESETS
    {"id": "custom", "accent": "#RRGGBB"}           — свой цвет (ползунки в редакторе)
    {"id": "default"}                                — стандартная тема ВСГУТУ
    + необязательное поле "mode": "dark"             — тёмный режим (по умолч. светлый)

Применение: themes.apply_spec(spec) собирает полный словарь цветов и отдаёт его в
styles.apply_palette(...), затем переустанавливает глобальный QSS у приложения.
"""
import json
from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import styles

#Дефолтные значения/опора для пресетов: светлый нейтрал + фирменный акцент. Сами
#нейтрали для конкретного режима берём напрямую из styles.NEUTRALS_* в build_palette.
BASE = {**styles.NEUTRALS_LIGHT, **styles.DEFAULT_ACCENT}

DEFAULT_ID = "default"

#Готовый пул палитр (≈ как на скрине). Каждая задаёт только акцент; вторичный цвет
#(`blue`) и затемнённый вариант (`green2`) вычисляются из акцента автоматически.
#accent2 можно задать явно, если хочется особый вторичный оттенок.
PRESETS = [
    {"id": "default",  "name": "Стандарт ВСГУТУ", "accent": BASE["green"]},
    {"id": "blue",     "name": "Синий",            "accent": "#1A56DB"},
    {"id": "slate",    "name": "Грифельный",       "accent": "#5B6B7F"},
    {"id": "navy",     "name": "Тёмно-синий",      "accent": "#1E4E79"},
    {"id": "steel",    "name": "Стальной",         "accent": "#4A6274"},
    {"id": "tealgrey", "name": "Серо-бирюзовый",   "accent": "#5E7E7E"},
    {"id": "teal",     "name": "Бирюзовый",        "accent": "#0E7C6B"},
    {"id": "green",    "name": "Зелёный",          "accent": "#2E7D32"},
    {"id": "sage",     "name": "Шалфей",           "accent": "#6F8B5F"},
    {"id": "olive",    "name": "Оливковый",        "accent": "#A8870B"},
    {"id": "amber",    "name": "Янтарный",         "accent": "#C2680F"},
    {"id": "brown",    "name": "Коричневый",       "accent": "#8D6E63"},
    {"id": "maroon",   "name": "Бордовый",         "accent": "#A33B5C"},
    {"id": "mauve",    "name": "Лиловый",          "accent": "#7E5A6B"},
    {"id": "pink",     "name": "Розовый",          "accent": "#C2417F"},
    {"id": "violet",   "name": "Фиолетовый",       "accent": "#6A4FB3"},
]

_PRESET_BY_ID = {p["id"]: p for p in PRESETS}


def _clamp(v: int) -> int:
    return max(0, min(255, v))


def _shift_value(hex_color: str, dv: int, ds: int = 0) -> str:
    """Сдвигает яркость/насыщенность цвета в пространстве HSV (для производных)."""
    c = QColor(hex_color)
    h, s, v, a = c.getHsv()
    c2 = QColor.fromHsv(h if h >= 0 else 0, _clamp(s + ds), _clamp(v + dv), a)
    return c2.name()


def _glow(hex_color: str, alpha: float = 0.10) -> str:
    """rgba-«свечение» акцента (используется для подсветок/hover в QSS)."""
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def _tint(hex_color: str, ratio: float) -> str:
    """Подмешивает акцент к БЕЛОМУ (ratio — доля акцента). Чем меньше ratio, тем
    ближе к белому. Так фон/поверхности получают лёгкий оттенок выбранной темы,
    оставаясь светлыми (тёмный текст по-прежнему читается)."""
    c = QColor(hex_color)
    r = round(c.red() * ratio + 255 * (1 - ratio))
    g = round(c.green() * ratio + 255 * (1 - ratio))
    b = round(c.blue() * ratio + 255 * (1 - ratio))
    return QColor(r, g, b).name()


def _mix(hex_a: str, hex_b: str, ratio: float) -> str:
    """Смешивает два цвета: ratio — доля hex_b, подмешиваемая в hex_a (0..1)."""
    a, b = QColor(hex_a), QColor(hex_b)
    r = round(a.red() * (1 - ratio) + b.red() * ratio)
    g = round(a.green() * (1 - ratio) + b.green() * ratio)
    bl = round(a.blue() * (1 - ratio) + b.blue() * ratio)
    return QColor(r, g, bl).name()


def _accent_slots(accent: str, accent2: str | None = None) -> dict:
    """Акцентные слоты из основного цвета темы (одинаково работают в обоих режимах)."""
    return {
        "green":      accent,
        "green2":     _shift_value(accent, dv=-35),          #тёмный вариант (hover/pressed)
        "green_glow": _glow(accent, 0.14),                   #подсветка hover/active/фокус
        "blue":       accent2 or _shift_value(accent, dv=30, ds=-25),
    }


def _tinted_surfaces(accent: str) -> dict:
    """СВЕТЛЫЙ режим: деликатный оттенок акцента на поверхностях (фирменная «цветная
    тема», но почти белый — с намёком на цвет). В ТЁМНОМ режиме поверхности НЕ
    тонируем: графитовый нейтрал одинаково читаем при любом из 16 акцентов."""
    return {
        "bg":      _tint(accent, 0.05),
        "bg2":     _tint(accent, 0.09),
        "card2":   _tint(accent, 0.045),
        "border":  _tint(accent, 0.14),
        "border2": _tint(accent, 0.22),
        #card оставляем чисто белым (контраст карточек к фону)
    }


def _dark_tinted_surfaces(accent: str) -> dict:
    """ТЁМНЫЙ режим: подмешиваем НЕМНОГО акцента в графитовые поверхности, чтобы фон
    «звучал» выбранной темой (тёмно-синий / тёмно-жёлтый и т.п.), оставаясь комфортным.
    Светлый текст не трогаем — читаемость сохраняется (проверено QA контраста)."""
    d = styles.NEUTRALS_DARK
    return {
        "bg":      _mix(d["bg"],      accent, 0.10),
        "bg2":     _mix(d["bg2"],     accent, 0.12),
        "card":    _mix(d["card"],    accent, 0.09),
        "card2":   _mix(d["card2"],   accent, 0.12),
        "border":  _mix(d["border"],  accent, 0.16),
        "border2": _mix(d["border2"], accent, 0.20),
    }


def build_palette(spec: dict) -> dict:
    """Собирает ПОЛНЫЙ словарь цветов (формат styles.C) по спецификации темы.

    Режим (ручной spec['mode'] или по расписанию) выбирает нейтральную базу; id/accent
    — акцентные слоты. Поверхности получают оттенок акцента: светлые — почти белые с
    намёком на цвет, тёмные — графит с тем же оттенком (тёмно-синий/жёлтый и т.п.)."""
    spec = spec or {}
    mode = effective_mode(spec)
    tid = spec.get("id", DEFAULT_ID)

    #Нейтрали выбранного режима — основа палитры.
    cols = dict(styles.NEUTRALS_DARK if mode == "dark" else styles.NEUTRALS_LIGHT)
    _surfaces = _tinted_surfaces if mode == "light" else _dark_tinted_surfaces

    if tid == "custom":
        accent = spec.get("accent") or styles.DEFAULT_ACCENT["green"]
        accent2 = spec.get("accent2")
    elif tid == DEFAULT_ID:
        #Заводская тема ВСГУТУ: фирменный акцент + оттенок поверхностей под него.
        cols.update(styles.DEFAULT_ACCENT)
        cols.update(_surfaces(styles.DEFAULT_ACCENT["green"]))
        return cols
    else:
        preset = _PRESET_BY_ID.get(tid)
        if not preset:
            cols.update(styles.DEFAULT_ACCENT)   #неизвестный id — безопасный откат
            return cols
        accent = preset["accent"]
        accent2 = preset.get("accent2")

    cols.update(_accent_slots(accent, accent2))
    cols.update(_surfaces(accent))
    return cols


def swatch_colors(spec: dict) -> tuple:
    """(accent, accent2, surface) — три цвета для кружка-превью палитры (учитывает режим)."""
    cols = build_palette(spec)
    return cols["green"], cols["blue"], cols["card2"]


def apply_spec(spec: dict) -> dict:
    """Применяет тему «вживую»: пересобирает палитру styles.C и глобальный QSS.

    Возвращает нормализованный spec (тот, что реально применили)."""
    spec = normalize_spec(spec)
    palette = build_palette(spec)
    styles.apply_palette(palette)
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(styles.APP_STYLE)
    return spec


def _norm_hhmm(v, default: str) -> str:
    """Валидирует время 'HH:MM' (на случай мусора из БД)."""
    try:
        hh, mm = str(v).split(":")
        hh, mm = int(hh), int(mm)
        if 0 <= hh < 24 and 0 <= mm < 60:
            return f"{hh:02d}:{mm:02d}"
    except Exception:
        pass
    return default


def normalize_spec(spec) -> dict:
    """Приводит вход к корректному spec (на случай мусора из БД/конфига).
    Сохраняет mode ('light'/'dark') и schedule (расписание тёмной темы)."""
    if isinstance(spec, str):
        spec = spec_from_json(spec)
    if not isinstance(spec, dict) or not spec.get("id"):
        return {"id": DEFAULT_ID}
    out = dict(spec)
    if out.get("mode") not in ("light", "dark"):
        out.pop("mode", None)
    sch = out.get("schedule")
    if isinstance(sch, dict):
        out["schedule"] = {
            "enabled": bool(sch.get("enabled")),
            "start": _norm_hhmm(sch.get("start"), "18:00"),
            "end":   _norm_hhmm(sch.get("end"), "08:00"),
        }
    else:
        out.pop("schedule", None)
    return out


def with_mode(spec, mode: str) -> dict:
    """Копия spec с заданным РУЧНЫМ режимом. 'dark' проставляет mode, иначе убирает."""
    out = normalize_spec(spec)
    if mode == "dark":
        out["mode"] = "dark"
    else:
        out.pop("mode", None)
    return out


def with_schedule(spec, enabled: bool, start: str = "18:00", end: str = "08:00") -> dict:
    """Копия spec с расписанием тёмной темы (вкл/выкл + окно времени)."""
    out = normalize_spec(spec)
    out["schedule"] = {"enabled": bool(enabled),
                       "start": _norm_hhmm(start, "18:00"),
                       "end": _norm_hhmm(end, "08:00")}
    return out


def get_schedule(spec) -> dict:
    """Расписание из spec с дефолтами (enabled=False, 18:00–08:00)."""
    sch = normalize_spec(spec).get("schedule")
    if isinstance(sch, dict):
        return sch
    return {"enabled": False, "start": "18:00", "end": "08:00"}


def _in_window(t: str, start: str, end: str) -> bool:
    """t/start/end — 'HH:MM'. Поддерживает окно ЧЕРЕЗ ПОЛНОЧЬ (start > end)."""
    if start == end:
        return False
    if start < end:
        return start <= t < end
    return t >= start or t < end   #напр. 18:00–08:00


def effective_mode(spec, now=None) -> str:
    """Фактический режим с учётом расписания. Если расписание включено — режим
    вычисляется по текущему времени; иначе берём ручной spec['mode'].
    now (datetime) — для тестируемости."""
    spec = spec if isinstance(spec, dict) else normalize_spec(spec)
    sch = spec.get("schedule")
    if isinstance(sch, dict) and sch.get("enabled"):
        t = (now or datetime.now()).strftime("%H:%M")
        return "dark" if _in_window(t, sch.get("start", "18:00"),
                                    sch.get("end", "08:00")) else "light"
    return "dark" if spec.get("mode") == "dark" else "light"


def is_dark(spec) -> bool:
    """True, если spec даёт тёмный режим прямо сейчас (с учётом расписания)."""
    return effective_mode(spec) == "dark"


#Сериализация темы в строку (хранится в config / в prefs пользователя).
def spec_to_json(spec: dict) -> str:
    return json.dumps(normalize_spec(spec), ensure_ascii=False)


def spec_from_json(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {"id": DEFAULT_ID}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"id": DEFAULT_ID}
    except (ValueError, TypeError):
        return {"id": DEFAULT_ID}
