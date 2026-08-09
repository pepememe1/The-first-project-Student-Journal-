"""Пересборка карты связей проекта (`graphify-out/`) БЕЗ обращения к модели.

━━ ЗАЧЕМ ЭТО ОТДЕЛЬНЫМ СКРИПТОМ ━━
Полный `/graphify` дорог: смысловой слой читают субагенты, и один такой заход стоил
нам 690 000 токенов. Но 95% карты — это разбор кода, а он БЕСПЛАТЕН и занимает минуту.
Поэтому обновление графа после обычной работы (переименовали функцию, добавили роут,
разрезали файл) должно идти вот так, а не полным перестроением.

Смысловой слой (`_origin: semantic` — узлы из документов и планов) берётся из кэша
`graphify-out/cache/semantic` и из уцелевших кусков прошлых заходов. Не нашёлся —
карта строится без него: код важнее, а выдумывать смысловые узлы нечем.

━━ ЧТО ДЕЛАЕТ, ЧЕГО НЕ ДЕЛАЕТ ━━
Делает: обход дерева, разбор кода, мост HTTP-контракта, кластеризацию, отчёт.
Не делает: не зовёт модель, не трогает `graph.html` (его рисует шаг визуализации
самого graphify), не переписывает карту, если новая ОКАЗАЛАСЬ МЕНЬШЕ прежней —
защита от усадки внутри `to_json` не даёт затереть хорошую карту испорченным прогоном.

━━ ЗАПУСК ━━
    python tools/graph_rebuild.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

OUT = ROOT / "graphify-out"


def main() -> int:
    try:
        from graphify.detect import detect
        from graphify.extract import collect_files, extract
        from graphify.cache import check_semantic_cache
        from graphify.build import build_from_json
        from graphify.cluster import cluster, score_all
        from graphify.analyze import god_nodes, surprising_connections, suggest_questions
        from graphify.report import generate
        from graphify.export import to_json
    except ImportError:
        print("graphify не установлен в этом интерпретаторе -- ставится вместе со скиллом")
        return 1

    import graph_api_bridge

    OUT.mkdir(exist_ok=True)

    print("[1/5] обход дерева ...", flush=True)
    det = detect(ROOT)
    (OUT / ".graphify_detect.json").write_text(
        json.dumps(det, ensure_ascii=False), encoding="utf-8"
    )
    code = det.get("files", {}).get("code", [])
    print(f"      код: {len(code)} путей", flush=True)

    print("[2/5] разбор кода ...", flush=True)
    files: list[Path] = []
    for f in code:
        p = Path(f)
        files.extend(collect_files(p) if p.is_dir() else [p])
    ast = extract(files, cache_root=ROOT)
    print(f"      узлов {len(ast['nodes'])} · рёбер {len(ast['edges'])}", flush=True)

    print("[3/5] смысловой слой из кэша ...", flush=True)
    sem = {"nodes": [], "edges": [], "hyperedges": []}
    try:
        n, e, h, uncached = check_semantic_cache(det.get("files", {}), root=str(ROOT))
        sem = {"nodes": n, "edges": e, "hyperedges": h}
        print(f"      из кэша: {len(n)} узлов; не в кэше файлов: {len(uncached)}", flush=True)
    except Exception as exc:
        print(f"      кэш недоступен ({type(exc).__name__}) -- только код", flush=True)
    for leftover in sorted(OUT.glob(".graphify_chunk_*.json")):
        try:
            c = json.loads(leftover.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        have = {x["id"] for x in sem["nodes"]}
        add = [x for x in c.get("nodes", []) if x["id"] not in have]
        sem["nodes"] += add
        sem["edges"] += c.get("edges", [])
        sem["hyperedges"] += c.get("hyperedges", [])
        print(f"      + {leftover.name}: {len(add)} узлов", flush=True)

    print("[4/5] мост HTTP-контракта ...", flush=True)
    pairs, orphan_calls, orphan_routes = graph_api_bridge.match()
    bridge = graph_api_bridge.to_graph_edges(pairs)
    print(f"      {len(bridge['edges'])} рёбер клиент->сервер; "
          f"висячих вызовов {len(orphan_calls)}, "
          f"невостребованных роутов {len(orphan_routes)}", flush=True)

    seen = {n["id"] for n in ast["nodes"]}
    nodes = list(ast["nodes"]) + [n for n in sem["nodes"] if n["id"] not in seen]
    known = {n["id"] for n in nodes}
    # Ребро в никуда графу не поможет: если по одну сторону моста узла нет (файл не
    # попал в разбор), связь молча исказит расчёт центральности. Отбрасываем и считаем.
    live_bridge = [e for e in bridge["edges"]
                   if e["source"] in known and e["target"] in known]
    dropped = len(bridge["edges"]) - len(live_bridge)
    if dropped:
        print(f"      отброшено рёбер без узла на конце: {dropped}", flush=True)

    extraction = {
        "nodes": nodes,
        "edges": ast["edges"] + sem["edges"] + live_bridge,
        "hyperedges": sem.get("hyperedges", []),
        "input_tokens": 0,
        "output_tokens": 0,
    }
    (OUT / ".graphify_extract.json").write_text(
        json.dumps(extraction, ensure_ascii=False), encoding="utf-8"
    )

    print("[5/5] сборка, кластеризация, отчёт ...", flush=True)
    G = build_from_json(extraction, root=str(ROOT), directed=False)
    if G.number_of_nodes() == 0:
        print("ОШИБКА: граф пуст -- разбор ничего не дал")
        return 1
    communities = cluster(G)
    cohesion = score_all(G, communities)
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    labels = {cid: "Community " + str(cid) for cid in communities}
    questions = suggest_questions(G, communities, labels)

    if not to_json(G, communities, str(OUT / "graph.json")):
        print("ОШИБКА: новая карта меньше прежней -- защита от усадки не дала перезаписать")
        return 1
    (OUT / "GRAPH_REPORT.md").write_text(
        generate(G, communities, cohesion, labels, gods, surprises, det,
                 {"input": 0, "output": 0}, str(ROOT), suggested_questions=questions),
        encoding="utf-8",
    )
    (OUT / ".graphify_analysis.json").write_text(
        json.dumps({
            "communities": {str(k): v for k, v in communities.items()},
            "cohesion": {str(k): v for k, v in cohesion.items()},
            "gods": gods,
            "surprises": surprises,
            "questions": questions,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"ГОТОВО: {G.number_of_nodes()} узлов, {G.number_of_edges()} рёбер, "
          f"{len(communities)} сообществ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
