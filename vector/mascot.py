"""
mascot.py — слой ЭМОЦИЙ маскота для «умного совета» на дашборде студента.

Это второй, НЕЗАВИСИМЫЙ от чата слой (см. mascot_emotion_prompt.md). В отличие от
анимации состояния чата (vector/speech.py — говорит/думает/ждёт/молчит), здесь
маскот показывает НАСТРОЕНИЕ по успеваемости и разовым событиям рядом с текстом
совета. Картинка — пара «эмоция (морда) + поза (жест)» из арт-матрицы Арины
(папка `emotes/` / `emotions/эмоции/`, загрузка через vector/emotes.py).

Состоит из трёх частей:
  1. resolveMascotState(data, events) — ЧИСТАЯ функция: по успеваемости и событиям
     возвращает (emotion, pose) по таблице приоритетов из ТЗ. Без побочных эффектов,
     легко тестируется.
  2. getMascotFrame(emotion, pose) — QPixmap кадра с фолбэком на «{emotion}+деф», а
     затем на «деф+деф», если конкретной комбинации в матрице нет.
  3. gather_student_data / detect_events — сбор фактов из журнала (оценки, тренд,
     посещаемость, экзамены, пересдачи) и разовый детект новых оценок через локальное
     хранилище (чтобы триггер срабатывал один раз, а не при каждом открытии дашборда).

⚠️ Эмоция маскота — ЧИСТО ВИЗУАЛЬНЫЙ слой поверх уже работающей логики совета: она
НЕ влияет на текст совета и не является источником правды для ИИ-промпта.
"""
from __future__ import annotations

from statistics import mean

from . import emotes

#Шесть эмоций лица и пять поз тела (ключи = части имени файла, см. emotes.py).
EMOTIONS = ("груст", "деф", "думает", "предупреж", "рад", "удив")
POSES = ("деф", "думает", "подбадрив", "поздрав", "предупреж")
DEFAULT_POSE = "деф"

#Порог «резкого скачка» для приоритета 3 (удивление).
SURPRISE_DELTA = 1.5
#Порог посещаемости, ниже которого маскот предупреждает (в процентах).
ATTENDANCE_WARN = 70.0
#Насколько средний за «последние N» должен отличаться от «предыдущих N», чтобы
#считать тренд растущим/падающим (иначе — стабильно).
TREND_EPS = 0.15


#  1. Загрузка кадра (эмоция + поза) с фолбэком
def getMascotFrame(emotion: str, pose: str = DEFAULT_POSE):
    """QPixmap кадра (эмоция, поза). Фолбэк: «{emotion}+деф» → «деф+деф» → None.

    Не все 30 комбинаций существуют — если конкретной пары нет, спускаемся к
    дефолтной позе той же эмоции, а в крайнем случае к нейтральному «деф+деф»."""
    pm = emotes.get(emotion, pose)
    if pm is not None and not pm.isNull():
        return pm
    if pose != DEFAULT_POSE:
        pm = emotes.get(emotion, DEFAULT_POSE)
        if pm is not None and not pm.isNull():
            return pm
    pm = emotes.get(emotes.DEFAULT_FACE, emotes.DEFAULT_GESTURE)
    return pm if (pm is not None and not pm.isNull()) else None


