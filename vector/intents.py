"""
intents.py — Whitelisted-интенты: распознавание намерения + РЕАЛЬНЫЙ SQL к базе.

Это слой, который защищает от галлюцинаций. Свободный вопрос пользователя НЕ уходит
в LLM как есть. Сначала мы локально определяем намерение из закрытого списка
(долги / пропуски / средний балл / зона риска / сводка), исполняем заранее
заготовленный параметризованный SQL и получаем ФАКТЫ-числа из своей базы. LLM потом
эти факты только переформулирует. Любая цифра в ответе — из базы, не из модели.

Все запросы фильтруются по VectorScope:
  • студент видит только свои данные (privacy-by-design на уровне SQL);
  • преподаватель — текущую группу и предмет;
  • админ — группу (по всем предметам) или всё.
"""
import sqlite3
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

#ВАЖНО: Вектор обязан читать ТУ ЖЕ базу, что и приложение. После переноса базы
#в локальную папку пользователя (core.LOCAL_DB) относительный путь сломался бы —
#поэтому берём путь из core.
try:
    from core import LOCAL_DB as DEFAULT_DB
except Exception:
    DEFAULT_DB = "vsgutu_grades.db"

PRACTICE_VALUES = {"2", "3", "4", "5"}


#Контекст доступа
@dataclass
class VectorScope:
    role: str = "student"                 #student / teacher / admin
    group: str = ""
    subject: Optional[str] = None         #None = все предметы группы
    student_f: str = ""                   #для роли student — своя фамилия
    student_n: str = ""                   #для роли student — своё имя
    db_path: str = DEFAULT_DB
    teacher_groups: List[str] = field(default_factory=list)  #для роли teacher — его группы


@dataclass
class Facts:
    intent: str
    facts_text: str                       #нейтральное текстовое представление
    names: List[str] = field(default_factory=list)   #реальные имена в тексте
    data: Dict = field(default_factory=dict)          #структурно (для карточек)
    mood_value: Optional[float] = None    #средний балл для настроения, если есть


#Низкоуровневые помощники
def _conn(scope: VectorScope) -> sqlite3.Connection:
    return sqlite3.connect(scope.db_path)


def _lessons(conn, group: str, subject: Optional[str]) -> List[tuple]:
    cur = conn.cursor()
    #COALESCE(deleted,0)=0 — Вектор не должен ссылаться на удалённые (надгробия) занятия.
    if subject:
        cur.execute(
            "SELECT id, type, number, topic, date FROM lessons "
            "WHERE group_name=? AND subject=? AND COALESCE(deleted,0)=0 "
            "ORDER BY type, number, hour",
            (group, subject),
        )
    else:
        cur.execute(
            "SELECT id, type, number, topic, date FROM lessons "
            "WHERE group_name=? AND COALESCE(deleted,0)=0 "
            "ORDER BY subject, type, number, hour",
            (group,),
        )
    return cur.fetchall()


def _records(conn, f: str, n: str) -> Dict[str, str]:
    cur = conn.cursor()
    cur.execute("SELECT lesson_id, grade FROM grades "
                "WHERE student_f=? AND student_n=? AND COALESCE(deleted,0)=0", (f, n))
    return {row[0]: row[1] for row in cur.fetchall()}


def _students(conn, group: str) -> List[Tuple[str, str]]:
    cur = conn.cursor()
    cur.execute("SELECT f, n FROM students WHERE group_name=? ORDER BY f", (group,))
    return cur.fetchall()


def _practice_average(lessons: List[tuple], records: Dict[str, str],
                      cfg: Optional[dict] = None) -> float:
    """Средний балл — через единый модуль grading (та же формула, что в core)."""
    import grading
    if cfg is None:
        try:
            from data_store import get_store
            cfg = get_store()._config()
        except Exception:
            cfg = {}
    return grading.practice_average(
        [(lid, ltype) for lid, ltype, *_ in lessons], records, cfg)


