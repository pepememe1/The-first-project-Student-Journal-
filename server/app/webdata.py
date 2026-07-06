"""
webdata.py — Общие выборки для веб-представлений (/web/*).

Читают серверную БД (SQLAlchemy) и формируют данные СТРОГО по роли: только то, что
пользователь вправе видеть, уже удобно для UI. В отличие от /sync/pull (отдаёт все
строки всех таблиц, включая хеши паролей) — эти выборки безопасно отдавать в браузер.

Расчёт среднего балла — через ЕДИНЫЙ модуль grading.py из корня репозитория
(инвариант §9: формулу НЕ дублируем). grading.py лёгкий (зависит только от typing),
поэтому импортируется на сервере без тяжёлых GUI-зависимостей.
"""
import os
import sys

#grading.py лежит в корне репозитория рядом с server/. Разворачивание идёт из того
#же репо (см. server/DEPLOY.md: git clone <repo> && cd server), поэтому корень
#доступен. Добавляем его в sys.path и переиспользуем единый расчёт.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import grading  # noqa: E402

from .models import User, Lesson, Grade, ConfigKV  # noqa: E402


def load_config(db) -> dict:
    """Методика оценок (веса Н, учитывать ли пропуск/экзамены) из таблицы config.

    Терпимо к раскладке: строка со словарём вливается целиком, строка «ключ→значение»
    кладётся как есть. Отсутствующие ключи grading.avg_config добьёт дефолтами."""
    cfg = {}
    for row in db.query(ConfigKV).filter(ConfigKV.deleted == False):  # noqa: E712
        v = row.value
        if isinstance(v, dict):
            cfg.update(v)
        elif row.key:
            cfg[row.key] = v
    return cfg


def student_records(db, surname: str, name: str) -> dict:
    """{lesson_id → оценка} для студента. Ключи пересдач (`<lid>_retake[_N]`) тоже
    приходят как отдельные строки grades — grading их учитывает по последней попытке."""
    rows = db.query(Grade.lesson_id, Grade.grade).filter(
        Grade.student_f == surname, Grade.student_n == name,
        Grade.deleted == False).all()  # noqa: E712
    return {lid: g for lid, g in rows}


def group_lessons(db, group: str, subject: str | None = None):
    """Занятия группы (опц. по предмету), в том же порядке, что и в десктопе."""
    q = db.query(Lesson).filter(Lesson.group_name == group,
                                Lesson.deleted == False)  # noqa: E712
    if subject:
        q = q.filter(Lesson.subject == subject)
    return q.order_by(Lesson.subject, Lesson.type, Lesson.number, Lesson.hour).all()


def lesson_pairs(lessons):
    return [(l.id, l.type) for l in lessons]


def average(lessons, records, cfg) -> float:
    """Средний балл — единый расчёт grading.practice_average."""
    return grading.practice_average(lesson_pairs(lessons), records, cfg)


def per_subject_averages(lessons, records, cfg):
    """Список {subject, average, lessons} — средний по каждому предмету группы."""
    from collections import OrderedDict
    buckets = OrderedDict()
    for l in lessons:
        buckets.setdefault(l.subject, []).append(l)
    out = []
    for subj, ls in buckets.items():
        out.append({"subject": subj, "average": average(ls, records, cfg),
                    "lessons": len(ls)})
    return out


def debts(lessons, records):
    """Причины задолженности (порт vector/intents._is_debt)."""
    reasons = []
    for l in lessons:
        if l.type == "Практика":
            v = records.get(l.id)
            if v in ("2", "Н"):
                reasons.append(f"практика №{l.number} не сдана ({v})")
        elif l.type == "Экзамен":
            v = grading.latest_exam_value(l.id, records)
            if v and ("Не зачтено" in v or v.strip().startswith(("2", "Н"))):
                reasons.append(f"экзамен №{l.number} не зачтён")
    return reasons


def absences(lessons, records):
    """Пропуски (порт vector/intents._count_absences). Строка лекции = 1 час."""
    res = {"Н": 0, "Б": 0, "О": 0}
    for l in lessons:
        v = records.get(l.id)
        if l.type == "Лекция" and v in ("Н", "Б", "О"):
            res[v] += 1
        elif l.type == "Практика" and v == "Н":
            res["Н"] += 1
    res["всего"] = res["Н"] + res["Б"] + res["О"]
    return res


def students_in_group(db, group: str):
    """Студенты группы — это пользователи с ролью student и этой group_name."""
    return db.query(User).filter(
        User.role == "student", User.group_name == group,
        User.deleted == False).order_by(User.surname, User.name).all()  # noqa: E712


def teacher_groups(db, subjects) -> list:
    """Группы, доступные преподавателю по его предметам. ДВА источника (объединение):
      1) группы, где уже есть его занятия (журнал наполнен);
      2) группы, у которых его предмет числится в списке предметов ГРУППЫ (после
         «Обновить группы» предметы привязаны к группам). Без п.2 НОВЫЙ преподаватель
         (у него ещё нет ни одного занятия) видел пустой журнал — не мог выбрать группу
         и создать первое занятие."""
    from .models import Group
    subjects = set(s for s in (subjects or []) if s)
    if not subjects:
        return []
    result = set()
    for r in db.query(Lesson.group_name).filter(
            Lesson.subject.in_(subjects), Lesson.deleted == False).distinct().all():  # noqa: E712
        if r[0]:
            result.add(r[0])
    for g in db.query(Group).filter(Group.deleted == False).all():  # noqa: E712
        if subjects & set(g.subjects or []):
            result.add(g.name)
    return sorted(result)


def display_name(user) -> str:
    return user.full_name or f"{user.surname} {user.name}".strip()
