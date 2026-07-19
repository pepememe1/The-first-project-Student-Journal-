# -*- coding: utf-8 -*-
"""
backfill_student_id_desktop.py — ЭТАП 2 миграции, сторона ДЕСКТОПА.

Зеркало server/backfill_student_id.py (правки делаем на ОБЕИХ платформах). Логика
сопоставления та же, отличается источник данных: локальный SQLite и таблица users,
которую читает data_store (payload зашифрован Fernet+DPAPI, напрямую SQL его не возьмёт).

Почему отдельный скрипт, а не «сервер посчитает и раздаст». Серверный бэкофилл намеренно
НЕ трогает updated_at: бамп объявил бы каждую оценку изменённой (весь парк выкачал бы базу
заново), а серверная метка могла бы перебить более свежую офлайн-правку на чьём-то ПК.
Обратная сторона — без бампа дельта проставленный id на десктоп не привезёт. Поэтому
каждый ПК проставляет его себе сам: локально, без сети, по своему же справочнику.

Запуск ИЗ КОРНЯ репозитория (нужен _bootstrap для плоских импортов):

    python tools/backfill_student_id_desktop.py                  # отчёт, БД не трогаем
    python tools/backfill_student_id_desktop.py --apply          # проставить id
    python tools/backfill_student_id_desktop.py --report out.txt # отчёт ещё и в файл

По умолчанию — ХОЛОСТОЙ ПРОГОН. Идемпотентен: заполненные строки пропускаются.
"""
import argparse
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  — кладёт ui/ sync/ data/ в sys.path

from core import DBManager, LOCAL_DB  # noqa: E402
from data_store import get_store  # noqa: E402

#Формулировки причин совпадают с серверными — отчёты двух платформ читаются рядом
#и сравниваются глазами без перевода.
REASON_NOT_FOUND = "студента с таким ФИО нет в справочнике"
REASON_AMBIGUOUS = "несколько студентов с одинаковым ФИО, группа не различила"
REASON_NO_GROUP = "занятие не найдено — не по чему различить однофамильцев"
REASON_TERM_NO_GROUP = "однофамильцы, а у итоговой оценки нет группы для различения"


def _students_index() -> dict:
    """(фамилия, имя) → список студентов. Надгробия пропускаем: привязывать живую
    оценку к удалённому аккаунту бессмысленно. get_students() их уже отфильтровал."""
    index = defaultdict(list)
    for s in (get_store().get_students() or []):
        key = ((s.get("surname") or "").strip(), (s.get("name") or "").strip())
        index[key].append(s)
    return index


def _resolve(candidates: list, group: str) -> tuple:
    """Кандидаты + группа → (id, причина_отказа). Пустой id = не склеилось.

    Однофамильцев разводим по группе. Если и после этого их несколько — ОТКАЗЫВАЕМСЯ.
    Приписать оценку не тому студенту хуже, чем оставить строку на ФИО: второе чинится
    руками, первое молча портит данные и обнаружится через семестр."""
    if not candidates:
        return "", REASON_NOT_FOUND
    if len(candidates) == 1:
        return candidates[0].get("id", ""), ""
    if not group:
        return "", REASON_NO_GROUP
    same = [s for s in candidates if (s.get("group") or "").strip() == group]
    if len(same) == 1:
        return same[0].get("id", ""), ""
    return "", REASON_AMBIGUOUS


def _scan(conn, index: dict) -> tuple:
    """Читает обе таблицы и решает по каждой строке. Возвращает (оценки, итоговые),
    где элемент = (ключ_для_UPDATE, фамилия, имя, группа, id, причина, надгробие?)."""
    cur = conn.cursor()
    #Группа берётся у ЗАНЯТИЯ — именно она различает однофамильцев (двух полных тёзок
    #в одну группу не заводят).
    cur.execute("SELECT id, COALESCE(group_name,'') FROM lessons")
    lesson_group = {r[0]: (r[1] or "").strip() for r in cur.fetchall()}

    cur.execute("SELECT student_f,student_n,lesson_id,COALESCE(deleted,0) FROM grades "
                "WHERE COALESCE(student_id,'')=''")
    grades = []
    for f, n, lid, deleted in cur.fetchall():
        f, n = (f or "").strip(), (n or "").strip()
        group = lesson_group.get(lid, "")
        sid, reason = _resolve(index.get((f, n), []), group)
        grades.append(((f, n, lid), f, n, group, sid, reason, bool(deleted)))

    cur.execute("SELECT id,student_f,student_n,COALESCE(deleted,0) FROM term_grades "
                "WHERE COALESCE(student_id,'')=''")
    terms = []
    for gid, f, n, deleted in cur.fetchall():
        f, n = (f or "").strip(), (n or "").strip()
        sid, reason = _resolve(index.get((f, n), []), "")
        if reason == REASON_NO_GROUP:
            reason = REASON_TERM_NO_GROUP    #у итоговой занятия нет вовсе
        terms.append(((gid,), f, n, "", sid, reason, bool(deleted)))
    return grades, terms


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
    """Считает (и при apply=True проставляет) id. Возвращает (текст_отчёта, записано).
    Вынесено из main отдельной функцией — так это можно вызвать из тестов и из админки."""
    index = _students_index()
    conn = DBManager.get_conn()
    try:
        grades, terms = _scan(conn, index)
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
            cur = conn.cursor()
            for (f, n, lid), _f, _n, _g, sid, _r, _d in m1:
                #updated_at НЕ трогаем: это техническая простановка связи, а не правка
                #оценки. Бамп метки отправил бы всю базу в push и мог бы перебить более
                #свежую правку на другом ПК.
                cur.execute("UPDATE grades SET student_id=? WHERE student_f=? AND "
                            "student_n=? AND lesson_id=?", (sid, f, n, lid))
                written += 1
            for (gid,), _f, _n, _g, sid, _r, _d in m2:
                cur.execute("UPDATE term_grades SET student_id=? WHERE id=?", (sid, gid))
                written += 1
            conn.commit()
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
    finally:
        conn.close()


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
    #UPDATE иначе нечем. Механизм уже есть и ротируется сам (MAX_BACKUPS).
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
