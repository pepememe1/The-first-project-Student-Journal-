"""
emotes.py — Реестр эмоций маскота «Вектор» (арт Арины).

Арт лежит в папке `emotes/` рядом с программой. Каждый файл — это комбинация
ВЫРАЖЕНИЯ МОРДЫ и ЖЕСТА/ПОЗЫ, имя вида «<морда>+<жест>.png»:

    морды (FACES):     груст · деф · думает · предупреж · рад · удив
    жесты (GESTURES):  деф · думает · подбадрив · поздрав · предупреж

Итого матрица 6×5 = 30 спрайтов в полный рост (прозрачный фон ~1536×2048).

Зачем отдельный модуль: картинки тяжёлые (по ~1.2 МБ PNG), поэтому грузим их
ЛЕНИВО и кэшируем уже уменьшенную версию (по высоте ≤ MAX_CACHE_H) — память не
раздувается, а на экране всё равно показываем максимум ~420 px.

`pick(state, mood, intent)` — главная функция: по состоянию машины маскота
(idle/thinking/speaking/away), настроению ответа (happy/neutral/sad) и намерению
(intent) выбирает осмысленную пару (морда, жест). Задействованы ВСЕ 6 выражений и
ВСЕ 5 жестов, поэтому Вектор проживает весь эмоциональный диапазон от Арины.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

#Папка с артом (имя как у Арины — рядом с программой/пакетом)
EMOTES_DIR = "emotes"
MAX_CACHE_H = 760           #до какой высоты ужимаем спрайт при загрузке (px)

#словарь морд и жестов (ключи = части имени файла)
FACES = ("груст", "деф", "думает", "предупреж", "рад", "удив")
GESTURES = ("деф", "думает", "подбадрив", "поздрав", "предупреж")

#дефолт — нейтральный Вектор «руки в карманах» (морда деф, жест деф)
DEFAULT_FACE = "деф"
DEFAULT_GESTURE = "деф"

#интенты, на которые Вектор реагирует особым образом
_WARN_INTENTS = {"debtors", "absences", "at_risk"}        #строго предупреждает
_INFO_INTENTS = {"help", "about_vsgutu", "about_college",  #спокойно рассказывает
                 "groups", "teachers", "roster", "group_stats"}

_dir_cache = None           #найденная папка emotes (или "")
_pix_cache = {}             #(face, gesture) -> QPixmap (уже уменьшенный)


def _find_dir() -> str:
    """Ищем папку с артом эмоций рядом с программой и рядом с пакетом vector.

    ВАЖНО про порядок: сначала ищем НОВУЮ раскладку `emotions/эмоции/` (актуальный арт
    Арины — все 30 пар «морда+жест»), и только потом историческую `emotes/`. Раньше
    приоритет был обратный, поэтому в кабинете студента показывался старый/образцовый
    набор из `emotes/`, а не подобранная по совету эмоция из `emotions/эмоции/`."""
    global _dir_cache
    if _dir_cache is not None:
        return _dir_cache
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)                            #корень проекта
    emotions_subdir = os.path.join("emotions", "эмоции")    #новая раскладка (приоритет)
    candidates = [
        os.path.join(os.getcwd(), emotions_subdir),
        os.path.join(root, emotions_subdir),
        os.path.join(here, emotions_subdir),
        #исторический fallback — старая папка `emotes/` рядом с программой/пакетом
        os.path.join(os.getcwd(), EMOTES_DIR),
        os.path.join(root, EMOTES_DIR),
        os.path.join(here, EMOTES_DIR),
    ]
    #если доступен app_paths (портативный .exe) — путь рядом с программой ставим первым
    try:
        import app_paths
        candidates.insert(0, os.path.join(app_paths.app_dir(), emotions_subdir))
    except Exception:
        pass
    _dir_cache = next((c for c in candidates if os.path.isdir(c)), "")
    return _dir_cache


def filename(face: str, gesture: str) -> str:
    """Имя файла спрайта для пары (морда, жест)."""
    return f"{face}+{gesture}.png"


def has_art() -> bool:
    """Есть ли вообще папка с артом (иначе маскот живёт на эмодзи-заглушке)."""
    return bool(_find_dir())


def get(face: str = DEFAULT_FACE, gesture: str = DEFAULT_GESTURE):
    """QPixmap спрайта (морда, жест) или None, если файла нет.

    Грузим один раз, кэшируем уже уменьшенную по высоте версию (≤ MAX_CACHE_H),
    чтобы 30 тяжёлых PNG не висели в памяти в полном разрешении."""
    key = (face, gesture)
    if key in _pix_cache:
        return _pix_cache[key]
    base = _find_dir()
    if not base:
        return None
    path = os.path.join(base, filename(face, gesture))
    if not os.path.isfile(path):
        _pix_cache[key] = None
        return None
    pm = QPixmap(path)
    if pm.isNull():
        _pix_cache[key] = None
        return None
    if pm.height() > MAX_CACHE_H:
        pm = pm.scaledToHeight(MAX_CACHE_H, Qt.SmoothTransformation)
    _pix_cache[key] = pm
    return pm


def pick(state: str, mood: str = "neutral", intent: str = "help"):
    """(морда, жест) под текущее поведение маскота.

    state — состояние машины: idle / thinking / speaking / away.
    mood  — настроение ответа: happy / neutral / sad.
    intent — намерение из движка (debtors, average, hello, ...).

    Задействованы все 6 морд и все 5 жестов:
      • thinking → думает+думает         (обдумывает вопрос)
      • away     → деф+деф               (расслаблен, руки в карманах)
      • idle     → удив+деф              (заметил курсор — насторожился)
      • warning-интенты → предупреж+предупреж   (долги/пропуски/зона риска)
      • hello    → рад+поздрав           (радостно здоровается)
      • thanks   → рад+подбадрив         (рад помочь)
      • happy    → рад+поздрав           (хорошие оценки/балл — поздравляет)
      • sad      → груст+подбадрив       (плохо, но подбадривает — «не сдавайся»)
      • инфо     → деф+подбадрив         (спокойно рассказывает, жестикулируя)
      • иначе    → деф+деф
    """
    if state == "thinking":
        return ("думает", "думает")
    if state == "away":
        return ("деф", "деф")
    if state == "idle":
        return ("удив", "деф")

    #speaking — самое богатое состояние: морду/жест ведут intent и настроение
    if intent in _WARN_INTENTS:
        return ("предупреж", "предупреж")
    if intent == "hello":
        return ("рад", "поздрав")
    if intent == "thanks":
        return ("рад", "подбадрив")
    if mood == "happy":
        return ("рад", "поздрав")
    if mood == "sad":
        return ("груст", "подбадрив")
    if intent in _INFO_INTENTS:
        return ("деф", "подбадрив")
    return ("деф", "деф")
