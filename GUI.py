import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QInputDialog, QMessageBox,
    QStackedWidget, QLabel, QLineEdit, QComboBox, QFormLayout,
    QGridLayout, QMenu, QColorDialog
)
from PySide6.QtGui import QColor, QBrush
from core import GradeBook, Student, APP_VERSION
from datetime import datetime, timedelta

GROUPS = ["к74/1", "к74/2", "к74/3", "к75/0"]
SUBJECTS = [
    "Компьютерные сети",
    "Основы алгоритмизации и программирования",
    "Основы проектирования баз данных",
    "Разработка программных модулей"
]


def parse_logins():
    teachers = {}
    pw = ""
    if os.path.exists("logins.txt"):
        with open("logins.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "password=" in line:
                    pw = line.split("=")[1].strip()
                elif "(" in line:
                    parts = line.split("(")
                    name = parts[0].strip()
                    subj = parts[1].replace(")", "").strip()
                    teachers[name] = subj
    return teachers, pw


class MainAppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Журнал ВСГУТУ — {APP_VERSION}")
        self.resize(1300, 700)

        self.teachers_db, self.teacher_pass = parse_logins()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.init_login_ui()
        self.init_teacher_ui()
        self.init_student_ui()

    # ================= LOGIN =================
    def init_login_ui(self):
        self.login_widget = QWidget()
        layout = QVBoxLayout(self.login_widget)

        title = QLabel("СИСТЕМА УЧЕТА УСПЕВАЕМОСТИ")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        btn_box = QHBoxLayout()
        b1 = QPushButton("Я Ученик")
        b2 = QPushButton("Я Учитель")
        btn_box.addWidget(b1)
        btn_box.addWidget(b2)
        layout.addLayout(btn_box)

        self.login_stack = QStackedWidget()
        layout.addWidget(self.login_stack)

        # Ученик
        sw = QWidget()
        sl = QFormLayout(sw)
        self.sn = QLineEdit()
        self.sf = QLineEdit()
        self.sg = QComboBox()
        self.sg.addItems(GROUPS)

        sl.addRow("Имя:", self.sn)
        sl.addRow("Фамилия:", self.sf)
        sl.addRow("Группа:", self.sg)

        btn_s = QPushButton("Войти")
        btn_s.clicked.connect(self.login_student)
        sl.addRow(btn_s)
        self.login_stack.addWidget(sw)

        # Учитель
        tw = QWidget()
        tl = QFormLayout(tw)
        self.tn = QLineEdit()
        self.tp = QLineEdit()
        self.tp.setEchoMode(QLineEdit.Password)

        tl.addRow("Фамилия Имя:", self.tn)
        tl.addRow("Пароль:", self.tp)

        btn_t = QPushButton("Войти")
        btn_t.clicked.connect(self.login_teacher)
        tl.addRow(btn_t)

        self.login_stack.addWidget(tw)

        b1.clicked.connect(lambda: self.login_stack.setCurrentIndex(0))
        b2.clicked.connect(lambda: self.login_stack.setCurrentIndex(1))

        self.stack.addWidget(self.login_widget)

    # ================= STUDENT =================
    def init_student_ui(self):
        self.student_widget = QWidget()
        self.student_layout = QVBoxLayout(self.student_widget)
        self.stack.addWidget(self.student_widget)

    def draw_student_dash(self):
        while self.student_layout.count():
            item = self.student_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        label = QLabel(
            f"Студент: {self.cur_stud['f']} {self.cur_stud['n']} ({self.cur_stud['g']})"
        )
        self.student_layout.addWidget(label)

        grid = QGridLayout()

        for i, subj in enumerate(SUBJECTS):
            btn = QPushButton(subj)
            btn.setMinimumHeight(60)
            btn.clicked.connect(lambda ch, s=subj: self.show_student_journal(s))
            grid.addWidget(btn, i // 2, i % 2)

        self.student_layout.addLayout(grid)

        # ИИ-помощник
        ai_btn = QPushButton("ИИ Помощник")
        ai_btn.clicked.connect(self.student_ai)
        self.student_layout.addWidget(ai_btn)

        back_btn = QPushButton("Выход в главное меню")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        self.student_layout.addWidget(back_btn)

    def show_student_journal(self, subj):
        self.cur_subj = subj
        self.book = GradeBook(self.cur_stud['g'], subj)

        # Создаём виджет
        self.stud_table_widget = QWidget()
        layout = QVBoxLayout(self.stud_table_widget)
        table = QTableWidget()
        layout.addWidget(table)

        table.setRowCount(1)
        table.setColumnCount(len(self.book.lessons) + 3)
        headers = ["№", "Фамилия", "Имя"] + [f"{l.type} {l.number}\n{l.date}\n{l.topic}" for l in self.book.lessons]
        table.setHorizontalHeaderLabels(headers)

        s = next((x for x in self.book.spisok_stud if x.f == self.cur_stud['f']), None)
        if not s:
            QMessageBox.warning(self, "Упс", "Вас нет в списке по этому предмету.")
            return

        table.setItem(0, 0, QTableWidgetItem("1"))
        table.setItem(0, 1, QTableWidgetItem(s.f))
        table.setItem(0, 2, QTableWidgetItem(s.n))

        for i, l in enumerate(self.book.lessons):
            combo = QComboBox()
            if l.type == "Практика":
                combo.addItems(["", "2", "3", "4", "5", "Н"])
                color = QColor(200, 255, 200)  # зеленый
            else:
                combo.addItems(["", "О", "Б", "✓", "Н"])
                color = QColor(255, 200, 200)  # розовый
            combo.setCurrentText(s.records.get(l.id, ""))
            table.setCellWidget(0, 3 + i, combo)
            table.item(0, 3 + i) and table.item(0, 3 + i).setBackground(QBrush(color))

        # Назад
        back_btn = QPushButton("Назад")
        back_btn.clicked.connect(lambda: self.stack.setCurrentWidget(self.student_widget))
        layout.addWidget(back_btn)

        self.stack.addWidget(self.stud_table_widget)
        self.stack.setCurrentWidget(self.stud_table_widget)

    # ================= TEACHER =================
    def init_teacher_ui(self):
        self.teacher_widget = QWidget()
        layout = QVBoxLayout(self.teacher_widget)

        self.t_table = QTableWidget()
        self.t_table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.t_table.horizontalHeader().customContextMenuRequested.connect(self.header_context_menu)
        layout.addWidget(self.t_table)

        btns = QHBoxLayout()
        ba = QPushButton("Добавить студента")
        bl = QPushButton("Добавить занятие")
        be = QPushButton("Назначить экзамен")
        bs = QPushButton("💾 Сохранить")
        bout = QPushButton("Главное меню")

        ba.clicked.connect(self.add_student)
        bl.clicked.connect(self.add_lesson)
        be.clicked.connect(self.add_exam)
        bs.clicked.connect(self.save_data)
        bout.clicked.connect(lambda: self.stack.setCurrentIndex(0))

        btns.addWidget(ba)
        btns.addWidget(bl)
        btns.addWidget(be)
        btns.addWidget(bs)
        btns.addWidget(bout)

        layout.addLayout(btns)
        self.stack.addWidget(self.teacher_widget)

    def add_student(self):
        f, ok1 = QInputDialog.getText(self, "Фамилия", "Введите фамилию:")
        n, ok2 = QInputDialog.getText(self, "Имя", "Введите имя:")
        if ok1 and ok2:
            self.book.add_student(Student(n, f, self.book.group))
            self.update_teacher_table()

    def add_lesson(self):
        t, ok = QInputDialog.getItem(self, "Тип занятия", "Выберите тип:", ["Лекция", "Практика"], 0, False)
        if not ok:
            return
        topic, ok2 = QInputDialog.getText(self, "Тема", "Введите тему занятия:")
        if not ok2:
            return
        lesson = self.book.add_lesson(t)
        lesson.topic = topic
        self.update_teacher_table()

    def add_exam(self):
        # создаём урок с типом "Экзамен"
        date_str, ok = QInputDialog.getText(self, "Дата экзамена", "Введите дату экзамена (дд.мм.гггг):", text=datetime.now().strftime('%d.%m.%Y'))
        if not ok:
            return
        topic, ok2 = QInputDialog.getText(self, "Тема экзамена", "Введите тему экзамена:")
        if not ok2:
            return
        lesson = self.book.add_lesson("Экзамен")
        lesson.date = date_str
        lesson.topic = topic
        self.update_teacher_table()

    def save_data(self):
        self.book.save_to_json()
        QMessageBox.information(self, "Успех", "Данные сохранены!")

    def update_teacher_table(self):
        students = self.book.spisok_stud
        lessons = self.book.lessons

        self.t_table.setRowCount(len(students))
        self.t_table.setColumnCount(3 + len(lessons))

        headers = ["№", "Фамилия", "Имя"]
        for l in lessons:
            headers.append(f"{l.type} {l.number}\n{l.date}\n{l.topic}")

        self.t_table.setHorizontalHeaderLabels(headers)

        for r, s in enumerate(students):
            self.t_table.setItem(r, 0, QTableWidgetItem(str(r + 1)))
            self.t_table.setItem(r, 1, QTableWidgetItem(s.f))
            self.t_table.setItem(r, 2, QTableWidgetItem(s.n))

            for i, l in enumerate(lessons):
                combo = QComboBox()
                if l.type == "Практика":
                    combo.addItems(["", "2", "3", "4", "5", "Н"])
                    color = QColor(200, 255, 200)
                elif l.type == "Лекция":
                    combo.addItems(["", "О", "Б", "✓", "Н"])
                    color = QColor(255, 200, 200)
                else:  # экзамен
                    combo.addItems(["", "2", "3", "4", "5", "Н"])
                    color = QColor(255, 255, 100)
                combo.setCurrentText(s.records.get(l.id, ""))
                def save_val(val, student=s, lesson=l):
                    student.records[lesson.id] = val
                combo.currentTextChanged.connect(save_val)
                self.t_table.setCellWidget(r, 3 + i, combo)

    # ================= HEADER MENU =================
    def header_context_menu(self, pos):
        col = self.t_table.horizontalHeader().logicalIndexAt(pos)
        if col < 3:
            return
        lesson = self.book.lessons[col - 3]
        menu = QMenu()
        change_date = menu.addAction("Изменить дату")
        change_topic = menu.addAction("Изменить тему")
        action = menu.exec(self.t_table.mapToGlobal(pos))
        if action == change_date:
            new_date, ok = QInputDialog.getText(self, "Дата", "Введите новую дату (дд.мм.гггг):", text=lesson.date)
            if ok:
                lesson.date = new_date
                self.update_teacher_table()
        elif action == change_topic:
            new_topic, ok = QInputDialog.getText(self, "Тема", "Введите новую тему:", text=lesson.topic)
            if ok:
                lesson.topic = new_topic
                self.update_teacher_table()

    # ================= STUDENT AI =================
    def student_ai(self):
        text, ok = QInputDialog.getText(self, "ИИ Помощник", "Задайте вопрос:")
        if not ok:
            return
        answer = self.process_ai_query(text)
        QMessageBox.information(self, "ИИ Помощник", answer)

    def process_ai_query(self, query):
        # простая обработка вопросов
        query = query.lower()
        all_books = [GradeBook(g, s) for g in GROUPS for s in SUBJECTS]
        if "средний балл" in query or "балл" in query:
            results = []
            for subj in SUBJECTS:
                b = GradeBook(self.cur_stud['g'], subj)
                s = next((x for x in b.spisok_stud if x.f == self.cur_stud['f']), None)
                if s:
                    avg = b.calculate_average(s)
                    results.append(f"{subj}: {avg:.2f}")
            return "\n".join(results) if results else "Нет данных"
        elif "оценки" in query:
            results = []
            for subj in SUBJECTS:
                b = GradeBook(self.cur_stud['g'], subj)
                s = next((x for x in b.spisok_stud if x.f == self.cur_stud['f']), None)
                if s:
                    vals = [v for v in s.records.values() if v not in ["", "Н"]]
                    results.append(f"{subj}: {len(vals)} оценок")
            return "\n".join(results) if results else "Нет данных"
        else:
            return "Извините, я пока не могу ответить на этот вопрос."
    
    # ================= LOGIN HANDLERS =================
    def login_student(self):
        if not self.sn.text() or not self.sf.text():
            return
        self.cur_stud = {"n": self.sn.text(), "f": self.sf.text(), "g": self.sg.currentText()}
        self.draw_student_dash()
        self.stack.setCurrentWidget(self.student_widget)

    def login_teacher(self):
        name = self.tn.text().strip()
        if name in self.teachers_db and self.tp.text() == self.teacher_pass:
            subj = self.teachers_db[name]
            g, ok = QInputDialog.getItem(self, "Выбор группы", f"Предмет: {subj}\nВыберите группу:", GROUPS, 0, False)
            if ok:
                self.book = GradeBook(g, subj)
                self.update_teacher_table()
                self.stack.setCurrentWidget(self.teacher_widget)
        else:
            QMessageBox.warning(self, "Ошибка", "Неверный логин или пароль!")