def _latest_exam_value(lid: str, records: Dict[str, str]) -> str:
    """Берёт последнюю попытку по экзамену: base, _retake, _retake_2 ..."""
    val = records.get(lid, "")
    i = 1
    while True:
        key = f"{lid}_retake" if i == 1 else f"{lid}_retake_{i}"
        if key in records and records[key]:
            val = records[key]
            i += 1
        else:
            break
    return val


def _is_debt(lessons: List[tuple], records: Dict[str, str]) -> List[str]:
    """Возвращает список причин задолженности (пусто — долгов нет)."""
    reasons = []
    for lid, ltype, num, *_ in lessons:
        if ltype == "Практика":
            v = records.get(lid)
            if v in ("2", "Н"):
                reasons.append(f"практика №{num} не сдана ({v})")
        elif ltype == "Экзамен":
            v = _latest_exam_value(lid, records)
            if v and ("Не зачтено" in v or v.strip().startswith(("2", "Н"))):
                reasons.append(f"экзамен №{num} не зачтён")
    return reasons


def _count_absences(lessons: List[tuple], records: Dict[str, str]) -> Dict[str, int]:
    """Считает пропуски. Каждая строка лекции = 1 час."""
    res = {"Н": 0, "Б": 0, "О": 0}
    for lid, ltype, *_ in lessons:
        v = records.get(lid)
        if ltype == "Лекция" and v in ("Н", "Б", "О"):
            res[v] += 1
        elif ltype == "Практика" and v == "Н":
            res["Н"] += 1
    res["всего"] = res["Н"] + res["Б"] + res["О"]
    return res


#Хендлеры интентов  (каждый возвращает Facts)
def _resolve_student(scope: VectorScope, asked_name: str) -> Optional[Tuple[str, str]]:
    """
    Кого спрашивают. Студент всегда видит только себя (privacy). Преподаватель/админ
    — указанного по фамилии; если не указали, вернёт None (значит запрос групповой).
    """
    if scope.role == "student":
        return (scope.student_f, scope.student_n)
    if not asked_name:
        return None
    #SQLite LOWER() не понижает кириллицу — сравниваем в Python.
    conn = _conn(scope)
    cur = conn.cursor()
    cur.execute("SELECT f, n FROM students WHERE group_name=?", (scope.group,))
    target = asked_name.strip().lower()
    for f, n in cur.fetchall():
        if f.strip().lower() == target:
            conn.close()
            return (f, n)
    conn.close()
    return None


def intent_average(scope: VectorScope, asked_name: str = "") -> Facts:
    conn = _conn(scope)
    lessons = _lessons(conn, scope.group, scope.subject)
    who = _resolve_student(scope, asked_name)
    if who:
        f, n = who
        recs = _records(conn, f, n)
        conn.close()
        avg = _practice_average(lessons, recs)
        name = f"{f} {n}".strip()
        txt = (f"{name}: средний балл {avg}." if avg
               else f"{name}: оценок по практикам пока нет.")
        return Facts("average", txt, names=[name, f],
                     data={"student": name, "average": avg}, mood_value=avg or None)
    #групповой средний
    studs = _students(conn, scope.group)
    avgs = []
    for f, n in studs:
        recs = _records(conn, f, n)
        a = _practice_average(lessons, recs)
        if a:
            avgs.append(a)
    conn.close()
    grp_avg = round(sum(avgs) / len(avgs), 2) if avgs else 0.0
    txt = (f"Группа {scope.group}: средний балл {grp_avg} "
           f"(посчитано по {len(avgs)} студентам)." if grp_avg
           else f"Группа {scope.group}: оценок пока нет.")
    return Facts("average", txt, data={"group_average": grp_avg},
                 mood_value=grp_avg or None)


