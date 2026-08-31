"""
grading.py — ЕДИНЫЙ источник правды для расчёта среднего балла.

Раньше формула жила в двух местах (в удалённом ныне core.GradeBook.calculate_average и
vector/intents._practice_average) и могла разойтись. Теперь обе считают через
этот модуль — расхождение исключено по построению.

МЕТОДИКА (документируется здесь и в подсказках интерфейса):
  • Средний балл считается по занятиям типа «Практика» и «ДЗ» (см. PRACTICE_TYPES),
    у которых проставлена числовая оценка 2–5.
  • Пропуск «Н» на практике учитывается как балл `avg_absence_weight`
    (по умолчанию 2.0), ЕСЛИ включён `avg_count_absence` (по умолчанию да).
    Это настраивается: вуз может решить, что пропуск НЕ занижает средний.
  • Экзамены по умолчанию в средний НЕ входят (`avg_include_exam` = False).
    Если включить — каждый экзамен даёт балл ПОСЛЕДНЕЙ попытки (с учётом
    пересдач): заваленная, но позже пересданная попытка считается как пересдача,
    а не как первоначальная двойка. Это убирает риск «средний по заваленной
    первой попытке».

Все параметры читаются из config (kv_store['config']) с безопасными дефолтами,
поэтому при отсутствии настроек поведение в точности прежнее.
"""
from collections.abc import Callable, Iterable
from typing import TypedDict

PRACTICE_VALUES = {"2", "3", "4", "5"}

#Типы занятий, оценка за которые идёт в средний балл НАРАВНЕ с практикой.
#«ДЗ» добавлено в 3.1 по решению заказчика: домашняя работа оценивается теми же 2–5 и
#влияет на успеваемость так же, как практическая. Набор живёт ЗДЕСЬ по той же причине,
#что и сама формула: тип занятия проверяется ещё в долгах, пропусках и ответах Вектора,
#и семь разрозненных сравнений с литералом «Практика» неизбежно разъехались бы.
PRACTICE_TYPES = ("Практика", "ДЗ")


def is_practice(lesson_type: str) -> bool:
    """Оценивается ли занятие «как практика» (2–5, идёт в средний балл)."""
    return lesson_type in PRACTICE_TYPES

#Дефолты методики (прежнее поведение: Н=2.0, экзамены не входят)
DEFAULTS = {
    "avg_absence_weight": 2.0,
    "avg_count_absence": True,
    "avg_include_exam": False,
}

METHODOLOGY_TEXT = (
    "Средний балл считается по практикам и домашним заданиям с оценкой 2–5. "
    "Пропуск «Н» учитывается как {w} балла{cnt}. "
    "Экзамены {exam} входят в средний{exam_note}."
)


def avg_config(cfg: dict | None) -> dict:
    """Достаёт параметры методики из config с дефолтами."""
    cfg = cfg or {}
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in cfg and cfg[k] is not None:
            out[k] = cfg[k]
    try:
        out["avg_absence_weight"] = float(out["avg_absence_weight"])
    except (TypeError, ValueError):
        out["avg_absence_weight"] = 2.0
    out["avg_count_absence"] = bool(out["avg_count_absence"])
    out["avg_include_exam"] = bool(out["avg_include_exam"])
    return out


def methodology_text(cfg: dict | None = None) -> str:
    c = avg_config(cfg)
    return METHODOLOGY_TEXT.format(
        w=c["avg_absence_weight"],
        cnt="" if c["avg_count_absence"] else " (если пропуск считается; сейчас — нет)",
        exam="" if c["avg_include_exam"] else "НЕ ",
        exam_note=" (по последней попытке с учётом пересдач)" if c["avg_include_exam"] else "",
    )


def lead_num(val: str) -> float | None:
    """Числовая оценка из строки вида '4 (Зачтено)' → 4.0; иначе None."""
    if not val:
        return None
    head = val.strip().split()[0] if val.strip() else ""
    return float(head) if head in PRACTICE_VALUES else None


