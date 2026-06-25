"""
ui_components.py — Компоненты UI (Sidebar, HeaderBar, LogoWidget, AnimatedBackground)
"""

import math
import random
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QPainter, QPen, QPolygonF, QBrush, QColor, QFont, QLinearGradient
from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)

from styles import C, SB
from widgets import lbl, sb_btn, vline


#SIDEBAR WIDGET

class Sidebar(QFrame):
    """Боковая панель навигации с кнопками вкладок"""
    
    from PySide6.QtCore import Signal as QSignal
    tab_clicked = QSignal(str)

    def __init__(self, items: list, parent=None):
        """
        items: список кортежей (key, icon, label) или ('__label__', '', 'Section Label')
        """
        super().__init__(parent)
        self.setFixedWidth(210)
        self.setStyleSheet(
            f"QFrame{{background:{C['bg2']};border-right:1px solid {C['border']};}}"
        )
        self._buttons = {}
        self._active  = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 16, 10, 16)
        lay.setSpacing(2)

        for item in items:
            key, icon, text = item
            if key == "__label__":
                #Это метка секции
                l = lbl(text.upper(), 10, C['text2'])
                l.setStyleSheet(l.styleSheet() + "padding:14px 10px 4px 10px;")
                lay.addWidget(l)
            else:
                #Это кнопка
                b = sb_btn(icon, text)
                b.clicked.connect(lambda checked, k=key: self._activate(k))
                self._buttons[key] = b
                lay.addWidget(b)

        lay.addStretch()

    def _activate(self, key):
        """Активировать кнопку и выключить остальные"""
        for k, b in self._buttons.items():
            b.setStyleSheet(SB["active"] if k == key else SB["normal"])
            b.setCheckable(False)
        self._active = key
        self.tab_clicked.emit(key)

    def set_active(self, key):
        """Установить активную кнопку"""
        self._activate(key)


#HEADER BAR

class HeaderBar(QFrame):
    """Верхняя панель с логотипом, инфо о пользователе и кнопкой выхода"""
    
    from PySide6.QtCore import Signal as QSignal
    logout_clicked = QSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.refresh_theme()
        
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(10)

        #Logo box (GB)
        hex_lbl = QLabel()
        hex_lbl.setFixedSize(32, 32)
        hex_lbl.setText("GB")
        hex_lbl.setAlignment(Qt.AlignCenter)
        hex_lbl.setStyleSheet(
            "color:#FFFFFF;font-size:11px;font-weight:800;"
            "background:rgba(255,255,255,0.16);border:1.5px solid rgba(255,255,255,0.55);"
            "border-radius:6px;"
        )
        
        logo_text = QLabel("GRADEBOOK")
        logo_text.setStyleSheet(
            "font-size:15px;font-weight:800;color:#FFFFFF;"
        )
        college_text = QLabel("Технологический колледж ВСГУТУ")
        college_text.setStyleSheet(
            "font-size:10px;font-weight:600;color:rgba(255,255,255,0.82);"
        )
        logo_box = QVBoxLayout()
        logo_box.setContentsMargins(0, 0, 0, 0)
        logo_box.setSpacing(0)
        logo_box.addWidget(logo_text)
        logo_box.addWidget(college_text)

        lay.addWidget(hex_lbl)
        lay.addLayout(logo_box)
        lay.addStretch()

        #User info
        from widgets import badge
        self.role_badge = badge("", "green")
        self.role_badge.setStyleSheet(
            "background:rgba(255,255,255,0.18);border:1px solid rgba(255,255,255,0.5);"
            "color:#FFFFFF;border-radius:100px;padding:3px 10px;font-size:11px;"
        )
        self.user_lbl   = lbl("", 13, "#EAF6F8")
        lay.addWidget(self.role_badge)
        lay.addWidget(self.user_lbl)

        sep = vline()
        sep.setFixedHeight(20)
        lay.addWidget(sep)

        #Logout button
        logout = QPushButton("Выйти")
        logout.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.15);color:#FFFFFF;"
            "border:1px solid rgba(255,255,255,0.5);border-radius:8px;padding:5px 14px;font-size:12px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.28);}"
        )
        logout.setCursor(Qt.PointingHandCursor)
        logout.clicked.connect(self.logout_clicked)
        lay.addWidget(logout)

    def set_role(self, role_text, user_text):
        """Установить информацию о роли пользователя"""
        self.role_badge.setText(role_text)
        self.user_lbl.setText(user_text)

    def refresh_theme(self):
        """Перекрасить верхнюю полосу в цвет активной темы. Шапка создаётся один раз
        (не пересобирается с дашбордом), поэтому при смене темы её обновляем явно —
        отсюда, читая текущий C['green']/C['green2']."""
        self.setStyleSheet(
            "QFrame{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f"stop:0 {C['green']}, stop:1 {C['green2']});"
            f"border-bottom:1px solid {C['green2']};}}"
        )


#HEX LOGO WIDGET

class HexLogoWidget(QWidget):
    """Логотип-шестиугольник (как на сайте Synapse)"""
    
    def __init__(self, size=60, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._size = size

    def paintEvent(self, event):
        """Нарисовать шестиугольник"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        cx = self._size / 2
        cy = self._size / 2
        r = self._size * 0.46
        
        #Внешний шестиугольник
        pts = QPolygonF([
            QPointF(cx + r * math.cos(math.radians(a - 90)), 
                   cy + r * math.sin(math.radians(a - 90)))
            for a in range(0, 360, 60)
        ])
        p.setPen(QPen(QColor("#147C8B"), 1.5))
        p.setBrush(QBrush(QColor(20, 124, 139, 10)))
        p.drawPolygon(pts)
        
        #Внутренний шестиугольник
        r2 = r * 0.72
        pts2 = QPolygonF([
            QPointF(cx + r2 * math.cos(math.radians(a - 90)), 
                   cy + r2 * math.sin(math.radians(a - 90)))
            for a in range(0, 360, 60)
        ])
        p.setPen(QPen(QColor(20, 124, 139, 60), 1))
        p.setBrush(QBrush(QColor(20, 124, 139, 18)))
        p.drawPolygon(pts2)
        
        #Текст "GB"
        p.setPen(QPen(QColor("#147C8B")))
        f = QFont("Segoe UI", int(self._size * 0.22), QFont.Bold)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, "GB")
        p.end()


#ANIMATED BACKGROUND

class AnimatedBackground(QWidget):
    """Чистый статичный институциональный фон ВСГУТУ.

    Мягкий светлый градиент с едва заметной бирюзовой сеткой.
    Без анимации и частиц — спокойный вид и нулевая нагрузка на CPU.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()

        #Мягкий вертикальный градиент: светлый фон -> чуть теплее книзу
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0.0, QColor("#EDF2F3"))
        grad.setColorAt(1.0, QColor("#E6EEEF"))
        p.fillRect(0, 0, W, H, QBrush(grad))

        #Едва заметная бирюзовая сетка (институциональный, спокойный акцент)
        p.setPen(QPen(QColor(20, 124, 139, 8), 1))
        step = 64
        for x in range(0, W, step):
            p.drawLine(x, 0, x, H)
        for y in range(0, H, step):
            p.drawLine(0, y, W, y)

        p.end()
