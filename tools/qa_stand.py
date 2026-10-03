# -*- coding: utf-8 -*-
"""qa_stand.py — стенд для ЖИВОГО тестирования: сервер из артефакта + выдуманный колледж.

━━ ЗАЧЕМ, ЕСЛИ ЕСТЬ smoke_release.py ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Смоук отвечает на вопрос «поднялось ли»: ему хватает одного администратора. Живому
тестированию (грани gb-qa-web / gb-qa-desktop, человек перед выпуском) нужны ВСЕ роли и
данные, на которых видны ошибки: должники, «зона риска», тёзки в разных группах, куратор,
родитель с подтверждённой привязкой, заявка на регистрацию. На пустой базе половина экранов
показывает «данных нет», и дефект «пусто при наличии данных» не отличить от честной пустоты.

Сервер берётся из ТОГО ЖЕ неизменяемого архива, что едет на бой (`tools/build_release.py`,
разворачивает `smoke_release.Stand`), а не из рабочего дерева: правки, которые идут в
дереве во время проверки, не должны менять проверяемый продукт посреди прогона.

🔒 ДАННЫЕ ТОЛЬКО ВЫДУМАННЫЕ, и это запрет, а не удобство (п. 5.2.4.1 политики ВСГУТУ:
копия боевой базы на машине разработчика — ПДн студентов на чужом оборудовании). Взять
живую базу этот скрипт не умеет по построению: база стенда создаётся с нуля в его папке.
Пароли ниже — выдуманные, действуют только на стенде; стенд слушает ТОЛЬКО 127.0.0.1.

Запуск (держит стенд, пока процесс не прервут):
    python -X utf8 tools/qa_stand.py                    # порт 8765, папка %TEMP%/gb-qa/stand
    python -X utf8 tools/qa_stand.py --port 8766 --dir <папка>
    python -X utf8 tools/qa_stand.py --artifact dist-release/<файл>.tar.gz
Учётки печатаются при старте и лежат в <папка>/STAND.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (логин, пароль, роль, фамилия, «Имя Отчество», отчество, группа)
ACCOUNTS = [
    ("qa_admin", "QaStand-Admin-2026", "admin", "Стендов", "Админ Админович", "Админович", ""),
    ("qa_moder", "QaStand-Moder-2026", "moderator", "Модеров", "Матвей Олегович", "Олегович", ""),
    ("qa_teacher", "QaStand-Teacher-2026", "teacher", "Семёнова", "Анна Петровна", "Петровна", ""),
    ("qa_teacher2", "QaStand-Teacher2-2026", "teacher", "Орлов", "Игорь Васильевич", "Васильевич", ""),
    ("qa_student", "QaStand-Student-2026", "student", "Дашиева", "Арюна Баировна", "Баировна", "К74/1"),
    ("qa_student2", "QaStand-Student2-2026", "student", "Петров", "Пётр Андреевич", "Андреевич", "К74/1"),
    ("qa_parent", "QaStand-Parent-2026", "parent", "Петрова", "Ольга Николаевна", "Николаевна", ""),
]

GROUPS = {"К74/1": 2025, "К74/2": 2025, "К64/2": 2024}
RPM, DB_, MATH, PE, ENG = ("Разработка программных модулей", "Базы данных", "Математика",
                           "Физическая культура", "Английский язык")
GROUP_SUBJECTS = {
    "К74/1": [RPM, DB_, MATH, PE, ENG],
    "К74/2": [RPM, DB_, MATH, PE, ENG],
    "К64/2": [MATH, PE, ENG, DB_],
}
# Кто ведёт: предмет → (id преподавателя, в каких группах). Остальные пары — у
# преподавателей без входа: им журнал на стенде не нужен, нужны их имена в справочниках.
TEACHERS_NO_LOGIN = [
    ("teach:budaeva", "Будаева", "Туяна Баировна", "Баировна", [PE]),
    ("teach:tsyrenov", "Цыренов", "Баир Дугарович", "Дугарович", [ENG]),
]

# Студенты без входа: (фамилия, «Имя Отчество», отчество, профиль оценок).
# Профили: ex — отличник, good, avg, debt — долги, risk — средний < 2.5, new — ни одной оценки.
# 🔥 Иванов Иван Сергеевич есть и в К74/1, и в К64/2 — полные тёзки в РАЗНЫХ группах
# (дефект W-04: оценки одного уезжали другому). На стенде это обязано быть видно.
STUDENTS = {
    "К74/1": [("Иванов", "Иван Сергеевич", "Сергеевич", "good"),
              ("Бадмаев", "Бато Цыренович", "Цыренович", "avg"),
              ("Смирнова", "Мария Алексеевна", "Алексеевна", "ex"),
              ("Кузнецов", "Никита Олегович", "Олегович", "risk"),
              ("Намсараева", "Сэсэг Жаргаловна", "Жаргаловна", "good"),
              ("Волков", "Артём Денисович", "Денисович", "debt"),
              ("Цыбикова", "Дарима Батоевна", "Батоевна", "new")],
    "К74/2": [("Соколова", "Анастасия Игоревна", "Игоревна", "ex"),
              ("Доржиев", "Аюр Баирович", "Баирович", "avg"),
              ("Морозов", "Даниил Павлович", "Павлович", "debt"),
              ("Лебедева", "Полина Сергеевна", "Сергеевна", "good"),
              ("Гармаев", "Солбон Андреевич", "Андреевич", "risk"),
              ("Новиков", "Егор Максимович", "Максимович", "avg")],
    "К64/2": [("Иванов", "Иван Сергеевич", "Сергеевич", "avg"),
              ("Федорова", "Ксения Романовна", "Романовна", "ex"),
              ("Балданов", "Жаргал Баторович", "Баторович", "debt"),
              ("Егорова", "Валерия Викторовна", "Викторовна", "good"),
              ("Шагдаров", "Тимур Эрдэмович", "Эрдэмович", "risk")],
}
PROFILES = {                       # пять практик + ДЗ, затем три лекции (посещаемость)
    "ex":   (["5", "5", "4", "5", "5"], "5", ["", "", ""]),
    "good": (["4", "5", "4", "4", "3"], "4", ["", "О", ""]),
    "avg":  (["3", "4", "3", "3", "4"], "3", ["Н", "", ""]),
    "debt": (["3", "2", "Н", "3", "4"], "Н", ["Н", "Н", ""]),
    "risk": (["2", "2", "Н", "3", "2"], "2", ["Н", "Н", "Б"]),
    "new":  (["", "", "", "", ""], "", ["", "", ""]),
}


def _parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="стенд живого тестирования на выдуманных данных")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--dir", default=os.path.join(tempfile.gettempdir(), "gb-qa", "stand"))
    ap.add_argument("--artifact", default="")
    ap.add_argument("--big", action="store_true",
                    help="добавить большой колледж: ~20 групп, ~500 студентов, все роли, "
                         "прошлый семестр, переписка (см. seed_big)")
    ap.add_argument("--seed-only", action="store_true", help=argparse.SUPPRESS)
    return ap.parse_args()


# ━━ БОЛЬШОЙ КОЛЛЕДЖ (--big) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Маленький стенд ловит дефекты ЛОГИКИ (тёзки, должники, родитель). Большой нужен для
# того, чего на двадцати студентах не видно вовсе: медленные списки и поиск, обрезки
# длинных таблиц, прокрутка журнала на тридцать строк, каталог мессенджера на сотни
# людей, разные шкалы оценок у разных преподавателей, архив прошлого семестра.
# ⚠️ Пароль у ВСЕХ сгенерированных учёток ОДИН, а хеш считается ОДИН раз и копируется:
# гибридный ГОСТ-хеш стоит ~0.5 с, и честный хеш на каждого из семисот человек
# превратил бы запуск стенда в десятиминутное ожидание. Для выдуманного стенда это
# допустимо — на бою так делать нельзя ни при каких обстоятельствах.
BIG_PASSWORD = "QaStand-Big-2026"

_M_SURNAMES = ["Смирнов", "Кузнецов", "Попов", "Васильев", "Соколов", "Михайлов", "Фёдоров",
               "Алексеев", "Лебедев", "Егоров", "Павлов", "Козлов", "Степанов", "Николаев",
               "Андреев", "Макаров", "Никитин", "Захаров", "Зайцев", "Соловьёв", "Борисов",
               "Яковлев", "Григорьев", "Романов", "Воробьёв", "Сергеев", "Кузьмин", "Фролов",
               "Дмитриев", "Королёв", "Гусев", "Киселёв", "Бадмаев", "Доржиев", "Гармаев",
               "Балданов", "Шагдаров", "Батуев", "Жамсуев", "Аюшеев", "Дамдинов", "Санжиев",
               "Цыдыпов", "Намжилов", "Раднаев", "Хандаков", "Баиров", "Очиров", "Тумуров",
               "Дашиев", "Пушкин", "Ильин", "Сорокин", "Голубев", "Виноградов", "Богданов"]
_M_NAMES = ["Александр", "Дмитрий", "Максим", "Сергей", "Андрей", "Алексей", "Артём", "Илья",
            "Кирилл", "Михаил", "Никита", "Матвей", "Роман", "Егор", "Арсений", "Денис",
            "Евгений", "Даниил", "Тимур", "Бато", "Баир", "Аюр", "Солбон", "Жаргал", "Тумэн",
            "Эрдэм", "Булат", "Чингис", "Батор", "Владимир"]
_F_NAMES = ["Анастасия", "Мария", "Анна", "Виктория", "Екатерина", "Наталья", "Марина",
            "Полина", "Дарья", "Алина", "Ксения", "Валерия", "Елизавета", "Софья", "Арина",
            "Арюна", "Сэсэг", "Дарима", "Туяна", "Оюна", "Саяна", "Билигма", "Баярма",
            "Цыпелма", "Ольга"]
# Отчество: основа + мужское/женское окончание.
_PATRONYMICS = [("Александров", "ич"), ("Сергеев", "ич"), ("Андреев", "ич"), ("Николаев", "ич"),
                ("Владимиров", "ич"), ("Олегов", "ич"), ("Игорев", "ич"), ("Викторов", "ич"),
                ("Павлов", "ич"), ("Баиров", "ич"), ("Цыренов", "ич"), ("Батоев", "ич"),
                ("Дугаров", "ич"), ("Жаргалов", "ич"), ("Эрдэмов", "ич"), ("Баторов", "ич"),
                ("Дмитриев", "ич"), ("Максимов", "ич"), ("Романов", "ич"), ("Юрьев", "ич")]

# Группы большого колледжа: имя → год поступления (курс считается от него).
BIG_GROUPS = {"К76/1": 2026, "К76/2": 2026, "К66/1": 2026, "К56/1": 2026,
              "К75/1": 2025, "К75/2": 2025, "К65/1": 2025, "К55/1": 2025,
              "К73/1": 2024, "К73/2": 2024, "К63/1": 2024, "К53/1": 2024,
              "К72/1": 2023, "К72/2": 2023, "К62/1": 2023, "К52/1": 2023,
              "К71/1": 2023, "К61/1": 2024, "К51/1": 2025, "К77/1": 2026}
BIG_SUBJECTS = [RPM, DB_, MATH, PE, ENG, "Операционные системы", "Компьютерные сети",
                "История России", "Русский язык", "Физика", "Информатика",
                "Экономика организации", "Web-программирование", "Тестирование ПО"]
# Учебный план занятий текущего семестра: 4 лекции, 7 практик, ДЗ — в порядке семестра.
_BIG_PLAN = [("Лекция", 1), ("Практика", 1), ("Практика", 2), ("Лекция", 2), ("Практика", 3),
             ("ДЗ", 1), ("Практика", 4), ("Лекция", 3), ("Практика", 5), ("Практика", 6),
             ("Лекция", 4), ("Практика", 7)]
# Профили успеваемости: доля в группе и «средняя» оценка, вокруг которой бросаем кости.
_BIG_PROFILES = [("ex", 0.15, 4.8), ("good", 0.30, 4.1), ("avg", 0.30, 3.4),
                 ("debt", 0.12, 2.9), ("risk", 0.08, 2.3), ("new", 0.05, 0.0)]


def _female(surname: str) -> str:
    return surname + "а" if surname.endswith(("ов", "ев", "ёв", "ин")) else surname


def _scaled(five: int, scale: str, rnd) -> str:
    """5-балльная оценка → значение в шкале преподавателя (как он её ставил бы сам).
    100-балльную нарочно ставим «живыми» числами (73, 88), а не ровными ×20: иначе
    перевод шкалы обратно в 5-балльную на стенде никогда не дал бы спорных случаев."""
    if scale == "100":
        return str(max(0, min(100, five * 20 - rnd.randint(0, 12))))
    if scale == "letter":
        return {5: "A", 4: "B", 3: "C"}.get(five, rnd.choice(["D", "F"]))
    if scale == "pass_fail":
        return "Зачтено" if five >= 3 else "Не зачтено"
    return str(five)


def seed_big() -> dict:
    """Добавляет к выдуманному колледжу большой: ~20 групп по 25 студентов, ~30
    преподавателей (у троих — другие шкалы оценок), кураторов, ~160 родителей (часть
    привязок ждёт согласия, часть отозвана), модераторов, второго админа, прошлый семестр
    с итоговыми оценками, раздельное обучение у одной группы и переписку в мессенджере.
    Всё детерминировано (одно зерно случайности) — находку можно воспроизвести на новом
    запуске стенда."""
    import random
    from datetime import datetime, timedelta, timezone
    from app.course_rollover import term_label
    from app.db import SessionLocal, default_term
    from app.models import (Conversation, ConversationParticipant, Group, Lesson, Grade,
                            Message, ParentLink, RegistrationRequest, StudentSubgroup, Subject,
                            SubjectHours, TermGrade, User, direct_conversation_id, grade_id,
                            parent_link_id, set_user_password, student_subgroup_id,
                            subject_hours_id, term_grade_id)

    rnd = random.Random(2026)
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    year, semester = default_term()
    y0 = int(year.split("/")[0])
    # Прошлый семестр — архив: второй семестр прошлого учебного года (или первый этого).
    prev_year, prev_sem = (f"{y0 - 1}/{y0}", 2) if semester == 1 else (year, 1)
    # Календарь дат занятий: (месяц, год) для текущего и прошлого семестров.
    cur_cal = (9, y0) if semester == 1 else (2, y0 + 1)
    prev_cal = (3, y0) if semester == 1 else (10, y0)
    db = SessionLocal()
    stats = {"groups": 0, "students": 0, "teachers": 0, "parents": 0, "lessons": 0,
             "grades": 0, "term_grades": 0, "messages": 0}
    try:
        template = User(id="tmp", role="student")
        set_user_password(template, BIG_PASSWORD)
        pwd_hash, pwd_at = template.password_hash, template.password_set_at
        used_names: set = set()

        def person(female: bool):
            for _ in range(50):
                sur = rnd.choice(_M_SURNAMES)
                first = rnd.choice(_F_NAMES if female else _M_NAMES)
                base, _end = rnd.choice(_PATRONYMICS)
                patr = base + ("на" if female else "ич")
                sur = _female(sur) if female else sur
                if (sur, first, patr) not in used_names:
                    used_names.add((sur, first, patr))
                    return sur, f"{first} {patr}", patr
            return sur, f"{first} {patr}", patr

        objs: list = []

        def user(uid, role, login, sur, name, patr, group="", **extra):
            row = User(id=uid, role=role, login=login, surname=sur, name=name,
                       patronymic=patr, full_name=f"{sur} {name}", group_name=group,
                       password_hash=pwd_hash if login else "",
                       password_set_at=pwd_at if login else "", updated_at=now, **extra)
            objs.append(row)
            return row

        existing_subjects = {s for subs in GROUP_SUBJECTS.values() for s in subs}
        for name in BIG_SUBJECTS:
            if name not in existing_subjects:
                objs.append(Subject(id=f"subj:{name}", name=name, updated_at=now))

        # Предметы группы: общий набор по курсу плюс сдвиг по номеру — у соседних групп
        # наборы пересекаются, но не совпадают (как в жизни).
        group_subjects = {}
        for gi, (g, enrolled) in enumerate(BIG_GROUPS.items()):
            start = (gi * 3) % len(BIG_SUBJECTS)
            subs = [BIG_SUBJECTS[(start + k) % len(BIG_SUBJECTS)] for k in range(7)]
            group_subjects[g] = subs
            # Метка «группу уже перевели на этот курс»: без неё сервер на старте сам
            # «переведёт» каждую группу с прошлым семестром (course_rollover.autorun) и
            # открепит всех назначенных преподавателей — на стенде журналы стали бы пустыми.
            objs.append(Group(id=f"grp:{g}", name=g, subjects=subs, enrollment_year=enrolled,
                              category="college", assignments_reset_term=term_label(year, semester),
                              updated_at=now))
        stats["groups"] = len(BIG_GROUPS)

        # Преподаватели с входом: по два на каждый предмет. Трое — с другими шкалами:
        # 100-балльная, буквенная и зачёт/незачёт.
        teachers = []
        by_subject: dict = {s: [] for s in BIG_SUBJECTS}
        special_scale = {3: "100", 5: "letter", 7: "pass_fail", 11: "100"}
        for ti in range(1, 29):
            female = ti % 2 == 0
            sur, name, patr = person(female)
            subs = [BIG_SUBJECTS[(ti * 2) % len(BIG_SUBJECTS)],
                    BIG_SUBJECTS[(ti * 2 + 1) % len(BIG_SUBJECTS)]]
            prefs = {"grading_scale": special_scale[ti]} if ti in special_scale else {}
            t = user(f"teach:qa_t{ti:02d}", "teacher", f"qa_t{ti:02d}", sur, name, patr,
                     subjects=subs, curated_groups=[], prefs=prefs)
            teachers.append(t)
            for s in subs:
                by_subject[s].append(t)
        stats["teachers"] = len(teachers)

        # Кураторы: первые 16 преподавателей курируют по группе.
        groups_list = list(BIG_GROUPS)
        curator_of = {}
        for ti, g in enumerate(groups_list[:16]):
            teachers[ti].curated_groups = [g]
            curator_of[g] = teachers[ti]

        # Студенты: 25 на группу, профиль успеваемости по долям.
        roster: dict = {g: [] for g in BIG_GROUPS}
        n = 0
        for g in BIG_GROUPS:
            for _ in range(25):
                n += 1
                female = rnd.random() < 0.5
                sur, name, patr = person(female)
                r, acc = rnd.random(), 0.0
                profile = _BIG_PROFILES[-1][0]
                for pname, share, _mean in _BIG_PROFILES:
                    acc += share
                    if r <= acc:
                        profile = pname
                        break
                st = user(f"stud:qa_s{n:04d}", "student", f"qa_s{n:04d}", sur, name, patr, g)
                roster[g].append((st, profile))
        stats["students"] = n

        mean_of = {p: m for p, _s, m in _BIG_PROFILES}

        def five_for(profile: str) -> int:
            m = mean_of[profile]
            return max(2, min(5, round(rnd.gauss(m, 0.7))))

        def add_lessons(g, s, gi, si, teacher, yr, sem, plan, prefix, cal, sub=0, studs=None):
            gcode = f"{gi:02d}"
            month, cal_year = cal
            for k, (ltype, num) in enumerate(plan):
                tcode = {"Практика": "pr", "ДЗ": "hw", "Лекция": "lec", "Экзамен": "ex"}[ltype]
                lid = f"{prefix}-{gcode}-{si:02d}-{tcode}{num}" + (f"-sg{sub}" if sub else "")
                topic = ("Выполнить лабораторную работу, оформить отчёт" if ltype == "ДЗ"
                         else f"{ltype} №{num}: тема по предмету «{s}»")
                day = min(28, 2 + k * 2 + si % 2)
                objs.append(Lesson(id=lid, group_name=g, subject=s, type=ltype, number=num,
                                   topic=topic, date=f"{day:02d}.{month:02d}.{cal_year}",
                                   year=yr, semester=sem, subgroup=sub, updated_at=now))
                stats["lessons"] += 1
                scale = (teacher.prefs or {}).get("grading_scale", "5") if teacher else "5"
                for stud, profile in (studs if studs is not None else roster[g]):
                    if profile == "new":
                        if yr == year:
                            continue          # «новенький»: в этом семестре оценок ещё нет
                        profile = "avg"
                    if ltype in ("Практика", "ДЗ"):
                        if rnd.random() < 0.06:
                            value = "Н"
                        elif rnd.random() < 0.08:
                            continue                      # ещё не поставлена
                        else:
                            value = _scaled(five_for(profile), scale, rnd)
                    elif ltype == "Экзамен":
                        value = str(max(2, five_for(profile)))
                    else:                                  # лекция — только посещаемость
                        p_abs = {"risk": 0.35, "debt": 0.2}.get(profile, 0.05)
                        if rnd.random() < p_abs:
                            value = rnd.choice(["Н", "Н", "Б", "О"])
                        else:
                            continue
                    objs.append(Grade(id=grade_id(stud.id, lid), student_id=stud.id,
                                      student_f=stud.surname, student_n=stud.name,
                                      lesson_id=lid, grade=value, updated_at=now))
                    stats["grades"] += 1

        for gi, g in enumerate(groups_list):
            enrolled = BIG_GROUPS[g]
            for si, s in enumerate(group_subjects[g]):
                pool = by_subject[s] or teachers
                teacher = pool[gi % len(pool)]
                split = (g == "К75/1" and s == group_subjects[g][0])
                second = pool[(gi + 1) % len(pool)] if split and len(pool) > 1 else None
                objs.append(SubjectHours(id=subject_hours_id(g, s, year, semester),
                                         group_name=g, subject=s, year=year,
                                         semester=semester, hours_total=72,
                                         teacher_id=teacher.id, split=split,
                                         teacher_id_2=second.id if second else "",
                                         updated_at=now))
                if split:
                    # Раздельное обучение: половина группы в подгруппе 1, половина — во 2.
                    halves = {1: roster[g][::2], 2: roster[g][1::2]}
                    for sub, studs in halves.items():
                        for stud, _p in studs:
                            objs.append(StudentSubgroup(
                                id=student_subgroup_id(g, s, year, semester, stud.id),
                                group_name=g, subject=s, year=year, semester=semester,
                                student_id=stud.id, subgroup=sub, updated_at=now))
                        add_lessons(g, s, gi, si, teacher if sub == 1 else (second or teacher),
                                    year, semester, _BIG_PLAN, "qb", cur_cal, sub=sub, studs=studs)
                else:
                    add_lessons(g, s, gi, si, teacher, year, semester, _BIG_PLAN, "qb", cur_cal)

                # Прошлый семестр — только у тех, кто уже учился: короткий план + экзамен
                # и итоговые оценки за семестр (архив, ведомости).
                if enrolled < y0:
                    objs.append(SubjectHours(id=subject_hours_id(g, s, prev_year, prev_sem),
                                             group_name=g, subject=s, year=prev_year,
                                             semester=prev_sem, hours_total=64,
                                             teacher_id=teacher.id, updated_at=now))
                    prev_plan = [("Лекция", 1), ("Практика", 1), ("Практика", 2),
                                 ("Практика", 3), ("Экзамен", 1)]
                    add_lessons(g, s, gi, si, teacher, prev_year, prev_sem, prev_plan,
                                "qbp", prev_cal)
                    form = "экзамен" if si % 3 == 0 else ("зачёт" if si % 3 == 1 else "диффзачёт")
                    for stud, profile in roster[g]:
                        five = five_for(profile if profile != "new" else "avg")
                        value = ("Зачтено" if five >= 3 else "Не зачтено") if form == "зачёт" else str(five)
                        objs.append(TermGrade(
                            id=term_grade_id(stud.id, s, prev_year, prev_sem),
                            student_id=stud.id, student_f=stud.surname, student_n=stud.name,
                            subject=s, year=prev_year, semester=prev_sem, grade=value,
                            form=form, updated_at=now))
                        stats["term_grades"] += 1

        # Итоговые в ТЕКУЩЕМ семестре у одной группы по одному предмету — чтобы был виден
        # замок зачётки (после итоговой текущие оценки не ставятся).
        g_lock = "К72/1"
        s_lock = group_subjects[g_lock][1]
        for stud, profile in roster[g_lock][:10]:
            objs.append(TermGrade(id=term_grade_id(stud.id, s_lock, year, semester),
                                  student_id=stud.id, student_f=stud.surname,
                                  student_n=stud.name, subject=s_lock, year=year,
                                  semester=semester, grade=str(five_for(profile)),
                                  form="диффзачёт", updated_at=now))
            stats["term_grades"] += 1

        # Родители: ~160, по одному ребёнку (у нескольких — двое детей). Статусы: большая
        # часть подтверждена студентом, часть ждёт согласия, часть отозвана.
        all_students = [st for g in groups_list for st, _p in roster[g]]
        rnd.shuffle(all_students)
        for pi in range(1, 161):
            child = all_students[pi - 1]
            female = rnd.random() < 0.6
            # Фамилия родителя — от фамилии ребёнка в нужном роде.
            male_form = (child.surname[:-1] if child.surname.endswith(("ова", "ева", "ёва", "ина"))
                         else child.surname)
            sur = _female(male_form) if female else male_form
            first = rnd.choice(_F_NAMES if female else _M_NAMES)
            base, _e = rnd.choice(_PATRONYMICS)
            patr = base + ("на" if female else "ич")
            par = user(f"qa_p{pi:03d}", "parent", f"qa_p{pi:03d}", sur, f"{first} {patr}", patr)
            kids = [child] + ([all_students[200 + pi]] if pi % 20 == 0 else [])
            for kid in kids:
                r = rnd.random()
                status = "active" if r < 0.7 else ("pending" if r < 0.9 else "revoked")
                objs.append(ParentLink(id=parent_link_id(par.id, kid.id), parent_id=par.id,
                                       student_id=kid.id, status=status, created_at=now,
                                       created_by="qa_admin",
                                       decided_at=now if status != "pending" else ""))
        stats["parents"] = 160

        # Ещё модераторы и второй админ.
        user("qa_moder2", "moderator", "qa_moder2", "Кравцова", "Елена Игоревна", "Игоревна",
             mod_number=2)
        user("qa_moder3", "moderator", "qa_moder3", "Тугутов", "Аюр Баирович", "Баирович",
             mod_number=3)
        user("qa_admin2", "admin", "qa_admin2", "Резервов", "Игорь Олегович", "Олегович")

        # Заявки на регистрацию: пачка ожидающих и несколько решённых.
        for ri in range(1, 16):
            sur, name, _p = person(ri % 2 == 0)
            g = groups_list[ri % len(groups_list)]
            status = "pending" if ri <= 12 else ("approved" if ri == 13 else "rejected")
            objs.append(RegistrationRequest(id=f"qa-regreq-big-{ri}", full_name=f"{sur} {name}",
                                            group_name=g, email=f"applicant{ri}@example.invalid",
                                            status=status, created_at=now))

        db.add_all(objs)
        db.flush()
        objs = []

        # Мессенджер: беседа каждой курируемой группы, три публичных канала на всех
        # студентов и личные переписки преподавателей со студентами. Часть прочитана,
        # часть нет — чтобы были видны счётчики непрочитанного.
        lines_teacher = ["Добрый день! Напоминаю про лабораторную к пятнице.",
                         "Завтра пара переносится в аудиторию 728.",
                         "Кто не сдал отчёты — подойдите на консультацию в среду.",
                         "Итоги контрольной выложил в журнал.",
                         "Не забудьте методичку на следующее занятие."]
        lines_student = ["Здравствуйте! А можно сдать отчёт в понедельник?", "Спасибо!",
                         "Я болел, пришлю справку.", "Поняла, буду.", "А какая тема у ДЗ?",
                         "Можно пересдать практику?", "Ок", "Хорошо, спасибо за информацию!"]
        msg_count = 0

        def conv(cid, kind, title, owner, members, about="", public=False, readers=False,
                 n_msgs=20, start_days=25):
            nonlocal msg_count
            created = (now_dt - timedelta(days=start_days)).isoformat()
            db.add(Conversation(id=cid, kind=kind, title=title, about=about, owner_id=owner.id,
                                is_public=public, created_at=created))
            for u in members:
                role = "owner" if u.id == owner.id else ("reader" if readers else "member")
                read_at = (now_dt - timedelta(days=rnd.randint(0, 6))).isoformat()
                db.add(ConversationParticipant(conversation_id=cid, user_id=u.id, role=role,
                                               joined_at=created, last_read_at=read_at))
            for mi in range(n_msgs):
                at = now_dt - timedelta(days=start_days) + timedelta(
                    hours=mi * (start_days * 24 / max(1, n_msgs)))
                sender = owner if (readers or mi % 3 == 0) else rnd.choice(members)
                body = rnd.choice(lines_teacher if sender.role != "student" else lines_student)
                db.add(Message(conversation_id=cid, sender_id=sender.id, body=body,
                               created_at=at.isoformat(), kind="text"))
                msg_count += 1

        for ci, (g, cur) in enumerate(curator_of.items()):
            members = [cur] + [st for st, _p in roster[g]]
            conv(f"conv:qa-grp-{ci:02d}", "group", f"Группа {g}", cur, members,
                 about="Беседа группы с куратором", n_msgs=30)
        everyone = all_students
        for ci, (title, about) in enumerate([("Новости колледжа", "Официальные объявления"),
                                             ("Олимпиады и конкурсы", "Анонсы и итоги"),
                                             ("Спорт", "Секции и соревнования")]):
            conv(f"conv:qa-ch-{ci}", "channel", title, teachers[ci], [teachers[ci]] + everyone,
                 about=about, public=True, readers=True, n_msgs=15)
        for di in range(60):
            t = teachers[di % len(teachers)]
            st = all_students[(di * 7) % len(all_students)]
            cid = direct_conversation_id(t.id, st.id)
            conv(cid, "direct", "", t, [t, st], n_msgs=rnd.randint(4, 14),
                 start_days=rnd.randint(2, 20))
        stats["messages"] = msg_count
        db.commit()
        print("  большой колледж: " + ", ".join(f"{k} {v}" for k, v in stats.items()))
        return stats
    finally:
        db.close()


# ━━ НАПОЛНЕНИЕ (исполняется ВНУТРИ развёрнутого артефакта, cwd = release/) ━━━━━━━━━━━━

def seed() -> None:
    """Пишет выдуманный колледж прямо в базу стенда через модели — ДО старта сервера,
    чтобы не делить базу с живым процессом."""
    sys.path.insert(0, os.getcwd())
    from datetime import datetime, timezone
    from app.db import SessionLocal, init_db, default_term
    from app.models import (Group, Lesson, Grade, ParentLink, RegistrationRequest, Subject,
                            SubjectHours, User, grade_id, parent_link_id, set_user_password,
                            subject_hours_id)

    now = datetime.now(timezone.utc).isoformat()
    year, semester = default_term()
    y0 = int(year.split("/")[0])
    init_db()
    db = SessionLocal()
    try:
        def user(uid, role, login, surname, name, patr, group="", **extra):
            row = User(id=uid, role=role, login=login, surname=surname, name=name,
                       patronymic=patr, full_name=f"{surname} {name}", group_name=group,
                       updated_at=now, **extra)
            db.add(row)
            return row

        for name in sorted({s for subs in GROUP_SUBJECTS.values() for s in subs}):
            db.add(Subject(id=f"subj:{name}", name=name, updated_at=now))
        for g, enrolled in GROUPS.items():
            db.add(Group(id=f"grp:{g}", name=g, subjects=GROUP_SUBJECTS[g],
                         enrollment_year=enrolled, category="college", updated_at=now))

        people = {}
        for login, pwd, role, surname, name, patr, group in ACCOUNTS:
            uid = {"student": f"stud:{login}", "teacher": f"teach:{login}"}.get(role, login)
            extra = {}
            if login == "qa_teacher":
                extra = {"subjects": [RPM, DB_], "curated_groups": ["К74/1"]}
            elif login == "qa_teacher2":
                extra = {"subjects": [MATH]}
            elif role == "moderator":
                extra = {"mod_number": 1}
            row = user(uid, role, login, surname, name, patr, group, **extra)
            set_user_password(row, pwd)
            people[login] = row
        for tid, surname, name, patr, subs in TEACHERS_NO_LOGIN:
            user(tid, "teacher", "", surname, name, patr, subjects=subs)

        owner = {RPM: "teach:qa_teacher", DB_: "teach:qa_teacher", MATH: "teach:qa_teacher2",
                 PE: "teach:budaeva", ENG: "teach:tsyrenov"}
        for g, subs in GROUP_SUBJECTS.items():
            for s in subs:
                db.add(SubjectHours(id=subject_hours_id(g, s, year, semester), group_name=g,
                                    subject=s, year=year, semester=semester, hours_total=72,
                                    teacher_id=owner[s], updated_at=now))

        # Студенты: двое с входом (qa_student — отличник, qa_student2 — должник) + без входа.
        roster = {g: [] for g in GROUPS}
        roster["К74/1"] += [(people["qa_student"], "ex"), (people["qa_student2"], "debt")]
        n = 0
        for g, rows in STUDENTS.items():
            for surname, name, patr, profile in rows:
                n += 1
                roster[g].append((user(f"stud:u:qa-{n:04d}", "student", "", surname, name,
                                       patr, g), profile))

        # Занятия текущего термина: по каждому предмету 3 лекции, 5 практик и ДЗ — в том
        # порядке, в каком они идут в семестре. id латиницей: id занятия уходит в адреса.
        gcode = {"К74/1": "k741", "К74/2": "k742", "К64/2": "k642"}
        scode = {RPM: "rpm", DB_: "db", MATH: "math", PE: "pe", ENG: "eng"}
        tcode = {"Практика": "pr", "ДЗ": "hw", "Лекция": "lec"}
        plan = [("Лекция", 1), ("Практика", 1), ("Практика", 2), ("Лекция", 2),
                ("Практика", 3), ("Практика", 4), ("Лекция", 3), ("Практика", 5), ("ДЗ", 1)]
        for g, subs in GROUP_SUBJECTS.items():
            for si, s in enumerate(subs):
                for k, (ltype, num) in enumerate(plan):
                    lid = f"qa-{gcode[g]}-{scode[s]}-{tcode[ltype]}{num}"
                    topic = ("Решить задачи 1–5 из методички, оформить отчёт"
                             if ltype == "ДЗ" else f"{ltype} №{num}: тема по предмету «{s}»")
                    db.add(Lesson(id=lid, group_name=g, subject=s, type=ltype, number=num,
                                  topic=topic, date=f"{2 + k * 2 + si % 2:02d}.09.{y0}",
                                  year=year, semester=semester, updated_at=now))
                    for stud, profile in roster[g]:
                        practice, hw, lectures = PROFILES[profile]
                        value = (practice[num - 1] if ltype == "Практика"
                                 else hw if ltype == "ДЗ" else lectures[num - 1])
                        if value:
                            db.add(Grade(id=grade_id(stud.id, lid), student_id=stud.id,
                                         student_f=stud.surname, student_n=stud.name,
                                         lesson_id=lid, grade=value, updated_at=now))

        link = parent_link_id(people["qa_parent"].id, people["qa_student2"].id)
        db.add(ParentLink(id=link, parent_id=people["qa_parent"].id,
                          student_id=people["qa_student2"].id, status="active",
                          created_at=now, created_by="qa_admin", decided_at=now))
        db.add(RegistrationRequest(id="qa-regreq-1", full_name="Жамсоева Оюна Баировна",
                                   group_name="К74/2", email="oyuna.qa@example.invalid",
                                   status="pending", created_at=now))
        db.commit()
        total = sum(len(v) for v in roster.values())
        print(f"  наполнено: групп {len(GROUPS)}, студентов {total}, термин {year}/{semester}")
    finally:
        db.close()


# ━━ ЗАПУСК ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main() -> int:
    args = _parse()
    if args.seed_only:
        seed()
        if args.big:
            stats = seed_big()
            with open("BIG_STATS.json", "w", encoding="utf-8") as fh:
                json.dump(stats, fh, ensure_ascii=False)
        return 0

    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import smoke_release as smoke

    artifact = args.artifact or smoke._latest_artifact()
    # Папку стенда пересоздаём целиком: база прошлого прогона — чужие правки прошлой
    # проверки, и находки по ней не воспроизвести.
    if os.path.isdir(args.dir):
        shutil.rmtree(args.dir, ignore_errors=True)
    os.makedirs(args.dir, exist_ok=True)
    stand = smoke.Stand(artifact, workdir=args.dir, port=args.port)
    print(f"стенд: {artifact}")
    stand.unpack()

    db_url = "sqlite:///" + os.path.join(args.dir, "smoke.db").replace("\\", "/")
    env = dict(os.environ, GRADEBOOK_DB_URL=db_url, PYTHONUTF8="1",
               PYTHONPATH=os.pathsep.join([stand.code, os.path.join(stand.code, "root")]))
    subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__), "--seed-only"]
                   + (["--big"] if args.big else []),
                   cwd=stand.code, env=env, check=True)

    # Внешние сервисы на стенде не нужны: погода — иностранный субобработчик, а стенд
    # не должен ходить наружу сам по себе. LLM не настроен — Вектор на офлайн-шаблонах.
    os.environ["GRADEBOOK_WEATHER"] = "off"
    stand.start()
    stand.wait_health(120)
    info = {"url": stand.base, "dir": args.dir, "artifact": os.path.basename(artifact),
            "accounts": [{"login": a[0], "password": a[1], "role": a[2],
                          "name": f"{a[3]} {a[4]}", "group": a[6]} for a in ACCOUNTS]}
    if args.big:
        stats_path = os.path.join(stand.code, "BIG_STATS.json")
        stats = {}
        if os.path.exists(stats_path):
            with open(stats_path, encoding="utf-8") as fh:
                stats = json.load(fh)
        info["big"] = {
            "password": BIG_PASSWORD, "stats": stats,
            "logins": {"students": "qa_s0001 … qa_s0500 (по 25 на группу, порядок групп как в BIG_GROUPS)",
                       "teachers": "qa_t01 … qa_t28 (qa_t01–qa_t16 — кураторы; qa_t03 и qa_t11 — "
                                   "100-балльная шкала, qa_t05 — буквенная, qa_t07 — зачёт/незачёт)",
                       "parents": "qa_p001 … qa_p160 (≈70% привязок подтверждены, ≈20% ждут, ≈10% отозваны)",
                       "moderators": "qa_moder2, qa_moder3", "admins": "qa_admin2"},
            "groups": BIG_GROUPS,
            "notes": ["К75/1: раздельное обучение по первому предмету (две подгруппы)",
                      "К72/1: у первых 10 студентов итоговая по второму предмету — семестр закрыт",
                      "прошлый семестр (архив) — у всех групп, поступивших раньше этого года"],
        }
    with open(os.path.join(args.dir, "STAND.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=1)
    print(f"СТЕНД ГОТОВ: {stand.base}  (лог: {stand.log_path})")
    for a in ACCOUNTS:
        print(f"  {a[2]:<10} {a[0]:<12} {a[1]:<24} {a[3]} {a[4]} {a[6]}")
    try:
        stand.proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stand.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
