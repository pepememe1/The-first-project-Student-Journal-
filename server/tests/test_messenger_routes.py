"""
test_messenger_routes.py — мессенджер разрезан на пакет, и порядок маршрутов от этого
не должен меняться по смыслу (3.7.7).

━━ ЧТО ИМЕННО ОХРАНЯЕТСЯ ━━
`routers/messenger.py` был одним файлом на 3543 строки; теперь это пакет из восьми
модулей, и все они дописывают маршруты в ОДИН объект `router`. Порядок регистрации
задаётся порядком импорта в `__init__.py`, то есть тем, что раньше задавалось порядком
строк в файле. FastAPI отдаёт запрос ПЕРВОМУ подошедшему маршруту — значит перестановка
модулей местами способна тихо увести запрос не туда.

Это не теория: у активностей `GET /{activity_id}` объявили выше остальных, и `/quizzes`,
`/journal`, `/boards` начали отвечать «Активность не найдена» при исправном коде и
зелёных тестах на сами эти эндпоинты (см. `test_single_segment_routes_are_not_shadowed`).

Здесь проверяется СВОЙСТВО, а не список: ни один буквальный путь не должен быть
перехвачен ранее зарегистрированным путём с параметром ТОГО ЖЕ метода. Список маршрутов
меняется каждый заход, а свойство — нет.
"""
import re

import pytest

from app.main import app


def _routes():
    """Плоский список (метод, путь) с разворотом подключённых роутеров.

    ⚠️ Плоским обходом `app.routes` этого не сделать: в текущей версии FastAPI
    подключённый роутер лежит объектом `_IncludedRouter` — без `path` и без `routes`,
    настоящие маршруты у него в `original_router`. Тест, написанный «в лоб», собрал бы
    два десятка объектов вместо трёх сотен маршрутов и был бы зелёным всегда.
    """
    out = []

    def walk(routes, prefix=""):
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:
                walk(inner.routes, prefix + getattr(r, "prefix", ""))
                continue
            sub = getattr(r, "routes", None)
            if sub and not hasattr(r, "methods"):
                walk(sub, prefix + getattr(r, "path", ""))
                continue
            path = prefix + (getattr(r, "path", "") or "")
            for m in (getattr(r, "methods", None) or {"WEBSOCKET"}):
                out.append((m, path))

    walk(app.routes)
    return out


def _to_regex(path: str) -> re.Pattern:
    """Путь с параметрами → регулярка. `{x}` — ровно один сегмент, `{x:path}` — любой."""
    parts, i = [], 0
    for m in re.finditer(r"\{([^}]+)\}", path):
        parts.append(re.escape(path[i:m.start()]))
        parts.append(".+" if m.group(1).endswith(":path") else "[^/]+")
        i = m.end()
    parts.append(re.escape(path[i:]))
    return re.compile("^" + "".join(parts) + "$")


MESSENGER = ("/web/messenger", "/web/admin/messenger")


def test_no_literal_messenger_route_is_shadowed_by_an_earlier_parametrised_one():
    routes = [(m, p) for m, p in _routes() if p.startswith(MESSENGER)]
    assert routes, "маршруты мессенджера не найдены — обход таблицы сломан"

    problems = []
    for i, (method, path) in enumerate(routes):
        if "{" in path:                       # проверяем только БУКВАЛЬНЫЕ пути
            continue
        for earlier_method, earlier in routes[:i]:
            if "{" not in earlier or earlier_method != method:
                continue
            if _to_regex(earlier).match(path):
                problems.append(f"{method} {path} перехватывается ранее "
                                f"зарегистрированным {earlier_method} {earlier}")
    assert not problems, (
        "Маршрут с параметром зарегистрирован РАНЬШЕ буквального и заберёт его запросы "
        "себе. Поменяй порядок импорта модулей в routers/messenger/__init__.py:\n  "
        + "\n  ".join(problems))


def test_both_routers_are_still_reachable_after_the_split():
    """Разрез не имеет права потерять целый роутер: у модерации СВОЙ префикс.

    Оба `DELETE /messages/{mid}` (обычное удаление и модераторское) выглядят одинаково
    и различаются ТОЛЬКО префиксом роутера. Потеряйся `mod_router` при сборке пакета —
    админ молча лишился бы удаления чужого сообщения, а тесты на обычное удаление
    остались бы зелёными.
    """
    paths = {p for _, p in _routes()}
    assert "/web/messenger/chats/{conv_id}/messages" in paths
    assert "/web/admin/messenger/messages/{mid}" in paths
    assert "/web/messenger/ws" in paths


@pytest.mark.parametrize("name", [
    "router", "mod_router", "ws_manager",
    "SYSTEM_SENDER_ID", "SYSTEM_SENDER_NAME",
    "_permissions_for", "_guard_can_write",      # их импортируют активности
])
def test_public_names_survived_the_split(name):
    """Пакет обязан отдавать наружу то же, что отдавал файл.

    ⚠️ Первая версия скрипта-разрезалки собирала только `def`/`class` и МОЛЧА теряла 29
    констант, объявленных между функциями, — включая `ws_manager`, то есть сам реестр
    веб-сокетов. Приложение тогда просто не импортировалось; но потеряйся что-то менее
    заметное, оно уехало бы на бой. Имена ниже — те, что зовут ИЗВНЕ пакета.
    """
    from app.routers import messenger
    assert hasattr(messenger, name), f"после разреза потерялось имя {name}"
