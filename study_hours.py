"""
study_hours.py — ЕДИНЫЙ источник правды для учебных часов («пройдено X из Y»).

Живёт в КОРНЕ репозитория рядом с grading.py и vector_nlu.py и по той же причине: правило
нужно и десктопу (нативный журнал), и серверу (сайт, мобилка). Стоит его продублировать —
и платформы начнут показывать студенту разные цифры по одному и тому же предмету.

ПРАВИЛО ПОДСЧЁТА (решение заказчика, 3.1):
  • часы дают только ЛЕКЦИИ и ПРАКТИКИ. ДЗ — нет: домашняя работа делается вне аудитории;
  • одно занятие = пара = 2 академических часа.

⚠️ Считаем УНИКАЛЬНЫЕ пары (тип, номер), а НЕ строки таблицы занятий. Лекция хранится
ДВУМЯ строками (hour=1 и hour=2 — та же пара, разбитая по академическим часам, см.
core.GradeBook.add_lesson), практика — одной. Подсчёт по строкам дал бы лекции 2 часа, а
практике 1, то есть занижал бы практику ровно вдвое.

Плановые часы (Y) хранятся в таблице subject_hours и задаются администратором; здесь
только арифметика пройденного — план приходит из хранилища своей платформы.
"""
from collections.abc import Iterable

#Типы занятий, идущие в учебные часы.
HOUR_BEARING_TYPES = ("Лекция", "Практика")
#Академических часов в одном занятии (паре).
HOURS_PER_LESSON = 2


def hours_done_from_pairs(items: Iterable[tuple[str, int]]) -> int:
    """items — итерируемое из пар (тип занятия, номер). Возвращает пройденные часы."""
    seen = set()
    for ltype, number in items:
        if ltype in HOUR_BEARING_TYPES:
            seen.add((ltype, number))
    return len(seen) * HOURS_PER_LESSON


def hours_done(lessons) -> int:
    """Адаптер для объектов занятия (у сервера — models.Lesson, у десктопа — core.Lesson):
    оба имеют поля .type и .number."""
    return hours_done_from_pairs((l.type, l.number) for l in lessons)


def format_progress(done: int, total: int) -> str:
    """Подпись для шапки журнала. Пустая строка = «план не задан» — тогда интерфейс не
    показывает ничего. Рисовать «24 из 0» нельзя: это выглядит как ошибка данных, а
    придумывать план за администратора мы не вправе."""
    if not total:
        return ""
    return f"Пройдено {done} из {total} ч"


# ── ЗЕТ (зачётные единицы трудоёмкости, ФГОС) — docs/PLAN-ZET.md ────────────────────
# 1 ЗЕТ = 36 академических часов. Задаёт АДМИНИСТРАТОР вручную (та же строка, что и
# hours_total, см. models.SubjectHours.zet) — здесь только подсказка-автовычисление и
# арифметика «сдан ли предмет», НЕ трогаем grading.py (ЗЕТ на средний балл не влияют).
# Функции ЧИСТЫЕ (без обращения к БД) — тот же принцип, что и у hours_done_from_pairs:
# и сервер (webdata.py), и десктоп (ui/dashboards.py) сами достают lessons/records и
# передают сюда, поэтому платформы не могут разойтись в подсчёте.
ZET_HOURS = 36


def zet_hint(total_hours) -> float:
    """Автовычисление-подсказка для поля ЗЕТ в редакторе часов. НЕ источник правды —
    сохраняется только то, что явно подтвердил администратор."""
    return round((total_hours or 0) / ZET_HOURS, 1) if total_hours else 0.0


def course_and_semester(enrollment_year: int, term_year: str, term_semester: int) -> tuple:
    """(курс 1-4, семестр-с-начала-обучения 1-8) по году поступления и ТЕКУЩЕМУ
    учебному термину (`webdata.current_term()`/`data/terms.py`, формат термина —
    `"YYYY/YYYY+1"`, semester — 1|2). Считаем не календарными днями от даты
    поступления, а по этим же дискретным терминам, которыми уже устроена вся
    остальная система (SubjectHours.year/semester) — иначе получилась бы вторая,
    несовместимая система координат.

    Не валидируем результат: год поступления введён некорректно (например, в
    будущем) даст курс <1 или >4 — это сигнал администратору поправить дату, а не
    повод бросить исключение здесь."""
    years = int(str(term_year).split("/")[0]) - int(enrollment_year)
    course = years + 1
    overall_semester = years * 2 + int(term_semester)
    return course, overall_semester


