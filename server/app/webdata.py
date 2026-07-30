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
import re
import sys

#grading.py лежит в корне репозитория рядом с server/. Разворачивание идёт из того
#же репо (см. server/DEPLOY.md: git clone <repo> && cd server), поэтому корень
#доступен. Добавляем его в sys.path и переиспользуем единый расчёт.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import grading  # noqa: E402
import study_hours  # noqa: E402  — общее с десктопом правило учебных часов

from .models import (User, Lesson, Grade, ConfigKV, SubjectHours,  # noqa: E402
                     subject_hours_id)


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


_RETAKE_RE = re.compile(r"_retake(_\d+)?$")


def base_lesson_id(lesson_id: str) -> str:
    """Базовый id занятия без суффикса пересдачи: `<lid>_retake[_N]` → `<lid>`.
    Оценки пересдач хранятся отдельными строками с таким суффиксом в lesson_id."""
    return _RETAKE_RE.sub("", lesson_id or "")


def group_lesson_ids(db, group: str) -> set:
    """Множество БАЗОВЫХ id занятий группы (без надгробий) — для скоупинга оценок.

    Зачем: оценки хранятся по ключу surname|name|lesson_id БЕЗ группы, поэтому выборка
    по (surname, name) затягивает и строки ОДНОФАМИЛЬЦА-ТЁЗКИ из другой группы. Их
    занятия принадлежат другой группе, значит их lesson_id НЕ попадёт в этот набор —
    так мы отфильтровываем чужие оценки, не меняя формат ключа (совместимость синка)."""
    rows = db.query(Lesson.id).filter(
        Lesson.group_name == group, Lesson.deleted == False).all()  # noqa: E712
    return {r[0] for r in rows}


def student_records(db, surname: str, name: str, group: str | None = None,
                    allowed_lesson_ids: set | None = None) -> dict:
    """{lesson_id → оценка} для студента. Ключи пересдач (`<lid>_retake[_N]`) тоже
    приходят как отдельные строки grades — grading их учитывает по последней попытке.

    ЗАЩИТА ОТ ТЁЗОК. Если задана `group` (или готовый `allowed_lesson_ids`), оставляем
    только оценки, чьё занятие принадлежит этой группе — так студент/преподаватель
    никогда не видит оценок однофамильца из ДРУГОЙ группы. Легитимные оценки студента
    всегда стоят на занятиях его группы, поэтому фильтр ничего своего не теряет.
    Без параметров — прежнее поведение (полная выборка по имени)."""
    rows = db.query(Grade.lesson_id, Grade.grade).filter(
        Grade.student_f == surname, Grade.student_n == name,
        Grade.deleted == False).all()  # noqa: E712
    if group is None and allowed_lesson_ids is None:
        return {lid: g for lid, g in rows}
    allowed = allowed_lesson_ids if allowed_lesson_ids is not None else group_lesson_ids(db, group)
    return {lid: g for lid, g in rows if base_lesson_id(lid) in allowed}


def current_term(cfg: dict) -> tuple:
    """Текущий учебный термин (год, семестр) из config, иначе — дефолт по дате.
    Год «YYYY/YYYY+1», семестр 1 (осень) | 2 (весна)."""
    from . import db as _db
    y = (cfg.get("current_year") or "").strip()
    s = cfg.get("current_semester")
    if y and s:
        try:
            return y, int(s)
        except (TypeError, ValueError):
            pass
    return _db.default_term()


def group_lessons(db, group: str, subject: str | None = None,
                  year: str | None = None, semester: int | None = None):
    """Занятия группы (опц. по предмету И учебному периоду), в порядке десктопа.

    Фильтр по термину (year+semester) — основа долгосрочного журнала: показываем
    занятия конкретного семестра. Без термина — все периоды (обратная совместимость)."""
    q = db.query(Lesson).filter(Lesson.group_name == group,
                                Lesson.deleted == False)  # noqa: E712
    if subject:
        q = q.filter(Lesson.subject == subject)
    if year:
        q = q.filter(Lesson.year == year)
    if semester:
        q = q.filter(Lesson.semester == int(semester))
    return q.order_by(Lesson.subject, Lesson.type, Lesson.number, Lesson.hour).all()


def list_terms(db) -> list:
    """Список учебных периodов, по которым есть занятия: [{year, semester}], новые сверху.
    Для селектора термина в журнале/статистике и для архива прошлых семестров."""
    rows = db.query(Lesson.year, Lesson.semester).filter(
        Lesson.deleted == False, Lesson.year != "").distinct().all()  # noqa: E712
    terms = sorted({(y, int(s or 0)) for y, s in rows if y},
                   key=lambda t: (t[0], t[1]), reverse=True)
    return [{"year": y, "semester": s} for y, s in terms]


