"""delete_impact.py — что затронет удаление: числа для окна подтверждения.

━━ ЗАЧЕМ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Живой обход стенда 13.10.2026: окна «Удалить группу К74/1?», «Удалить студента …?»
не говорили о последствиях НИЧЕГО — при том что за группой стояли девять студентов и
сотни отметок. Вопрос без цены — это не вопрос: «Удалить?» — «Да», как на любое
всплывающее окно. Страница этих чисел не знает (в списке групп нет отметок), поэтому их
считает сервер, одной ручкой на все четыре вида.

━━ ЧТО ЭТО НЕ ДЕЛАЕТ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Только СЧИТАЕТ. Ничего не удаляет, не запрещает и не решает: окно показывает числа, а
удаление идёт прежними ручками с прежними проверками.

⚠️ Удаление у нас мягкое (надгробие `deleted`): отметки и занятия физически остаются в
базе. Но кнопки «вернуть» в продукте нет, поэтому для человека удаление необратимо —
окно так и говорит, а эти числа называют, чего он перестанет видеть.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Grade, Group, Lesson, ParentLink, SubjectHours, TermGrade, User

KINDS = ("group", "subject", "student", "teacher")


def _marks_in(db: Session, lesson_filter) -> int:
    """Непустые отметки в занятиях, подходящих под условие."""
    lesson_ids = select(Lesson.id).where(Lesson.deleted == False, lesson_filter)     # noqa: E712
    return int(db.query(func.count(Grade.id)).filter(
        Grade.deleted == False, Grade.grade != "",                                    # noqa: E712
        Grade.lesson_id.in_(lesson_ids)).scalar() or 0)


def _group(db: Session, name: str) -> dict:
    students = db.query(func.count(User.id)).filter(
        User.role == "student", User.group_name == name, User.deleted == False).scalar()  # noqa: E712
    lessons = db.query(func.count(Lesson.id)).filter(
        Lesson.group_name == name, Lesson.deleted == False).scalar()                  # noqa: E712
    teachers = set()
    for t1, t2 in db.query(SubjectHours.teacher_id, SubjectHours.teacher_id_2).filter(
            SubjectHours.group_name == name, SubjectHours.deleted == False):          # noqa: E712
        teachers.update(t for t in (t1, t2) if t)
    return {"students": int(students or 0), "lessons": int(lessons or 0),
            "marks": _marks_in(db, Lesson.group_name == name), "teachers": len(teachers)}


def _subject(db: Session, name: str) -> dict:
    groups = sum(1 for (subjects,) in db.query(Group.subjects).filter(Group.deleted == False)  # noqa: E712
                 if name in (subjects or []))
    lessons = db.query(func.count(Lesson.id)).filter(
        Lesson.subject == name, Lesson.deleted == False).scalar()                     # noqa: E712
    return {"groups": groups, "lessons": int(lessons or 0),
            "marks": _marks_in(db, Lesson.subject == name)}


def _student(db: Session, login: str) -> dict:
    sid = f"stud:{login}"
    marks = db.query(func.count(Grade.id)).filter(
        Grade.student_id == sid, Grade.deleted == False, Grade.grade != "").scalar()  # noqa: E712
    finals = db.query(func.count(TermGrade.id)).filter(
        TermGrade.student_id == sid, TermGrade.deleted == False,                      # noqa: E712
        TermGrade.grade != "").scalar()
    parents = db.query(func.count(ParentLink.id)).filter(
        ParentLink.student_id == sid, ParentLink.status == "active").scalar()
    return {"marks": int(marks or 0), "finals": int(finals or 0), "parents": int(parents or 0)}


def _teacher(db: Session, login: str) -> dict:
    tid = f"teach:{login}"
    row = db.get(User, tid)
    journals = db.query(func.count(SubjectHours.id)).filter(
        SubjectHours.deleted == False,                                                # noqa: E712
        (SubjectHours.teacher_id == tid) | (SubjectHours.teacher_id_2 == tid)).scalar()
    return {"subjects": len((row.subjects if row else None) or []),
            "journals": int(journals or 0),
            "curated": len((row.curated_groups if row else None) or [])}


def impact(db: Session, kind: str, key: str) -> dict:
    """Числа для окна удаления. Неизвестный вид — ValueError (ручка ответит 400)."""
    key = (key or "").strip()
    if kind == "group":
        return _group(db, key)
    if kind == "subject":
        return _subject(db, key)
    if kind == "student":
        return _student(db, key)
    if kind == "teacher":
        return _teacher(db, key)
    raise ValueError(kind)