def subject_zet_earned(lessons, records, zet, scale: str = "5"):
    """ЗЕТ по ОДНОМУ предмету (lessons — занятия ТОЛЬКО этого предмета за термин),
    если студент его СДАЛ, иначе None. zet=None (администратор не задавал) → всегда
    None — так вызывающий код по этому же флагу решает, показывать ли предмет вообще.

    Критерий сдачи (docs/PLAN-ZET.md §2): если у предмета есть занятие «Экзамен» —
    по ПОСЛЕДНЕЙ попытке (с учётом пересдач, как и everywhere в проекте); иначе —
    средний балл по практике/ДЗ >= 3.0 (используем ЕДИНЫЙ grading.practice_average
    с шкалой ведущего преподавателя — не изобретаем свою проверку "5/4/3/Зачтено")."""
    import grading
    if zet is None:
        return None
    exam = next((l for l in lessons if l.type == "Экзамен"), None)
    if exam is not None:
        val = grading.latest_exam_value(exam.id, records)
        passed = bool(val) and not grading.is_failed(val)
    else:
        avg = grading.practice_average(grading.pairs_from_objects(lessons), records, scale=scale)
        passed = avg >= 3.0
    return float(zet) if passed else None


def zet_summary(subject_rows) -> dict:
    """Сводка ЗЕТ студента за термин. subject_rows — [{"subject","zet","earned"}], где
    earned уже посчитан вызывающим кодом через subject_zet_earned (этот модуль не хранит
    занятий/оценок, только сводит готовые числа). Предметы без zet (None) в сводку не
    попадают — «ЗЕТ не задан» показывать нигде нельзя (docs/PLAN-ZET.md §10)."""
    rows = [r for r in subject_rows if r.get("zet") is not None]
    total = sum(r["zet"] for r in rows)
    earned = sum(r["earned"] for r in rows if r.get("earned") is not None)
    subjects = [{"subject": r["subject"], "zet": r["zet"], "earned": r.get("earned") or 0.0,
                "passed": r.get("earned") is not None} for r in rows]
    return {"earned": round(earned, 1), "total": round(total, 1),
            "pct": round(earned / total * 100, 1) if total else 0.0,
            "subjects": subjects}


def group_zet_report(students, min_zet) -> list:
    """Отчёт куратора для кнопки перевода на курс. students — [{"student_id",
    "display_name", "summary": <результат zet_summary()>}]. min_zet — порог
    (ZetThreshold.min_zet) или None (порог не задан — тогда все eligible).
    Сортировка: сначала НЕ готовые (eligible=False), внутри — по earned по возрастанию
    (меньше набравшие — выше, они нуждаются в внимании куратора в первую очередь).

    `subjects` в каждой строке — сырой per-subject список из zet_summary() (earned/zet
    по каждому предмету отдельно), а НЕ только агрегат earned/total: куратор выбирает
    ОДИН предмет в выпадающем списке над таблицей, и фронт сам достаёт из этого списка
    нужную пару без второго похода на сервер при переключении предмета."""
    out = []
    for s in students:
        summ = s["summary"]
        eligible = (min_zet is None) or (summ["earned"] >= min_zet)
        out.append({
            "student_id": s["student_id"], "display_name": s["display_name"],
            "earned": summ["earned"], "total": summ["total"], "pct": summ["pct"],
            "eligible": eligible,
            "missing_zet": round((min_zet or 0) - summ["earned"], 1) if not eligible else 0.0,
            "unsatisfied": [x["subject"] for x in summ["subjects"] if not x["passed"]],
            "subjects": summ["subjects"],
        })
    out.sort(key=lambda x: (x["eligible"], x["earned"]))
    return out
