"""
test_route_policy.py — сторож КЛАССА «в программе раздел пишет в пустоту или читает
пустоту» (аудит 22.09.2026, находка F-02, P1).

Дефект был не в одном маршруте: из 193 маршрутов записи сервера 86 обслуживались
локальной копией программы, и у большинства не было пути на бой — оценки, расписание,
курсы, согласие на доступ родителя, второй фактор. Чинить поштучно значило бы оставить
следующий маршрут тем же дефектом. Поэтому здесь свойства по ВСЕМ маршрутам сервера:

  • у каждой строки REPLAY/LOCAL есть живой маршрут (мёртвая запись — ложная уверенность);
  • ни одну из них не перекрывает пересылка `_PROXY_PREFIXES` (иначе строка не значит
    ничего: запрос уйдёт на бой раньше, чем до неё дойдёт);
  • журнал преподавателя пишется офлайн (REPLAY), а неизвестная запись — на бой;
  • раздел, читающий таблицы БЕЗ зеркала, пересылается целиком — иначе в программе он
    открывается пустым (курсы, связи родителя, ачивки — ровно так и было);
  • префикс пересылки не совпадает ни со страницей SPA: иначе перезагрузка страницы
    уходила бы на бой и возвращала чужую оболочку сайта.

Обратный ход (проверен): вычеркнуть "/web/courses" из `_PROXY_PREFIXES` — краснеет
`test_sections_without_mirror_are_proxied_whole`; дописать в REPLAY выдуманный путь —
краснеет `test_every_policy_row_has_a_live_route`.
"""
import inspect
import re

import pytest

from desktop import local_api, route_policy

WRITE = ("POST", "PUT", "PATCH", "DELETE")


@pytest.fixture(scope="module")
def routes():
    local_api.prepare_env()
    from fastapi.routing import APIRoute
    from app import main

    def walk(rs):
        for r in rs:
            if isinstance(r, APIRoute):
                yield r
            elif hasattr(r, "original_router"):
                yield from walk(r.original_router.routes)
            elif hasattr(r, "routes"):
                yield from walk(r.routes)

    out = list(walk(main.app.router.routes))
    assert len(out) > 150, "маршрутов подозрительно мало — разбор сломался"
    return out


def _sample(path_template: str) -> str:
    """Шаблон маршрута → конкретный путь для сопоставления с правилами."""
    return re.sub(r"\{[^}]+\}", "x", path_template)


def test_every_policy_row_has_a_live_route(routes):
    live = {(m, _sample(r.path)) for r in routes for m in r.methods}
    dead = []
    for spec in route_policy.REPLAY:
        rx = re.compile(spec["path"] + r"\Z")
        if not any(m == spec["method"] and rx.match(p) for m, p in live):
            dead.append(("REPLAY", spec["method"], spec["path"]))
    for (method, pattern), why in route_policy.LOCAL.items():
        assert why.strip(), f"у LOCAL {method} {pattern} нет причины"
        rx = re.compile(pattern + r"\Z")
        if not any(m == method and rx.match(p) for m, p in live):
            dead.append(("LOCAL", method, pattern))
    assert not dead, f"строки политики без живого маршрута: {dead}"


def test_no_policy_row_is_shadowed_by_the_proxy():
    shadowed = [spec["path"] for spec in route_policy.REPLAY
                if _sample(spec["path"].replace("[^/]+", "x")).startswith(
                    local_api._PROXY_PREFIXES)]
    shadowed += [p for (_m, p) in route_policy.LOCAL
                 if _sample(p.replace("[^/]+", "x")).startswith(local_api._PROXY_PREFIXES)]
    assert not shadowed, f"эти строки политики перекрыты пересылкой и не действуют: {shadowed}"


@pytest.mark.parametrize("method,path", [
    ("POST", "/web/teacher/grade"), ("POST", "/web/teacher/lesson"),
    ("PUT", "/web/teacher/lesson/abc"), ("DELETE", "/web/teacher/lesson/abc"),
    ("POST", "/web/teacher/term-grade"),
])
def test_teacher_journal_is_written_offline(method, path):
    assert route_policy.classify(method, path) == "replay"


def test_unknown_write_goes_to_the_server_and_reads_stay_local():
    assert route_policy.classify("POST", "/web/admin/groups") == "proxy"
    assert route_policy.classify("POST", "/web/teacher/grade-import") == "proxy", (
        "похожий, но другой путь не должен молча стать офлайновым")
    assert route_policy.classify("GET", "/web/teacher/journal") == "read"


