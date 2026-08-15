"""Мост «кнопка на сайте → обработчик на сервере» для карты связей.

━━ ЗАЧЕМ ━━
Построитель графа (`graphify`) читает КОД: импорты, вызовы, наследование. Разговор
браузера с сервером идёт по HTTP, и в коде его нет ни с одной стороны — есть строка
`'/web/student/stats'` у клиента и такая же строка в декораторе у сервера, но связать
их может только тот, кто знает, что это один и тот же контракт.

Из-за этого весь фронтенд (≈1900 узлов) висел в графе отдельным материком, сцепленным
с Python ровно ДВУМЯ рёбрами — и оба оказались одним и тем же упоминанием `.vue`-файла
в комментарии тогдашнего `ui/notifications_view.py` (модуль давно удалён вместе с Qt).
Формально связь была, по сути её не было: вопрос «кто на сервере отвечает вот этой
кнопке» по графу не решался.

Этот скрипт достраивает недостающий слой: `endpoints.js:имяФункции` → `calls_http` →
`server/app/routers/…:имя_обработчика`. После него граф отвечает на вопросы вида
«что сломается на сайте, если тронуть этот эндпоинт» одним запросом, а не перебором
grep по трём каталогам.

━━ ГРАНИЦА ЧЕСТНОСТИ ━━
Сопоставление идёт по ПАРЕ (метод, путь с обезличенными параметрами). Параметр пути
не сверяется по имени: у клиента он `${encodeURIComponent(login)}`, у сервера
`{login}` — это одно и то же место, но не одна и та же строка. Что не сошлось —
попадает в отчёт как «висячий», а не подгоняется: несуществующая связь в карте хуже
отсутствующей, потому что по ней делают выводы.

━━ ЗАПУСК ━━
    python tools/graph_api_bridge.py            # отчёт в консоль
    python tools/graph_api_bridge.py --json PATH  # рёбра для графа
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTERS = ROOT / "server" / "app" / "routers"
# Часть публичных маршрутов объявлена прямо на приложении, минуя роутеры
# (`/desktop-info`, раздача SPA и загрузок) — без них отчёт врал бы «висячим вызовом».
MAIN = ROOT / "server" / "app" / "main.py"
ENDPOINTS = ROOT / "web" / "src" / "api" / "endpoints.js"

# `router = APIRouter(prefix="/web/messenger", ...)` — префикс объявляется в самом
# модуле; `include_router` в main.py второго префикса не добавляет (проверено).
_ROUTER_DECL = re.compile(r"^(\w+)\s*=\s*APIRouter\(\s*prefix=[\"']([^\"']*)[\"']", re.M)
_ROUTE = re.compile(
    r"@(\w+)\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"'][^)]*\)\s*"
    r"(?:@[^\n]*\n\s*)*"          # промежуточные декораторы, если появятся
    r"(?:async\s+)?def\s+(\w+)",
    re.M,
)
# Объявление обёртки: `имя: (аргументы) =>`. Сам вызов ищем ОТДЕЛЬНО и построчно —
# тело бывает и выражением (`=> api.get(...)`), и блоком (`=> { const form = …;
# return api.post(…) }`). Единая регулярка на оба случая ловила только первый и
# молча теряла загрузку файлов — то есть врала в отчёте, а не просто недобирала.
_DECL = re.compile(r"^\s{2}(?:async\s+)?(\w+)\s*(?::\s*(?:\([^)]*\)|\w+)\s*=>|\([^)]*\)\s*\{)")
_INVOKE = re.compile(r"api\.(get|post|put|delete|patch)\(\s*([\"'`])([^\"'`]+)\2")
# `export const studentApi = {` — именно ОБЪЕКТ, а не отдельная обёртка, попадает в граф
# узлом (разбор JS не спускается до полей объекта). Значит и мост вешаем на объект,
# иначе ребро уйдёт в несуществующий узел и будет молча отброшено.
_GROUP = re.compile(r"^export\s+const\s+(\w+)\s*=\s*\{")


def _norm(path: str) -> str:
    """Путь без параметров и хвоста запроса: `/web/x/{id}?a=1` → `/web/x/{}`."""
    path = path.split("?")[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)   # клиент: ${encodeURIComponent(id)}
    path = re.sub(r"\{[^}]*\}", "{}", path)     # сервер: {student_id}
    return path.rstrip("/") or "/"


def server_routes() -> list[dict]:
    out: list[dict] = []
    for py in sorted(ROUTERS.rglob("*.py")) + [MAIN]:
        text = py.read_text(encoding="utf-8", errors="replace")
        prefixes = dict(_ROUTER_DECL.findall(text))
        if py == MAIN:
            prefixes = {"app": ""}   # `@app.get("/desktop-info")` — префикса нет
        # Подмодули пакета routers/web/ берут общий роутер из _common (§3 CLAUDE.md).
        if not prefixes and "from ._common import" in text and "router" in text:
            prefixes = {"router": "/web"}
        rel = py.relative_to(ROOT).as_posix()
        for var, verb, path, fn in _ROUTE.findall(text):
            prefix = prefixes.get(var)
            if prefix is None:
                continue
            line = text[: text.index(f"@{var}.{verb}(")].count("\n") + 1 if f"@{var}.{verb}(" in text else 1
            out.append({
                "verb": verb.upper(),
                "path": _norm(prefix + path),
                "file": rel,
                "fn": fn,
                "line": line,
            })
    return out


def client_calls() -> list[dict]:
    """Обёртки из endpoints.js. Имя обёртки «живёт» до следующего объявления.

    Разбор построчный, а не одной регуляркой: только так вызов из блочного тела
    (`=> { … return api.post(…) }`) достаётся вместе с именем, которому он
    принадлежит.
    """
    rel = ENDPOINTS.relative_to(ROOT).as_posix()
    out: list[dict] = []
    name, name_line, group = "", 0, ""
    for i, line in enumerate(ENDPOINTS.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        grp = _GROUP.match(line)
        if grp:
            group = grp.group(1)
        decl = _DECL.match(line)
        if decl:
            name, name_line = decl.group(1), i
        for verb, _q, path in _INVOKE.findall(line):
            if not path.startswith("/") or not name:
                continue
            out.append({
                "verb": verb.upper(),
                "path": _norm(path),
                "file": rel,
                "fn": name,
                "group": group,
                "line": name_line,
            })
    return out


def match() -> tuple[list, list, list]:
    routes = server_routes()
    calls = client_calls()
    index: dict[tuple, list] = {}
    for r in routes:
        index.setdefault((r["verb"], r["path"]), []).append(r)

    pairs, orphan_calls = [], []
    hit = set()
    for c in calls:
        targets = index.get((c["verb"], c["path"]))
        if not targets:
            orphan_calls.append(c)
            continue
        for r in targets:
            pairs.append((c, r))
            hit.add((r["file"], r["fn"]))
    orphan_routes = [r for r in routes if (r["file"], r["fn"]) not in hit]
    return pairs, orphan_calls, orphan_routes


def to_graph_edges(pairs: list) -> dict:
    """Рёбра в формате graphify.

    Идентификатор узла у graphify — это путь файла (разделители в подчёркивания, без
    расширения, в нижнем регистре) плюс имя объявления. Формат подсмотрен у самого
    разбора, а не выдуман: `server/app/routers/auth.py::login` → `server_app_routers_
    auth_login`. Промахнуться тут дёшево и незаметно — ребро с несуществующим концом
    отбрасывается молча, поэтому пересборка их пересчитывает и печатает.
    """
    def nid(file: str, name: str) -> str:
        base = re.sub(r"[^A-Za-z0-9]+", "_", file.rsplit(".", 1)[0]).strip("_").lower()
        return f"{base}_{name.lower()}"

    edges = []
    for c, r in pairs:
        if not c.get("group"):
            continue          # вызов вне экспортируемого объекта — узла для него нет
        edges.append({
            "source": nid(c["file"], c["group"]),
            "target": nid(r["file"], r["fn"]),
            "relation": "calls_http",
            "confidence": "EXTRACTED",
            "confidence_score": 1.0,
            "source_file": c["file"],
            "source_location": f"L{c['line']}",
            "weight": 1.0,
            "_origin": "api_bridge",
            "context": f"{c['group']}.{c['fn']} -- {c['verb']} {c['path']}",
        })
    return {"nodes": [], "edges": edges, "hyperedges": []}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", metavar="PATH", help="записать рёбра для графа")
    args = ap.parse_args()

    pairs, orphan_calls, orphan_routes = match()
    print(f"Сошлось:            {len(pairs)} пар (клиент -> сервер)")
    print(f"Клиент зовёт в пустоту: {len(orphan_calls)}")
    print(f"Сервер никто не зовёт:  {len(orphan_routes)}")

    if orphan_calls:
        print("\n── вызовы без обработчика (проверить вручную) ──")
        for c in orphan_calls[:25]:
            print(f"  {c['verb']:6} {c['path']:52} <- {c['fn']} (L{c['line']})")
        if len(orphan_calls) > 25:
            print(f"  … ещё {len(orphan_calls) - 25}")

    if args.json:
        Path(args.json).write_text(
            json.dumps(to_graph_edges(pairs), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"\nРёбра записаны: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
