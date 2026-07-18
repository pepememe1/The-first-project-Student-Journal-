"""
backfill_student_id.py — ЭТАП 2 миграции оценок с ФИО-ключей на неизменяемый student_id.

Что делает: у накопленных оценок (grades, term_grades) поле student_id пустое — их
записали до этапа 1. Скрипт находит для каждой строки студента по ФИО и проставляет id.

Зачем вообще: оценка ключуется по написанию ФИО. Студентка выходит замуж, админ правит
фамилию — история остаётся висеть на старом ключе. id строки users не меняется никогда.

ГЛАВНОЕ — не цифра «сматчилось», а СПИСОК несклеенных. Именно он решает, можно ли
переходить к этапу 3 (переключению первичного ключа): пока в нём есть живые оценки,
переключать нельзя — они потеряют владельца. Поэтому скрипт печатает каждую
неразрешённую строку с ПРИЧИНОЙ, а не просто счётчик.

По умолчанию — ХОЛОСТОЙ ПРОГОН (ничего не пишет). Запись только с --apply: это боевые
данные с ПДн студентов, и «посмотреть отчёт → потом решить» здесь единственный
разумный порядок.

    python backfill_student_id.py                     # отчёт, БД не трогаем
    python backfill_student_id.py --apply             # проставить id
    python backfill_student_id.py --report out.txt    # отчёт ещё и в файл

Идемпотентен: строки с уже заполненным student_id пропускаются, поэтому повторный
запуск безопасен и досчитывает только новое.

ВАЖНО: updated_at НЕ трогаем намеренно. Бампнуть метку значило бы объявить каждую
оценку изменённой — все клиенты выкачали бы всю базу заново, а серверная метка могла бы
перебить более свежую офлайн-правку на чьём-то ПК.

⚠️ Следствие: этот скрипт чинит ТОЛЬКО серверную базу. На десктопах student_id у старых
оценок останется пустым — по той же причине (без бампа метки дельта их не привезёт).
Десктопный бэкофилл ещё НЕ НАПИСАН, это следующая задача (правки делаем на обеих
платформах). До неё этап 3 не запускать: часть парка окажется без связи.
"""
import argparse
import sys
from collections import defaultdict

from app.db import SessionLocal, init_db
from app.models import Grade, Lesson, TermGrade, User


#Причины, по которым строка не склеилась. Текст идёт человеку в отчёт, поэтому
#формулировки — про то, ЧТО ДЕЛАТЬ, а не про внутренности кода.
REASON_NOT_FOUND = "студента с таким ФИО нет в справочнике"
REASON_AMBIGUOUS = "несколько студентов с одинаковым ФИО, группа не различила"
REASON_NO_GROUP = "занятие не найдено — не по чему различить однофамильцев"
#У итоговой оценки занятия нет вовсе, поэтому причина другая — иначе отчёт
#отправлял бы искать несуществующее занятие.
REASON_TERM_NO_GROUP = "однофамильцы, а у итоговой оценки нет группы для различения"


def _students_index(db):
    """(фамилия, имя) → список студентов. Надгробия пропускаем: привязывать живую
    оценку к удалённому аккаунту бессмысленно."""
    index = defaultdict(list)
    for u in db.query(User).filter(User.role == "student",
                                   User.deleted == False).all():  # noqa: E712
        index[((u.surname or "").strip(), (u.name or "").strip())].append(u)
    return index


def _resolve(candidates, group):
    """Список кандидатов + группа → (id, причина_отказа). id пустой = не склеилось.

    Однофамильцев с одинаковым именем разводим по группе, если она известна. Если и
    после этого их несколько — ОТКАЗЫВАЕМСЯ. Приписать оценку не тому студенту хуже,
    чем оставить строку на ФИО: второе чинится, первое молча портит данные."""
    if not candidates:
        return "", REASON_NOT_FOUND
    if len(candidates) == 1:
        return candidates[0].id, ""
    if not group:
        return "", REASON_NO_GROUP
    same_group = [u for u in candidates if (u.group_name or "").strip() == group]
    if len(same_group) == 1:
        return same_group[0].id, ""
    return "", REASON_AMBIGUOUS


def _scan_grades(db, index):
    """Оценки за занятия. Группу берём у ЗАНЯТИЯ — это и есть то, чем различаются
    однофамильцы (в одну группу двух полных тёзок не заводят)."""
    lesson_group = {l.id: (l.group_name or "").strip() for l in db.query(Lesson).all()}
    rows = db.query(Grade).filter((Grade.student_id == "") |
                                  (Grade.student_id.is_(None))).all()
    out = []
    for g in rows:
        f, n = (g.student_f or "").strip(), (g.student_n or "").strip()
        group = lesson_group.get(g.lesson_id, "")
        sid, reason = _resolve(index.get((f, n), []), group)
        out.append((g, f, n, group, sid, reason))
    return out


