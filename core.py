import sqlite3
import os
import uuid
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

APP_VERSION = "Pre-release 1.5"

@dataclass
class Lesson:
    id: str
    type: str        # "Лекция" | "Практика" | "Экзамен"
    number: int
    topic: str
    date: str
    # Для экзаменов: дата пересдачи (пустая если нет)
    retake_date: str = ""
    # Для лекций: час (1 или 2, иначе 0)
    hour: int = 0

@dataclass
class Student:
    n: str
    f: str
    group: str
    records: Dict[str, str] = field(default_factory=dict)
    # records хранит: lesson_id -> оценка/зачет
    # Для пересдачи: lesson_id + "_retake" -> оценка/зачет на пересдаче


class GradeBook:
    def __init__(self, group: str, subject: str):
        self.group   = group
        self.subject = subject
        self.db_name = "vsgutu_grades.db"
        self.lessons: List[Lesson] = []
        self.spisok_stud: List[Student] = []
        self.init_db()
        self.load_from_sqlite()

    def init_db(self):
        conn = sqlite3.connect(self.db_name)
        cur  = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS lessons
            (id TEXT PRIMARY KEY, group_name TEXT, subject TEXT,
             type TEXT, number INTEGER, topic TEXT, date TEXT,
             retake_date TEXT DEFAULT "", hour INTEGER DEFAULT 0)''')
        # Миграция: добавить колонки если старая БД
        for col, default in [("retake_date", "TEXT DEFAULT ''"), ("hour", "INTEGER DEFAULT 0")]:
            try:
                cur.execute(f"ALTER TABLE lessons ADD COLUMN {col} {default}")
            except Exception:
                pass
        cur.execute('''CREATE TABLE IF NOT EXISTS students
            (f TEXT, n TEXT, group_name TEXT, PRIMARY KEY(f, n, group_name))''')
        cur.execute('''CREATE TABLE IF NOT EXISTS grades
            (student_f TEXT, student_n TEXT, lesson_id TEXT, grade TEXT,
             FOREIGN KEY(lesson_id) REFERENCES lessons(id))''')
        conn.commit()
        conn.close()

    # ── CRUD студентов ──────────────────────────────────────────
    def add_student(self, st: Student):
        self.spisok_stud.append(st)
        self.save_to_sqlite()

    def delete_student(self, surname: str, name: str):
        surname = surname.strip()
        name    = name.strip()
        self.spisok_stud = [
            s for s in self.spisok_stud
            if not (s.f.strip().lower() == surname.lower()
                    and s.n.strip().lower() == name.lower())
        ]
        conn = sqlite3.connect(self.db_name)
        cur  = conn.cursor()
        cur.execute("DELETE FROM grades WHERE student_f=? AND student_n=?", (surname, name))
        cur.execute("DELETE FROM students WHERE f=? AND n=?", (surname, name))
        conn.commit()
        conn.close()

    # ── CRUD занятий ────────────────────────────────────────────
    def add_lesson(self, lesson_type: str, topic: str = "", date: str = "", hour: int = 0) -> "Lesson":
        """
        Добавляет занятие. Для Лекции создаёт СРАЗУ ДВА занятия (1-й и 2-й час).
        Возвращает первое (или единственное) занятие.
        """
        nums     = [l.number for l in self.lessons if l.type == lesson_type and getattr(l,'hour',0) in (0,1)]
        next_num = max(nums) + 1 if nums else 1
        dt = date or datetime.now().strftime('%d.%m.%Y')

        if lesson_type == "Лекция" and hour == 0:
            # Создаём 1-й и 2-й час одновременно
            l1 = Lesson(id=str(uuid.uuid4()), type="Лекция", number=next_num,
                        topic=topic, date=dt, retake_date="", hour=1)
            l2 = Lesson(id=str(uuid.uuid4()), type="Лекция", number=next_num,
                        topic=topic, date=dt, retake_date="", hour=2)
            self.lessons.extend([l1, l2])
            self.save_to_sqlite()
            return l1
        else:
            l = Lesson(id=str(uuid.uuid4()), type=lesson_type, number=next_num,
                       topic=topic, date=dt, retake_date="", hour=hour)
            self.lessons.append(l)
            self.save_to_sqlite()
            return l

    def set_retake_date(self, lesson_id: str, retake_date: str):
        """Устанавливает дату пересдачи для экзамена."""
        for l in self.lessons:
            if l.id == lesson_id:
                l.retake_date = retake_date
                break
        conn = sqlite3.connect(self.db_name)
        cur  = conn.cursor()
        cur.execute("UPDATE lessons SET retake_date=? WHERE id=?", (retake_date, lesson_id))
        conn.commit()
        conn.close()

    # ── Сохранение / загрузка ───────────────────────────────────
    def save_to_sqlite(self):
        conn = sqlite3.connect(self.db_name)
        cur  = conn.cursor()
        for l in self.lessons:
            cur.execute(
                "INSERT OR REPLACE INTO lessons VALUES (?,?,?,?,?,?,?,?,?)",
                (l.id, self.group, self.subject, l.type,
                 l.number, l.topic, l.date, l.retake_date, getattr(l, 'hour', 0))
            )
        for s in self.spisok_stud:
            cur.execute(
                "INSERT OR IGNORE INTO students VALUES (?,?,?)",
                (s.f, s.n, s.group)
            )
            for lesson_id, grade in s.records.items():
                cur.execute(
                    "INSERT OR REPLACE INTO grades VALUES (?,?,?,?)",
                    (s.f, s.n, lesson_id, grade)
                )
        conn.commit()
        conn.close()

    def load_from_sqlite(self):
        conn = sqlite3.connect(self.db_name)
        cur  = conn.cursor()
        cur.execute(
            "SELECT id, type, number, topic, date, retake_date, hour "
            "FROM lessons WHERE group_name=? AND subject=? ORDER BY rowid",
            (self.group, self.subject)
        )
        self.lessons = []
        for row in cur.fetchall():
            self.lessons.append(Lesson(
                id=row[0], type=row[1], number=row[2],
                topic=row[3], date=row[4],
                retake_date=row[5] if len(row) > 5 else "",
                hour=row[6] if len(row) > 6 and row[6] else 0
            ))

        # ── Синхронизация из secure_store ──────────────────────
        # Студенты добавленные через панель администратора хранятся
        # в secure_store. Добавляем их в SQLite если ещё не там.
        try:
            from security import secure_store
            store_students = secure_store.get_students()
            for s in store_students:
                if s.get("group", "") == self.group:
                    f = s.get("surname", "").strip()
                    n = s.get("name", "").strip()
                    if f and n:
                        cur.execute(
                            "INSERT OR IGNORE INTO students VALUES (?,?,?)",
                            (f, n, self.group)
                        )
            conn.commit()
        except Exception:
            pass  # secure_store недоступен — работаем только с SQLite

        cur.execute(
            "SELECT f, n, group_name FROM students WHERE group_name=?",
            (self.group,)
        )
        self.spisok_stud = []
        for f, n, g in cur.fetchall():
            student = Student(n, f, g)
            cur.execute(
                "SELECT lesson_id, grade FROM grades WHERE student_f=? AND student_n=?",
                (f, n)
            )
            student.records = {row[0]: row[1] for row in cur.fetchall()}
            self.spisok_stud.append(student)
        conn.close()

    # ── Вспомогательное ────────────────────────────────────────
    def calculate_average(self, student: Student) -> float:
        total, count = 0.0, 0
        for l in self.lessons:
            if l.type == "Практика":
                val = student.records.get(l.id)
                if val in ["2", "3", "4", "5"]:
                    total += float(val)
                    count += 1
                elif val == "Н":
                    total += 2.0
                    count += 1
        return total / count if count > 0 else 0.0

    def export_to_excel(self, file_path: str):
        wb = Workbook()
        ws = wb.active
        title     = f"Успеваемость {self.group}"
        safe_title = re.sub(r'[\[\]:*?/\\]', '_', title)
        ws.title  = safe_title[:31]

        headers = ["Фамилия", "Имя"]
        for l in self.lessons:
            if l.type == "Экзамен":
                headers.append(f"Экзамен №{l.number}\n({l.date})\n{l.topic}")
                if l.retake_date:
                    headers.append(f"Пересдача\n({l.retake_date})")
            else:
                headers.append(f"{l.type} №{l.number}\n({l.date})")
        headers.append("Средний балл")
        ws.append(headers)

        for cell in ws[1]:
            cell.font      = Font(bold=True, color="FFFFFF")
            cell.fill      = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", wrap_text=True)

        for s in self.spisok_stud:
            row = [s.f, s.n]
            for l in self.lessons:
                row.append(s.records.get(l.id, ""))
                if l.type == "Экзамен" and l.retake_date:
                    row.append(s.records.get(l.id + "_retake", ""))
            row.append(round(self.calculate_average(s), 2))
            ws.append(row)
        wb.save(file_path)