def is_failed(grade: str) -> bool:
    """Считается ли оценка ЗАВАЛЕННОЙ (нужна пересдача).

    ЕДИНЫЙ источник правды для мест, где это раньше дублировалось инлайном: сервер
    (`webdata.debts`, он же обслуживает журнал ВНУТРИ программы) и веб/мобилка
    (`web/src/utils/grades.js` — точный порт). Третьим был нативный десктопный журнал,
    но нативных экранов нет с удаления Qt — десктоп показывает ту же SPA.
    Правило: непусто И (начинается с «2» или «Н») ЛИБО содержит «Не зачтено».
    Пороговые случаи закреплены контрактом docs/contracts/grade-cases.json (парные тесты
    Python и JS) — молчаливое расхождение реализаций больше невозможно."""
    v = (grade or "").strip()
    return bool(v) and (v.startswith(("2", "Н")) or "Не зачтено" in v)


def attempt_key(lesson_id: str, ri: int) -> str:
    """Ключ записи попытки №ri по экзамену: 0 — основной (lesson_id), 1 — <id>_retake,
    2+ — <id>_retake_N. Единый формат для десктопа и веба (закреплён контрактом)."""
    if ri <= 0:
        return lesson_id
    return lesson_id + ("_retake" if ri == 1 else f"_retake_{ri}")


def needs_retake(records: dict[str, str], lesson_id: str, ri: int) -> bool:
    """Нужна ли студенту пересдача №ri: либо у него уже проставлена оценка за эту
    попытку (показываем существующее), либо ПРЕДЫДУЩАЯ попытка завалена (is_failed).
    Единый источник для сервера (он же питает журнал внутри программы) и веба
    (`grades.js::needsRetake`) — закреплён контрактом docs/contracts/grade-cases.json
    (парные тесты Python/JS)."""
    if records.get(attempt_key(lesson_id, ri)):
        return True
    return is_failed(records.get(attempt_key(lesson_id, ri - 1), ""))


def latest_exam_value(lesson_id: str, records: dict[str, str]) -> str:
    """
    Последняя попытка по экзамену с учётом пересдач:
    база → <id>_retake → <id>_retake_2 → ... Возвращает «сырую» строку оценки.
    """
    val = records.get(lesson_id, "")
    i = 1
    while True:
        key = f"{lesson_id}_retake" if i == 1 else f"{lesson_id}_retake_{i}"
        if records.get(key):
            val = records[key]
            i += 1
        else:
            break
    return val


def practice_average(items: Iterable[tuple[str, str]],
                     records: dict[str, str],
                     cfg: dict | None = None,
                     scale="5") -> float:
    """
    items — итерируемое из пар (lesson_id, lesson_type).
    records — {lesson_id|retake_key: оценка}.
    cfg — config (методика). scale — шкала преподавателя, ведущего эти занятия (§ролей,
    3.3.1) — сырое значение оценки конвертируется в 5-балльное ПЕРЕД суммированием
    (to_five_point), поэтому средний ВСЕГДА в привычной 5-балльной, независимо от того,
    в чём препод вводил (100-балльная/буквенная/...). scale="5" (умолчание) даёт
    результат бит-в-бит как раньше — to_five_point(v, "5") это lead_num(v).
    scale может быть СТРОКОЙ (одна шкала на все items — журнал одного предмета, где
    препод один) либо СЛОВАРЁМ {lesson_id: scale} — нужен там, где items смешивает
    занятия РАЗНЫХ предметов/преподавателей разом (общий средний студента/группы по
    всем предметам), и каждое занятие может вести препод со своей шкалой.
    Возвращает средний балл, округлённый до 2 знаков.
    """
    c = avg_config(cfg)
    total, count = 0.0, 0
    scale_map = scale if isinstance(scale, dict) else None
    for lid, ltype in items:
        if is_practice(ltype):
            v = records.get(lid)
            lscale = scale_map.get(lid, DEFAULT_SCALE) if scale_map is not None else scale
            num = to_five_point(v, lscale) if v else None
            if num is not None:
                total += num
                count += 1
            elif v == "Н" and c["avg_count_absence"]:
                total += c["avg_absence_weight"]
                count += 1
        elif ltype == "Экзамен" and c["avg_include_exam"]:
            v = latest_exam_value(lid, records)
            num = lead_num(v) if v else None
            if num is not None:
                total += num
                count += 1
    return round(total / count, 2) if count else 0.0