def lesson_pairs(lessons):
    return [(l.id, l.type) for l in lessons]


def hours_done(lessons) -> int:
    """Пройденные академические часы — через общий с десктопом study_hours."""
    return study_hours.hours_done(lessons)


def hours_plan(db, group: str, subject: str, year: str, semester) -> int:
    """Плановые часы предмета для группы на семестр (0 — админ ещё не задавал)."""
    row = db.get(SubjectHours, subject_hours_id(group, subject, year, semester))
    if row is None or row.deleted:
        return 0
    return int(row.hours_total or 0)


def hours_progress(db, group: str, subject: str, lessons, year: str, semester) -> dict:
    """{done, total} — «пройдено X из Y часов» для шапки журнала.

    total=0 означает «часы не заданы»: клиент в этом случае просто не показывает строку,
    а не рисует «24 из 0». Придумывать план за администратора нельзя."""
    return {"done": hours_done(lessons),
            "total": hours_plan(db, group, subject, year, semester)}


def teacher_scale(user) -> str:
    """Шкала ОДНОГО преподавателя (§ролей, 3.3.1) — для мест, где все lessons в списке
    заведомо ведёт ОН ЖЕ (журнал/статистика по своим назначениям): дешевле, чем
    lesson_scale_map, лишних запросов не требует."""
    sc = (user.prefs or {}).get("grading_scale") or grading.DEFAULT_SCALE
    return sc if sc in grading.SCALES else grading.DEFAULT_SCALE


def lesson_scale_map(db, lessons) -> dict:
    """{lesson_id: шкала} — какой шкалой (§ролей, 3.3.1) вводил оценку преподаватель,
    ведущий именно ЭТО занятие. Разрешение — через ТО ЖЕ назначение препод↔предмет↔
    группа, что и видимость групп (SubjectHours.teacher_id, см. teacher_assignments):
    занятие → (группа,предмет,термин) → назначенный преподаватель → его User.prefs
    ["grading_scale"]. Без назначения ИЛИ без выбора шкалы — DEFAULT_SCALE ("5"),
    то есть сегодняшнее поведение бит-в-бит. Нужен именно СЛОВАРЬ (не одна строка на
    все lessons), потому что список занятий часто смешивает НЕСКОЛЬКО предметов
    разом (общий средний студента/группы по всем предметам) — у каждого предмета
    может быть свой преподаватель со своей шкалой."""
    if not lessons:
        return {}
    pair_terms = {(l.group_name, l.subject, l.year or "", int(l.semester or 0))
                  for l in lessons}
    year_sem = {(y, s) for (_g, _sub, y, s) in pair_terms}
    hours_rows = []
    for y, s in year_sem:
        hours_rows.extend(db.query(SubjectHours).filter(
            SubjectHours.year == y, SubjectHours.semester == s,
            SubjectHours.deleted == False).all())  # noqa: E712
    teacher_by_pair = {}
    for r in hours_rows:
        if r.teacher_id:
            teacher_by_pair[(r.group_name, r.subject, r.year or "",
                             int(r.semester or 0))] = r.teacher_id
    teacher_ids = set(teacher_by_pair.values())
    scale_by_teacher = {}
    if teacher_ids:
        for u in db.query(User).filter(User.id.in_(teacher_ids)).all():
            sc = (u.prefs or {}).get("grading_scale") or grading.DEFAULT_SCALE
            scale_by_teacher[u.id] = sc if sc in grading.SCALES else grading.DEFAULT_SCALE
    out = {}
    for l in lessons:
        key = (l.group_name, l.subject, l.year or "", int(l.semester or 0))
        tid = teacher_by_pair.get(key)
        out[l.id] = scale_by_teacher.get(tid, grading.DEFAULT_SCALE)
    return out


def average(lessons, records, cfg, scale=None) -> float:
    """Средний балл — единый расчёт grading.practice_average. scale — {lesson_id:
    шкала} из lesson_scale_map (или None/строка — тогда как раньше, "5" для всех)."""
    return grading.practice_average(lesson_pairs(lessons), records, cfg,
                                    scale=scale if scale is not None else grading.DEFAULT_SCALE)


def per_subject_averages(lessons, records, cfg, scale=None):
    """Список {subject, average, lessons} — средний по каждому предмету группы."""
    from collections import OrderedDict
    buckets = OrderedDict()
    for l in lessons:
        buckets.setdefault(l.subject, []).append(l)
    out = []
    for subj, ls in buckets.items():
        out.append({"subject": subj, "average": average(ls, records, cfg, scale=scale),
                    "lessons": len(ls)})
    return out


