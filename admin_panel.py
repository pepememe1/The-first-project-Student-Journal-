"""
admin_panel.py — Панель администратора ВСГУТУ Журнала
"""

import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QStackedWidget,
    QFormLayout, QScrollArea, QCheckBox, QMessageBox,
    QComboBox, QSizePolicy, QFrame, QInputDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from security import secure_store

ALL_SUBJECTS = [
    "Аварийно-спасательные работы на высоте",
    "Аварийно-спасательное, газоспасательное и пожарное оборудование и инструменты",
    "Административный процесс",
    "Архитектура аппаратных средств",
    "Архитектурно-строительные конструкции",
    "Безопасность жизнедеятельности",
    "Безопасность работ при эксплуатации и ремонте оборудования электрических подстанций и сетей",
    "Гражданское право",
    "Дискретная математика",
    "Договорное право",
    "Инженерная графика",
    "Иностранный язык",
    "Иностранный язык второй",
    "Иностранный язык в профессиональной деятельности",
    "Информационно-коммуникационные технологии в туризме и гостеприимстве",
    "Информационные технологии в профессиональной деятельности",
    "Информационные технологии в юридической деятельности",
    "История России",
    "Компьютерные сети",
    "Компьютерные сети ЭВМ",
    "Координация работы по реализации заказа экскурсионных услуг",
    "Корпоративное право и юридическое сопровождение деятельности организаций и физических лиц",
    "Метрология и стандартизация",
    "Монтаж и наладка воздушных линий электропередачи",
    "Оказание первой помощи и психологическая поддержка",
    "Операционные системы и среды",
    "Организация принципы построения и функционирования компьютерных сетей",
    "Организация ремонта и наладки устройств электроснабжения",
    "Освоение должности служащего",
    "Основы алгоритмизации и программирования",
    "Основы бережливого производства",
    "Основы ведения аварийно-спасательных работ",
    "Основы геологии",
    "Основы предпринимательской деятельности",
    "Основы проектирования баз данных",
    "Основы топографии",
    "Основы финансовой грамотности",
    "Основы эксплуатации электрооборудования",
    "Оформление и обработка заказов клиентов экскурсионных услуг",
    "Охрана труда",
    "Подготовка по профессии пожарный",
    "Подготовка по профессии промышленный альпинист",
    "Подготовка по профессии электромонтёр по обслуживанию подстанций",
    "Потенциально опасные процессы",
    "Предпринимательская деятельность в сфере туризма и гостиничного бизнеса",
    "Правовое и документационное обеспечение в туризме и гостеприимстве",
    "Психология делового общения и конфликтология",
    "Психология экстремальных ситуаций",
    "Разработка объемно-планировочных и конструктивных решений объектов капитального строительства",
    "Разработка программных модулей",
    "Разработка проектной документации по организации строительства объектов капитального строительства",
    "Сервисная деятельность в туризме и гостеприимстве",
    "Сопровождение туристов при прохождении маршрута",
    "Судебная и альтернативные формы защиты прав организаций и физических лиц",
    "Судоустройство и правоохранительные органы",
    "Техническая механика",
    "Техническое обслуживание и ремонт оборудования электрических подстанций и сетей",
    "Трудовое право",
    "Физическая культура",
    "Численные методы",
    "Экономика и бухгалтерский учёт предприятий туризма и гостиничного дела",
    "Экологические основы природопользования",
    "Электроматериаловедение",
    "Электротехника и электроника",
    "Элементы высшей математики",
]

STYLE_BTN = """
QPushButton {
    background-color: #2c3e50;
    color: white;
    border-radius: 6px;
    padding: 8px 14px;
    font-size: 13px;
}
QPushButton:hover { background-color: #34495e; }
QPushButton:pressed { background-color: #1a252f; }
"""

STYLE_BTN_RED = """
QPushButton {
    background-color: #c0392b;
    color: white;
    border-radius: 6px;
    padding: 8px 14px;
}
QPushButton:hover { background-color: #e74c3c; }
"""

STYLE_BTN_GREEN = """
QPushButton {
    background-color: #27ae60;
    color: white;
    border-radius: 6px;
    padding: 8px 14px;
}
QPushButton:hover { background-color: #2ecc71; }
"""


def make_back_btn(callback) -> QPushButton:
    btn = QPushButton("← Назад")
    btn.setStyleSheet(STYLE_BTN)
    btn.clicked.connect(callback)
    return btn


