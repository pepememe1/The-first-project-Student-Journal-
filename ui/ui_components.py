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
from widgets import lbl, sb_btn, vline, ElidingLabel
import icons


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
        #250px — чтобы длинные пункты («Запросы на подключение») влезали целиком
        #на базовом шрифте 14px и не обрезались в оконном режиме.
        self.setFixedWidth(250)
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
        """Активировать кнопку и выключить остальные (иконку активной красим в акцент)"""
        for k, b in self._buttons.items():
            active = (k == key)
            b.setStyleSheet(SB["active"] if active else SB["normal"])
            b.setCheckable(False)
            name = getattr(b, "_icon_name", None)
            if name and icons.has(name):
                b.setIcon(icons.icon(name, C["green"] if active else C["text3"], 18))
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
        #ФИО может быть длинным — эллипсис по ширине + полное имя в подсказке,
        #чтобы верхняя панель не «разъезжалась» на длинных ФИО.
        self.user_lbl   = ElidingLabel("", 13, "#EAF6F8", max_width=360)
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
        """Установить информацию о роли пользователя.

        Если имя пользователя пустое или дословно совпадает с ролью (как у админа,
        чья «личность» — это и есть «Администратор»), вторую подпись не показываем —
        иначе в углу два раза подряд выводится «Администратор»."""
        self.role_badge.setText(role_text)
        name = (user_text or "").strip()
        if not name or name.casefold() == (role_text or "").strip().casefold():
            self.user_lbl.set_full_text("")
            self.user_lbl.hide()
        else:
            self.user_lbl.set_full_text(name)
            self.user_lbl.show()

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
    """Фон ВСГУТУ. Два режима:

    • статичный (по умолчанию) — мягкий градиент + едва заметная сетка, ноль нагрузки;
    • анимированный (`animated=True`, используется на экране входа) — поверх градиента
      плывут частицы и полупрозрачные шестиугольники-«соты» (отсыл к лого GB) плюс
      мягкие световые пятна за карточкой. Молодёжно-профессиональный вид, а не «госсайт».

    Анимация лёгкая: ~30 fps, ~26 частиц, таймер живёт только пока виджет на экране
    (showEvent/hideEvent), поэтому CPU практически не нагружается. Все цвета берём из
    активной палитры темы (C) — фон сам подстраивается под свет/тьму."""

    def __init__(self, parent=None, animated=False):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._animated = animated
        self._t = 0                      #счётчик кадров (для плавных колебаний)
        self._particles = []             #летящие точки
        self._hexes = []                 #дрейфующие шестиугольники
        self._blobs = []                 #мягкие световые пятна
        self._timer = None
        if animated:
            self._timer = QTimer(self)
            self._timer.setInterval(33)  #~30 fps
            self._timer.timeout.connect(self._tick)

    #--- жизненный цикл анимации (бережём CPU: крутим только пока виден) ---
    def showEvent(self, event):
        if self._animated and self._timer is not None:
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        if self._timer is not None:
            self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._t += 1
        self._advance()
        self.update()

    def _seed(self):
        """Создаём частицы/шестиугольники/пятна под текущий размер окна."""
        W, H = max(self.width(), 1), max(self.height(), 1)
        self._particles = []
        for _ in range(30):
            self._particles.append({
                "x": random.uniform(0, W), "y": random.uniform(0, H),
                "r": random.uniform(2.0, 5.0),
                "vx": random.uniform(-0.25, 0.25), "vy": random.uniform(-0.55, -0.15),
                "a": random.uniform(0.30, 0.70),         #базовая прозрачность (заметнее)
                "ph": random.uniform(0, math.tau),       #фаза мерцания
            })
        self._hexes = []
        for _ in range(5):
            self._hexes.append({
                "x": random.uniform(0, W), "y": random.uniform(0, H),
                "R": random.uniform(40, 110),
                "vx": random.uniform(-0.18, 0.18), "vy": random.uniform(-0.18, 0.18),
                "ang": random.uniform(0, math.pi), "spin": random.uniform(-0.004, 0.004),
            })
        #пара мягких пятен — статичные опорные точки, слегка «дышат» в _advance
        self._blobs = [
            {"x": W * 0.30, "y": H * 0.35, "R": max(W, H) * 0.28},
            {"x": W * 0.72, "y": H * 0.62, "R": max(W, H) * 0.22},
        ]

    def _advance(self):
        """Сдвигаем частицы/шестиугольники; на краях заворачиваем (бесшовно)."""
        W, H = max(self.width(), 1), max(self.height(), 1)
        if not self._particles:
            self._seed()
        for pt in self._particles:
            pt["x"] += pt["vx"]; pt["y"] += pt["vy"]
            if pt["y"] < -5: pt["y"] = H + 5; pt["x"] = random.uniform(0, W)
            if pt["x"] < -5: pt["x"] = W + 5
            elif pt["x"] > W + 5: pt["x"] = -5
        for hx in self._hexes:
            hx["x"] += hx["vx"]; hx["y"] += hx["vy"]; hx["ang"] += hx["spin"]
            if hx["x"] < -hx["R"]: hx["x"] = W + hx["R"]
            elif hx["x"] > W + hx["R"]: hx["x"] = -hx["R"]
            if hx["y"] < -hx["R"]: hx["y"] = H + hx["R"]
            elif hx["y"] > H + hx["R"]: hx["y"] = -hx["R"]

    def resizeEvent(self, event):
        if self._animated:
            self._seed()       #пересоздаём под новый размер
        super().resizeEvent(event)

    def _hexagon(self, cx, cy, r, ang=0.0) -> QPolygonF:
        return QPolygonF([
            QPointF(cx + r * math.cos(ang + math.radians(a)),
                    cy + r * math.sin(ang + math.radians(a)))
            for a in range(0, 360, 60)
        ])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()

        #Мягкий вертикальный градиент из АКТИВНОЙ палитры (bg → bg2): сам подстраивается
        #под светлую/тёмную тему, без захардкоженных светлых цветов.
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0.0, QColor(C['bg']))
        grad.setColorAt(1.0, QColor(C['bg2']))
        p.fillRect(0, 0, W, H, QBrush(grad))

        if not self._animated:
            #Едва заметная сетка акцентным цветом темы (очень низкая прозрачность).
            acc = QColor(C['green']); acc.setAlpha(10)
            p.setPen(QPen(acc, 1))
            step = 64
            for x in range(0, W, step):
                p.drawLine(x, 0, x, H)
            for y in range(0, H, step):
                p.drawLine(0, y, W, y)
            p.end()
            return

        if not self._particles:
            self._seed()

        #1) Мягкие световые пятна (глубина за карточкой) — радиальные градиенты.
        from PySide6.QtGui import QRadialGradient
        for i, b in enumerate(self._blobs):
            pulse = 0.5 + 0.5 * math.sin(self._t * 0.01 + i)
            rg = QRadialGradient(b["x"], b["y"], b["R"])
            base = QColor(C['green2'] if i else C['green'])
            c0 = QColor(base); c0.setAlpha(int(26 + 14 * pulse))
            c1 = QColor(base); c1.setAlpha(0)
            rg.setColorAt(0.0, c0); rg.setColorAt(1.0, c1)
            p.setPen(Qt.NoPen); p.setBrush(QBrush(rg))
            p.drawEllipse(QPointF(b["x"], b["y"]), b["R"], b["R"])

        #2) Шестиугольники-«соты» (контур + заливка) — отсыл к лого GB. Заметнее, чем
        #раньше: толще контур и выше прозрачность, чтобы фигуры читались, а не терялись.
        for hx in self._hexes:
            poly = self._hexagon(hx["x"], hx["y"], hx["R"], hx["ang"])
            edge = QColor(C['green']); edge.setAlpha(70)
            fill = QColor(C['green']); fill.setAlpha(20)
            p.setPen(QPen(edge, 2.0)); p.setBrush(QBrush(fill))
            p.drawPolygon(poly)

        #3) Частицы (мерцают по фазе) — лёгкое «звёздное» поле в цвет акцента.
        p.setPen(Qt.NoPen)
        for pt in self._particles:
            tw = 0.65 + 0.35 * math.sin(self._t * 0.05 + pt["ph"])
            col = QColor(C['green']); col.setAlpha(int(max(0, min(255, pt["a"] * tw * 255))))
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(pt["x"], pt["y"]), pt["r"], pt["r"])

        p.end()
