"""
theme_ui.py — Виджет выбора темы оформления (как палитры тем в Google Chrome).

Один и тот же ThemeCustomizer переиспользуется:
  • в профиле преподавателя/ученика — сохраняет ЛИЧНУЮ тему (в БД, роуминг);
  • в админке («Оформление») — сохраняет тему учебного заведения (общий config).
Кому что сохранять, решает переданный колбэк on_save(spec) — сам виджет про это
не знает, он лишь даёт выбрать палитру (готовую или свою ползунками) и нажать
«Сохранить».
"""
from PySide6.QtCore import Qt, Signal, QTime
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSlider,
    QScrollArea, QCheckBox, QTimeEdit
)

import themes
from styles import C, BTN
from widgets import title_lbl, section_lbl, lbl, btn, card


class _Swatch(QWidget):
    """Круглый двухцветный свотч палитры (акцент + вторичный + нейтральная подложка).
    Клик выбирает палитру; на выбранной рисуется галочка (как на скрине Chrome)."""
    clicked = Signal()

    SIZE = 64

    def __init__(self, accent: str, secondary: str, surface: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self._accent = accent
        self._secondary = secondary
        self._surface = surface
        self._selected = False

    def set_colors(self, accent: str, secondary: str, surface: str):
        self._accent, self._secondary, self._surface = accent, secondary, surface
        self.update()

    def set_selected(self, on: bool):
        if self._selected != on:
            self._selected = on
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = self.SIZE - 8
        x = y = 4
        #Подложка-круг (нейтральная поверхность) — нижняя «половина» свотча.
        p.setPen(QPen(QColor(C["border2"]), 1))
        p.setBrush(QBrush(QColor(self._surface)))
        p.drawEllipse(x, y, d, d)
        #Верхняя половина — акцент.
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(self._accent)))
        p.drawPie(x, y, d, d, 0 * 16, 180 * 16)
        #Левый нижний сектор — вторичный цвет (как трёхцветные кружки на скрине).
        p.setBrush(QBrush(QColor(self._secondary)))
        p.drawPie(x, y, d, d, 180 * 16, 90 * 16)
        #Обводка круга.
        p.setPen(QPen(QColor(C["border2"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(x, y, d, d)
        #Галочка на выбранной палитре.
        if self._selected:
            r = 11
            cx, cy = x + d - r, y + r
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(C["green"])))
            p.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
            pen = QPen(QColor("#FFFFFF"), 2)
            p.setPen(pen)
            p.drawLine(cx - 5, cy, cx - 1, cy + 4)
            p.drawLine(cx - 1, cy + 4, cx + 5, cy - 4)
        p.end()


class ThemeCustomizer(QWidget):
    """Сетка готовых палитр + редактор своего цвета (ползунки) + кнопка «Сохранить»."""

    def __init__(self, initial_spec: dict = None, on_save=None, parent=None):
        super().__init__(parent)
        self._on_save = on_save
        init = themes.normalize_spec(initial_spec or {"id": themes.DEFAULT_ID})
        #Режим (светлая/тёмная) держим ОТДЕЛЬНО от акцентной части spec — иначе при
        #выборе палитры он бы терялся. В spec режим подмешиваем только на применение.
        self._mode = "dark" if init.get("mode") == "dark" else "light"
        #акцентная часть spec (без mode/schedule — их держим отдельно)
        self._spec = {k: v for k, v in init.items() if k not in ("mode", "schedule")}
        self._schedule = themes.get_schedule(init)   #{"enabled","start","end"}
        self._swatches = {}   #id пресета → _Swatch
        self._custom_swatch = None
        self._mode_btns = {}
        self._sched_chk = None
        self._sched_from = None
        self._sched_to = None
        self._building = True
        self._build()
        self._building = False
        self._select_initial()

    def _compose(self) -> dict:
        """Полный spec на применение/сохранение = акцент + ручной режим + расписание."""
        out = themes.with_mode(self._spec, self._mode)
        return themes.with_schedule(out, self._schedule["enabled"],
                                    self._schedule["start"], self._schedule["end"])

    #сборка
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none;")
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        lay.addWidget(title_lbl("Оформление", 20))
        lay.addWidget(lbl("Выберите режим и цвета темы. Полное применение — после «Сохранить».",
                          12, C["text3"]))

        #Режим: светлая / тёмная тема (накладывается поверх любой палитры).
        mode_card = card()
        mlc = QVBoxLayout(mode_card)
        mlc.setContentsMargins(18, 16, 18, 16)
        mlc.setSpacing(10)
        mlc.addWidget(section_lbl("Режим"))
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        for key, text in (("light", "☀  Светлая"), ("dark", "🌙  Тёмная")):
            b = btn(text, "ghost")
            b.setCheckable(True)
            b.clicked.connect(lambda _checked=False, k=key: self._pick_mode(k))
            self._mode_btns[key] = b
            mode_row.addWidget(b)
        mode_row.addStretch()
        mlc.addLayout(mode_row)

        #Тёмная тема по расписанию (по умолчанию 18:00–08:00, время настраивается).
        self._sched_chk = QCheckBox("Тёмная тема по расписанию")
        self._sched_chk.setChecked(self._schedule["enabled"])
        self._sched_chk.toggled.connect(self._on_sched_toggled)
        mlc.addWidget(self._sched_chk)

        sched_row = QHBoxLayout()
        sched_row.setSpacing(8)
        sched_row.addWidget(lbl("Тёмная с", 12, C["text3"]))
        self._sched_from = QTimeEdit(QTime.fromString(self._schedule["start"], "HH:mm"))
        self._sched_from.setDisplayFormat("HH:mm")
        self._sched_from.timeChanged.connect(self._on_sched_time)
        sched_row.addWidget(self._sched_from)
        sched_row.addWidget(lbl("до", 12, C["text3"]))
        self._sched_to = QTimeEdit(QTime.fromString(self._schedule["end"], "HH:mm"))
        self._sched_to.setDisplayFormat("HH:mm")
        self._sched_to.timeChanged.connect(self._on_sched_time)
        sched_row.addWidget(self._sched_to)
        sched_row.addStretch()
        mlc.addLayout(sched_row)

        lay.addWidget(mode_card)

        #Сетка готовых палитр
        grid_card = card()
        gl = QVBoxLayout(grid_card)
        gl.setContentsMargins(18, 16, 18, 16)
        gl.addWidget(section_lbl("Готовые палитры"))
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, preset in enumerate(themes.PRESETS):
            accent, secondary, surface = themes.swatch_colors(
                themes.with_mode({"id": preset["id"]}, self._mode))
            sw = _Swatch(accent, secondary, surface)
            sw.setToolTip(preset["name"])
            sw.clicked.connect(lambda pid=preset["id"]: self._pick_preset(pid))
            self._swatches[preset["id"]] = sw
            grid.addWidget(sw, i // 6, i % 6, alignment=Qt.AlignCenter)
        gl.addLayout(grid)
        lay.addWidget(grid_card)

        #Свой цвет (ползунки)
        custom_card = card()
        cl = QVBoxLayout(custom_card)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.setSpacing(10)
        cl.addWidget(section_lbl("Свой цвет"))
        cl.addWidget(lbl("Соберите акцент ползунками — для цветов, которых нет в пуле.",
                         11, C["text3"]))

        prev_row = QHBoxLayout()
        self._custom_swatch = _Swatch("#147C8B", "#2BA6B8", C["card2"])
        self._custom_swatch.clicked.connect(self._pick_custom)
        prev_row.addWidget(self._custom_swatch)
        self._hex_lbl = lbl("#147C8B", 13, C["text"], True)
        prev_row.addWidget(self._hex_lbl)
        prev_row.addStretch()
        cl.addLayout(prev_row)

        self._sliders = {}
        for key, label, maxv in [("h", "Оттенок", 359), ("s", "Насыщенность", 255),
                                 ("v", "Яркость", 255)]:
            row = QHBoxLayout()
            row.addWidget(lbl(label, 12, C["text3"]))
            s = QSlider(Qt.Horizontal)
            s.setRange(0, maxv)
            s.valueChanged.connect(self._on_slider)
            row.addWidget(s, 1)
            self._sliders[key] = s
            cl.addLayout(row)
        lay.addWidget(custom_card)

        #Сохранить
        save_row = QHBoxLayout()
        save_row.addStretch()
        self._save_btn = btn("Сохранить", "green", icon_name="save")
        self._save_btn.clicked.connect(self._save)
        save_row.addWidget(self._save_btn)
        lay.addLayout(save_row)

        lay.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll)

    #выбор/предпросмотр
    def _select_initial(self):
        self._style_mode_btns()
        if self._spec.get("id") == "custom":
            self._set_sliders_from_hex(self._spec.get("accent", "#147C8B"))
            self._mark_selected("custom")
        else:
            self._mark_selected(self._spec.get("id", themes.DEFAULT_ID))
            #ползунки выставим по акценту выбранной палитры (для удобного перехода)
            accent = themes.build_palette(self._spec).get("green", "#147C8B")
            self._set_sliders_from_hex(accent)

    #режим (светлая/тёмная) и расписание
    def _pick_mode(self, mode: str):
        if self._schedule["enabled"]:
            return   #ручной режим заблокирован — им управляет расписание
        self._mode = "dark" if mode == "dark" else "light"
        self._style_mode_btns()
        self._refresh_all_swatches()   #кружки-превью показывают поверхность режима
        self._preview()

    def _display_mode(self) -> str:
        """Режим, который сейчас реально показываем (с учётом расписания)."""
        return themes.effective_mode(self._compose())

    def _style_mode_btns(self):
        disp = self._display_mode()
        sched_on = self._schedule["enabled"]
        for key, b in self._mode_btns.items():
            b.setStyleSheet(BTN["green"] if key == disp else BTN["ghost"])
            b.setChecked(key == disp)
            b.setEnabled(not sched_on)   #при расписании режим выбирает время, не кнопка
            b.setToolTip("Управляется расписанием" if sched_on else "")

    def _on_sched_toggled(self, on: bool):
        self._schedule["enabled"] = bool(on)
        self._style_mode_btns()
        self._refresh_all_swatches()
        self._preview()

    def _on_sched_time(self):
        self._schedule["start"] = self._sched_from.time().toString("HH:mm")
        self._schedule["end"] = self._sched_to.time().toString("HH:mm")
        if self._schedule["enabled"]:
            self._style_mode_btns()
            self._refresh_all_swatches()
            self._preview()

    def _refresh_all_swatches(self):
        dm = self._display_mode()
        for pid, sw in self._swatches.items():
            a, s, surf = themes.swatch_colors(themes.with_mode({"id": pid}, dm))
            sw.set_colors(a, s, surf)
        self._refresh_custom_preview(self._current_hex())

    def _mark_selected(self, sel_id: str):
        for pid, sw in self._swatches.items():
            sw.set_selected(pid == sel_id)
        if self._custom_swatch:
            self._custom_swatch.set_selected(sel_id == "custom")

    def _pick_preset(self, pid: str):
        self._spec = {"id": pid}
        self._mark_selected(pid)
        self._preview()

    def _pick_custom(self):
        self._spec = {"id": "custom", "accent": self._current_hex()}
        self._mark_selected("custom")
        self._preview()

    def _current_hex(self) -> str:
        h = self._sliders["h"].value()
        s = self._sliders["s"].value()
        v = self._sliders["v"].value()
        return QColor.fromHsv(h, s, v).name()

    def _set_sliders_from_hex(self, hex_color: str):
        c = QColor(hex_color)
        h, s, v, _ = c.getHsv()
        for key, val in (("h", max(0, h)), ("s", s), ("v", v)):
            self._sliders[key].blockSignals(True)
            self._sliders[key].setValue(val)
            self._sliders[key].blockSignals(False)
        self._refresh_custom_preview(hex_color)

    def _on_slider(self):
        hexc = self._current_hex()
        self._refresh_custom_preview(hexc)
        self._spec = {"id": "custom", "accent": hexc}
        self._mark_selected("custom")
        self._preview()

    def _refresh_custom_preview(self, hex_color: str):
        accent, secondary, surface = themes.swatch_colors(
            themes.with_mode({"id": "custom", "accent": hex_color}, self._display_mode()))
        self._custom_swatch.set_colors(accent, secondary, surface)
        self._hex_lbl.setText(hex_color.upper())

    def _preview(self):
        if self._building:
            return
        #Живой предпросмотр: глобальный QSS перекрашивается сразу (акцент + режим);
        #полная перекраска инлайн-виджетов произойдёт после «Сохранить» (пересборка дашборда).
        themes.apply_spec(self._compose())

    def _save(self):
        if callable(self._on_save):
            self._on_save(self._compose())
