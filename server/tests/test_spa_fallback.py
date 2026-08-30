# -*- coding: utf-8 -*-
"""Заглушка сайта не должна проглатывать адреса API.

🔥 Куплено дважды за один час 29.08.2026, причём на собственных тестах. Проверки
второго фактора стучались в «/me» и «/web/admin/users» — таких маршрутов НЕТ, —
и катч-олл Vue отвечал им 200 и страницей. Тесты «проходили», не дойдя до кода.
Зелёный тест, не достигший проверяемого места, хуже отсутствующего: он создаёт
уверенность там, где её нет.

Тот же дефект уже стоил боевого отказа: канал «Расписание · Группа» для группы со
слэшем в названии не открывался, потому что клиент получал HTML вместо JSON
(CLAUDE.md, 3.8).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import _is_api_path, app  # noqa: E402


def _all_paths(router):
    """Полный обход. ⚠️ Плоского перебора НЕ ХВАТАЕТ — см. §16 и `_IncludedRouter`."""
    out = []
    for r in getattr(router, "routes", []):
        path = getattr(r, "path", "")
        if path:
            out.append(path)
        nested = getattr(r, "original_router", None) or (r if hasattr(r, "routes") else None)
        if nested is not None and nested is not router:
            out.extend(_all_paths(nested))
    return out


@pytest.mark.parametrize("path", [
    "/web/admin/users",          # адрес, на котором обжёгся тест второго фактора
    "/me",                       # и второй такой же
    "/auth/nonexistent",
    "/web/student/nothing-here",
    "/sync/whatever",
])
def test_unknown_api_paths_answer_404_and_not_a_page(client, path):
    r = client.get(path)
    assert r.status_code == 404, (
        f"{path} отдал {r.status_code} вместо 404 — значит опечатка в адресе "
        f"выглядит как успех и для клиента, и для теста"
    )
    assert "text/html" not in r.headers.get("content-type", ""), (
        "на месте JSON пришла страница — клиент сломается на разборе, "
        "а причину будет искать в своём коде"
    )


#Корни разделов SPA — РЕАЛЬНЫЕ, из `web/src/router/index.js`. Не выдуманные: см.
#объяснение в тесте ниже.
_SPA_ROOTS = ("/", "/login", "/reset-password", "/connect", "/404",
              "/student", "/teacher", "/admin", "/parent",
              "/student/journal", "/teacher/students", "/admin/groups", "/admin/settings")


@pytest.mark.parametrize("path", _SPA_ROOTS)
def test_the_site_itself_still_opens(client, path):
    """Обратная сторона: адреса САЙТА обязаны отдавать страницу, а не JSON.

    Без этой проверки достаточно расширить список префиксов до «всего», и клиентский
    роутинг Vue перестанет работать целиком — а заметят это люди, а не мы.

    🔥 ЗДЕСЬ СТОЯЛИ ВЫДУМАННЫЕ АДРЕСА, И ИМЕННО ПОЭТОМУ ТЕСТ МОЛЧАЛ. Проверялись
    `/login`, `/dashboard` и `/messenger/42`; последних двух в роутере НЕТ ВООБЩЕ, они
    ни с чем не сталкивались и проходили всегда. Ни одного из четырёх настоящих корней
    ролей в списке не было — и когда «admin» попал в префиксы API, вся админка стала
    отдавать `{"detail":"Неизвестный адрес API"}` при зелёном наборе из 1201 теста.
    Тот же класс промаха, что с группой «К-24» вместо «К74/1»: проверка не того случая.
    Поэтому список ниже — РЕАЛЬНЫЕ маршруты SPA, и трогать его можно только вслед за
    `web/src/router/index.js`.
    """
    r = client.get(path)
    assert r.status_code == 200, (
        f"{path} — адрес страницы сайта, а сервер ответил {r.status_code}. "
        "Значит приложение не загрузится вовсе: ни оболочки, ни проверки роли, "
        "ни человеческой страницы «раздел не ваш» — голый JSON в окне браузера.")
    assert r.headers["content-type"].startswith("text/html"), (
        f"{path} отдан как {r.headers['content-type']}, а должен быть страницей. "
        "Код 200 сам по себе ничего не значит: JSON с кодом 200 сломает клиент так же.")


def test_no_api_route_lives_outside_the_prefix_list():
    """Список префиксов не имеет права отстать от подключённых роутеров.

    ⚠️ Проверяем СВОЙСТВО: каждый существующий маршрут API попадает под какой-то
    префикс. Иначе новый роутер с новым префиксом окажется снаружи, и его
    неизвестные адреса снова начнут отвечать страницей — молча.
    """
    skipped = []
    for path in sorted(set(_all_paths(app))):
        p = path.lstrip("/")
        if not p or p.startswith("{") or p.startswith("assets") or p.startswith("downloads"):
            continue          # катч-олл, статика и раздача файлов — не API
        if p.startswith("desktop-info") or p.startswith("public/") or p.startswith("favicon"):
            continue
        if not _is_api_path(p):
            skipped.append(path)
    assert not skipped, (
        "эти маршруты API не попадают ни под один префикс — их неизвестные соседи "
        "будут отвечать страницей вместо 404:\n  " + "\n  ".join(skipped)
        + "\nДополни _API_PREFIXES в server/app/main.py."
    )
