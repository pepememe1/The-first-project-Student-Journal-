"""
sched_smoke.py — ЖИВАЯ проверка парсера расписания (не юнит-тест, ходит в сеть).

Запуск из корня репозитория:
    python tests/sched_smoke.py

Делает реальные GET к portal.esstu.ru: печатает найденные группы колледжа (на «К»),
число предметов и пример расписания одной группы и одного преподавателя. Нужен,
чтобы быстро убедиться, что разметка сайта не изменилась. Юнит-тесты (pytest) от
сети НЕ зависят — они гоняют сохранённую фикстуру.
"""
import sys
import os

#запускаемся из tests/ — добавим корень и его папки в путь, как делает pytest.ini
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_ROOT, os.path.join(_ROOT, "data")):
    if p not in sys.path:
        sys.path.insert(0, p)

#на Windows консоль может быть cp1251 — попросим UTF-8, иначе кириллица «крякает»
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import schedule.parser as p
from schedule.model import DEFAULT_PAIR_TIMES


def main():
    try:
        idx = p.fetch_text(p.COLLEGE_INDEX)
    except Exception as e:
        print(f"⚠️  Портал недоступен ({e}). Это не ошибка парсера — проверьте сеть.")
        return 1

    groups = p.list_college_groups(idx)
    print(f"✅ Групп колледжа (на «К») найдено: {len(groups)}")
    print("   Примеры:", ", ".join(n for n, _ in groups[:10]))
    if not groups:
        print("❌ Группы не найдены — возможно, разметка сайта изменилась.")
        return 1

    name, href = groups[0]
    page = p.fetch_text(p.BASE_URL + p.COLLEGE_DIR + href)
    gs = p.parse_group_page(page, name=name, href=href)
    print(f"\n📚 Группа {name}: недели {sorted(gs.weeks.keys())}, "
          f"предметов {len(gs.subjects())}")
    print("   Времена пар:", " | ".join(gs.pair_times))
    for day in ("Пнд", "Втр"):
        lessons = gs.weeks.get(1, {}).get(day, [])
        print(f"   {day} (нед. I):")
        for l in lessons:
            print(f"      {l.pair_no}. {l.time}  [{l.kind or '—'}] "
                  f"{l.subject}  · {l.teacher}  · а.{l.room}")

    #инверсия преподавателей по всем группам колледжа — тяжело, поэтому считаем
    #на первых нескольких группах, чтобы smoke был быстрым
    print("\n👨‍🏫 Проверка инверсии преподавателей (первые 5 групп)...")
    tindex = {}
    for n, h in groups[:5]:
        try:
            g = p.parse_group_page(p.fetch_text(p.BASE_URL + p.COLLEGE_DIR + h), name=n)
        except Exception:
            continue
        p._index_teachers(tindex, n, g)
    print(f"   Преподавателей собрано: {len(tindex)}")
    if tindex:
        t = sorted(tindex.keys())[0]
        cnt = sum(len(v) for w in tindex[t].values() for v in w.values())
        print(f"   Пример: {t} — пар в расписании: {cnt}")
    print("\n✅ Smoke завершён.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