def _scan_term_grades(db, index):
    """Итоговые. Группы у них нет вовсе, поэтому однофамильцы тут неразрешимы в
    принципе — это ожидаемо и честно попадает в отчёт отдельной причиной."""
    rows = db.query(TermGrade).filter((TermGrade.student_id == "") |
                                      (TermGrade.student_id.is_(None))).all()
    out = []
    for t in rows:
        f, n = (t.student_f or "").strip(), (t.student_n or "").strip()
        sid, reason = _resolve(index.get((f, n), []), "")
        if reason == REASON_NO_GROUP:
            reason = REASON_TERM_NO_GROUP
        out.append((t, f, n, "", sid, reason))
    return out


def _report(lines, title, scanned):
    """Свод по одной таблице. Несклеенные группируем по ФИО — глазами читать список из
    трёх сотен одинаковых строк невозможно, а «Иванов Иван — 47 оценок» осмысленно."""
    matched = [r for r in scanned if r[4]]
    failed = [r for r in scanned if not r[4]]
    lines.append(f"\n{title}")
    lines.append(f"  без id до запуска : {len(scanned)}")
    lines.append(f"  сматчилось        : {len(matched)}")
    lines.append(f"  осталось по ФИО   : {len(failed)}")
    if not failed:
        return matched
    buckets = defaultdict(lambda: {"count": 0, "groups": set(), "live": 0})
    for row, f, n, group, _sid, reason in failed:
        b = buckets[(f, n, reason)]
        b["count"] += 1
        if group:
            b["groups"].add(group)
        if not row.deleted:
            b["live"] += 1
    lines.append("  НЕРАЗРЕШЁННЫЕ (глазами проверить, почему не склеились):")
    for (f, n, reason), b in sorted(buckets.items(), key=lambda kv: -kv[1]["count"]):
        groups = f", группы: {', '.join(sorted(b['groups']))}" if b["groups"] else ""
        #«живых» показываем отдельно: надгробия переключению ключа не мешают,
        #а живые оценки без владельца — прямой стоп-сигнал для этапа 3.
        lines.append(f"    · {f} {n} — строк: {b['count']} (живых: {b['live']}){groups}")
        lines.append(f"        причина: {reason}")
    return matched


def main() -> int:
    ap = argparse.ArgumentParser(description="Бэкофилл student_id (этап 2 миграции)")
    ap.add_argument("--apply", action="store_true",
                    help="записать изменения (без флага — только отчёт)")
    ap.add_argument("--report", metavar="ФАЙЛ", default="",
                    help="сохранить отчёт в файл (в консоль он печатается всегда)")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        index = _students_index(db)
        grades = _scan_grades(db, index)
        terms = _scan_term_grades(db, index)

        lines = ["=" * 70,
                 "БЭКОФИЛЛ student_id — этап 2 миграции оценок с ФИО-ключей",
                 "=" * 70,
                 f"студентов в справочнике: "
                 f"{sum(len(v) for v in index.values())}"]
        m1 = _report(lines, "ОЦЕНКИ ЗА ЗАНЯТИЯ (grades)", grades)
        m2 = _report(lines, "ИТОГОВЫЕ ОЦЕНКИ (term_grades)", terms)

        total_failed = len(grades) - len(m1) + len(terms) - len(m2)
        live_failed = sum(1 for r in grades + terms if not r[4] and not r[0].deleted)
        lines.append("\n" + "-" * 70)
        if args.apply:
            for row, _f, _n, _group, sid, _reason in m1 + m2:
                row.student_id = sid          #updated_at НЕ трогаем — см. докстринг
            db.commit()
            lines.append(f"ЗАПИСАНО: проставлен id у {len(m1) + len(m2)} строк.")
        else:
            lines.append(f"ХОЛОСТОЙ ПРОГОН: БД не изменялась. Записать — с флагом --apply "
                         f"(готово к записи: {len(m1) + len(m2)} строк).")
        if live_failed:
            lines.append(f"⚠️  ЖИВЫХ оценок без владельца: {live_failed}. "
                         f"Пока их не разобрать руками, ЭТАП 3 (переключение "
                         f"первичного ключа) запускать НЕЛЬЗЯ — они потеряют студента.")
        elif total_failed:
            lines.append(f"Неразрешёнными остались только надгробия ({total_failed}) — "
                         f"переключению ключа они не мешают.")
        else:
            lines.append("Все строки склеены — данные готовы к этапу 3.")
        lines.append("-" * 70)

        text = "\n".join(lines)
        print(text)
        if args.report:
            with open(args.report, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"\nОтчёт сохранён: {args.report}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