def intent_absences(scope: VectorScope, asked_name: str = "") -> Facts:
    conn = _conn(scope)
    lessons = _lessons(conn, scope.group, scope.subject)
    who = _resolve_student(scope, asked_name)
    if not who:
        conn.close()
        return Facts("absences",
                     "Уточните, по какому студенту посчитать пропуски (фамилия).")
    f, n = who
    recs = _records(conn, f, n)
    conn.close()
    a = _count_absences(lessons, recs)
    name = f"{f} {n}".strip()
    txt = (f"{name}: пропусков {a['всего']} ч "
           f"(неуваж. {a['Н']}, болезнь {a['Б']}, уваж. {a['О']}).")
    return Facts("absences", txt, names=[name, f], data={"student": name, **a})


def intent_debtors(scope: VectorScope, asked_name: str = "") -> Facts:
    conn = _conn(scope)
    lessons = _lessons(conn, scope.group, scope.subject)
    studs = ([_resolve_student(scope, "")] if scope.role == "student"
             else _students(conn, scope.group))
    debtors = []
    names = []
    for who in studs:
        if not who:
            continue
        f, n = who
        recs = _records(conn, f, n)
        reasons = _is_debt(lessons, recs)
        if reasons:
            name = f"{f} {n}".strip()
            debtors.append({"student": name, "reasons": reasons})
            names += [name, f]
    conn.close()
    if not debtors:
        scope_txt = "у тебя" if scope.role == "student" else f"в группе {scope.group}"
        return Facts("debtors", f"Задолженностей {scope_txt} нет.", data={"debtors": []})
    if scope.role == "student":
        d = debtors[0]
        txt = "Есть незакрытые долги: " + "; ".join(d["reasons"]) + "."
    else:
        listing = ", ".join(f"{d['student']} ({len(d['reasons'])})" for d in debtors)
        txt = f"Должников в группе {scope.group}: {len(debtors)}. {listing}."
    return Facts("debtors", txt, names=names, data={"debtors": debtors})


def intent_grades(scope: VectorScope, asked_name: str = "") -> Facts:
    conn = _conn(scope)
    lessons = _lessons(conn, scope.group, scope.subject)
    who = _resolve_student(scope, asked_name)
    if not who:
        conn.close()
        return Facts("grades", "Уточните фамилию студента для выписки оценок.")
    f, n = who
    recs = _records(conn, f, n)
    conn.close()
    marks = []
    for lid, ltype, _num, *_ in lessons:
        v = recs.get(lid)
        if ltype == "Практика" and v in PRACTICE_VALUES:
            marks.append(v)
    name = f"{f} {n}".strip()
    avg = _practice_average(lessons, recs)
    if marks:
        txt = f"{name}: оценки по практикам — {', '.join(marks)}; средний {avg}."
    else:
        txt = f"{name}: оценок по практикам пока нет."
    return Facts("grades", txt, names=[name, f],
                 data={"student": name, "marks": marks, "average": avg},
                 mood_value=avg or None)


def intent_at_risk(scope: VectorScope, asked_name: str = "") -> Facts:
    conn = _conn(scope)
    lessons = _lessons(conn, scope.group, scope.subject)
    studs = _students(conn, scope.group)
    risky, names = [], []
    for f, n in studs:
        recs = _records(conn, f, n)
        avg = _practice_average(lessons, recs)
        absc = _count_absences(lessons, recs)["всего"]
        if (avg and avg < 3.0) or absc >= 10:
            name = f"{f} {n}".strip()
            risky.append({"student": name, "average": avg, "absences": absc})
            names += [name, f]
    conn.close()
    if not risky:
        return Facts("at_risk", f"В группе {scope.group} студентов в зоне риска нет.",
                     data={"risky": []})
    listing = ", ".join(f"{r['student']} (ср.{r['average']}, проп.{r['absences']})"
                        for r in risky)
    txt = f"В зоне риска ({len(risky)}): {listing}."
    return Facts("at_risk", txt, names=names, data={"risky": risky})


