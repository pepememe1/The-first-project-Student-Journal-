"""
fonts.py — Шрифты GradeBookAI.

Используются СИСТЕМНЫЕ шрифты (на ПК колледжа под Windows — Segoe UI).
Никакой загрузки из интернета: предсказуемо, работает офлайн, без сбоев на старте.
При желании можно положить .ttf-файлы в папку fonts/ рядом с программой —
они будут зарегистрированы автоматически.

Использование в main.py (после создания QApplication):
    from fonts import load_fonts
    load_fonts()
"""
import os
import sys

from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication

#Приоритет — фирменный DM Sans (если .ttf лежит в fonts/), иначе системный Segoe UI.
_BODY_CANDIDATES  = ["DM Sans", "Segoe UI", "PT Sans", "Arial", "Helvetica", "sans-serif"]


def _get_fonts_dir() -> str:
    """Папка fonts/ рядом с .exe/скриптом или в распаковке onefile (_MEIPASS)."""
    if getattr(sys, "frozen", False):
        #onefile: ассеты распакованы во временный sys._MEIPASS — рядом с .exe их нет.
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass and os.path.isdir(os.path.join(meipass, "fonts")):
            return os.path.join(meipass, "fonts")
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "fonts")


def _pick(candidates: list) -> str:
    """Первый доступный в системе шрифт из списка кандидатов."""
    available = set(QFontDatabase.families())
    for fam in candidates:
        if fam in available:
            return fam
    return candidates[0]


def load_fonts() -> dict:
    """
    Регистрирует локальные .ttf из папки fonts/ (если они есть) и
    выставляет дефолтный шрифт приложения.

    Вызывать ПОСЛЕ создания QApplication.
    """
    loaded: dict = {}
    fonts_dir = _get_fonts_dir()
    if os.path.isdir(fonts_dir):
        for fn in os.listdir(fonts_dir):
            if fn.lower().endswith((".ttf", ".otf")):
                fid = QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fn))
                if fid >= 0:
                    for fam in QFontDatabase.applicationFontFamilies(fid):
                        loaded[fam] = loaded.get(fam, 0) + 1

    app = QApplication.instance()
    if app:
        app.setFont(QFont(_pick(_BODY_CANDIDATES), 10))

    print(f"[Fonts] Основной шрифт: {_pick(_BODY_CANDIDATES)}")
    return loaded
