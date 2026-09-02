# -*- coding: utf-8 -*-
"""
asvs_report.py — человекочитаемый отчёт о соответствии OWASP ASVS 5.0.

SBOM читает машина, а на приёмке спросит человек — и наоборот: вердикты должны жить в
машинно-проверяемом виде, иначе они протухают молча. Отсюда разделение: источник правды
— `docs/security/asvs-baseline.json`, а этот файл СОБИРАЕТ из него markdown.

    python -X utf8 tools/asvs_report.py            # записать docs/security/ASVS-BASELINE.md
    python -X utf8 tools/asvs_report.py --check    # только проверить, ничего не писать
    python -X utf8 tools/asvs_report.py --open     # показать открытые требования в охвате

⚠️ Править markdown РУКАМИ бессмысленно — следующий прогон затрёт. В шапке файла об этом
сказано, потому что на грабли «поправил сгенерированное» наступают все и всегда.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asvs_baseline as ab                                     # noqa: E402

OUT_PATH = os.path.join(ab.SECURITY_DIR, "ASVS-BASELINE.md")

#Значок и подпись статуса. Значок нужен не для красоты: таблицу на 345 строк глазами
#читают по колонке символов, а не по словам.
_MARK = {
    "done":    ("[x]", "выполнено"),
    "partial": ("[~]", "частично"),
    "todo":    ("[ ]", "не сделано"),
    "n/a":     ("[-]", "неприменимо"),
}


def _evidence_cell(verdict: dict) -> str:
    parts = []
    for ev in verdict.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        f = ev.get("file", "")
        needles = ev.get("contains")
        if isinstance(needles, str):
            needles = [needles]
        if needles:
            parts.append("`%s` → `%s`" % (f, "`, `".join(str(n) for n in needles)))
        else:
            parts.append("`%s`" % f)
    for t in verdict.get("tests") or []:
        parts.append("тест `%s`" % t)
    return "<br>".join(parts) if parts else "—"


def build(standard=None, baseline=None) -> str:
    standard = standard if standard is not None else ab.load_standard()
    baseline = baseline if baseline is not None else ab.load_baseline()
    cov = ab.coverage(standard, baseline)
    lines: list[str] = []
    add = lines.append

    add("<!-- ФАЙЛ СГЕНЕРИРОВАН. Источник правды — docs/security/asvs-baseline.json.")
    add("     Правки здесь будут затёрты: python -X utf8 tools/asvs_report.py -->")
    add("")
    add("# Соответствие OWASP ASVS 5.0.0 — GradeBookAI %s" % baseline.get("product_version", ""))
    add("")
    add("Стандарт: **%s**, файл `docs/security/%s`, sha256 `%s…`."
        % (baseline.get("standard", ""), baseline.get("standard_file", ""),
           str(baseline.get("standard_sha256", ""))[:16]))
    add("Целевой уровень: **L%d**. Дата: %s." % (cov["target_level"], baseline.get("updated", "")))
    add("")
    for para in baseline.get("scope_note", []) or []:
        add(para)
    add("")
    add("> ⚠️ **Как читать.** «Выполнено» здесь означает: есть код по названному адресу И есть")
    add("> тест. Оба факта проверяет `tests/test_asvs_baseline.py` — он открывает файл и ищет")
    add("> названную строку, поэтому вердикт не может пережить удаление защиты. Чего сторож")
    add("> НЕ проверяет: что защита ДОСТАТОЧНА и что она стоит на нужной ручке. Это работа")
    add("> ревью, и подменять её галочкой нельзя.")
    add("")
    add("> ⚠️ Отсутствие записи о требовании читается как **не сделано**, а не как «вопрос снят».")
    add("")

    # ── сводка ──
    add("## Сводка")
    add("")
    add("| | Требований |")
    add("|---|---|")
    add("| Всего в стандарте | %d |" % cov["total"])
    for st in ("done", "partial", "todo", "n/a"):
        add("| %s %s | %d |" % (_MARK[st][0], _MARK[st][1], cov["by_status"].get(st, 0)))
    add("")
    add("**В охвате** (уровень ≤ L%d, применимо к продукту): %d требований, из них закрыто "
        "полностью **%d** — %.1f %%."
        % (cov["target_level"], cov["in_scope_total"], cov["in_scope_done"], cov["in_scope_percent"]))
    add("")
    add("> ⚠️ **Эта доля означает не «мы защищены на %.0f %%», а «мы прошли по чек-листу %.0f %%».**"
        % (cov["in_scope_percent"], cov["in_scope_percent"]))
    add("> Разница принципиальная. Требование со статусом «не сделано» чаще всего значит")
    add("> «вердикт ещё не выносился»: продукт может ему соответствовать, но пока никто не")
    add("> открыл файл и не приложил доказательство. Записывать такое как «выполнено» без")
    add("> проверки — ровно то, ради чего вся эта затея и заведена, поэтому умолчание строгое.")
    add("> Растущая доля здесь — это мера проделанной РАБОТЫ ПО ПРОВЕРКЕ, а не уровень риска.")
    add("")
    add("Число «закрыто» СЧИТАЕТСЯ при генерации, а не хранится: хранимое устаревает молча.")
    add("")

    # ── по главам ──
    add("## По главам")
    add("")
    add("| Глава | Название | [x] | [~] | [ ] | [-] |")
    add("|---|---|---|---|---|---|")
    for ch_code, ch_name in ab.chapter_titles(standard):
        row = cov["by_chapter"].get(ch_code, {})
        add("| %s | %s | %d | %d | %d | %d |"
            % (ch_code, ch_name, row.get("done", 0), row.get("partial", 0),
               row.get("todo", 0), row.get("n/a", 0)))
    add("")

    # ── неприменимые главы целиком ──
    na_ch = {c: v for c, v in (baseline.get("chapters") or {}).items()
             if v.get("status") == "n/a"}
    if na_ch:
        add("## Главы, неприменимые целиком")
        add("")
        add("Неприменимость — это утверждение, а не пропуск, поэтому у каждой названа причина.")
        add("")
        for ch_code in sorted(na_ch, key=lambda c: int(c[1:]) if c[1:].isdigit() else 0):
            name = dict(ab.chapter_titles(standard)).get(ch_code, "")
            add("### %s %s" % (ch_code, name))
            add("")
            add(na_ch[ch_code].get("note", ""))
            add("")

    # ── открытые пункты ──
    add("## Открытые требования в охвате")
    add("")
    add("То, что НЕ закрыто и относится к нам. Этот раздел — рабочий список, а не признание:")
    add("честно названный пробел дешевле обнаруженного проверяющим.")
    add("")
    open_rows = []
    for req in ab.iter_in_order(standard):
        v = ab.verdict_for(req["id"], req, baseline)
        st = v.get("status", "todo")
        lvl = req.get("level")
        in_scope = st != "n/a" and (lvl is None or lvl <= cov["target_level"])
        if in_scope and st in ("todo", "partial") and v.get("source") != "default":
            open_rows.append((req, v, st))
    if open_rows:
        for req, v, st in open_rows:
            add("- **%s** (L%s) %s — %s" % (req["id"], req.get("level") or "—",
                                            _MARK[st][0], req["text"][:150]))
            note = (v.get("note") or "").strip()
            if note:
                add("  - %s" % note)
        add("")
    add("Плюс требования, по которым вердикт ещё не выносился (умолчание `не сделано`): %d."
        % (cov["by_status"].get("todo", 0) - len([1 for _, _, s in open_rows if s == "todo"])))
    add("")

    # ── полная таблица ──
    add("## Полная таблица требований")
    add("")
    add("| № | L | Статус | Требование | Доказательство / тест |")
    add("|---|---|---|---|---|")
    for req in ab.iter_in_order(standard):
        v = ab.verdict_for(req["id"], req, baseline)
        st = v.get("status", "todo")
        text = req["text"].replace("|", "\\|").replace("\n", " ")
        if len(text) > 260:
            text = text[:257] + "…"
        add("| %s | %s | %s | %s | %s |"
            % (req["id"], req.get("level") or "—", _MARK[st][0], text, _evidence_cell(v)))
    add("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Отчёт о соответствии OWASP ASVS 5.0")
    ap.add_argument("--check", action="store_true", help="только проверить, ничего не писать")
    ap.add_argument("--open", action="store_true", dest="show_open",
                    help="показать открытые требования в охвате")
    args = ap.parse_args()

    standard = ab.load_standard()
    baseline = ab.load_baseline()
    problems = ab.check(standard, baseline)
    if problems:
        print("БАЗОВЫЙ УРОВЕНЬ РАЗОШЁЛСЯ С КОДОМ (%d):" % len(problems))
        for p in problems:
            print("  -", p)
        return 1

    cov = ab.coverage(standard, baseline)
    print("ASVS 5.0.0: всего %d; выполнено %d, частично %d, не сделано %d, неприменимо %d"
          % (cov["total"], cov["by_status"]["done"], cov["by_status"]["partial"],
             cov["by_status"]["todo"], cov["by_status"]["n/a"]))
    print("В охвате L<=%d: %d, закрыто %d (%.1f %%)"
          % (cov["target_level"], cov["in_scope_total"], cov["in_scope_done"],
             cov["in_scope_percent"]))

    if args.show_open:
        print("\nОткрытые требования, по которым вердикт вынесен:")
        for req in ab.iter_in_order(standard):
            v = ab.verdict_for(req["id"], req, baseline)
            if v.get("source") == "default" or v.get("status") not in ("todo", "partial"):
                continue
            lvl = req.get("level")
            if lvl is not None and lvl > cov["target_level"]:
                continue
            print("  %-9s %-8s %s" % (req["id"], v["status"], (v.get("note") or "")[:110]))

    if args.check:
        return 0

    body = build(standard, baseline)
    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    print("\nЗАПИСАНО: %s (%d строк)" % (OUT_PATH, body.count("\n")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
