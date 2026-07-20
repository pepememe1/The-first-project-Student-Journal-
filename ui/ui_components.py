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

        #Утверждённый фирменный знак: вращающийся гексагон GB (цвет — из темы, белая
        #обводка/кольца видны на акцентном фоне шапки). Заменил прежний плоский «GB».
        hex_lbl = HexLogo(40)

        #Бренд пишем как «GradeBookAI» (фирменное написание, как на сайте и экране входа),
        #а не капсом «GRADEBOOK» — так шапка выглядит опрятно и узнаваемо.
        logo_text = QLabel("GradeBookAI")
        logo_text.setStyleSheet(
            "font-size:16px;font-weight:800;color:#FFFFFF;letter-spacing:0.2px;"
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

        #Индикатор связи с сервером (онлайн/офлайн). Обновляется из фонового синка через
        #сигнал (main_window._on_sync_state → set_online). По умолчанию скрыт, пока синк
        #не определил состояние — не пугаем пользователя «офлайн» до первой попытки.
        #Чистый вид: маленький цветной кружок + короткое слово (без эмодзи и длинной фразы).
        self._online_lbl = QLabel("")
        self._online_lbl.setTextFormat(Qt.RichText)
        self._online_lbl.setStyleSheet(
            "color:rgba(255,255,255,0.92);font-size:11px;font-weight:600;"
            "background:rgba(255,255,255,0.12);border-radius:100px;padding:3px 11px;")
        self._online_lbl.hide()
        lay.addWidget(self._online_lbl)

        #User info. Бейдж роли — ТОТ ЖЕ тонкий стиль, что и индикатор онлайн (без яркой
        #обводки/подсветки), чтобы элементы шапки выглядели единообразно, а не «кто в лес».
        from widgets import badge
        self.role_badge = badge("", "green")
        self.role_badge.setStyleSheet(
            "background:rgba(255,255,255,0.12);color:rgba(255,255,255,0.92);"
            "border-radius:100px;padding:3px 11px;font-size:11px;font-weight:600;"
        )
        #ФИО — эллипсис по ширине + полное имя в подсказке. Ширину даём щедрую (420): шапка
        #на весь экран, места справа много, и длинные ФИО должны влезать целиком, а не «…».
        self.user_lbl   = ElidingLabel("", 13, "#FFFFFF", max_width=420)
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

    def set_online(self, online: bool):
        """Показать состояние связи с сервером: маленький цветной кружок + короткое слово.
        Подробности — в подсказке. Вызывается из UI-потока."""
        dot = "#3ddc84" if online else "#ff8a8a"
        word = "Онлайн" if online else "Офлайн"
        self._online_lbl.setText(
            f'<span style="font-size:14px;color:{dot}">&#9679;</span>&nbsp;{word}')
        self._online_lbl.setToolTip(
            "Данные синхронизируются с сервером колледжа." if online else
            "Нет связи с сервером. Изменения сохраняются локально и уйдут на сервер "
            "автоматически, как только связь восстановится.")
        self._online_lbl.show()

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
        #СПЛОШНОЙ акцентный фон (без градиента): горизонтальный градиент green→green2 давал
        #резкую видимую полосу-«обрыв» на широкой шапке (акцент и акцент2 — разные оттенки).
        #Ровный цвет + тонкая полупрозрачная тёмная граница снизу выглядит чисто и не рябит.
        self.setStyleSheet(
            f"QFrame{{background:{C['green']};border-bottom:1px solid rgba(0,0,0,0.14);}}"
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
        #Цвет бренда берём из АКТИВНОЙ темы (акцент), а не хардкодом — значок меняется
        #вместе с темой оформления (тёмная/светлая/кастомный акцент).
        acc = QColor(C['green'])
        fill1 = QColor(C['green']); fill1.setAlpha(10)
        p.setPen(QPen(acc, 1.5))
        p.setBrush(QBrush(fill1))
        p.drawPolygon(pts)

        #Внутренний шестиугольник
        r2 = r * 0.72
        pts2 = QPolygonF([
            QPointF(cx + r2 * math.cos(math.radians(a - 90)),
                   cy + r2 * math.sin(math.radians(a - 90)))
            for a in range(0, 360, 60)
        ])
        edge2 = QColor(C['green']); edge2.setAlpha(60)
        fill2 = QColor(C['green']); fill2.setAlpha(18)
        p.setPen(QPen(edge2, 1))
        p.setBrush(QBrush(fill2))
        p.drawPolygon(pts2)

        #Текст "GB"
        p.setPen(QPen(acc))
        f = QFont("Segoe UI", int(self._size * 0.22), QFont.Bold)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignCenter, "GB")
        p.end()


class HexLogo(QWidget):
    """Утверждённый фирменный знак (вариант №8), анимированный.

    Двухцветный гексагон «GB» (ЦВЕТ ЯДРА — всегда из темы, C['green']/C['green2']) + средняя
    обводка + мягкая тень; ВРАЩАЮЩЕЕСЯ внешнее кольцо со свечением и СТАТИЧНОЕ внутреннее
    кольцо. Знак подстраивается под цветовую гамму.

    oncard=True — вариант для КАРТОЧКИ (экран входа): кольца/свечение — акцентным цветом
    темы (видны на белом фоне), ядро двухцветное, «GB» белые, без белого ободка. По
    умолчанию (шапка на акцентном фоне): кольца/обводка/свечение белые.

    Qt/QtSvg не поддерживает SMIL-анимацию, поэтому вращение рисуем сами: QTimer двигает
    углы, paintEvent перерисовывает. Значок читает C[...] на каждом кадре, так что смену
    темы подхватывает без доп. кода."""

    def __init__(self, size=40, oncard=False, parent=None):
        super().__init__(parent)
        self._size = size
        self._oncard = oncard
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground)   #лечь на цветную шапку без «плашки»
        self._ao = 0.0      #угол внешнего кольца
        self._ac = 0.0      #угол ядра
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)                            #~25 к/с — плавно и не грузит CPU

    def _tick(self):
        #22 c и 19 c на оборот (как в веб-версии) при шаге 40 мс.
        self._ao = (self._ao + 360.0 / 22.0 * 0.040) % 360.0
        self._ac = (self._ac + 360.0 / 19.0 * 0.040) % 360.0
        self.update()

    def _hex(self, r, rot_deg=0.0) -> QPolygonF:
        """Гексагон вершиной вверх (радиус r), повёрнутый на rot_deg, вокруг (0,0)."""
        return QPolygonF([
            QPointF(r * math.cos(math.radians(60 * k - 90 + rot_deg)),
                    r * math.sin(math.radians(60 * k - 90 + rot_deg)))
            for k in range(6)
        ])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self._size
        f = s / 200.0                       #масштаб от эталонного viewBox 200
        R_out, R_in, R_core = 93 * f, 82 * f, 70 * f
        rim = 6.0 * f
        white = QColor("#ffffff")
        #Кольца/обводка/свечение: на карточке — акцент темы (виден на белом), в шапке — белые.
        line = QColor(C['green']) if self._oncard else white

        p.translate(s / 2.0, s / 2.0)

        #1) Мягкая тень ядра. Тень статична (гексагон почти симметричен, вращать незачем)
        #   → всегда снизу. Мягкость имитируем несколькими тёмными слоями со смещением.
        core_shadow = self._hex(R_core, 0)
        p.setPen(Qt.NoPen)
        for i in range(1, 5):
            sh = QColor(15, 27, 34); sh.setAlpha(14)
            p.setBrush(sh)
            p.save(); p.translate(0, i * 0.9 * f + 0.5); p.drawPolygon(core_shadow); p.restore()

        #2) ВНЕШНЕЕ кольцо: вращается, со свечением (широкий бледный контур снизу + чёткий
        #   пунктир сверху).
        p.save()
        p.rotate(self._ao)
        ring = self._hex(R_out, 0)
        glow = QColor(line); glow.setAlpha(70)
        p.setPen(QPen(glow, 9 * f, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush); p.drawPolygon(ring)
        dash = QPen(QColor(line), 4 * f, Qt.CustomDashLine, Qt.RoundCap, Qt.RoundJoin)
        dash.setDashPattern([5, 4])
        p.setPen(dash); p.setBrush(Qt.NoBrush); p.drawPolygon(ring)
        p.restore()

        #3) ВНУТРЕННЕЕ кольцо: СТАТИЧНОЕ (не крутится).
        inner = self._hex(R_in, 0)
        ic = QColor(line); ic.setAlpha(215)
        p.setPen(QPen(ic, 3 * f, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush); p.drawPolygon(inner)

        #4) ЯДРО: вращается, двухцветная заливка из темы. В шапке — белый ободок (виден на
        #   акцентном фоне); на карточке ободок не нужен (цветное ядро само видно на белом).
        p.save()
        p.rotate(self._ac)
        core = self._hex(R_core, 0)
        if not self._oncard:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(white)); p.drawPolygon(self._hex(R_core + rim, 0))
        grad = QLinearGradient(-R_core, -R_core, R_core, R_core)
        light = QColor(C['green']); dark = QColor(C['green2'])
        grad.setColorAt(0.0, light); grad.setColorAt(0.5, light)
        grad.setColorAt(0.5, dark); grad.setColorAt(1.0, dark)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad)); p.drawPolygon(core)
        p.restore()

        #5) GB: белые на цветном ядре, уменьшены, стоят ровно (не крутятся).
        gb = QFont("Syne")
        gb.setPixelSize(max(7, int(56 * f)))
        gb.setWeight(QFont.ExtraBold)
        gb.setLetterSpacing(QFont.AbsoluteSpacing, -2 * f)
        p.setFont(gb)
        p.setPen(QPen(white))
        from PySide6.QtCore import QRectF
        p.drawText(QRectF(-s / 2.0, -s / 2.0 + 1.0 * f, s, s), Qt.AlignCenter, "GB")
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
        for _ in range(6):
            self._hexes.append({
                "x": random.uniform(0, W), "y": random.uniform(0, H),
                "R": random.uniform(70, 190),
                "vx": random.uniform(-0.16, 0.16), "vy": random.uniform(-0.16, 0.16),
                "ang": random.uniform(0, math.pi), "spin": random.uniform(-0.0035, 0.0035),
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

        #2.5) «Живая» сеть-созвездие: тонкие линии между близкими частицами — оживляет
        #фон, как связанные узлы. Дёшево: 30 точек → ~435 пар за кадр.
        p.setBrush(Qt.NoBrush)
        n = len(self._particles)
        for i in range(n):
            a = self._particles[i]
            for j in range(i + 1, n):
                b = self._particles[j]
                d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                if d < 155:
                    lc = QColor(C['green']); lc.setAlpha(int(38 * (1 - d / 155)))
                    p.setPen(QPen(lc, 1))
                    p.drawLine(QPointF(a["x"], a["y"]), QPointF(b["x"], b["y"]))

        #3) Частицы (мерцают по фазе) — лёгкое «звёздное» поле в цвет акцента.
        p.setPen(Qt.NoPen)
        for pt in self._particles:
            tw = 0.65 + 0.35 * math.sin(self._t * 0.05 + pt["ph"])
            col = QColor(C['green']); col.setAlpha(int(max(0, min(255, pt["a"] * tw * 255))))
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(pt["x"], pt["y"]), pt["r"], pt["r"])

        p.end()
