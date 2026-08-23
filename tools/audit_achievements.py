"""
audit_achievements.py — сверка ВСЕХ стыков системы ачивок и пасхалок.

    python -X utf8 tools/audit_achievements.py

━━ ЗАЧЕМ ОТДЕЛЬНЫЙ ИНСТРУМЕНТ, ЕСЛИ ЕСТЬ ТЕСТЫ ━━
Тесты проверяют по одному правилу и живут в трёх местах (`server/tests/test_achievements.py`,
`web/tests/easterEggsWired.test.mjs`, `easterEggsHealth.test.mjs`). Здесь — ОДНА таблица
на все половины продукта разом: питоновский реестр, клиентский справочник, карта сцен,
триггеры, реплики при уходе, шансы, кулдауны, ассеты.

Смысл в том, что почти каждый дефект этой подсистемы был РАССОГЛАСОВАНИЕМ ДВУХ МЕСТ, а
не ошибкой в одном: id есть на сервере и нет на клиенте, пасхалка есть — сцены нет,
сцена есть — никто не зовёт, зовут — а `claim` не вызывается. По одному файлу такое не
видно вовсе.

⚠️ Инструмент ТОЛЬКО ЧИТАЕТ. Ничего не чинит и не переписывает: решение всегда за
человеком, а молчаливая «автопочинка» рассогласования — способ спрятать дефект.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def read_web_sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for base, _, files in os.walk(os.path.join(ROOT, "web", "src")):
        for f in files:
            if f.endswith((".vue", ".js")):
                p = os.path.join(base, f)
                out[os.path.relpath(p, ROOT).replace("\\", "/")] = read(os.path.relpath(p, ROOT))
    return out


def block(text: str, start: str, end: str) -> str:
    """Кусок между маркерами. Пусто, если разметка изменилась, — это тоже находка."""
    if start not in text:
        return ""
    tail = text.split(start, 1)[1]
    return tail.split(end, 1)[0] if end in tail else tail


def main() -> int:
    srv = read("server", "app", "easter_eggs.py")
    cfg = read("web", "src", "config", "achievements.js")
    store = read("web", "src", "stores", "easterEggs.js")
    host = read("web", "src", "components", "easter", "EasterEggHost.vue")
    web = read_web_sources()
    all_web = "\n".join(web.values())

    # ── что откуда берём ────────────────────────────────────────────────────
    srv_pairs = dict(re.findall(r'"(\w+)":\s+"(\w+)",', block(srv, "ACHIEVEMENTS: dict", "}")))
    chances = {k: int(v) for k, v in re.findall(r'"(\w+)":\s*(\d+)', block(srv, "EGG_CHANCES: dict", "}"))}
    #Доля в процентах — вторая форма записи шанса (см. EGG_PERCENT в easter_eggs.py).
    percents = {k: int(v) for k, v in re.findall(r'"(\w+)":\s*(\d+)', block(srv, "EGG_PERCENT: dict", "}"))}
    cooldowns = {k: int(v) for k, v in re.findall(r'"(\w+)":\s*(\d+)', block(srv, "EGG_COOLDOWN_S: dict", "}"))}
    cfg_ids = re.findall(r"^\s{2}\{\s*id:\s*'([a-z0-9_]+)'", cfg, re.M)
    cli_pairs = dict(re.findall(r"^\s{2}([a-z0-9_]+):\s+'([a-z0-9_]+)',",
                                block(store, "EGG_ACHIEVEMENT = {", "\n}"), re.M))
    #⚠️ Форма объявления сцены менялась (`defineAsyncComponent` → своя обёртка
    #`lazyScene`, добавившая обработку неудачной загрузки). Принимаем ОБЕ: разбор,
    #привязанный к одной, находит ноль сцен и объявляет все пасхалки неподключёнными —
    #то есть сверка начинает врать ровно там, где должна ловить враньё.
    scenes = set(re.findall(r"^\s+(\w+):\s+(?:defineAsyncComponent|lazyScene)\(", host, re.M))
    in_page = set(re.findall(r"'([a-z0-9_]+)'", block(store, "const IN_PAGE = new Set([", "])")))
    missable = set(re.findall(r"'([a-z0-9_]+)'", block(store, "const MISSABLE_IN_PAGE = new Set([", "])")))
    phrases = set(re.findall(r"^\s{2}([a-z0-9_]+):\s*\{", block(store, "const LEAVE_ASK = {", "\n}"), re.M))
    claims = set(re.findall(r"claim\('([a-z0-9_]+)'\)", all_web))

    problems: list[str] = []
    note = problems.append

    # ── 1. Реестр ачивок: сервер против клиента ─────────────────────────────
    if set(srv_pairs) != set(cfg_ids):
        note(f"реестр ачивок разошёлся: только на сервере {sorted(set(srv_pairs) - set(cfg_ids))}, "
             f"только на клиенте {sorted(set(cfg_ids) - set(srv_pairs))}")
    dupes = [a for a in set(srv_pairs.values()) if list(srv_pairs.values()).count(a) > 1]
    if dupes:
        note(f"одна пасхалка выдаёт НЕСКОЛЬКО ачивок: {sorted(dupes)}")

    # ── 2. Пара «пасхалка → ачивка» на обеих половинах ──────────────────────
    srv_by_egg = {egg: aid for aid, egg in srv_pairs.items()}
    for egg, aid in cli_pairs.items():
        if srv_by_egg.get(egg) != aid:
            note(f"пара разошлась: клиент {egg} → {aid}, сервер {egg} → {srv_by_egg.get(egg)}")
    for egg in set(srv_by_egg) - set(cli_pairs):
        note(f"пасхалка {egg} есть на сервере, но её нет в EGG_ACHIEVEMENT клиента")

    # ── 3. У каждой пасхалки есть чем нарисовать и кто зовёт ────────────────
    for egg in sorted(srv_by_egg):
        if egg not in scenes and egg not in in_page:
            note(f"{egg}: нет ни сцены-оверлея, ни слоя внутри страницы — бросок уйдёт впустую")
        if egg in scenes and egg in in_page:
            note(f"{egg}: объявлена И оверлеем, И слоем страницы — каналы путать нельзя")
        from_web = all_web.count(f"'{egg}'") >= 2
        from_srv = f'"{egg}"' in srv
        if not from_web and not from_srv:
            note(f"{egg}: никто не запускает")
        if egg not in claims:
            note(f"{egg}: ачивку никто не закрывает вызовом claim()")

    # ── 4. Шанс и кулдаун ───────────────────────────────────────────────────
    both = set(chances) & set(percents)
    if both:
        note(f"шанс объявлен ДВАЖДЫ, знаменателем и процентом: {sorted(both)} — "
             f"значения означают разное, промах на порядок гарантирован")
    rolled = set(chances) | set(percents)
    for egg in sorted(rolled | set(cooldowns)):
        if egg in cooldowns and egg not in rolled:
            note(f"{egg}: кулдаун задан, а шанса нет — бросок не состоится никогда")
        if egg in cooldowns and chances.get(egg, 0) > 150:
            note(f"{egg}: редкий шанс 1/{chances[egg]} И кулдаун {cooldowns[egg]} с — "
                 f"вторая невидимая стена поверх первой")
    deterministic = sorted(set(srv_by_egg) - rolled)
    for egg in deterministic:
        if "mark_triggered" not in srv or f'"{egg}"' not in srv:
            note(f"{egg}: детерминированная, но следа mark_triggered в сервере не видно — "
                 f"claim откажет молча")

    # ── 5. Реплики при уходе ────────────────────────────────────────────────
    for egg in sorted(missable):
        if egg not in phrases:
            note(f"{egg}: можно пропустить, а реплики при уходе нет")
    for egg in sorted(phrases - missable - scenes):
        note(f"{egg}: реплика при уходе есть, но пасхалка не считается пропускаемой — "
             f"её никогда не покажут")

    # ── 6. Ассеты сцен ──────────────────────────────────────────────────────
    for path, text in web.items():
        if "/components/easter/" not in path:
            continue
        for m in re.finditer(r"""['"(](/easter/[^'")\s]+)""", text):
            after = text[m.end():m.end() + 6].lstrip("'\")").lstrip()
            if after.startswith("+"):
                continue                      # имя собирается строкой, проверяется отдельно
            if not os.path.exists(os.path.join(ROOT, "web", "public", m.group(1).lstrip("/"))):
                note(f"{os.path.basename(path)}: нет файла {m.group(1)}")

    # ── отчёт ───────────────────────────────────────────────────────────────
    #⚠️ Считаем шансы ТОЛЬКО у пасхалок с ачивкой: в EGG_CHANCES лежат ещё три
    #(skyrim, rdr2, far cry), у которых ачивки нет по замыслу, и общий счётчик врал.
    with_chance = len([e for e in srv_by_egg if e in rolled])
    print(f"ачивок: {len(srv_pairs)} · пасхалок: {len(srv_by_egg)} · "
          f"с шансом: {with_chance} · детерминированных: {len(deterministic)} · "
          f"с кулдауном: {len(cooldowns)} · без ачивки (по замыслу): "
          f"{sorted(rolled - set(srv_by_egg))}")
    print(f"оверлеев: {len(scenes)} · слоёв в странице: {len(in_page)} · "
          f"пропускаемых: {len(missable)} · реплик: {len(phrases)}")
    print()
    print(f"{'пасхалка':24} {'ачивка':22} {'шанс':>8} {'кулдаун':>8}  показ")
    print("-" * 88)
    for egg in sorted(srv_by_egg):
        ch = (f"1/{chances[egg]}" if egg in chances
              else f"{percents[egg]} %" if egg in percents else "условие")
        cd = f"{cooldowns[egg]} с" if egg in cooldowns else "—"
        show = "оверлей" if egg in scenes else ("в странице" if egg in in_page else "НЕТ")
        print(f"{egg:24} {srv_by_egg[egg]:22} {ch:>8} {cd:>8}  {show}")

    print()
    if problems:
        print(f"КОНФЛИКТОВ: {len(problems)}")
        for p in problems:
            print("  ❌", p)
        return 1
    print("Конфликтов нет.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