def pairs_from_objects(lessons) -> list[tuple[str, str]]:
    """Адаптер для объектов занятия с полями .id/.type: [(l.id, l.type), ...]."""
    return [(l.id, l.type) for l in lessons]


# ── Кастомные шкалы оценок (§ролей, 3.3.1) ──────────────────────────────────────────
# Каждый преподаватель может выбрать СВОЮ шкалу ввода/просмотра (User.prefs
# ["grading_scale"], self-service, как тема/цвет плашки). "5" — умолчание и ведёт себя
# БУКВА В БУКВУ как раньше (identity через уже существующий lead_num) — препод, ничего
# не выбравший, не заметит разницы. Средний балл/итоговая — ВСЕГДА в переводе на
# 5-балльную (см. practice_average(scale=...)), чтобы сохранить сопоставимость между
# преподавателями/предметами, статистику и ответы Вектора едиными.
#
# Экзамены/пересдачи НЕ переводятся на кастомные шкалы (осознанное сужение объёма):
# у них уже есть свой toggle (avg_include_exam) и своя семантика зачёта/пересдачи,
# смешивать её с произвольной шкалой — отдельная задача с открытыми вопросами
# («что значит "3 (пересдача)" на буквенной шкале?»), не блокирующая эту.

DEFAULT_SCALE = "5"


def _is_failed_5(raw: str) -> bool:
    return is_failed(raw)


def _to_five_100(raw: str) -> float | None:
    """0..100 → 5-балльная: пороги 90/75/60 (стандартная вузовская привязка)."""
    if not raw:
        return None
    head = raw.strip().split()[0] if raw.strip() else ""
    try:
        n = float(head)
    except ValueError:
        return None
    if not (0 <= n <= 100):
        return None
    if n >= 90:
        return 5.0
    if n >= 75:
        return 4.0
    if n >= 60:
        return 3.0
    return 2.0


def _is_failed_100(raw: str) -> bool:
    v = _to_five_100(raw)
    return v is not None and v <= 2.0


_LETTER_TO_FIVE = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "F": 2.0}


def _to_five_letter(raw: str) -> float | None:
    if not raw:
        return None
    head = raw.strip().split()[0].upper() if raw.strip() else ""
    return _LETTER_TO_FIVE.get(head)


def _is_failed_letter(raw: str) -> bool:
    if not raw:
        return False
    head = raw.strip().split()[0].upper() if raw.strip() else ""
    return head in ("D", "F")


def _to_five_pass_fail(raw: str) -> float | None:
    #Зачёт/незачёт в числовой средний не входит вовсе — та же логика, что у экзаменов
    #с выключенным avg_include_exam: это статус, а не балл.
    return None


def _is_failed_pass_fail(raw: str) -> bool:
    v = (raw or "").strip().lower()
    return v.startswith("не") or v.startswith("незач")


class Scale(TypedDict):
    """Одна шкала оценивания преподавателя.

    Тип описан ЯВНО, а не выведен: без него mypy видел значения словаря как `object` и
    честно ругался на `SCALES[...]["to_five"](x)` — «object not callable» (три из трёх
    ошибок проверки типов во всём allowlist приходились на это место). Заглушить их
    через `Any` было бы дешевле, но тогда подмена функции конвертации на функцию с
    другой сигнатурой прошла бы молча — а это ровно та ошибка, из-за которой средний
    балл разъезжается между платформами.
    """
    label: str
    values: tuple[str, ...]
    to_five: Callable[[str], float | None]
    is_failed: Callable[[str], bool]


