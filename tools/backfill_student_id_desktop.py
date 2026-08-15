"""
backfill_student_id_desktop.py — ЭТАП 2 миграции, сторона ДЕСКТОПА (ручной прогон).

Тонкая обёртка над data/student_link.py: сама логика сопоставления живёт В ПРИЛОЖЕНИИ,
потому что доклеивать id десктоп обязан САМ (скрипты из tools/ не попадают в .exe, а
преподаватель в колледже не станет запускать python руками — см. sync_runner, там
student_link.backfill_quietly() зовётся после каждого удачного синка).

Этот скрипт нужен для ДИАГНОСТИКИ: он печатает подробный отчёт со списком несклеенных
ФИО и причинами — то, что фоновая до-клейка молча не показывает.

Запуск ИЗ КОРНЯ репозитория (оттуда резолвятся пакеты `data`/`sync`; модуля
`_bootstrap`, который когда-то подкладывал их в sys.path, больше нет):

    python tools/backfill_student_id_desktop.py                  # отчёт, БД не трогаем
    python tools/backfill_student_id_desktop.py --apply          # проставить id
    python tools/backfill_student_id_desktop.py --report out.txt # отчёт ещё и в файл

По умолчанию — ХОЛОСТОЙ ПРОГОН. Идемпотентен: заполненные строки пропускаются.
"""
import argparse
import os
import sys
from collections import defaultdict
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import student_link as SL  # noqa: E402
from data.core import DBManager, LOCAL_DB  # noqa: E402


def _report(lines: list, title: str, scanned: list) -> list:
    """Свод по одной таблице. Несклеенные группируем по ФИО: читать глазами триста
    одинаковых строк невозможно, а «Иванов Иван — 47 строк» осмысленно."""
    matched = [r for r in scanned if r[4]]
    failed = [r for r in scanned if not r[4]]
    lines.append(f"\n{title}")
    lines.append(f"  без id до запуска : {len(scanned)}")
    lines.append(f"  сматчилось        : {len(matched)}")
    lines.append(f"  осталось по ФИО   : {len(failed)}")
    if not failed:
        return matched
    buckets = defaultdict(lambda: {"count": 0, "groups": set(), "live": 0})
    for _key, f, n, group, _sid, reason, deleted in failed:
        b = buckets[(f, n, reason)]
        b["count"] += 1
        if group:
            b["groups"].add(group)
        if not deleted:
            b["live"] += 1
    lines.append("  НЕРАЗРЕШЁННЫЕ (глазами проверить, почему не склеились):")
    for (f, n, reason), b in sorted(buckets.items(), key=lambda kv: -kv[1]["count"]):
        groups = f", группы: {', '.join(sorted(b['groups']))}" if b["groups"] else ""
        #«живых» считаем отдельно: надгробия переключению ключа не мешают, а живая
        #оценка без владельца — прямой стоп-сигнал для этапа 3.
        lines.append(f"    · {f} {n} — строк: {b['count']} (живых: {b['live']}){groups}")
        lines.append(f"        причина: {reason}")
    return matched


def run(apply: bool = False) -> tuple:
    """Считает (и при apply=True проставляет) id. Возвращает (текст_отчёта, записано)."""
    index = SL.students_index()
    with closing(DBManager.get_conn()) as conn:
        grades, terms = SL.scan(conn, index)
        lines = ["=" * 70,
                 "БЭКОФИЛЛ student_id (ДЕСКТОП) — этап 2 миграции с ФИО-ключей",
                 "=" * 70,
                 f"студентов в справочнике: {sum(len(v) for v in index.values())}",
                 f"локальная база: {LOCAL_DB}"]
        m1 = _report(lines, "ОЦЕНКИ ЗА ЗАНЯТИЯ (grades)", grades)
        m2 = _report(lines, "ИТОГОВЫЕ ОЦЕНКИ (term_grades)", terms)

        written = 0
        lines.append("\n" + "-" * 70)
        if apply:
            written = SL.apply_matches(conn, grades, terms)
            lines.append(f"ЗАПИСАНО: проставлен id у {written} строк.")
        else:
            lines.append(f"ХОЛОСТОЙ ПРОГОН: БД не изменялась. Записать — с флагом --apply "
                         f"(готово к записи: {len(m1) + len(m2)} строк).")

        live_failed = sum(1 for r in grades + terms if not r[4] and not r[6])
        total_failed = sum(1 for r in grades + terms if not r[4])
        if live_failed:
            lines.append(f"⚠️  ЖИВЫХ оценок без владельца: {live_failed}. Пока их не "
                         f"разобрать руками, ЭТАП 3 (переключение первичного ключа) "
                         f"запускать НЕЛЬЗЯ — они потеряют студента.")
        elif total_failed:
            lines.append(f"Неразрешёнными остались только надгробия ({total_failed}) — "
                         f"переключению ключа они не мешают.")
        else:
            lines.append("Все строки склеены — эта машина готова к этапу 3.")
        lines.append("-" * 70)
        return "\n".join(lines), written


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Бэкофилл student_id на десктопе (этап 2 миграции)")
    ap.add_argument("--apply", action="store_true",
                    help="записать изменения (без флага — только отчёт)")
    ap.add_argument("--report", metavar="ФАЙЛ", default="",
                    help="сохранить отчёт в файл (в консоль он печатается всегда)")
    args = ap.parse_args()

    DBManager.init()
    #Бэкап ПЕРЕД записью: скрипт правит боевую локальную базу преподавателя, а откатить
    #UPDATE иначе нечем. Механизм штатный и ротируется сам (MAX_BACKUPS).
    if args.apply:
        path = DBManager.backup(reason="backfill")
        print(f"Бэкап локальной базы: {path or '(не удался — см. лог)'}")

    text, _written = run(apply=args.apply)
    print(text)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"\nОтчёт сохранён: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