def debts(lessons, records, scale=None):
    """Причины задолженности (порт vector/intents._is_debt). scale — {lesson_id: шкала}
    из lesson_scale_map, для распознавания «завалено» в шкале ведущего преподавателя."""
    reasons = []
    scale_map = scale if isinstance(scale, dict) else None
    for l in lessons:
        if grading.is_practice(l.type):
            v = records.get(l.id)
            lscale = (scale_map.get(l.id, grading.DEFAULT_SCALE) if scale_map is not None
                     else (scale or grading.DEFAULT_SCALE))
            if v == "Н" or (v and grading.is_failed_scaled(v, lscale)):
                #ДЗ — тоже долг: «Н» на домашней работе значит «не сдал», а не «не был».
                what = "ДЗ" if l.type == "ДЗ" else "практика"
                ending = "о" if l.type == "ДЗ" else "а"
                reasons.append(f"{what} №{l.number} не сдан{ending} ({v})")
        elif l.type == "Экзамен":
            v = grading.latest_exam_value(l.id, records)
            if grading.is_failed(v):   #единый источник fail-логики (см. grading.is_failed)
                reasons.append(f"экзамен №{l.number} не зачтён")
    return reasons


def absences(lessons, records):
    """Пропуски (порт vector/intents._count_absences). Строка лекции = 1 час.

    ⚠️ ДЗ здесь НЕ учитывается, хотя в средний балл идёт наравне с практикой: «Н» на
    домашней работе означает «не сдал», а не «не был на занятии». Записать это в пропуски
    значило бы наказать студента посещаемостью за несданную домашку."""
    res = {"Н": 0, "Б": 0, "О": 0}
    for l in lessons:
        v = records.get(l.id)
        if l.type == "Лекция" and v in ("Н", "Б", "О"):
            res[v] += 1
        elif l.type == "Практика" and v == "Н":
            res["Н"] += 1
    res["всего"] = res["Н"] + res["Б"] + res["О"]
    return res


def zet_summary_for_student(db, surname: str, name: str, group: str, year: str, semester) -> dict:
    """Сводка ЗЕТ студента за термин (docs/PLAN-ZET.md) — {earned,total,pct,subjects[]}.
    Собирает занятия/оценки/шкалы преподавателей и сводит через ЧИСТЫЕ функции
    study_hours (та же логика для студента/куратора/родителя, один расчёт)."""
    lessons = group_lessons(db, group, year=year, semester=semester)
    records = student_records(db, surname, name, group)
    scale_map = lesson_scale_map(db, lessons)
    hrows = {r.subject: r for r in db.query(SubjectHours).filter(
        SubjectHours.group_name == group, SubjectHours.year == (year or ""),
        SubjectHours.semester == int(semester or 0), SubjectHours.deleted == False).all()}  # noqa: E712
    from collections import OrderedDict
    by_subject = OrderedDict()
    for l in lessons:
        by_subject.setdefault(l.subject, []).append(l)
    rows = []
    for subj, ls in by_subject.items():
        row = hrows.get(subj)
        zet = row.zet if row is not None else None
        if zet is None:
            continue
        scale = scale_map.get(ls[0].id, grading.DEFAULT_SCALE) if ls else grading.DEFAULT_SCALE
        earned = study_hours.subject_zet_earned(ls, records, zet, scale=scale)
        rows.append({"subject": subj, "zet": zet, "earned": earned})
    return study_hours.zet_summary(rows)


def group_zet_report(db, group: str, year: str, semester, min_zet) -> list:
    """Отчёт группы для кнопки перевода на курс (docs/PLAN-ZET.md §7.4) — по каждому
    студенту сводит zet_summary_for_student, дальше решает study_hours.group_zet_report."""
    students = []
    for s in students_in_group(db, group):
        students.append({"student_id": s.id, "display_name": display_name(s),
                         "summary": zet_summary_for_student(db, s.surname, s.name, group,
                                                            year, semester)})
    return study_hours.group_zet_report(students, min_zet)


def students_in_group(db, group: str):
    """Студенты группы — это пользователи с ролью student и этой group_name."""
    return db.query(User).filter(
        User.role == "student", User.group_name == group,
        User.deleted == False).order_by(User.surname, User.name).all()  # noqa: E712