#Реестр шкал: values — допустимые сырые значения (для селектора ввода оценки), to_five/
#is_failed — функции конвертации. Ключ — то же значение, что хранится в User.prefs
#["grading_scale"].
SCALES: dict[str, Scale] = {
    "5": {
        "label": "5-балльная",
        "values": ("2", "3", "4", "5"),
        "to_five": lead_num,
        "is_failed": _is_failed_5,
    },
    "100": {
        "label": "100-балльная",
        "values": tuple(str(i) for i in range(0, 101)),
        "to_five": _to_five_100,
        "is_failed": _is_failed_100,
    },
    "letter": {
        "label": "Буквенная (A–F)",
        "values": ("A", "B", "C", "D", "F"),
        "to_five": _to_five_letter,
        "is_failed": _is_failed_letter,
    },
    "pass_fail": {
        "label": "Зачёт / незачёт",
        "values": ("Зачтено", "Не зачтено"),
        "to_five": _to_five_pass_fail,
        "is_failed": _is_failed_pass_fail,
    },
}


def scale_values(scale: str = DEFAULT_SCALE) -> tuple:
    """Допустимые сырые значения шкалы — для UI-селектора ввода оценки."""
    return SCALES.get(scale, SCALES[DEFAULT_SCALE])["values"]


#Метки посещаемости — они не часть шкалы, но живут в том же поле оценки.
#⚠️ «О» — ОПОЗДАЛ (3.7.6), а не «уважительная причина»; в пропуски не идёт
#(см. server/app/webdata.py::absences).
ATTENDANCE_VALUES = ("✓", "Н", "Б", "О")

#Разумный потолок длины. Поле уезжает в xlsx, docx и отчёт куратора; ничего осмысленного
#длиннее «Не зачтено» там быть не может, а 500 символов — это уже порча вёрстки отчёта.
MAX_GRADE_LEN = 32


def is_allowed_value(raw_value: str) -> bool:
    """Можно ли вообще записать такое значение в поле оценки.

    Проверяем по ОБЪЕДИНЕНИЮ всех шкал, а не по шкале конкретного преподавателя, и это
    осознанно: шкала — настройка, которая меняется, а отказ записать законную оценку
    ломает работу человеку, который ни в чём не виноват. Задача проверки скромнее —
    не пустить в журнал то, что не является оценкой ни в одной шкале («Ништяк», HTML,
    строка на 500 символов). Пустая строка разрешена: это СНЯТИЕ оценки.

    Составные значения вида «5 (Зачтено)» принимаются по первому слову — они уже лежат
    в базах, и отвергать их значило бы сломать правку старых записей."""
    v = (raw_value or "").strip()
    if not v:
        return True
    if len(v) > MAX_GRADE_LEN:
        return False
    allowed = set(ATTENDANCE_VALUES)
    for meta in SCALES.values():
        allowed.update(meta["values"])
    return v in allowed or v.split()[0] in allowed


def to_five_point(raw_value: str, scale: str = DEFAULT_SCALE) -> float | None:
    """Сырое значение оценки (в ШКАЛЕ ПРЕПОДА) → 5-балльный эквивалент для среднего/
    итоговой. None — значение не распознано этой шкалой (не считается)."""
    fn = SCALES.get(scale, SCALES[DEFAULT_SCALE])["to_five"]
    return fn(raw_value)


def is_failed_scaled(raw_value: str, scale: str = DEFAULT_SCALE) -> bool:
    """Провалена ли оценка — версия is_failed(), учитывающая шкалу препода."""
    fn = SCALES.get(scale, SCALES[DEFAULT_SCALE])["is_failed"]
    return fn(raw_value)
