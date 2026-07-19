"""
migrate_grade_keys.py — ЭТАП 3: перевод ключей оценок с ФИО на student_id.

Переписывает id уже накопленных строк:
    grades       `{фамилия}|{имя}|{lesson_id}`            → `{student_id}|{lesson_id}`
    term_grades  `{фамилия}|{имя}|{предмет}|{год}|{сем}`  → `{student_id}|{предмет}|…`

Это ТОЧКА НЕВОЗВРАТА: старые ключи после прогона в базе не остаются. Поэтому —
    1) обязателен свежий бэкап БД (снимается отдельно, скрипт его не делает);
    2) по умолчанию ХОЛОСТОЙ ПРОГОН, запись только с --apply;
    3) строки без student_id НЕ ТРОГАЕМ: их ключ остаётся прежним. Такое бывает
       законно (студента ещё не завели в справочнике — ростер преподавателя ведётся
       отдельно), и терять оценку ради «чистоты формата» недопустимо. Сервер умеет
       работать со смешанной базой: нормализация ключей на push это учитывает.

Предусловие: этап 2 (backfill_student_id.py) прогнан и показал 0 живых несклеенных.

    python migrate_grade_keys.py            # отчёт, БД не трогаем
    python migrate_grade_keys.py --apply    # переписать ключи

Идемпотентен: строки, уже имеющие ключ нового формата, пропускаются.
"""
import argparse
import sys

from app.db import SessionLocal, init_db
from app.models import Grade, TermGrade, grade_id, is_new_style_key, term_grade_id


def _plan(db) -> tuple:
    """Считает, что предстоит сделать. Возвращает (переименования, пропуски, конфликты).

    Конфликт — когда целевой ключ УЖЕ занят другой строкой. На практике это означает,
    что одну и ту же оценку успели записать и по старому, и по новому ключу (например,
    веб уже писал по-новому, а десктоп по-старому). Такие случаи не сливаем молча:
    выводим списком, решение за человеком."""
    renames, skipped, conflicts = [], [], []
    for model, build in ((Grade, lambda r: grade_id(r.student_id, r.lesson_id)),
                         (TermGrade, lambda r: term_grade_id(r.student_id, r.subject,
                                                             r.year, r.semester))):
        rows = db.query(model).all()
        existing = {r.id for r in rows}
        for r in rows:
            if is_new_style_key(r.id):
                continue                       #уже переведена
            if not (r.student_id or "").strip():
                skipped.append((model.__tablename__, r.id))
                continue
            new_id = build(r)
            if new_id in existing:
                conflicts.append((model.__tablename__, r.id, new_id))
                continue
            renames.append((model, r.id, new_id))
            existing.add(new_id)
    return renames, skipped, conflicts


def main() -> int:
    ap = argparse.ArgumentParser(description="Перевод ключей оценок на student_id (этап 3)")
    ap.add_argument("--apply", action="store_true",
                    help="переписать ключи (без флага — только отчёт)")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    try:
        renames, skipped, conflicts = _plan(db)
        print("=" * 70)
        print("ЭТАП 3: перевод ключей оценок с ФИО на student_id")
        print("=" * 70)
        print(f"  к переводу        : {len(renames)}")
        print(f"  пропущено (нет id): {len(skipped)}")
        print(f"  конфликтов        : {len(conflicts)}")

        if skipped:
            print("\nПРОПУЩЕННЫЕ (остаются на ФИО-ключах — это допустимо):")
            for table, old in skipped[:20]:
                print(f"    · {table}: {old}")
            if len(skipped) > 20:
                print(f"    … и ещё {len(skipped) - 20}")
        if conflicts:
            print("\n⚠️  КОНФЛИКТЫ — целевой ключ уже занят. Разобрать РУКАМИ, "
                  "молча сливать нельзя (это разные записи одной оценки):")
            for table, old, new in conflicts:
                print(f"    · {table}: {old}  →  {new} (занят)")

        if not args.apply:
            print("\nХОЛОСТОЙ ПРОГОН: БД не изменялась. Записать — с флагом --apply.")
            print("⚠️  Перед --apply убедись, что снят свежий бэкап: старые ключи "
                  "после прогона не остаются.")
            return 1 if conflicts else 0

        if conflicts:
            print("\nОСТАНОВЛЕНО: сначала разберите конфликты. Ничего не записано.")
            return 1

        #SQLAlchemy не любит смену первичного ключа у живого объекта, поэтому идём
        #голым UPDATE по таблице — операция простая и предсказуемая.
        from sqlalchemy import text
        for model, old_id, new_id in renames:
            db.execute(text(f"UPDATE {model.__tablename__} SET id=:new WHERE id=:old"),
                       {"new": new_id, "old": old_id})
        db.commit()
        print(f"\nЗАПИСАНО: переведено ключей — {len(renames)}.")
        print("Старый формат в базе больше не создаётся; входящие ключи от старых "
              "клиентов сервер нормализует на приёме (см. sync._normalize_grade_key).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
