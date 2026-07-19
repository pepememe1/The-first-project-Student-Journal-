"""
widgets.py — Переиспользуемые фабрики для создания UI элементов.
Цвета/типографику берём из дизайн-системы (styles.C + токены), поэтому виджеты
автоматически живут и в светлой, и в тёмной теме.
"""

from PySide6.QtWidgets import (
    QFrame, QLabel, QPushButton, QLineEdit, QComboBox, QVBoxLayout, QWidget,
    QGraphicsDropShadowEffect, QLayout
)
from PySide6.QtCore import Qt, QSize, QRect, QPoint
from PySide6.QtGui import QFontMetrics, QColor

import icons


def _shadow_color() -> QColor:
    """QColor мягкой тени из активной палитры (C['shadow'] вида rgba(r,g,b,a))."""
    s = C.get("shadow", "rgba(15,27,34,0.10)")
    try:
        nums = s[s.index("(") + 1:s.index(")")].split(",")
        c = QColor(int(nums[0]), int(nums[1]), int(nums[2]))
        c.setAlphaF(float(nums[3]) if len(nums) > 3 else 0.12)
        return c
    except Exception:
        c = QColor(0, 0, 0); c.setAlphaF(0.15); return c


def attach_shadow(widget, blur: int = 26, dy: int = 7):
    """Навешивает мягкую тень (глубина вместо жёсткой рамки). Цвет — из палитры, поэтому
    в тёмной теме тень глубже автоматически. Вызывать на карточках/поповерах."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setXOffset(0)
    eff.setYOffset(dy)
    eff.setColor(_shadow_color())
    widget.setGraphicsEffect(eff)
    return widget

from styles import C, BTN, SB, FONT_TITLE, FONT_BODY, H_INPUT


#CARD & FRAME FACTORIES

def card(parent=None) -> QFrame:
    """Создать основную карточку (card) с мягкой тенью-глубиной."""
    f = QFrame(parent)
    f.setObjectName("card")
    f.setFrameShape(QFrame.StyledPanel)
    attach_shadow(f)
    return f


def card2(parent=None) -> QFrame:
    """Создать карточку card2 (более светлая)"""
    f = QFrame(parent)
    f.setObjectName("card2")
    f.setFrameShape(QFrame.StyledPanel)
    return f


#LABEL FACTORIES

def lbl(text="", size=13, color=None, bold=False, parent=None, wrap=False) -> QLabel:
    """Создать стилизованный лейбл (DM Sans).

    wrap=True — включить перенос по словам. По умолчанию выключен (короткие подписи в
    рядах не должны менять высоту), но для длинных описаний его ОБЯЗАТЕЛЬНО включать:
    иначе длинный текст раздувает виджет шире области и уезжает за правый край окна."""
    l = QLabel(text, parent)
    s = f"font-size:{size}px;font-family:{FONT_BODY};"
    if color:
        s += f"color:{color};"
    if bold:
        s += "font-weight:700;"
    l.setStyleSheet(s)
    if wrap:
        l.setWordWrap(True)
    return l


class ElidingLabel(QLabel):
    """Лейбл, который сам укорачивает длинный текст многоточием по своей ширине, а
    полный текст показывает в подсказке. Нужен для шапки: ФИО бывают очень разной
    длины («Ли Ян» против «Будрин Владислав Владиславович»), и без эллипсиса длинное
    имя ломало бы вёрстку верхней панели. Ширину ограничивает maximumWidth — короткое
    имя показывается целиком, длинное — обрезается с «…»."""

    def __init__(self, text="", size=13, color=None, max_width=360, parent=None):
        super().__init__(parent)
        self._full = text or ""
        s = f"font-size:{size}px;font-family:{FONT_BODY};"
        if color:
            s += f"color:{color};"
        self.setStyleSheet(s)
        self.setMaximumWidth(max_width)
        self.setToolTip(self._full)
        self._apply_elide()

    def set_full_text(self, text: str):
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply_elide()

    def _apply_elide(self):
        fm = QFontMetrics(self.font())
        avail = self.width() if self.width() > 0 else self.maximumWidth()
        self.setText(fm.elidedText(self._full, Qt.ElideRight, max(10, avail)))

    def resizeEvent(self, event):
        self._apply_elide()
        super().resizeEvent(event)


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

def btn(text, style="ghost", parent=None, icon_name=None) -> QPushButton:
    """Создать кнопку. icon_name (необязательно) — иконка из icons.py слева от текста."""
    b = QPushButton(text, parent)
    b.setStyleSheet(BTN.get(style, BTN["ghost"]))
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(36)
    if icon_name and icons.has(icon_name):
        #цвет иконки — под вариант кнопки: на зелёной заливке белый, у red/blue — их цвет.
        col = {"green": "#FFFFFF", "sm_green": "#FFFFFF",
               "red": C["red"], "sm_red": C["red"], "blue": C["blue"]}.get(style, C["green"])
        b.setIcon(icons.icon(icon_name, col, 16))
        b.setIconSize(QSize(16, 16))
    return b


def sb_btn(icon_name, text, parent=None) -> QPushButton:
    """Кнопка сайдбара: иконка (icon_name) слева + текст. Если иконки нет — символ
    остаётся текстом (обратная совместимость со старыми эмодзи-метками)."""
    b = QPushButton(parent)
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(40)
    b.setCheckable(False)
    b._icon_name = icon_name
    if icons.has(icon_name):
        b.setText(f"  {text}")
        b.setIcon(icons.icon(icon_name, C["text3"], 18))
        b.setIconSize(QSize(18, 18))
    else:
        b.setText(f"  {icon_name}  {text}")
    b.setStyleSheet(SB["normal"])
    return b


#INPUT FACTORIES

def field_input(placeholder="", password=False) -> QLineEdit:
    """Создать поле ввода. Цвета/рамку/фокус задаёт глобальный QSS (styles), поэтому
    поле автоматически корректно в обеих темах — здесь только высота и поведение."""
    f = QLineEdit()
    f.setPlaceholderText(placeholder)
    if password:
        f.setEchoMode(QLineEdit.Password)
    f.setMinimumHeight(H_INPUT)
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


class FlowLayout(QLayout):
    """Layout, который ПЕРЕНОСИТ элементы на новую строку, когда они не влезают.

    Зачем. В журнале преподавателя девять кнопок и три выпадающих списка лежали в
    QHBoxLayout. Он не переносит — он СЖИМАЕТ: в неполноэкранном окне кнопки уезжали
    за край и часть из них была просто недоступна. Qt такого layout'а не даёт из
    коробки (это классический пример из документации), поэтому он здесь.

    Поведение: элементы идут слева направо; кончилась ширина — следующая строка.
    Высота считается по фактическому числу строк, поэтому родитель корректно
    выделяет место и ничего не обрезается.
    """

    def __init__(self, parent=None, margin=0, h_spacing=6, v_spacing=6):
        super().__init__(parent)
        self._items = []
        self._h = h_spacing
        self._v = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):          # noqa: N802 — имя из Qt API
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):              # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):              # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):    # noqa: N802
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):      # noqa: N802
        return True                   #высота зависит от ширины — в этом весь смысл

    def heightForWidth(self, width):  # noqa: N802
        return self._layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):      # noqa: N802
        super().setGeometry(rect)
        self._layout(rect, test_only=False)

    def sizeHint(self):               # noqa: N802
        return self.minimumSize()

    def minimumSize(self):            # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, test_only: bool) -> int:
        """Раскладывает элементы, возвращает итоговую ВЫСОТУ.
        test_only=True — только посчитать (для heightForWidth), ничего не двигая."""
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        line_h = 0
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            #Не влезает в текущую строку — переносим (кроме случая, когда строка пуста:
            #иначе одинокий широкий элемент уходил бы в бесконечный перенос).
            if line_h > 0 and x + w > right:
                x = rect.x() + m.left()
                y += line_h + self._v
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x += w + self._h
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()