def intent_group_stats(scope: VectorScope, asked_name: str = "") -> Facts:
    conn = _conn(scope)
    lessons = _lessons(conn, scope.group, scope.subject)
    studs = _students(conn, scope.group)
    avgs, total_abs, debtors = [], 0, 0
    for f, n in studs:
        recs = _records(conn, f, n)
        a = _practice_average(lessons, recs)
        if a:
            avgs.append(a)
        total_abs += _count_absences(lessons, recs)["всего"]
        if _is_debt(lessons, recs):
            debtors += 1
    conn.close()
    grp_avg = round(sum(avgs) / len(avgs), 2) if avgs else 0.0
    txt = (f"Группа {scope.group}: студентов {len(studs)}, средний балл {grp_avg}, "
           f"должников {debtors}, пропусков всего {total_abs} ч.")
    return Facts("group_stats", txt,
                 data={"students": len(studs), "average": grp_avg,
                       "debtors": debtors, "absences": total_abs},
                 mood_value=grp_avg or None)


def intent_help(scope: VectorScope, asked_name: str = "") -> Facts:
    from .faq import help_text
    return Facts("help", help_text(scope.role))


def _store():
    from data_store import get_store
    return get_store()


def intent_groups(scope: VectorScope, asked_name: str = "") -> Facts:
    """Список групп. Студент видит свою группу; препод — открытую/свои; админ — все."""
    if scope.role == "student":
        g = scope.group or "—"
        return Facts("groups", f"Твоя группа — {g}. Списком всех групп колледжа "
                               f"распоряжается администрация.")
    try:
        #get_groups() возвращает СЛОВАРИ {"name":..,"subjects":[..]} — раньше их пытались
        #склеить через join как строки, отсюда падало «expected str instance, dict found».
        #Берём именно имена групп.
        groups = [g.get("name", "") for g in (_store().get_groups() or [])
                  if isinstance(g, dict) and g.get("name")]
    except Exception:
        groups = []
    if scope.role == "teacher":
        cur = scope.group
        extra = f" Сейчас открыта группа {cur}." if cur else ""
        #Преподаватель видит ТОЛЬКО свои группы (из назначений предмет→группа), а не
        #весь список колледжа — им распоряжается администрация.
        my = [g for g in (scope.teacher_groups or []) if g]
        if my:
            word = "группа" if len(my) == 1 else "группы"
            return Facts("groups", f"Твои {word} ({len(my)}): {', '.join(my)}.{extra}")
        #Назначений нет — покажем хотя бы открытую сейчас.
        if cur:
            return Facts("groups", f"Открытая группа: {cur}. "
                                   f"Полный список групп ведёт администрация.")
        return Facts("groups", "За тобой пока не закреплено ни одной группы — "
                               "это настраивает администратор.")
    # admin
    if not groups:
        return Facts("groups", "Групп в системе пока нет — добавьте их во вкладке «Группы».")
    return Facts("groups", f"Всего групп: {len(groups)}. {', '.join(groups)}.")


def intent_teachers(scope: VectorScope, asked_name: str = "") -> Facts:
    """Список преподавателей колледжа — ТОЛЬКО для администратора.

    Просмотр кадрового состава — задача администрации. Преподавателю Вектор
    больше не показывает других преподавателей (это не его зона ответственности),
    а студенту — тем более. И тому и другому даём вежливый редирект; полный
    список с предметами видит лишь роль admin."""
    if scope.role != "admin":
        return Facts("teachers", "Список преподавателей ведёт администрация — "
                                 "за полным перечнем обратись к администратору. "
                                 "Кто ведёт конкретные предметы, смотри в расписании.")
    try:
        teachers = _store().get_teachers() or {}
    except Exception:
        teachers = {}
    names = list(teachers.keys())
    if not names:
        return Facts("teachers", "Преподаватели пока не заведены — добавьте их "
                                 "во вкладке «Преподаватели».")
    #админу показываем преподавателей вместе с их предметами
    lines = []
    for nm in names:
        subj = teachers.get(nm, {}).get("subjects", []) if isinstance(teachers.get(nm), dict) else []
        lines.append(f"{nm}" + (f" ({', '.join(subj)})" if subj else ""))
    return Facts("teachers", f"Преподаватели ({len(names)}): " + "; ".join(lines) + ".")


