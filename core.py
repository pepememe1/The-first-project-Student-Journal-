import json
import os
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import List, Dict

APP_VERSION = "Альфа 1.1"

@dataclass
class Lesson:
    id: str
    type: str
    number: int
    topic: str
    date: str

@dataclass
class Student:
    n: str
    f: str
    group: str
    records: Dict[str, str] = field(default_factory=dict)

class GradeBook:
    def __init__(self, group: str, subject: str):
        self.group = group
        self.subject = subject

        safe_group = group.replace('/', '_')
        safe_subj = subject.replace(' ', '_')
        self.db_file = f"data_{safe_group}_{safe_subj}.json"
        
        self.lessons: List[Lesson] = []
        self.spisok_stud: List[Student] = []
        self.load_from_json()

    def add_student(self, st: Student):
        self.spisok_stud.append(st)

    def add_lesson(self, lesson_type: str) -> Lesson:
        nums = [l.number for l in self.lessons if l.type == lesson_type]
        next_num = max(nums) + 1 if nums else 1
        l = Lesson(str(uuid.uuid4()), lesson_type, next_num, "", datetime.now().strftime('%d.%m.%Y'))
        self.lessons.append(l)
        return l

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

    def save_to_json(self):
        with open(self.db_file, "w", encoding="utf-8") as f:
            json.dump({
                "lessons": [asdict(l) for l in self.lessons],
                "students": [asdict(s) for s in self.spisok_stud]
            }, f, ensure_ascii=False, indent=4)

    def load_from_json(self):
        if not os.path.exists(self.db_file):
            return
        try:
            with open(self.db_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.lessons = [Lesson(**l) for l in data.get("lessons", [])]
            self.spisok_stud = [Student(**s) for s in data.get("students", [])]
        except Exception as e:
            print(f"Ошибка загрузки данных: {e}")