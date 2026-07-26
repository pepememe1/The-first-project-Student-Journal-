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
        if grading.is_practice(l.type):
            v = records.get(l.id)
            if v in ("2", "Н"):
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
