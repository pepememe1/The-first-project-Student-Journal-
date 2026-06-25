"""
widgets.py — Переиспользуемые фабрики для создания UI элементов
Шрифты: Syne для заголовков, DM Sans для текста (как на сайте Synapse).
"""

from PySide6.QtWidgets import (
    QFrame, QLabel, QPushButton, QLineEdit, QComboBox, QVBoxLayout, QWidget
)
from PySide6.QtCore import Qt

from styles import C, BTN, SB, FONT_TITLE, FONT_BODY


#CARD & FRAME FACTORIES

def card(parent=None) -> QFrame:
    """Создать основную карточку (card)"""
    f = QFrame(parent)
    f.setObjectName("card")
    f.setFrameShape(QFrame.StyledPanel)
    return f


def card2(parent=None) -> QFrame:
    """Создать карточку card2 (более светлая)"""
    f = QFrame(parent)
    f.setObjectName("card2")
    f.setFrameShape(QFrame.StyledPanel)
    return f


#LABEL FACTORIES

def lbl(text="", size=13, color=None, bold=False, parent=None) -> QLabel:
    """Создать стилизованный лейбл (DM Sans)"""
    l = QLabel(text, parent)
    s = f"font-size:{size}px;font-family:{FONT_BODY};"
    if color:
        s += f"color:{color};"
    if bold:
        s += "font-weight:700;"
    l.setStyleSheet(s)
    return l


def title_lbl(text, size=22) -> QLabel:
    """Создать заголовок — Syne ExtraBold (как на сайте)"""
    l = QLabel(text)
    l.setObjectName("title")
    l.setStyleSheet(
        f"font-size:{size}px;"
        f"font-weight:800;"
        f"color:{C['text']};"
        f""
        f"font-family:{FONT_TITLE};"
    )
    return l


def vector_unavailable_widget(parent=None) -> QWidget:
    """Заглушка на случай, если панель Вектора не смогла собраться.
    Раньше при сбое подключался отдельный облачный чат — его убрали, поэтому теперь
    просто показываем понятное сообщение, а не пустой экран."""
    w = QWidget(parent)
    lay = QVBoxLayout(w)
    lay.setContentsMargins(24, 24, 24, 24)
    lay.setSpacing(8)
    lay.addWidget(title_lbl("🐯  Вектор временно недоступен", 18))
    lay.addWidget(lbl("Не удалось запустить ИИ-помощника. Перезапустите приложение, "
                      "а если не помогло — сообщите администратору.", 13, C['text3']))
    lay.addStretch()
    return w


def section_lbl(text) -> QLabel:
    """Создать заголовок секции — Syne Bold (как на сайте)"""
    l = QLabel(text)
    l.setStyleSheet(
        f"font-size:16px;"
        f"font-weight:700;"
        f"color:{C['text']};"
        f"margin-bottom:4px;"
        f"font-family:{FONT_TITLE};"
    )
    return l


def badge(text, color="green") -> QLabel:
    """Создать бейдж (значок)"""
    colors = {
        "green": (C['green'], "rgba(20,124,139,0.12)", "rgba(20,124,139,0.3)"),
        "blue":  (C['blue'],  "rgba(43,166,184,0.12)", "rgba(43,166,184,0.3)")
    }
    fg, bg, br = colors.get(color, colors["green"])
    l = QLabel(text)
    l.setStyleSheet(
        f"color:{fg};background:{bg};border:1px solid {br};"
        f"border-radius:100px;padding:3px 10px;"
        f"font-size:11px;font-weight:500;font-family:{FONT_BODY};"
    )
    return l


#BUTTON FACTORIES

def btn(text, style="ghost", parent=None) -> QPushButton:
    """Создать кнопку с определённым стилем"""
    b = QPushButton(text, parent)
    b.setStyleSheet(BTN.get(style, BTN["ghost"]))
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(36)
    return b


def sb_btn(icon, text, parent=None) -> QPushButton:
    """Создать кнопку для сайдбара (sidebar button)"""
    b = QPushButton(f"  {icon}  {text}", parent)
    b.setStyleSheet(SB["normal"])
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(36)
    b.setCheckable(False)
    return b


#INPUT FACTORIES

def field_input(placeholder="", password=False) -> QLineEdit:
    """Создать стилизованное поле ввода"""
    f = QLineEdit()
    f.setPlaceholderText(placeholder)
    if password:
        f.setEchoMode(QLineEdit.Password)
    f.setMinimumHeight(38)
    f.setStyleSheet(
        f"QLineEdit{{background:{C['card2']};border:1px solid {C['border2']};"
        f"border-radius:8px;padding:8px 12px;color:#16282D;"
        f"font-size:13px;font-family:{FONT_BODY};}}"
        f"QLineEdit:focus{{border:1px solid {C['green']};}}"
    )
    return f


def combo(items=None) -> QComboBox:
    """Создать выпадающее меню (комбобокс)"""
    c = QComboBox()
    if items:
        c.addItems(items)
    c.setMinimumHeight(36)
    return c


#SEPARATOR FACTORIES

def separator() -> QFrame:
    """Создать горизонтальный разделитель"""
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{C['border']};background:{C['border']};max-height:1px;")
    return f


def vline() -> QFrame:
    """Создать вертикальный разделитель"""
    f = QFrame()
    f.setFrameShape(QFrame.VLine)
    f.setStyleSheet(f"color:{C['border']};")
    return f


#STAT CARD FACTORY

def stat_card(label: str, value: str, color="text") -> QFrame:
    """Создать статистическую карточку (число — Syne, текст — DM Sans)"""
    colors = {
        "green": C['green'],
        "blue":  C['blue'],
        "orange": C['orange'],
        "text":  C['text'],
    }
    c_val = colors.get(color, C['text'])

    f = card()
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(4)

    #Метка — DM Sans uppercase
    lbl_w = QLabel(label.upper())
    lbl_w.setStyleSheet(
        f"font-size:10px;color:{C['text2']};font-family:{FONT_BODY};"
    )
    lay.addWidget(lbl_w)

    #Значение — Syne Bold (как цифры на сайте)
    val_w = QLabel(value)
    val_w.setStyleSheet(
        f"font-size:28px;font-weight:800;color:{c_val};"
        f"font-family:{FONT_TITLE};"
    )
    lay.addWidget(val_w)

    return f