def teacher_assignments(db, teacher_id: str, year: str, semester,
                        allow_fallback: bool = True) -> list:
    """Пары (группа, предмет), ЯВНО назначенные преподавателю на этот термин —
    ЕДИНЫЙ источник правды «какие группы видит препод» (см. models.SubjectHours.
    teacher_id). Заменяет старую teacher_groups()/«предмет числится у препода» —
    та отдавала ЛЮБУЮ группу, где предмет вообще упоминался, даже группам, которых
    препод в глаза не видел (баг, найденный в 3.3.1: препод с 5 предметами видел
    все группы этих предметов, а не только свои).

    Без назначения на семестр (админ ещё не расставил) — пустой список: это НЕ
    «видно всё», а «видно ничего, пока не назначили» — осознанно строже старого
    поведения, ошибка в другую сторону (спрятать своё) тут безопаснее."""
    if not teacher_id:
        return []
    rows = (db.query(SubjectHours)
            .filter(SubjectHours.teacher_id == teacher_id,
                    SubjectHours.year == (year or ""),
                    SubjectHours.semester == int(semester or 0),
                    SubjectHours.deleted == False).all())  # noqa: E712
    pairs = sorted({(r.group_name, r.subject) for r in rows if r.group_name and r.subject})
    if pairs or not allow_fallback:
        return pairs
    #⚠️ НОЛЬ назначений — это НЕ «админ назначил пусто», и разница стоила боевого простоя.
    #30.07.2026 нагрузка обнулилась сразу у ВСЕХ преподавателей (проверено на живых
    #аккаунтах Saha/ddxd/Dixm/Artur/Golubev): в базе 13 строк SubjectHours, teacher_id
    #пуст во всех — до появления редактора назначений заполнять его было нечем. Пустой
    #журнал получили и сайт, и десктоп (он ходит в тот же API), и офлайн-копия: строгий
    #скоуп заодно перестал привозить группы в /sync/pull.
    #Решение тимлида: до расстановки назначений работаем по ПРЕЖНЕМУ правилу. Замысел
    #точного скоупа цел — появилось хоть одно назначение, и работают ТОЛЬКО они (return
    #выше), поэтому «препод видит чужие группы» не возвращается. Это мост на время ввода
    #данных, а не режим: снимается удалением этой ветки, когда назначения расставлены.
    return _assignments_fallback(db, teacher_id)


def _assignments_fallback(db, teacher_id: str) -> list:
    """Пары (группа, предмет) по прежнему правилу — для преподавателя БЕЗ назначений.

    Два источника, как было до перехода на явные назначения: группы его РЕАЛЬНЫХ занятий
    и группы, где его предмет числится в справочнике. Второй нужен новичку — у него ещё
    нет ни одного занятия, и без этого он не смог бы создать первое."""
    from .models import Group
    user = db.get(User, teacher_id)
    subjects = {s for s in ((user.subjects if user else None) or []) if s}
    if not subjects:
        return []
    pairs = set()
    for g_name, subj in (db.query(Lesson.group_name, Lesson.subject)
                         .filter(Lesson.subject.in_(subjects),
                                 Lesson.deleted == False).distinct().all()):  # noqa: E712
        if g_name and subj:
            pairs.add((g_name, subj))
    for g in db.query(Group).filter(Group.deleted == False).all():  # noqa: E712
        for subj in subjects & set(g.subjects or []):
            pairs.add((g.name, subj))
    return sorted(pairs)


def teacher_group_names(db, teacher_id: str, year: str, semester) -> list:
    """Только имена групп из teacher_assignments — для мест, которым предмет не нужен
    (аудитория уведомлений, список групп для создания чата и т.п.)."""
    return sorted({g for g, _s in teacher_assignments(db, teacher_id, year, semester)})


def display_name(user) -> str:
    return user.full_name or f"{user.surname} {user.name}".strip()


def first_name(user) -> str:
    """Имя БЕЗ отчества (первое слово name) — для раздельного показа/ввода.
    name хранит «Имя Отчество» и остаётся ключом оценок, поэтому имя берём как
    первое слово, а отчество отдаём отдельным полем (см. patronymic_of)."""
    n = (getattr(user, "name", "") or "").strip()
    return n.split(" ", 1)[0] if " " in n else n


def patronymic_of(user) -> str:
    """Отчество: из отдельного поля users.patronymic, а если оно пусто (напр. строка
    пришла со старого десктопа без этого поля) — из хвоста name. Так отчество всегда
    показывается раздельно, независимо от источника строки."""
    p = (getattr(user, "patronymic", "") or "").strip()
    if p:
        return p
    n = (getattr(user, "name", "") or "").strip()
    return n.split(" ", 1)[1].strip() if " " in n else ""


def split_fio(full_name: str) -> tuple:
    """Разбор «Фамилия Имя Отчество» → (surname, first_name, patronymic).
    Отчество — всё, что после 2-го слова (на случай двойных отчеств/фамилий редко,
    но хвост целиком относим к отчеству, как и раньше делал name= parts[1:])."""
    parts = (full_name or "").split()
    surname = parts[0] if parts else ""
    first = parts[1] if len(parts) > 1 else ""
    patr = " ".join(parts[2:]) if len(parts) > 2 else ""
    return surname, first, patr