#  2. Чистая функция решения эмоции
def _trend(recent: list) -> str:
    """Тренд успеваемости по списку числовых оценок в хронологическом порядке.

    Сравниваем средний за последние N с предыдущими N (N≤5). 'up' / 'down' / 'flat'."""
    vals = [v for v in (recent or []) if isinstance(v, (int, float))]
    if len(vals) < 2:
        return "flat"
    k = min(5, len(vals) // 2)
    last = vals[-k:]
    prev = vals[-2 * k:-k]
    if not prev:
        return "flat"
    a, b = mean(last), mean(prev)
    if a > b + TREND_EPS:
        return "up"
    if a < b - TREND_EPS:
        return "down"
    return "flat"


def resolveMascotState(data: dict, events=None) -> dict:
    """Возвращает {'emotion','pose'} по успеваемости и разовым событиям.

    Приоритеты (сверху вниз, первое совпадение побеждает):
      П1 — разовые события и срочные условия (новые оценки, экзамен ≤3 дней, пересдача);
      П3 — «удивление» при резком скачке последней оценки (перекрывает П2, не П1);
      П2 — общий тренд успеваемости и посещаемость.
    Подробности соответствия — в mascot_emotion_prompt.md.
    """
    events = list(events or [])
    data = data or {}

    #  Приоритет 1 — события/срочные условия (порядок как в таблице ТЗ)
    if "grade_5" in events:
        return _st("рад", "поздрав")
    if "grade_4" in events:
        return _st("рад", "думает")
    if "grade_2" in events:          # новая «2» или «Н»
        return _st("груст", "предупреж")
    if "grade_3" in events:
        return _st("деф", "думает")
    if data.get("exam_soon"):        # экзамен/зачёт через ≤3 дня
        return _st("предупреж", "думает")
    if data.get("retake_scheduled"):
        return _st("груст", "думает")
    if data.get("retake_passed"):
        return _st("рад", "подбадрив")

    avg = data.get("average") or 0.0
    has_data = bool(data.get("has_data"))
    last = data.get("last_grade")

    #  Приоритет 3 — резкий скачок последней оценки → удивление
    if has_data and last is not None and avg and abs(last - avg) > SURPRISE_DELTA:
        return _st("удив", "думает")

    #  Приоритет 2 — посещаемость и тренд
    att = data.get("attendance_pct")
    if att is not None and att < ATTENDANCE_WARN:   # независимо от баллов
        return _st("предупреж", "предупреж")
    if not has_data:                                # новый ученик, данных нет
        return _st("удив", "деф")

    trend = data.get("trend") or _trend(data.get("recent", []))
    if avg >= 4.5:
        return _st("рад", "деф")
    if 3.5 <= avg < 4.5:
        return _st("рад", "подбадрив") if trend == "up" else _st("деф", "деф")
    if 2.5 <= avg < 3.5:
        return _st("деф", "подбадрив") if trend == "up" else _st("предупреж", "деф")
    if avg < 2.5:
        return _st("груст", "предупреж")
    return _st("деф", "деф")


def _st(emotion: str, pose: str) -> dict:
    return {"emotion": emotion, "pose": pose}


#  3. Сбор фактов из журнала + разовый детект событий
def _student_key(stud: dict) -> str:
    return f"{stud.get('f','')}|{stud.get('n','')}|{stud.get('g','')}".strip().lower()


def _parse_date(s: str):
    """Дата занятия в формате %d.%m.%Y → datetime.date (или None)."""
    from datetime import datetime
    try:
        return datetime.strptime((s or "").strip(), "%d.%m.%Y").date()
    except Exception:
        return None


def gather_student_data(stud: dict) -> tuple:
    """Собирает факты по студенту для эмоции маскота из ЛОКАЛЬНОГО журнала.

    Возвращает (data, signature):
      • data — словарь для resolveMascotState (average, recent, trend, last_grade,
        attendance_pct, exam_soon, retake_scheduled, retake_passed, has_data);
      • signature — {subject|lesson_id: оценка} текущего состояния оценок, для
        разового детекта новых оценок (detect_events).

    Цифры берём строго из журнала (как и весь Вектор), офлайн. Любая ошибка по
    конкретному предмету не должна ронять подсказку — оборачиваем в try/except.
    """
    from datetime import date
    from grading import lead_num

    group = stud.get("g", "")
    surname = (stud.get("f", "") or "").strip().lower()

    graded = []          # (date|None, value:float) — практики с числовой оценкой
    attended = absent = 0
    exam_soon = retake_scheduled = retake_passed = False
    signature = {}
    today = date.today()

    subjects = _subjects_for_group(group)
    for subj in subjects:
        try:
            book = _gradebook(group, subj)
        except Exception:
            continue
        st = next((x for x in book.spisok_stud
                   if (x.f or "").strip().lower() == surname), None)
        if st is None:
            continue
        recs = st.records or {}
        for l in book.lessons:
            v = recs.get(l.id)
            if v:
                signature[f"{subj}|{l.id}"] = v
            if l.type == "Практика":
                num = lead_num(v) if v else None
                if num is not None:
                    graded.append((_parse_date(l.date), num))
                    attended += 1
                elif v == "Н":
                    absent += 1
            elif l.type in ("Экзамен", "Зачёт"):
                d = _parse_date(l.date)
                if d is not None and 0 <= (d - today).days <= 3:
                    exam_soon = True
            #пересдача: назначена дата пересдачи
            if getattr(l, "retake_date", ""):
                retake_scheduled = True
                #если по экзамену есть пересдачная оценка и она проходная — «сдал»
                for key in (f"{l.id}_retake", f"{l.id}_retake_2"):
                    rv = lead_num(recs.get(key, "")) if recs.get(key) else None
                    if rv is not None and rv >= 3:
                        retake_passed = True
                        retake_scheduled = False

    #хронологический порядок оценок для тренда (по дате, неизвестные даты — в конец)
    graded.sort(key=lambda t: (t[0] is None, t[0] or today))
    recent = [v for _, v in graded]
    total = attended + absent
    data = {
        "average": round(mean(recent), 2) if recent else 0.0,
        "recent": recent,
        "trend": _trend(recent),
        "last_grade": recent[-1] if recent else None,
        "attendance_pct": (attended / total * 100.0) if total else None,
        "exam_soon": exam_soon,
        "retake_scheduled": retake_scheduled,
        "retake_passed": retake_passed,
        "has_data": bool(recent) or total > 0,
    }
    return data, signature


def detect_events(stud: dict, signature: dict, mark_seen: bool = True) -> list:
    """Сравнивает текущие оценки с «увиденными» и возвращает список новых событий.

    Типы: 'grade_5' / 'grade_4' / 'grade_3' / 'grade_2' (последнее — для «2» и «Н»).
    Срабатывает ОДИН раз: после вычисления сохраняем новую отметку «увидено»
    (mark_seen=True), поэтому при повторном открытии дашборда событие не повторится.
    Хранилище — локальное зашифрованное (per-account, не синхронизируется)."""
    key = f"mascot_seen:{_student_key(stud)}"
    prev = {}
    try:
        import data_store
        prev = data_store.local_get(key, {}) or {}
    except Exception:
        prev = {}

    events = []
    #первый запуск (prev пуст) НЕ считаем за «новые оценки» — иначе при первом входе
    #вспыхнули бы все события скопом; просто запоминаем текущее состояние.
    if prev:
        for sig_key, val in signature.items():
            if prev.get(sig_key) != val:
                ev = _grade_event(val)
                if ev:
                    events.append(ev)

    if mark_seen:
        try:
            import data_store
            data_store.local_set(key, signature)
        except Exception:
            pass
    return events


def _grade_event(value: str) -> str:
    """Тип события по новой оценке ('5'→grade_5, '2'/'Н'→grade_2 и т.д.)."""
    v = (value or "").strip()
    head = v.split()[0] if v else ""
    if head == "5":
        return "grade_5"
    if head == "4":
        return "grade_4"
    if head == "3":
        return "grade_3"
    if head == "2" or v == "Н":
        return "grade_2"
    return ""


#Ленивые обёртки над тяжёлыми импортами проекта (чтобы vector.mascot можно было
#импортировать и тестировать без полной инициализации GUI/БД).
def _subjects_for_group(group: str) -> list:
    from utils import get_subjects_for_group
    return get_subjects_for_group(group)


def _gradebook(group: str, subject: str):
    from core import GradeBook
    return GradeBook(group, subject)
