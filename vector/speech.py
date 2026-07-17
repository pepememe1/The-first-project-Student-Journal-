"""
speech.py — кадры состояния ЧАТА маскота «Вектор» (папка `речь/`, арт Арины).

Это ОТДЕЛЬНЫЙ от эмоций (vector/emotes.py) слой. Эмоции (морда+жест) показывают
настроение по успеваемости в советах на дашборде; а ЗДЕСЬ — простая анимация
«что сейчас делает помощник в чате»: говорит / думает / ждёт вопрос / молчит.
Именно эти 4 кадра показываются в боковой шторке Вектора и в отдельном окне
«ИИ Помощник» (раньше там была эмодзи-заглушка).

Файлы (полноростовые PNG, прозрачный фон ~1536×2048):
    говорит.png · думает.png · ждет.png · молчит.png

Состояния машины маскота → файл:
    speaking → говорит   thinking → думает   idle → ждет   away → молчит

Грузим лениво и кэшируем уменьшенную по высоте версию — как в emotes.py, чтобы
тяжёлые PNG не висели в памяти в полном разрешении.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

#Имя папки с речью у Арины — лежит в каталоге ассетов `emotions/`.
_DIR_PARTS = ("emotions", "речь")
#Анимированные состояния чата (WebP с альфой) — приоритетнее статичных PNG выше.
#Тот же WebP играет и в браузере (веб/мобилка), и в Qt (десктоп) — общий формат.
_ANIM_PARTS = ("emotions", "анимации")
MAX_CACHE_H = 760           #до какой высоты ужимаем кадр при загрузке (px)

#Состояние машины маскота (см. widget.py) → базовое имя файла без расширения.
STATE_FILE = {
    "speaking": "говорит",
    "thinking": "думает",
    "idle": "ждет",
    "away": "молчит",
}
#Состояние → базовое имя анимированного файла (WebP). «away» живёт тем же покоем, что idle;
#«greeting» — появление (проигрывается один раз при первом показе панели).
STATE_ANIM = {
    "speaking": "speaking",
    "thinking": "thinking",
    "idle": "idle",
    "away": "idle",
    "greeting": "greeting",
}
DEFAULT_STATE = "idle"

_dir_cache = None           #найденная папка речи (или "")
_anim_dir_cache = None      #найденная папка анимаций (или "")
_pix_cache = {}             #имя файла -> QPixmap (уже уменьшенный)


def _find_dir() -> str:
    """Ищем папку `emotions/речь` рядом с программой, проектом и пакетом vector.

    Кандидатов несколько, потому что приложение запускают и из исходников (cwd =
    корень проекта), и собранным .exe (рядом с exe). Берём первую существующую."""
    global _dir_cache
    if _dir_cache is not None:
        return _dir_cache
    here = os.path.dirname(os.path.abspath(__file__))      # .../vector
    root = os.path.dirname(here)                            # корень проекта
    rel = os.path.join(*_DIR_PARTS)
    candidates = [
        os.path.join(os.getcwd(), rel),
        os.path.join(root, rel),
        os.path.join(here, rel),
        #на случай, если папку «речь» положат без обёртки emotions/
        os.path.join(os.getcwd(), _DIR_PARTS[-1]),
        os.path.join(root, _DIR_PARTS[-1]),
    ]
    #если доступен app_paths (портативный .exe) — добавим путь рядом с программой
    try:
        import app_paths
        candidates.insert(0, os.path.join(app_paths.app_dir(), rel))
    except Exception:
        pass
    _dir_cache = next((c for c in candidates if os.path.isdir(c)), "")
    return _dir_cache


def has_art() -> bool:
    """Есть ли вообще папка с речью (иначе маскот живёт на эмодзи-заглушке)."""
    return bool(_find_dir())


def _find_anim_dir() -> str:
    """Ищем папку `emotions/анимации` (анимированные WebP чата). Та же логика, что и у
    статичной `речь`: приложение запускают из исходников (cwd=корень) и собранным .exe."""
    global _anim_dir_cache
    if _anim_dir_cache is not None:
        return _anim_dir_cache
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    rel = os.path.join(*_ANIM_PARTS)
    candidates = [
        os.path.join(os.getcwd(), rel),
        os.path.join(root, rel),
        os.path.join(here, rel),
    ]
    try:
        import app_paths
        candidates.insert(0, os.path.join(app_paths.app_dir(), rel))
    except Exception:
        pass
    _anim_dir_cache = next((c for c in candidates if os.path.isdir(c)), "")
    return _anim_dir_cache


def anim_path(state: str = DEFAULT_STATE) -> str:
    """Полный путь к анимированному WebP для состояния чата (или '', если анимации нет).
    Приоритетнее статичного get() — если файл есть, маскот в чате живёт анимацией."""
    base = _find_anim_dir()
    if not base:
        return ""
    name = STATE_ANIM.get(state, STATE_ANIM[DEFAULT_STATE])
    path = os.path.join(base, name + ".webp")
    return path if os.path.isfile(path) else ""


def has_anim() -> bool:
    """Есть ли папка анимаций (тогда чат-маскот анимирован, а не статичен)."""
    return bool(_find_anim_dir())


def get(state: str = DEFAULT_STATE):
    """QPixmap кадра для состояния чата (или None, если арта нет).

    Грузим один раз, кэшируем уже уменьшенную по высоте версию (≤ MAX_CACHE_H)."""
    name = STATE_FILE.get(state, STATE_FILE[DEFAULT_STATE])
    if name in _pix_cache:
        return _pix_cache[name]
    base = _find_dir()
    if not base:
        return None
    path = os.path.join(base, name + ".png")
    if not os.path.isfile(path):
        _pix_cache[name] = None
        return None
    pm = QPixmap(path)
    if pm.isNull():
        _pix_cache[name] = None
        return None
    if pm.height() > MAX_CACHE_H:
        pm = pm.scaledToHeight(MAX_CACHE_H, Qt.SmoothTransformation)
    _pix_cache[name] = pm
    return pm
