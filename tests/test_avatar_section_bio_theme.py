"""
test_avatar_section_bio_theme.py — цвет текста поля «О себе» следует теме.

Раньше QTextEdit не имел собственного стиля и рисовался системной палитрой (белый
фон, чёрный текст) НЕЗАВИСИМО от темы приложения — на тёмной теме получался чёрный
текст на светлом поле. Проверяем, что стиль поля явно ссылается на текущий C['text'],
а не оставлен пустым.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_bio_field_has_explicit_theme_color(qapp, fresh_db):
    from styles import C
    from avatar_dialog import AvatarSection
    section = AvatarSection("student", {"f": "Иванова", "n": "Мария", "g": "к74/1"})
    assert C['text'] in section._bio.styleSheet(), \
        "поле «О себе» должно явно красить текст под тему, а не полагаться на системную палитру"


def test_bio_field_recolors_after_theme_switch(qapp, fresh_db):
    """Пересборка секции после смены темы должна взять НОВЫЙ цвет (C мутируется на месте,
    см. styles.apply_palette) — а не «запомнить» старый на момент первой сборки."""
    import styles
    from avatar_dialog import AvatarSection
    original_text = styles.C['text']
    try:
        styles.C['text'] = "#123456"
        section = AvatarSection("student", {"f": "Иванова", "n": "Мария", "g": "к74/1"})
        assert "#123456" in section._bio.styleSheet()
    finally:
        styles.C['text'] = original_text
