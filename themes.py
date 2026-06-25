"""
themes.py — Кастомные цветовые палитры (как темы в Google Chrome).

Идея простая и безопасная: палитра меняет только АКЦЕНТЫ интерфейса (основной
бирюзовый/зелёный слот `green` и его производные + вторичный `blue`), а нейтральные
поверхности (фон, карточки, границы, тёмный текст) берутся из БАЗОВОЙ палитры
ВСГУТУ. Так тёмный текст всегда читается на светлом, и ни одна тема не делает
интерфейс нечитаемым.

Тема описывается «спецификацией» (spec) — это маленький JSON:
    {"id": "<id пресета>"}                 — готовая палитра из PRESETS
    {"id": "custom", "accent": "#RRGGBB"}  — свой цвет (ползунки в редакторе)
    {"id": "default"}                       — стандартная тема ВСГУТУ

Применение: themes.apply_spec(spec) собирает полный словарь цветов и отдаёт его в
styles.apply_palette(...), затем переустанавливает глобальный QSS у приложения.
"""
import json

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import styles

#Снимок дефолтной палитры ВСГУТУ — источник НЕЙТРАЛЬНЫХ поверхностей (bg/card/
#border/text), которые кастом-темы не трогают. Снимаем один раз при импорте, до
#того как кто-либо успел сменить тему (styles.C ещё в заводском состоянии).
BASE = dict(styles.C)

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


def _derive(accent: str, accent2: str | None = None) -> dict:
    """По акценту собирает ПОЛНУЮ перекраску в формате styles.C: акценты + лёгкий
    оттенок фона/поверхностей под выбранную тему (как просили — почти белый с
    намёком на основной цвет), плюс шапка/границы."""
    blue = accent2 or _shift_value(accent, dv=30, ds=-25)   #вторичный — светлее/мягче
    return {
        #акценты
        "green":      accent,
        "green2":     _shift_value(accent, dv=-35),          #тёмный вариант (hover/pressed/шапка)
        "green_glow": _glow(accent, 0.10),
        "blue":       blue,
        #светлые поверхности с оттенком темы (почти белые, но оттенок виден)
        "bg":         _tint(accent, 0.10),                   #фон окна — лёгкий оттенок темы
        "bg2":        _tint(accent, 0.16),                   #сайдбар/подложки — чуть насыщеннее
        "card":       "#FFFFFF",                             #карточки оставляем белыми (контраст)
        "card2":      _tint(accent, 0.07),                   #вторичные карточки/инпуты
        "border":     _tint(accent, 0.22),
        "border2":    _tint(accent, 0.30),
    }


def build_palette(spec: dict) -> dict:
    """Собирает ПОЛНЫЙ словарь цветов (формат styles.C) по спецификации темы.

    Нейтральные поверхности — всегда из BASE; меняем только акцентные слоты."""
    spec = spec or {}
    tid = spec.get("id", DEFAULT_ID)
    cols = dict(BASE)

    if tid == DEFAULT_ID:
        return cols   #заводская тема ВСГУТУ — ничего не переопределяем

    if tid == "custom":
        accent = spec.get("accent") or BASE["green"]
        accent2 = spec.get("accent2")
    else:
        preset = _PRESET_BY_ID.get(tid)
        if not preset:
            return cols   #неизвестный id — безопасно откатываемся к базовой
        accent = preset["accent"]
        accent2 = preset.get("accent2")

    cols.update(_derive(accent, accent2))
    return cols


def swatch_colors(spec: dict) -> tuple:
    """(accent, accent2, surface) — три цвета для рисования кружка-превью палитры."""
    cols = build_palette(spec)
    return cols["green"], cols["blue"], BASE["card2"]


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


def normalize_spec(spec) -> dict:
    """Приводит вход к корректному spec (на случай мусора из БД/конфига)."""
    if isinstance(spec, str):
        spec = spec_from_json(spec)
    if not isinstance(spec, dict) or not spec.get("id"):
        return {"id": DEFAULT_ID}
    return spec


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