def intent_roster(scope: VectorScope, asked_name: str = "") -> Facts:
    """Список студентов группы. Студенту НЕ выдаём (чужие ПДн). Препод/админ — да."""
    if scope.role == "student":
        return Facts("roster", "Список одногруппников и их данные я не показываю — "
                               "это персональные данные других студентов. "
                               "Зато покажу твои оценки, пропуски и долги.")
    conn = _conn(scope)
    studs = _students(conn, scope.group)
    conn.close()
    if not studs:
        return Facts("roster", f"В группе {scope.group or '—'} студентов пока нет "
                               f"(или группа не выбрана).")
    names = [f"{f} {n}".strip() for f, n in studs]
    return Facts("roster", f"Студенты группы {scope.group} ({len(names)}): "
                           f"{', '.join(names)}.", names=names)


def intent_about_vsgutu(scope: VectorScope, asked_name: str = "") -> Facts:
    from .knowledge import ANSWER_VSGUTU
    return Facts("about_vsgutu", ANSWER_VSGUTU)


def intent_about_college(scope: VectorScope, asked_name: str = "") -> Facts:
    from .knowledge import ANSWER_COLLEGE
    return Facts("about_college", ANSWER_COLLEGE)


def intent_hello(scope: VectorScope, asked_name: str = "") -> Facts:
    from .faq import hello_text
    return Facts("hello", hello_text(scope.role))


def intent_thanks(scope: VectorScope, asked_name: str = "") -> Facts:
    from .faq import thanks_text
    return Facts("thanks", thanks_text(scope.role))


def intent_unknown(scope: VectorScope, asked_name: str = "") -> Facts:
    """Вопрос не из пула. Текст здесь — фолбэк; engine может отдать вопрос LLM."""
    from .faq import unknown_offline_text
    return Facts("unknown", unknown_offline_text(scope.role))


#Классификатор намерения (локальный, без сети).
#Само сопоставление вынесено в faq.py: нормализация текста + словарь
#основ-синонимов. Благодаря этому «у кого хвосты», «кто завалил экзамен»
#и «у кого долги» дают ОДИН И ТОТ ЖЕ ответ без всякой LLM.
#Если суммарный вес совпадений ниже порога — интент «unknown», и engine
#передаёт вопрос живой ИИ-модели (если она подключена).
def classify(question: str, known_surnames: List[str]) -> Tuple[str, str]:
    """
    Возвращает (intent_name, asked_surname). Чисто локально, без сети.
    intent_name == "unknown" означает «вопроса нет в пуле» → дорога к LLM.
    """
    from .faq import classify_by_stems, normalize
    best, _score = classify_by_stems(question)
    q = normalize(question)
    asked = ""
    for surname in known_surnames:
        if not surname:
            continue
        s = surname.lower().replace("ё", "е")
        #сначала точное вхождение, затем основа (для склонений: Петрова, Сидоровой)
        if s in q:
            asked = surname
            break
        stem = s[:-1] if len(s) > 4 else s
        if stem and stem in q:
            asked = surname
            break
    return best, asked


_HANDLERS = {
    "debtors": intent_debtors,
    "absences": intent_absences,
    "at_risk": intent_at_risk,
    "average": intent_average,
    "group_stats": intent_group_stats,
    "grades": intent_grades,
    "groups": intent_groups,
    "teachers": intent_teachers,
    "roster": intent_roster,
    "about_vsgutu": intent_about_vsgutu,
    "about_college": intent_about_college,
    "hello": intent_hello,
    "thanks": intent_thanks,
    "help": intent_help,
    "unknown": intent_unknown,
}


def run_intent(intent: str, scope: VectorScope, asked_name: str = "") -> Facts:
    handler = _HANDLERS.get(intent, intent_help)
    return handler(scope, asked_name)
