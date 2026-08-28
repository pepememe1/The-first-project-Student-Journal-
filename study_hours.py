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
# вызывающий сам достаёт lessons/records и передаёт сюда, поэтому платформы не могут
# разойтись в подсчёте. Сейчас вызывающий один — `server/app/webdata.py`, и он же
# обслуживает журнал ВНУТРИ программы (десктоп поднимает то же серверное приложение на
# 127.0.0.1). Прежняя ссылка на второй, нативный вызывающий `ui/dashboards.py` устарела:
# нативных экранов нет с удаления Qt.
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


def subject_zet_state(lessons, records, zet, term_over: bool, scale: str = "5"):
    """Состояние предмета по ЗЕТ: "passed" | "pending" | "failed" | None (docs/PLAN-ZET.md §2).

    Три состояния, а не два (решение по варианту C, 26.08.2026 — купленный багом урок,
    см. CLAUDE.md): «ожидается» отделено от «не сдан».
      • "passed"  — предмет СДАН, ЗЕТ идут в зачёт;
      • "pending" — предмет ещё ИДЁТ («ожидается»): рубеж семестра не пройден, судить рано.
                    ЗЕТ НЕ засчитываются, но и не «сгорают» — показываются серым отдельно;
      • "failed"  — предмет ЗАВЕРШЁН, но НЕ сдан;
      • None      — zet не задан администратором (предмет нигде не участвует).

    `term_over` — пройден ли РУБЕЖ по этому предмету (его вычисляет вызывающий): архивный
    (не текущий) термин, ИЛИ пройдены плановые часы предмета. Экзамен — сам себе рубеж и
    обрабатывается независимо от `term_over`.

    Зачем «ожидается» вообще (баг Влада): у предмета БЕЗ экзамена критерий — средний по
    практике >= 3.0. Пока семестр идёт, ОДНА оценка «4» давала средний 4.0 >= 3.0 и весь
    предмет мгновенно засчитывался — «одна оценка, а пишет, будто весь семестр прошёл».
    Теперь до рубежа такой предмет «ожидается», а итог подводится, когда рубеж пройден.

    Критерий СДАЧИ (не изменился): экзамен — по ПОСЛЕДНЕЙ попытке (с учётом пересдач);
    без экзамена — средний по практике/ДЗ >= 3.0 через ЕДИНЫЙ grading.practice_average со
    шкалой ведущего преподавателя (не изобретаем свою проверку «5/4/3/Зачтено»)."""
    import grading
    if zet is None:
        return None
    exam = next((l for l in lessons if l.type == "Экзамен"), None)
    if exam is not None:
        val = grading.latest_exam_value(exam.id, records)
        if not val:
            # Экзамен в плане есть, но оценки ещё нет — он впереди, а не провален.
            return "pending"
        return "passed" if not grading.is_failed(val) else "failed"
    # Предмет без экзамена: пока рубеж не пройден — «ожидается» (вариант C), иначе итог.
    if not term_over:
        return "pending"
    avg = grading.practice_average(grading.pairs_from_objects(lessons), records, scale=scale)
    return "passed" if avg >= 3.0 else "failed"


def subject_zet_earned(lessons, records, zet, scale: str = "5", term_over: bool = True):
    """ЗЕТ по предмету, если студент его СДАЛ, иначе None. Тонкая обёртка над
    subject_zet_state для обратной совместимости: по умолчанию term_over=True (историческое
    поведение — подводить итог сразу), новый код передаёт настоящий term_over."""
    state = subject_zet_state(lessons, records, zet, term_over=term_over, scale=scale)
    return float(zet) if state == "passed" else None


def zet_summary(subject_rows) -> dict:
    """Сводка ЗЕТ студента за термин. subject_rows — [{"subject","zet","state"}], где state
    посчитан вызывающим через subject_zet_state (этот модуль не хранит занятий/оценок,
    только сводит готовые числа). Предметы без zet (None) в сводку не попадают — «ЗЕТ не
    задан» показывать нигде нельзя (docs/PLAN-ZET.md §10).

    `earned` — сумма ЗЕТ по СДАННЫМ предметам; `pending` — по «ожидающим» (семестр идёт).
    pending НЕ входит в earned (вариант C): засчитываем только пройденное, но показываем
    рядом серым, чтобы студент видел, сколько «в работе». В каждом subject — и `state`
    (новое, три состояния для UI), и `passed` (булево, для обратной совместимости с
    потребителями, читающими только его)."""
    rows = [r for r in subject_rows if r.get("zet") is not None]
    total = sum(r["zet"] for r in rows)
    earned = sum(r["zet"] for r in rows if r.get("state") == "passed")
    pending = sum(r["zet"] for r in rows if r.get("state") == "pending")
    subjects = [{"subject": r["subject"], "zet": r["zet"],
                 "earned": r["zet"] if r.get("state") == "passed" else 0.0,
                 "state": r.get("state") or "failed",
                 "passed": r.get("state") == "passed"} for r in rows]
    return {"earned": round(earned, 1), "total": round(total, 1),
            "pending": round(pending, 1),
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
            # «Не удовлетворяет» — именно ПРОВАЛЕННЫЕ (failed), а НЕ «ожидающие» (pending):
            # предмет, по которому семестр ещё идёт, — не проблема куратора, он просто не
            # закрыт. Мешать их значило бы пугать куратора красным на каждом идущем предмете.
            "unsatisfied": [x["subject"] for x in summ["subjects"] if x.get("state") == "failed"],
            "pending": [x["subject"] for x in summ["subjects"] if x.get("state") == "pending"],
            "subjects": summ["subjects"],
        })
    out.sort(key=lambda x: (x["eligible"], x["earned"]))
    return out
