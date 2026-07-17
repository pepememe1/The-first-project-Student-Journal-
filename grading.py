"""
grading.py — ЕДИНЫЙ источник правды для расчёта среднего балла.

Раньше формула жила в двух местах (core.GradeBook.calculate_average и
vector/intents._practice_average) и могла разойтись. Теперь обе считают через
этот модуль — расхождение исключено по построению.

МЕТОДИКА (документируется здесь и в подсказках интерфейса):
  • Средний балл считается по занятиям типа «Практика», у которых проставлена
    числовая оценка 2–5.
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
from typing import Dict, Iterable, List, Optional, Tuple

PRACTICE_VALUES = {"2", "3", "4", "5"}

# Дефолты методики (прежнее поведение: Н=2.0, экзамены не входят)
DEFAULTS = {
    "avg_absence_weight": 2.0,
    "avg_count_absence": True,
    "avg_include_exam": False,
}

METHODOLOGY_TEXT = (
    "Средний балл считается по практикам с оценкой 2–5. "
    "Пропуск «Н» учитывается как {w} балла{cnt}. "
    "Экзамены {exam} входят в средний{exam_note}."
)


def avg_config(cfg: Optional[dict]) -> dict:
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


def methodology_text(cfg: Optional[dict] = None) -> str:
    c = avg_config(cfg)
    return METHODOLOGY_TEXT.format(
        w=c["avg_absence_weight"],
        cnt="" if c["avg_count_absence"] else " (если пропуск считается; сейчас — нет)",
        exam="" if c["avg_include_exam"] else "НЕ ",
        exam_note=" (по последней попытке с учётом пересдач)" if c["avg_include_exam"] else "",
    )


def lead_num(val: str) -> Optional[float]:
    """Числовая оценка из строки вида '4 (Зачтено)' → 4.0; иначе None."""
    if not val:
        return None
    head = val.strip().split()[0] if val.strip() else ""
    return float(head) if head in PRACTICE_VALUES else None


def latest_exam_value(lesson_id: str, records: Dict[str, str]) -> str:
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


def practice_average(items: Iterable[Tuple[str, str]],
                     records: Dict[str, str],
                     cfg: Optional[dict] = None) -> float:
    """
    items — итерируемое из пар (lesson_id, lesson_type).
    records — {lesson_id|retake_key: оценка}.
    cfg — config (методика). Возвращает средний балл, округлённый до 2 знаков.
    """
    c = avg_config(cfg)
    total, count = 0.0, 0
    for lid, ltype in items:
        if ltype == "Практика":
            v = records.get(lid)
            num = lead_num(v) if v else None
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


def pairs_from_objects(lessons) -> List[Tuple[str, str]]:
    """Адаптер для core.Lesson: [(l.id, l.type), ...]."""
    return [(l.id, l.type) for l in lessons]


def pairs_from_rows(rows) -> List[Tuple[str, str]]:
    """Адаптер для строк intents (lid, ltype, ...): [(lid, ltype), ...]."""
    return [(r[0], r[1]) for r in rows]