class SubjectSelector(QWidget):
    """Выпадающий список предметов с множественным выбором."""
    changed = Signal(list)

    def __init__(self, selected: list = None, parent=None):
        super().__init__(parent)
        self._selected = list(selected or [])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.btn = QPushButton("Выбрать предметы ▼")
        self.btn.setStyleSheet(STYLE_BTN)
        self.btn.clicked.connect(self._toggle)
        layout.addWidget(self.btn)

        self.panel = QWidget()
        self.panel.hide()
        panel_layout = QVBoxLayout(self.panel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(200)
        inner = QWidget()
        self.checkboxes = []
        inner_l = QVBoxLayout(inner)
        for subj in ALL_SUBJECTS:
            cb = QCheckBox(subj)
            cb.setChecked(subj in self._selected)
            cb.stateChanged.connect(self._update)
            self.checkboxes.append(cb)
            inner_l.addWidget(cb)
        scroll.setWidget(inner)
        panel_layout.addWidget(scroll)
        layout.addWidget(self.panel)
        self._update_btn_text()

    def _toggle(self):
        self.panel.setVisible(not self.panel.isVisible())

    def _update(self):
        self._selected = [cb.text() for cb in self.checkboxes if cb.isChecked()]
        self._update_btn_text()
        self.changed.emit(self._selected)

    def _update_btn_text(self):
        if self._selected:
            self.btn.setText(f"Выбрано предметов: {len(self._selected)} ▼")
        else:
            self.btn.setText("Выбрать предметы ▼")

    def get_selected(self) -> list:
        return self._selected

    def set_selected(self, subjects: list):
        self._selected = list(subjects)
        for cb in self.checkboxes:
            cb.setChecked(cb.text() in self._selected)
        self._update_btn_text()


class GroupSelector(QWidget):
    """Выпадающий список групп с опциональной фильтрацией по предмету."""
    changed = Signal(str)

    def __init__(self, selected: str = "", filter_subject: str = "", parent=None):
        super().__init__(parent)
        self._selected = selected
        self._filter_subject = filter_subject  # если задан — показывать только группы с этим предметом
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.btn = QPushButton(selected or "Выбрать группу ▼")
        self.btn.setStyleSheet(STYLE_BTN)
        self.btn.clicked.connect(self._toggle)
        layout.addWidget(self.btn)

        self.panel = QWidget()
        self.panel.hide()
        panel_layout = QVBoxLayout(self.panel)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(150)
        self._inner = QWidget()
        self.group_btns = []
        self.inner_l = QVBoxLayout(self._inner)
        self._rebuild()
        scroll.setWidget(self._inner)
        panel_layout.addWidget(scroll)
        layout.addWidget(self.panel)

    def set_filter_subject(self, subject: str):
        """Устанавливает фильтр — показывать только группы с этим предметом."""
        self._filter_subject = subject
        self._rebuild()

    def _rebuild(self):
        for w in self.group_btns:
            w.setParent(None)
        self.group_btns.clear()
        groups = secure_store.get_groups()
        for g in groups:
            # Фильтрация: если задан предмет — показывать только группы у которых он есть
            if self._filter_subject and self._filter_subject not in g.get("subjects", []):
                continue
            gb = QPushButton(g["name"])
            gb.clicked.connect(lambda _, name=g["name"]: self._select(name))
            self.group_btns.append(gb)
            self.inner_l.addWidget(gb)
        # Если нет подходящих групп — показываем подсказку
        if not self.group_btns and self._filter_subject:
            lbl = QPushButton("(нет групп с этим предметом)")
            lbl.setEnabled(False)
            lbl.setStyleSheet("color:#888;")
            self.group_btns.append(lbl)
            self.inner_l.addWidget(lbl)

    def _toggle(self):
        self._rebuild()
        self.panel.setVisible(not self.panel.isVisible())

    def _select(self, name: str):
        self._selected = name
        self.btn.setText(name)
        self.panel.hide()
        self.changed.emit(name)

    def get_selected(self) -> str:
        return self._selected


# ===================== СТРАНИЦЫ АДМИНИСТРАТОРА =====================

class ApiKeyPage(QWidget):
    def __init__(self, back_cb, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(make_back_btn(back_cb))

        title = QLabel("API ключ OpenRouter")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        layout.addWidget(title)

        # Статус ключа
        current_key = secure_store.get_api_key()
        self.status_lbl = QLabel()
        self._update_status_label(current_key)
        self.status_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_lbl)

        layout.addWidget(QLabel("Введите новый API ключ:"))
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("sk-or-v1-...")
        self.key_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.key_input)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("💾 Сохранить")
        save_btn.setStyleSheet(STYLE_BTN_GREEN)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        delete_btn = QPushButton("🗑 Удалить ключ")
        delete_btn.setStyleSheet(STYLE_BTN_RED)
        delete_btn.clicked.connect(self._delete)
        btn_row.addWidget(delete_btn)
        layout.addLayout(btn_row)

        layout.addStretch()

    def _update_status_label(self, key: str):
        if key:
            masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
            self.status_lbl.setText(f"Текущий ключ: {masked}")
            self.status_lbl.setStyleSheet("color:#27ae60; font-size:12px;")
        else:
            self.status_lbl.setText("Ключ не установлен — ИИ работать не будет.")
            self.status_lbl.setStyleSheet("color:#e74c3c; font-size:12px;")

    def _save(self):
        key = self.key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "Ошибка", "Введите API ключ.")
            return
        secure_store.set_api_key(key)
        self._update_status_label(key)
        self.key_input.clear()
        QMessageBox.information(self, "Сохранено", "API ключ успешно сохранён и зашифрован.")

    def _delete(self):
        confirm = QMessageBox.question(
            self, "Подтверждение",
            "Удалить API ключ?\nИИ-помощник перестанет работать до установки нового ключа.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            secure_store.delete("openrouter_api_key")
            self._update_status_label("")
            QMessageBox.information(self, "Удалено", "API ключ удалён.")


class TeacherDetailPage(QWidget):
    saved = Signal()

    def __init__(self, teacher_name: str, back_cb, parent=None):
        super().__init__(parent)
        self.teacher_name = teacher_name
        layout = QVBoxLayout(self)
        layout.addWidget(make_back_btn(back_cb))

        teachers = secure_store.get_teachers()
        data = teachers.get(teacher_name, {"password": "", "subjects": []})

        title = QLabel(teacher_name)
        title.setStyleSheet("font-size:18px; font-weight:bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        layout.addWidget(QLabel("Предметы:"))
        self.subj_selector = SubjectSelector(data.get("subjects", []))
        layout.addWidget(self.subj_selector)

        # Назначение групп по предметам
        layout.addWidget(QLabel("Назначение групп по предметам:"))
        self.group_assignments = {}
        self.assign_widget = QWidget()
        self.assign_layout = QVBoxLayout(self.assign_widget)
        layout.addWidget(self.assign_widget)
        self.subj_selector.changed.connect(self._rebuild_assignments)
        self._rebuild_assignments(data.get("subjects", []))

        # Пароль
        pw_layout = QHBoxLayout()
        pw_layout.addWidget(QLabel("Пароль:"))
        self.pw_edit = QLineEdit(data.get("password", ""))
        self.pw_edit.setEchoMode(QLineEdit.Password)
        pw_layout.addWidget(self.pw_edit)
        show_btn = QPushButton("👁")
        show_btn.setFixedWidth(35)
        show_btn.clicked.connect(lambda: self.pw_edit.setEchoMode(
            QLineEdit.Normal if self.pw_edit.echoMode() == QLineEdit.Password else QLineEdit.Password))
        pw_layout.addWidget(show_btn)
        layout.addLayout(pw_layout)

        save_btn = QPushButton("Сохранить данные преподавателя")
        save_btn.setStyleSheet(STYLE_BTN_GREEN)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

        del_btn = QPushButton("🗑 Удалить преподавателя")
        del_btn.setStyleSheet(STYLE_BTN_RED)
        del_btn.clicked.connect(self._delete)
        layout.addWidget(del_btn)

    def _rebuild_assignments(self, subjects: list):
        for i in reversed(range(self.assign_layout.count())):
            w = self.assign_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        self.group_assignments = {}
        teachers = secure_store.get_teachers()
        data = teachers.get(self.teacher_name, {})
        existing = data.get("group_assignments", {})
        for subj in subjects:
            row = QHBoxLayout()
            lbl = QLabel(f"  {subj}:")
            lbl.setFixedWidth(300)
            # Передаём предмет как фильтр — показываем только группы у которых он есть
            combo = GroupSelector(existing.get(subj, ""), filter_subject=subj)
            row.addWidget(lbl)
            row.addWidget(combo)
            container = QWidget()
            container.setLayout(row)
            self.assign_layout.addWidget(container)
            self.group_assignments[subj] = combo

    def _save(self):
        teachers = secure_store.get_teachers()
        assignments = {subj: sel.get_selected() for subj, sel in self.group_assignments.items()}
        teachers[self.teacher_name] = {
            "password": self.pw_edit.text(),
            "subjects": self.subj_selector.get_selected(),
            "group_assignments": assignments
        }
        secure_store.set_teachers(teachers)
        QMessageBox.information(self, "Сохранено", "Данные преподавателя сохранены.")
        self.saved.emit()

    def _delete(self):
        confirm = QMessageBox.question(
            self, "Удаление преподавателя",
            f"Удалить преподавателя «{self.teacher_name}»?\n\n"
            "Все его данные (предметы, назначения групп, пароль) будут удалены безвозвратно.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        teachers = secure_store.get_teachers()
        teachers.pop(self.teacher_name, None)
        secure_store.set_teachers(teachers)
        QMessageBox.information(self, "Удалено", f"Преподаватель «{self.teacher_name}» удалён.")
        self.saved.emit()


class TeachersPage(QWidget):
    def __init__(self, stack: QStackedWidget, back_cb, parent=None):
        super().__init__(parent)
        self.stack = stack
        layout = QVBoxLayout(self)
        layout.addWidget(make_back_btn(back_cb))

        title = QLabel("Преподаватели")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        layout.addWidget(title)

        # Фильтр по предмету
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Фильтр по предмету:"))
        self.subject_filter = QComboBox()
        self.subject_filter.addItem("Все")
        self.subject_filter.addItems(ALL_SUBJECTS)
        self.subject_filter.currentTextChanged.connect(self._refresh)
        filter_layout.addWidget(self.subject_filter)
        self.free_only = QCheckBox("Не занят")
        self.free_only.stateChanged.connect(self._refresh)
        filter_layout.addWidget(self.free_only)
        layout.addLayout(filter_layout)

        self.teacher_list = QListWidget()
        self.teacher_list.itemDoubleClicked.connect(self._open_teacher)
        layout.addWidget(self.teacher_list)
        self._refresh()

    def _refresh(self):
        self.teacher_list.clear()
        teachers = secure_store.get_teachers()
        subj_filter = self.subject_filter.currentText()
        free_only = self.free_only.isChecked()

        for name, data in teachers.items():
            subjects = data.get("subjects", [])
            if subj_filter != "Все" and subj_filter not in subjects:
                continue
            if free_only and subj_filter != "Все":
                assignments = data.get("group_assignments", {})
                if assignments.get(subj_filter):
                    continue
            item = QListWidgetItem(name)
            self.teacher_list.addItem(item)

    def _open_teacher(self, item):
        name = item.text()
        detail = TeacherDetailPage(name, lambda: self.stack.setCurrentWidget(self))
        detail.saved.connect(self._refresh)
        self.stack.addWidget(detail)
        self.stack.setCurrentWidget(detail)


class StudentDetailPage(QWidget):
    def __init__(self, student_data: dict, back_cb, parent=None):
        super().__init__(parent)
        self.student_data = student_data
        self._back_cb = back_cb
        layout = QVBoxLayout(self)
        layout.addWidget(make_back_btn(back_cb))

        name = f"{student_data.get('name', '')} {student_data.get('surname', '')}"
        title = QLabel(name)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:18px; font-weight:bold;")
        layout.addWidget(title)

        form = QFormLayout()
        layout.addLayout(form)

        form.addRow("Группа обучающегося:", QLabel())
        self.group_sel = GroupSelector(student_data.get("group", ""))
        form.addRow("", self.group_sel)

        self.group_sel.changed.connect(self._update_subjects)
        self.subjects_label = QLabel()
        layout.addWidget(QLabel("Предметы группы:"))
        layout.addWidget(self.subjects_label)
        self._update_subjects(student_data.get("group", ""))

        save_btn = QPushButton("Сохранить")
        save_btn.setStyleSheet(STYLE_BTN_GREEN)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

        del_btn = QPushButton("🗑 Удалить студента")
        del_btn.setStyleSheet(STYLE_BTN_RED)
        del_btn.clicked.connect(self._delete)
        layout.addWidget(del_btn)

    def _delete(self):
        name = f"{self.student_data.get('surname', '')} {self.student_data.get('name', '')}"
        confirm = QMessageBox.question(
            self, "Удаление студента",
            f"Удалить студента «{name}»?\n\n"
            "Студент будет удалён из списков. Оценки в журналах останутся в базе данных.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        students = secure_store.get_students()
        idx = self.student_data.get("_idx", -1)
        if 0 <= idx < len(students):
            students.pop(idx)
            secure_store.set_students(students)
        QMessageBox.information(self, "Удалено", f"Студент «{name}» удалён.")
        # Возвращаемся назад через back_cb
        self._back_cb()

    def _update_subjects(self, group_name: str):
        groups = secure_store.get_groups()
        for g in groups:
            if g["name"] == group_name:
                subjects = g.get("subjects", [])
                self.subjects_label.setText("\n".join(f"• {s}" for s in subjects) or "—")
                return
        self.subjects_label.setText("—")

    def _save(self):
        students = secure_store.get_students()
        idx = self.student_data.get("_idx", -1)
        new_data = {
            "name": self.student_data["name"],
            "surname": self.student_data["surname"],
            "group": self.group_sel.get_selected()
        }
        if 0 <= idx < len(students):
            students[idx] = new_data
            secure_store.set_students(students)
            QMessageBox.information(self, "Сохранено", "Данные студента сохранены.")


class StudentsPage(QWidget):
    def __init__(self, stack: QStackedWidget, back_cb, parent=None):
        super().__init__(parent)
        self.stack = stack
        layout = QVBoxLayout(self)
        layout.addWidget(make_back_btn(back_cb))

        title = QLabel("Студенты")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        layout.addWidget(title)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Фильтр по группе:"))
        self.group_filter = QComboBox()
        self.group_filter.addItem("Все")
        self.group_filter.addItem("Без группы")
        groups = secure_store.get_groups()
        for g in groups:
            self.group_filter.addItem(g["name"])
        self.group_filter.currentTextChanged.connect(self._refresh)
        filter_layout.addWidget(self.group_filter)
        layout.addLayout(filter_layout)

        self.student_list = QListWidget()
        self.student_list.itemDoubleClicked.connect(self._open_student)
        layout.addWidget(self.student_list)
        self._refresh()

    def _refresh(self):
        self.student_list.clear()
        students = secure_store.get_students()
        group_filter = self.group_filter.currentText()
        for i, s in enumerate(students):
            group = s.get("group", "")
            if group_filter == "Без группы" and group:
                continue
            if group_filter not in ("Все", "Без группы") and group != group_filter:
                continue
            label = f"{s.get('surname', '')} {s.get('name', '')}  [{group or '—'}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, i)
            self.student_list.addItem(item)

    def _open_student(self, item):
        idx = item.data(Qt.UserRole)
        students = secure_store.get_students()
        data = dict(students[idx])
        data["_idx"] = idx
        detail = StudentDetailPage(data, lambda: self.stack.setCurrentWidget(self))
        self.stack.addWidget(detail)
        self.stack.setCurrentWidget(detail)


class SubjectSelectorWithSearch(QWidget):
    """Список предметов с поиском и чекбоксами."""
    changed = Signal(list)

    def __init__(self, selected: list = None, parent=None):
        super().__init__(parent)
        self._selected = list(selected or [])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Поле поиска
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 Поиск предмета...")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        # Счётчик выбранных
        self.count_lbl = QLabel()
        self.count_lbl.setStyleSheet("color:#7eb8f7; font-size:11px;")
        layout.addWidget(self.count_lbl)

        # Список с прокруткой
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(220)
        self._inner = QWidget()
        self._inner_l = QVBoxLayout(self._inner)
        self._inner_l.setSpacing(2)
        self.checkboxes = []
        for subj in ALL_SUBJECTS:
            cb = QCheckBox(subj)
            cb.setChecked(subj in self._selected)
            cb.stateChanged.connect(self._update)
            self.checkboxes.append(cb)
            self._inner_l.addWidget(cb)
        scroll.setWidget(self._inner)
        layout.addWidget(scroll)
        self._update_count()

    def _filter(self, text: str):
        text = text.lower()
        for cb in self.checkboxes:
            cb.setVisible(text == "" or text in cb.text().lower())

    def _update(self):
        self._selected = [cb.text() for cb in self.checkboxes if cb.isChecked()]
        self._update_count()
        self.changed.emit(self._selected)

    def _update_count(self):
        self.count_lbl.setText(f"Выбрано предметов: {len(self._selected)}")

    def get_selected(self) -> list:
        return self._selected

    def set_selected(self, subjects: list):
        self._selected = list(subjects)
        for cb in self.checkboxes:
            cb.setChecked(cb.text() in self._selected)
        self._update_count()


class GroupDetailPage(QWidget):
    saved = Signal()

    def __init__(self, group_data: dict, back_cb, parent=None):
        super().__init__(parent)
        self.group_name = group_data.get("name", "")
        self._back_cb = back_cb
        layout = QVBoxLayout(self)
        layout.addWidget(make_back_btn(back_cb))

        title = QLabel(self.group_name)
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Студенты группы
        students = secure_store.get_students()
        group_students = [s for s in students if s.get("group") == self.group_name]
        stud_lbl = QLabel(f"Студентов в группе: {len(group_students)}")
        stud_lbl.setStyleSheet("color:#7eb8f7; font-size:12px;")
        layout.addWidget(stud_lbl)

        stud_scroll = QScrollArea()
        stud_scroll.setFixedHeight(100)
        stud_scroll.setWidgetResizable(True)
        stud_inner = QWidget()
        stud_inner_l = QVBoxLayout(stud_inner)
        if group_students:
            for s in group_students:
                stud_inner_l.addWidget(QLabel(f"• {s.get('surname', '')} {s.get('name', '')}"))
        else:
            stud_inner_l.addWidget(QLabel("  (нет студентов)"))
        stud_scroll.setWidget(stud_inner)
        layout.addWidget(stud_scroll)

        # Предметы — с поиском и редактированием
        layout.addWidget(QLabel("Предметы группы (можно редактировать):"))
        self.subj_selector = SubjectSelectorWithSearch(group_data.get("subjects", []))
        layout.addWidget(self.subj_selector)

        save_btn = QPushButton("💾 Сохранить изменения группы")
        save_btn.setStyleSheet(STYLE_BTN_GREEN)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

        del_btn = QPushButton("🗑 Удалить группу")
        del_btn.setStyleSheet(STYLE_BTN_RED)
        del_btn.clicked.connect(self._delete)
        layout.addWidget(del_btn)

    def _delete(self):
        confirm = QMessageBox.question(
            self, "Удаление группы",
            f"Удалить группу «{self.group_name}»?\n\n"
            "Группа будет удалена из списков.\n"
            "Студенты этой группы останутся в базе, но без привязки к группе.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        # Удаляем группу
        groups = secure_store.get_groups()
        groups = [g for g in groups if g["name"] != self.group_name]
        secure_store.set_groups(groups)
        # Убираем привязку студентов к этой группе
        students = secure_store.get_students()
        for s in students:
            if s.get("group") == self.group_name:
                s["group"] = ""
        secure_store.set_students(students)
        QMessageBox.information(self, "Удалено", f"Группа «{self.group_name}» удалена.")
        self._back_cb()

    def _save(self):
        groups = secure_store.get_groups()
        for g in groups:
            if g["name"] == self.group_name:
                g["subjects"] = self.subj_selector.get_selected()
                break
        secure_store.set_groups(groups)
        QMessageBox.information(self, "Сохранено", f"Предметы группы {self.group_name} обновлены.")
        self.saved.emit()


class GroupsPage(QWidget):
    def __init__(self, stack: QStackedWidget, back_cb, parent=None):
        super().__init__(parent)
        self.stack = stack
        layout = QVBoxLayout(self)
        layout.addWidget(make_back_btn(back_cb))

        title = QLabel("Группы")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        layout.addWidget(title)

        layout.addWidget(QLabel("Фильтр по предметам:"))
        self.subject_checkboxes = {}
        scroll = QScrollArea()
        scroll.setFixedHeight(120)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_l = QVBoxLayout(inner)
        for subj in ALL_SUBJECTS:
            cb = QCheckBox(subj)
            cb.stateChanged.connect(self._refresh)
            self.subject_checkboxes[subj] = cb
            inner_l.addWidget(cb)
        scroll.setWidget(inner)
        layout.addWidget(scroll)

        self.group_list = QListWidget()
        self.group_list.itemDoubleClicked.connect(self._open_group)
        layout.addWidget(self.group_list)
        self._refresh()

    def _refresh(self):
        self.group_list.clear()
        selected_subjects = [subj for subj, cb in self.subject_checkboxes.items() if cb.isChecked()]
        groups = secure_store.get_groups()
        for g in groups:
            if selected_subjects:
                g_subjects = set(g.get("subjects", []))
                if not any(s in g_subjects for s in selected_subjects):
                    continue
            self.group_list.addItem(QListWidgetItem(g["name"]))

    def _open_group(self, item):
        name = item.text()
        groups = secure_store.get_groups()
        data = next((g for g in groups if g["name"] == name), {"name": name, "subjects": []})
        detail = GroupDetailPage(data, lambda: self.stack.setCurrentWidget(self))
        self.stack.addWidget(detail)
        self.stack.setCurrentWidget(detail)


class AddDataPage(QWidget):
    """Страница добавления: Преподаватель / Студент / Группа"""

    def __init__(self, back_cb, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(make_back_btn(back_cb))

        title = QLabel("Добавить данные")
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        layout.addWidget(title)

        tabs = QHBoxLayout()
        btn_t = QPushButton("Добавить преподавателя")
        btn_s = QPushButton("Добавить студента")
        btn_g = QPushButton("Добавить группу")
        for b in [btn_t, btn_s, btn_g]:
            b.setStyleSheet(STYLE_BTN)
            tabs.addWidget(b)
        layout.addLayout(tabs)

        self.inner_stack = QStackedWidget()
        layout.addWidget(self.inner_stack)

        btn_t.clicked.connect(lambda: self.inner_stack.setCurrentIndex(0))
        btn_s.clicked.connect(lambda: self.inner_stack.setCurrentIndex(1))
        btn_g.clicked.connect(lambda: self.inner_stack.setCurrentIndex(2))

        self.inner_stack.addWidget(self._build_teacher_form())
        self.inner_stack.addWidget(self._build_student_form())
        self.inner_stack.addWidget(self._build_group_form())

    def _build_teacher_form(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()
        self.t_name = QLineEdit()
        self.t_surname = QLineEdit()
        self.t_password = QLineEdit()
        self.t_password.setEchoMode(QLineEdit.Password)
        form.addRow("Имя:", self.t_name)
        form.addRow("Фамилия:", self.t_surname)
        form.addRow("Пароль:", self.t_password)
        layout.addLayout(form)
        layout.addWidget(QLabel("Предметы:"))
        self.t_subj_sel = SubjectSelector()
        layout.addWidget(self.t_subj_sel)
        save_btn = QPushButton("Сохранить")
        save_btn.setStyleSheet(STYLE_BTN_GREEN)
        save_btn.clicked.connect(self._save_teacher)
        layout.addWidget(save_btn)
        return w

    def _build_student_form(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()
        self.s_name = QLineEdit()
        self.s_surname = QLineEdit()
        form.addRow("Имя:", self.s_name)
        form.addRow("Фамилия:", self.s_surname)
        layout.addLayout(form)
        layout.addWidget(QLabel("Группа:"))
        self.s_group_sel = GroupSelector()
        layout.addWidget(self.s_group_sel)
        save_btn = QPushButton("Сохранить")
        save_btn.setStyleSheet(STYLE_BTN_GREEN)
        save_btn.clicked.connect(self._save_student)
        layout.addWidget(save_btn)

        sep = QLabel("── или импортировать из Excel ──")
        sep.setAlignment(Qt.AlignCenter)
        sep.setStyleSheet("color:#6080a0; font-size:11px; margin-top:10px;")
        layout.addWidget(sep)

        imp_btn = QPushButton("📥 Импортировать студентов из Excel...")
        imp_btn.setStyleSheet(STYLE_BTN)
        imp_btn.clicked.connect(self._import_students_excel)
        layout.addWidget(imp_btn)
        return w

    def _import_students_excel(self):
        """Импорт студентов из Excel-журнала колледжа. Группу выбираем вручную."""
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть Excel с журналом", "",
            "Excel Files (*.xlsx *.xls)"
        )
        if not path:
            return
        # Выбор группы вручную
        groups = [g["name"] for g in secure_store.get_groups()]
        if not groups:
            QMessageBox.warning(self, "Нет групп", "Сначала создайте группы в системе.")
            return
        group, ok = QInputDialog.getItem(
            self, "Выберите группу",
            "В какую группу добавить студентов?", groups, 0, False
        )
        if not ok:
            return
        try:
            from openpyxl import load_workbook
            wb   = load_workbook(path)
            ws   = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if len(rows) < 2:
                QMessageBox.warning(self, "Ошибка", "Файл пустой.")
                return

            row0 = rows[0]
            row1 = rows[1]
            is_college = (
                row1 and any(str(v).strip() in ("1 час","2 час") for v in row1 if v)
            )

            existing = secure_store.get_students()
            existing_keys = {
                (s.get("surname","").lower(), s.get("group",""))
                for s in existing
            }
            added = 0

            if is_college:
                # Строки с 3-й: col 1 = ФИО
                data_rows = rows[2:]
                fio_col   = 1
            else:
                # Строки с 2-й: col 0 = фамилия, col 1 = имя
                data_rows = rows[1:]
                fio_col   = None

            for row in data_rows:
                if not row:
                    continue
                if is_college:
                    if not row[fio_col]:
                        continue
                    fio   = str(row[fio_col]).strip()
                    parts = fio.split()
                    if not parts:
                        continue
                    surname  = parts[0]
                    initials = " ".join(parts[1:]) if len(parts) > 1 else ""
                    name     = initials
                else:
                    if not row[0]:
                        continue
                    surname = str(row[0]).strip()
                    name    = str(row[1]).strip() if len(row) > 1 and row[1] else ""

                if not surname:
                    continue
                key = (surname.lower(), group)
                if key not in existing_keys:
                    existing.append({"name": name, "surname": surname, "group": group})
                    existing_keys.add(key)
                    added += 1

            secure_store.set_students(existing)
            QMessageBox.information(
                self, "Импорт завершён",
                f"Группа: {group}\nДобавлено новых студентов: {added}"
            )
        except ImportError:
            QMessageBox.critical(self, "Ошибка", "Установите: pip install openpyxl")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", str(e))

    def _build_group_form(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QFormLayout()
        self.g_name = QLineEdit()
        form.addRow("Название группы:", self.g_name)
        layout.addLayout(form)
        layout.addWidget(QLabel("Предметы:"))
        self.g_subj_sel = SubjectSelector()
        layout.addWidget(self.g_subj_sel)
        save_btn = QPushButton("Сохранить")
        save_btn.setStyleSheet(STYLE_BTN_GREEN)
        save_btn.clicked.connect(self._save_group)
        layout.addWidget(save_btn)
        return w

    def _save_teacher(self):
        name = self.t_name.text().strip()
        surname = self.t_surname.text().strip()
        if not name or not surname:
            QMessageBox.warning(self, "Ошибка", "Введите имя и фамилию.")
            return
        full_name = f"{surname} {name}"
        teachers = secure_store.get_teachers()
        teachers[full_name] = {
            "password": self.t_password.text(),
            "subjects": self.t_subj_sel.get_selected(),
            "group_assignments": {}
        }
        secure_store.set_teachers(teachers)
        QMessageBox.information(self, "Добавлено", f"Преподаватель {full_name} добавлен.")
        self.t_name.clear(); self.t_surname.clear(); self.t_password.clear()

    def _save_student(self):
        name = self.s_name.text().strip()
        surname = self.s_surname.text().strip()
        if not name or not surname:
            QMessageBox.warning(self, "Ошибка", "Введите имя и фамилию.")
            return
        students = secure_store.get_students()
        students.append({"name": name, "surname": surname, "group": self.s_group_sel.get_selected()})
        secure_store.set_students(students)
        QMessageBox.information(self, "Добавлено", f"Студент {surname} {name} добавлен.")
        self.s_name.clear(); self.s_surname.clear()

    def _save_group(self):
        gname = self.g_name.text().strip()
        if not gname:
            QMessageBox.warning(self, "Ошибка", "Введите название группы.")
            return
        groups = secure_store.get_groups()
        if any(g["name"] == gname for g in groups):
            QMessageBox.warning(self, "Ошибка", "Группа с таким именем уже существует.")
            return
        groups.append({"name": gname, "subjects": self.g_subj_sel.get_selected()})
        secure_store.set_groups(groups)
        QMessageBox.information(self, "Добавлено", f"Группа {gname} добавлена.")
        self.g_name.clear()


class AdminLoginPage(QWidget):
    """Страница входа в аккаунт администратора."""
    login_success = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel("⚙ Администратор")
        title.setStyleSheet("font-size:20px; font-weight:bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        form = QFormLayout()
        self.login_input = QLineEdit()
        self.login_input.setPlaceholderText("Логин")
        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.pass_input.setPlaceholderText("Пароль")
        form.addRow("Логин:", self.login_input)
        form.addRow("Пароль:", self.pass_input)
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        layout.addWidget(self.error_label)

        enter_btn = QPushButton("Войти")
        enter_btn.setStyleSheet(STYLE_BTN)
        enter_btn.clicked.connect(self._try_login)
        self.pass_input.returnPressed.connect(self._try_login)
        layout.addWidget(enter_btn)

    def _try_login(self):
        login = self.login_input.text().strip()
        password = self.pass_input.text()
        admin_password = secure_store.get_admin_password()
        if login == "admin_vsgutu" and password == admin_password:
            self.error_label.setText("")
            self.login_success.emit()
        else:
            self.error_label.setText("Неверный логин или пароль.")


class TransferPage(QWidget):
    """
    Страница переноса данных между ПК.
    Экспорт: сохраняет secure_data.enc в выбранное место.
    Импорт: загружает файл с другого ПК и заменяет текущие данные.
    Файл читается только программой — открыть вручную невозможно.
    """

    def __init__(self, back_cb, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(14)
        layout.addWidget(make_back_btn(back_cb))

        title = QLabel("📦 Перенос данных между компьютерами")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:16px; font-weight:bold;")
        layout.addWidget(title)

        # ── Пояснение ──────────────────────────────────────────
        info = QLabel(
            "Данные шифруются паролем администратора.\n"
            "Файл можно перенести на любой ПК — программа его расшифрует.\n"
            "Открыть файл вручную невозможно."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            "background-color:#1e2d1e; border:1px solid #2d5a2d;"
            "border-radius:6px; padding:10px; color:#7dd87d; font-size:12px;"
        )
        layout.addWidget(info)

        # ── Экспорт ────────────────────────────────────────────
        exp_frame = QFrame()
        exp_frame.setStyleSheet(
            "QFrame{background-color:#252b40;border:1px solid #3d4460;border-radius:8px;}"
        )
        exp_layout = QVBoxLayout(exp_frame)
        exp_layout.setContentsMargins(16, 12, 16, 12)

        exp_title = QLabel("⬆ Экспорт (отправить данные на другой ПК)")
        exp_title.setStyleSheet("font-weight:bold; color:#c5d0f0;")
        exp_layout.addWidget(exp_title)

        exp_desc = QLabel(
            "Сохраняет зашифрованный файл данных.\n"
            "Передайте его на другой ПК и импортируйте там."
        )
        exp_desc.setStyleSheet("color:#a0aac0; font-size:12px;")
        exp_desc.setWordWrap(True)
        exp_layout.addWidget(exp_desc)

        export_btn = QPushButton("💾 Экспортировать данные...")
        export_btn.setStyleSheet(STYLE_BTN_GREEN)
        export_btn.setMinimumHeight(38)
        export_btn.clicked.connect(self._export)
        exp_layout.addWidget(export_btn)

        layout.addWidget(exp_frame)

        # ── Импорт ────────────────────────────────────────────
        imp_frame = QFrame()
        imp_frame.setStyleSheet(
            "QFrame{background-color:#252b40;border:1px solid #3d4460;border-radius:8px;}"
        )
        imp_layout = QVBoxLayout(imp_frame)
        imp_layout.setContentsMargins(16, 12, 16, 12)

        imp_title = QLabel("⬇ Импорт (принять данные с другого ПК)")
        imp_title.setStyleSheet("font-weight:bold; color:#c5d0f0;")
        imp_layout.addWidget(imp_title)

        imp_desc = QLabel(
            "Загружает файл экспорта и заменяет текущие данные.\n"
            "Текущие данные будут перезаписаны!"
        )
        imp_desc.setStyleSheet("color:#e8a87c; font-size:12px;")
        imp_desc.setWordWrap(True)
        imp_layout.addWidget(imp_desc)

        import_btn = QPushButton("📂 Импортировать данные...")
        import_btn.setStyleSheet(STYLE_BTN)
        import_btn.setMinimumHeight(38)
        import_btn.clicked.connect(self._import)
        imp_layout.addWidget(import_btn)

        layout.addWidget(imp_frame)
        layout.addStretch()

    def _export(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить файл данных", "vsgutu_data.enc",
            "Зашифрованные данные (*.enc);;Все файлы (*)"
        )
        if not path:
            return
        ok, msg = secure_store.export_portable(path)
        if ok:
            QMessageBox.information(
                self, "Экспорт выполнен",
                f"✅ {msg}\n\nПередайте этот файл на другой ПК\nи импортируйте его там через эту же страницу."
            )
        else:
            QMessageBox.critical(self, "Ошибка экспорта", msg)

    def _import(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть файл данных", "",
            "Зашифрованные данные (*.enc);;Все файлы (*)"
        )
        if not path:
            return
        confirm = QMessageBox.question(
            self, "Подтверждение",
            "Текущие данные будут заменены данными из файла.\n\n"
            "Продолжить?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return
        ok, msg = secure_store.import_portable(path)
        if ok:
            QMessageBox.information(
                self, "Импорт выполнен",
                f"✅ {msg}\n\nПерезапустите программу чтобы данные применились."
            )
        else:
            QMessageBox.critical(
                self, "Ошибка импорта",
                f"❌ {msg}\n\nУбедитесь что файл создан этой программой."
            )


class AdminDashboard(QWidget):
    """Главная панель администратора."""

    def __init__(self, back_to_login_cb, parent=None):
        super().__init__(parent)
        self.back_cb = back_to_login_cb
        main_layout = QVBoxLayout(self)

        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        self.main_page = self._build_main_page()
        self.stack.addWidget(self.main_page)

    def _build_main_page(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        title = QLabel("⚙ Панель администратора ВСГУТУ")
        title.setStyleSheet("font-size:18px; font-weight:bold; margin-bottom:10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        buttons = [
            ("👨‍🏫 Преподаватели", self._open_teachers),
            ("🎓 Студенты", self._open_students),
            ("👥 Группы", self._open_groups),
            ("➕ Добавить данные", self._open_add),
            ("🔑 Ввести API ключ", self._open_api_key),
            ("📦 Перенос данных", self._open_transfer),
        ]
        for label, callback in buttons:
            btn = QPushButton(label)
            btn.setStyleSheet(STYLE_BTN)
            btn.setMinimumHeight(45)
            btn.clicked.connect(callback)
            layout.addWidget(btn)

        exit_btn = QPushButton("Выйти из панели")
        exit_btn.setStyleSheet(STYLE_BTN_RED)
        exit_btn.clicked.connect(self.back_cb)
        layout.addWidget(exit_btn)
        layout.addStretch()
        return w

    def _open_teachers(self):
        page = TeachersPage(self.stack, lambda: self.stack.setCurrentWidget(self.main_page))
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def _open_students(self):
        page = StudentsPage(self.stack, lambda: self.stack.setCurrentWidget(self.main_page))
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def _open_groups(self):
        page = GroupsPage(self.stack, lambda: self.stack.setCurrentWidget(self.main_page))
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def _open_add(self):
        page = AddDataPage(lambda: self.stack.setCurrentWidget(self.main_page))
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def _open_api_key(self):
        page = ApiKeyPage(lambda: self.stack.setCurrentWidget(self.main_page))
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)

    def _open_transfer(self):
        page = TransferPage(lambda: self.stack.setCurrentWidget(self.main_page))
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