def test_every_local_write_route_is_classified(routes):
    """Каждая запись сервера, не ушедшая в пересылку целиком, получает политику.
    Классификатор отвечает всегда (умолчание — «на бой»), поэтому проверяется главное:
    журнал — офлайн, локальными остаются только перечисленные с причиной."""
    local_writes = [(m, _sample(r.path)) for r in routes for m in r.methods
                    if m in WRITE and not r.path.startswith(local_api._PROXY_PREFIXES)]
    kinds = {route_policy.classify(m, p) for m, p in local_writes}
    assert kinds <= {"replay", "local", "proxy"}
    offline = sorted(p for m, p in local_writes
                     if route_policy.classify(m, p) in ("replay", "local"))
    #⚠️ `/desk/*` и `/desktop/*` — маршруты самой программы: на бою их нет вовсе, и
    #политика «локально» записана за ними в `route_policy` с причиной. Список берём ИЗ
    #ПРОДУКТА. До 26.09.2026 его здесь не было, и тест краснел ТОЛЬКО в общем прогоне:
    #эти маршруты ставит на общее приложение `local_api.start()`, то есть появлялись
    #они лишь после `test_local_api.py`, а в одиночном запуске их не было.
    allowed = ("/web/teacher/", "/auth/", "/connect/", "/web/vector/", "/vector/",
               "/sync/") + tuple(route_policy.DESKTOP_OWN_PREFIXES)
    assert all(p.startswith(allowed) for p in offline), offline


def test_sections_without_mirror_are_proxied_whole(routes):
    """GET, читающий таблицу БЕЗ зеркала, внутри программы вернул бы пустоту."""
    local_api.prepare_env()
    from app import models
    synced = {m.__name__ for m in models.SYNC_MODELS.values()}
    #Таблицы, которые читают многие ручки попутно и которые НЕ означают «раздел без
    #зеркала»: пользователь (он в зеркале), сессии входа локального сервера (своя
    #локальная сессия программы — так и задумано).
    incidental = {"User", "AuthSession"}
    names = {n for n, o in vars(models).items()
             if isinstance(o, type) and hasattr(o, "__tablename__")}
    unsynced = names - synced - incidental
    offenders = []
    for r in routes:
        if "GET" not in r.methods or r.path.startswith(local_api._PROXY_PREFIXES):
            continue
        try:
            src = inspect.getsource(r.endpoint)
        except (OSError, TypeError):
            continue
        used = sorted(n for n in unsynced if re.search(r"\b%s\b" % n, src))
        if used:
            offenders.append(f"{r.path} → {', '.join(used)}")
    assert not offenders, (
        "эти разделы читают таблицы без зеркала и в программе откроются пустыми — "
        "добавь префикс в local_api._PROXY_PREFIXES:\n  " + "\n  ".join(offenders))


def test_proxy_prefixes_never_capture_a_page_of_the_spa():
    """Перезагрузка страницы в программе идёт на локальный сервер. Префикс, совпавший с
    путём страницы, отправил бы её на бой, и вместо кабинета пришла бы оболочка сайта."""
    import pathlib
    router = (pathlib.Path(local_api.__file__).resolve().parents[1]
              / "web" / "src" / "router" / "index.js").read_text(encoding="utf-8")
    tops = set(re.findall(r"path: '(/[^']*)'", router))
    #Дочерние страницы: '/admin' + page('teachers', …) → '/admin/teachers'.
    pages = set(tops)
    for block in re.findall(r"path: '(/[a-z]+)'[^\n]*\n\s*children: \[(.*?)\n\s*\]",
                            router, re.S):
        base, body = block
        for child in re.findall(r"(?:page\('|path: ')([a-z][^'/:]*)", body):
            pages.add(f"{base}/{child}")
    assert len(pages) > 20, "страниц SPA подозрительно мало — разбор роутера сломался"
    clash = sorted(p for p in pages if p.startswith(local_api._PROXY_PREFIXES))
    assert not clash, f"префиксы пересылки захватывают страницы SPA: {clash}"


def test_every_proxy_prefix_has_a_live_route(routes):
    paths = [_sample(r.path) for r in routes]
    dead = [p for p in local_api._PROXY_PREFIXES
            if not any(x.startswith(p) for x in paths)]
    assert not dead, f"префиксы пересылки без живых маршрутов: {dead}"
