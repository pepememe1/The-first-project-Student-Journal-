"""
schedule_view.py — переиспользуемый виджет расписания (студент/преподаватель/админ).

Один виджет на все роли:
  • студент   — видит расписание своей группы (привязка по группе аккаунта);
  • препод    — свои пары (инверсия групповых расписаний, привязка по ФИО);
  • админ     — может смотреть любую группу или любого преподавателя.

Данные берёт из ЛОКАЛЬНОГО зашифрованного кэша (schedule.store). Кнопка «Обновить»
перепарсивает сайт в фоновом потоке (тяжёлая сетевая операция — UI не блокируем) и
сохраняет свежий снимок в кэш. Привязка пользователя (какая группа / какое ФИО на
сайте) хранится per-account и подставляется автоматически, если совпала с аккаунтом.

Стиль строго из дизайн-системы Synapse (styles.C + фабрики widgets) — своих цветов и
шрифтов не вводим.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QComboBox,
    QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal as QSignal

from styles import C, BTN
from widgets import card, card2, lbl, title_lbl, section_lbl, ElidingLabel

import schedule as sched

#Полные имена дней для заголовков колонок (в модели — короткие «Пнд» и т.п.).
_DAY_FULL = {
    "Пнд": "Понедельник", "Втр": "Вторник", "Срд": "Среда",
    "Чтв": "Четверг", "Птн": "Пятница", "Сбт": "Суббота",
}

#Цвет бейджа по типу занятия — из палитры (без новых цветов).
_KIND_COLOR = {
    "лек": C["blue"], "пр": C["green"], "лаб": C["green2"],
    "сем": C["blue"], "конс": C["text3"], "зач": C["orange"], "экз": C["red"],
}
_KIND_FULL = {
    "лек": "Лекция", "пр": "Практика", "лаб": "Лаборат.",
    "сем": "Семинар", "конс": "Консульт.", "зач": "Зачёт", "экз": "Экзамен",
}


class _BgWorker(QThread):
    """Выполняет fn() в фоне; результат/ошибка — через сигналы (как в admin_dashboard)."""
    done = QSignal(object)
    error = QSignal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as e:
            self.error.emit(str(e))


class ScheduleView(QWidget):
    def __init__(self, role: str, login: str = "", app_hint: str = "", parent=None):
        super().__init__(parent)
        self.role = role
        self.login = login or ""
        self.app_hint = app_hint or ""
        self._workers = []
        self.snapshot = None
        self.kind = "teacher" if role == "teacher" else "group"
        self.entity = ""
        self.category = sched.DEFAULT_CATEGORY       # «колледж» — как и всегда было
        self.week = sched.current_week_parity()      # по умолчанию — текущая неделя
        self._build()
        self._load_from_cache()

    #  Сборка интерфейса
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        #Шапка: заголовок + статус обновления + кнопка «Обновить»
        hdr = QHBoxLayout()
        hdr.addWidget(title_lbl("Расписание"), 0)
        self._week_badge = lbl("", 13, C["green"], True)
        hdr.addWidget(self._week_badge, 0)
        hdr.addStretch(1)
        self._updated_lbl = lbl("", 11, C["text3"])
        hdr.addWidget(self._updated_lbl, 0)
        self._refresh_btn = QPushButton("⟳ Обновить")
        self._refresh_btn.setStyleSheet(BTN["ghost"])
        self._refresh_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_btn.clicked.connect(self._on_refresh)
        hdr.addWidget(self._refresh_btn, 0)
        root.addLayout(hdr)

        #Подсказка-описание
        root.addWidget(lbl(
            "Расписание занятий колледжа ВСГУТУ. Данные берутся с портала и хранятся "
            "локально — после обновления доступны и без интернета.", 11, C["text3"]))

        #Категория расписания (портал ВСГУТУ читается в 4 разделах — см. schedule/
        #parser.py::CATEGORIES). Видна ВСЕМ ролям (не только админу, в отличие от
        #«Показать:» ниже) — «колледж» выбран по умолчанию, поведение по умолчанию
        #не меняется ни для студента, ни для препода, пока они её не трогают.
        cat_row = QHBoxLayout()
        cat_row.setSpacing(8)
        cat_row.addWidget(lbl("Категория:", 12, C["text3"]))
        self._category_combo = QComboBox()
        self._category_combo.setMinimumWidth(260)
        for key, meta in sched.CATEGORIES.items():
            self._category_combo.addItem(meta["label"], key)
        self._category_combo.currentIndexChanged.connect(self._on_category_changed)
        cat_row.addWidget(self._category_combo)
        cat_row.addStretch(1)
        root.addLayout(cat_row)

        #Селектор сущности (группа / преподаватель)
        sel = QHBoxLayout()
        sel.setSpacing(8)
        self._kind_combo = QComboBox()
        self._kind_combo.addItem("Группа", "group")
        self._kind_combo.addItem("Преподаватель", "teacher")
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        #тип выбора нужен только админу; студенту/преподавателю он фиксирован
        if self.role != "admin":
            self._kind_combo.setVisible(False)
        else:
            sel.addWidget(lbl("Показать:", 12, C["text3"]))
            sel.addWidget(self._kind_combo)

        self._entity_label = lbl("Группа:", 12, C["text3"])
        sel.addWidget(self._entity_label)
        self._entity_combo = QComboBox()
        self._entity_combo.setMinimumWidth(220)
        self._entity_combo.currentIndexChanged.connect(self._on_entity_changed)
        sel.addWidget(self._entity_combo)
        sel.addStretch(1)

        #Переключатель недели I/II (колледж/бакалавриат) или сессий (заочка) —
        #число кнопок не фиксировано, строится динамически в _sync_week_buttons
        #(у сессионного расписания может быть больше 2 блоков, см. schedule/
        #parser.py::parse_group_page_dated).
        self._week_row = QHBoxLayout()
        self._week_row.setSpacing(6)
        sel.addLayout(self._week_row)
        root.addLayout(sel)

        #Полоса дней (горизонтальная прокрутка)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("border:none;")
        self._days_host = QWidget()
        self._days_lay = QHBoxLayout(self._days_host)
        self._days_lay.setContentsMargins(0, 0, 0, 0)
        self._days_lay.setSpacing(12)
        self._days_lay.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._scroll.setWidget(self._days_host)
        root.addWidget(self._scroll, 1)

        self._status_lbl = lbl("", 12, C["text3"])
        self._status_lbl.setWordWrap(True)
        root.addWidget(self._status_lbl)

        self._sync_week_buttons()

    #  Загрузка/состояние
    def _is_dated(self) -> bool:
        """Сессионная категория (Заочное 1/2) — заголовки дней это даты, а не
        дни недели, и число «недель» (сессионных блоков) не фиксировано 2."""
        return bool(sched.CATEGORIES.get(self.category, {}).get("dated"))

    def _current_group_schedule(self):
        """GroupSchedule текущей сущности (только kind=="group") в ТЕКУЩЕЙ
        категории — с оверлеями для колледжа (см. store.group_schedule)."""
        if not self.entity:
            return None
        gs = sched.group_schedule(self.entity, category=self.category)
        if gs is None and self.snapshot:
            gs = self.snapshot.groups.get(self.entity)
        return gs

    def _load_from_cache(self):
        self.snapshot = sched.load_cached(self.category)
        if self.snapshot is None:
            self._status_lbl.setText(
                "📭 Расписание ещё не загружено. Нажмите «⟳ Обновить», чтобы скачать "
                "его с портала (нужен интернет).")
            self._populate_entities()
            self._sync_week_buttons()
            self._update_meta()
            return
        self._populate_entities()
        self._resolve_identity()
        self._sync_week_buttons()
        self._render()
        self._update_meta()

    def _update_meta(self):
        """Обновляет бейдж текущей недели и метку «обновлено N минут назад»."""
        if self._is_dated():
            #«I/II неделя» — понятие чётности КОЛЕНДАРНОЙ недели, у сессионного
            #расписания его нет (сессия — не «сейчас», а конкретные будущие даты).
            self._week_badge.setText("")
        else:
            self._week_badge.setText("Сейчас: " + sched.week_label(
                sched.current_week_parity()))
        age = sched.cache_age_minutes(self.category)
        if age is None:
            self._updated_lbl.setText("нет данных")
        elif age < 1:
            self._updated_lbl.setText("обновлено только что")
        elif age < 60:
            self._updated_lbl.setText(f"обновлено {int(age)} мин назад")
        elif age < 60 * 24:
            self._updated_lbl.setText(f"обновлено {int(age // 60)} ч назад")
        else:
            self._updated_lbl.setText(f"обновлено {int(age // (60 * 24))} дн назад")

    def _entities(self) -> list:
        """Список сущностей выбранного типа (имена групп или преподавателей)."""
        if not self.snapshot:
            return []
        if self.kind == "teacher":
            return self.snapshot.teachers()
        return self.snapshot.group_names()

    def _populate_entities(self):
        self._entity_label.setText(
            "Преподаватель:" if self.kind == "teacher" else "Группа:")
        self._entity_combo.blockSignals(True)
        self._entity_combo.clear()
        for name in self._entities():
            self._entity_combo.addItem(name)
        self._entity_combo.blockSignals(False)

    def _resolve_identity(self):
        """Подбирает сущность для пользователя: сохранённый выбор → автоугадывание
        по данным аккаунта → первый в списке. Студенту/преподавателю выбор фиксируем
        по их роли, админ выбирает свободно. Автоугадывание по аккаунту имеет смысл
        ТОЛЬКО в категории по умолчанию (колледж) — свою группу/ФИО студент/препод
        может угадать лишь среди СВОИХ данных, не среди бакалавриата/заочки."""
        names = self._entities()
        if not names:
            return
        chosen = ""
        is_default_category = (self.category == sched.DEFAULT_CATEGORY)
        #1) ранее сохранённый личный выбор (per-account, только для дефолтной категории)
        if is_default_category:
            saved = sched.get_identity(self.role, self.login)
            if saved and saved in names:
                chosen = saved
            #2) автоугадывание по аккаунту (только для студента/преподавателя)
            if not chosen and self.role == "student":
                chosen = sched.guess_group(self.app_hint, names)
            if not chosen and self.role == "teacher":
                chosen = sched.guess_teacher(self.app_hint, names)
        #3) запасной вариант — первый
        if not chosen:
            chosen = names[0]
        self.entity = chosen
        idx = self._entity_combo.findText(chosen)
        if idx >= 0:
            self._entity_combo.blockSignals(True)
            self._entity_combo.setCurrentIndex(idx)
            self._entity_combo.blockSignals(False)

    #  Реакции на выбор
    def _on_category_changed(self):
        self.category = self._category_combo.currentData() or sched.DEFAULT_CATEGORY
        self.week = 1
        self._load_from_cache()

    def _on_kind_changed(self):
        self.kind = self._kind_combo.currentData() or "group"
        self._populate_entities()
        names = self._entities()
        self.entity = names[0] if names else ""
        self._sync_week_buttons()
        self._render()

    def _on_entity_changed(self):
        self.entity = self._entity_combo.currentText()
        #запоминаем личный выбор студента/преподавателя — только для категории по
        #умолчанию (колледж): выбор группы бакалавриата/заочки — не «домашняя»
        #привязка аккаунта, а разовый просмотр.
        if (self.category == sched.DEFAULT_CATEGORY
               and self.role in ("student", "teacher") and self.entity):
            sched.set_identity(self.role, self.login, self.entity)
        self._sync_week_buttons()
        self._render()

    def _set_week(self, week: int):
        self.week = week
        self._sync_week_buttons()
        self._render()

    def _week_keys(self) -> list:
        """Номера недель/сессионных блоков для кнопок-переключателей.

        Обычные категории — ВСЕГДА [1, 2] (I/II неделя), как было всегда:
        кнопка нужна и тогда, когда у конкретной группы на эту чётность нет пар
        (просто покажет «нет занятий») — исчезающая кнопка выглядела бы как
        баг, а не как «пар нет». Сессионные (заочка) — число блоков НЕ
        фиксировано (страница может дать 3-4 сессии, у разных групп по-разному),
        поэтому берём реальные ключи текущей сущности."""
        if not self._is_dated():
            return [1, 2]
        if self.kind == "teacher":
            weeks = (self.snapshot.teacher_index.get(self.entity) or {}) if self.snapshot else {}
            keys = sorted(weeks.keys())
        else:
            gs = self._current_group_schedule()
            keys = sorted((gs.weeks if gs else {}).keys())
        return keys or [1]

    def _sync_week_buttons(self):
        #Число «недель»/сессий не фиксировано (заочка) — кнопки строим заново, а не
        #переиспользуем 2 статичные (было так, пока категория была всегда одна).
        while self._week_row.count():
            it = self._week_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        dated = self._is_dated()
        keys = self._week_keys()
        if self.week not in keys:
            self.week = keys[0]
        cur = None if dated else sched.current_week_parity()
        gs = None if self.kind == "teacher" else self._current_group_schedule()

        for wk in keys:
            active = (wk == self.week)
            if dated:
                days = list((gs.weeks.get(wk) or {}).keys()) if gs else []
                label = f"Сессия {wk}"
                if days:
                    #«06 апреля» — хвост после «Пнд, » — короче и достаточно для кнопки
                    first = days[0].split(", ", 1)[-1]
                    last = days[-1].split(", ", 1)[-1]
                    label += f" ({first}–{last})" if first != last else f" ({first})"
            else:
                label = sched.week_label(wk) + ("  • сейчас" if wk == cur else "")
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(active)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(BTN["sm_green"] if active else BTN["sm_ghost"])
            b.clicked.connect(lambda _=False, w=wk: self._set_week(w))
            self._week_row.addWidget(b)

    #  Обновление с сайта (фон)
    def _on_refresh(self):
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("⏳ Загрузка...")
        self._status_lbl.setText("⏳ Скачиваю и разбираю расписание с портала "
                                 "(это может занять до минуты)...")
        category = self.category

        def _do():
            snap = sched.build_snapshot(category=category)
            sched.save(snap, category=category)
            return snap

        def _done(snap):
            self.snapshot = snap
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setText("⟳ Обновить")
            self._status_lbl.setText("✅ Расписание обновлено.")
            self._populate_entities()
            self._resolve_identity()
            self._sync_week_buttons()
            self._render()
            self._update_meta()

        def _err(msg):
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setText("⟳ Обновить")
            self._status_lbl.setText(
                f"⚠️ Не удалось обновить расписание: {msg}. "
                "Проверьте интернет; ранее загруженные данные сохранены.")

        self._run_bg(_do, _done, _err)

    def _run_bg(self, fn, on_done, on_err):
        w = _BgWorker(fn)
        self._workers.append(w)
        w.done.connect(on_done)
        w.error.connect(on_err)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        w.start()

    #  Отрисовка дней
    def _day_map(self) -> dict:
        """Возвращает {day: [(tag, Lesson)]} для выбранной сущности и недели.

        tag — пустой для группы, имя группы для преподавателя (показываем, в какой
        группе пара). Для обычных категорий day ∈ WEEKDAYS и предзаполнен ПУСТЫМИ
        списками (чтобы показать все 6 колонок, даже пустые дни); для сессионных
        (заочка) day — строка-дата, предзаполнять фиксированным набором нечем —
        реальные дни появляются по мере разбора."""
        out = {} if self._is_dated() else {d: [] for d in sched.WEEKDAYS}
        if not self.snapshot or not self.entity:
            return out
        if self.kind == "teacher":
            weeks = self.snapshot.teacher_index.get(self.entity, {})
            for d, entries in weeks.get(self.week, {}).items():
                out.setdefault(d, [])
                for e in entries:
                    out[d].append((e.get("group", ""), e["lesson"]))
        else:
            #Расписание группы С НАЛОЖЕННЫМИ админ-правками (overlay, только колледж) —
            #единый источник, как на вебе. Правки синкуются, поэтому видны и здесь.
            gs = self._current_group_schedule()
            if gs:
                for d, lessons in gs.weeks.get(self.week, {}).items():
                    out.setdefault(d, [])
                    for ls in lessons:
                        out[d].append(("", ls))
        #сортируем пары по номеру внутри дня
        for d in out:
            out[d].sort(key=lambda t: t[1].pair_no)
        return out

    def _render(self):
        #чистим прежние карточки дней
        while self._days_lay.count():
            it = self._days_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        if not self.snapshot:
            return
        if not self.entity:
            self._status_lbl.setText("Выберите группу или преподавателя.")
            return
        self._status_lbl.setText("")

        dmap = self._day_map()
        #Обычные категории — фиксированные 6 колонок (даже пустые). Сессионные
        #(заочка) — сколько дней реально нашлось, В ТОМ ПОРЯДКЕ, в котором их
        #разобрал парсер (уже хронологический, Пнд→Вск — см. dmap).
        day_order = list(dmap.keys()) if self._is_dated() else sched.WEEKDAYS
        for day in day_order:
            self._days_lay.addWidget(self._build_day_card(day, dmap.get(day, [])))

    def _build_day_card(self, day: str, items: list) -> QWidget:
        c = card()
        c.setFixedWidth(250)
        c.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        lay = QVBoxLayout(c)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignTop)
        lay.addWidget(section_lbl(_DAY_FULL.get(day, day)))

        if not items:
            empty = lbl("— нет занятий —", 12, C["text3"])
            lay.addWidget(empty)
            return c

        for tag, ls in items:
            lay.addWidget(self._build_pair_widget(tag, ls))
        return c

    def _build_pair_widget(self, tag: str, ls) -> QWidget:
        w = card2()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)

        #верхняя строка: № пары + время + бейдж типа
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(lbl(f"{ls.pair_no}.", 12, C["text3"], True))
        top.addWidget(lbl(ls.time or "", 11, C["text3"]))
        top.addStretch(1)
        if ls.kind:
            top.addWidget(self._kind_badge(ls.kind))
        lay.addLayout(top)

        #предмет (крупно, с укорачиванием длинных названий)
        subj = ls.subject or ls.raw
        lay.addWidget(ElidingLabel(subj, 13, C["text"], max_width=216))

        #преподаватель / группа и аудитория
        meta_parts = []
        if self.kind == "teacher" and tag:
            meta_parts.append(f"гр. {tag}")
        elif ls.teacher:
            meta_parts.append(ls.teacher)
        if ls.room:
            meta_parts.append(f"ауд. {ls.room}")
        if meta_parts:
            lay.addWidget(ElidingLabel("  ·  ".join(meta_parts), 11, C["text3"],
                                       max_width=216))
        #вторая подгруппа / сноска, если была
        if ls.extra:
            lay.addWidget(ElidingLabel(ls.extra, 10, C["text2"], max_width=216))
        return w

    def _kind_badge(self, kind: str) -> QFrame:
        color = _KIND_COLOR.get(kind, C["text3"])
        text = _KIND_FULL.get(kind, kind)
        f = QFrame()
        fl = QHBoxLayout(f)
        fl.setContentsMargins(0, 0, 0, 0)
        b = lbl(text, 10, color, True)
        b.setStyleSheet(
            f"font-size:10px;font-weight:700;color:{color};"
            f"background:rgba(0,0,0,0.0);border:1px solid {color};"
            f"border-radius:6px;padding:1px 6px;")
        fl.addWidget(b)
        return f
