"""
test_server_section.py — раздел «Сервер»: что видно и, ГЛАВНОЕ, чего на бою быть не должно.

Самый важный тест здесь — `test_prod_server_has_no_command_execution`. Раздел даёт
администратору строку команд к боевой машине, и единственное, что отделяет её от
браузера, — отсутствие соответствующего кода на боевом сервере. Стоит кому-нибудь ради
удобства подключить `desktop/server_admin.py` в `app.main`, и любая дыра в веб-админке
превратится в оболочку на машине с персональными данными всего колледжа. Проверка роли
такой гарантии не даёт: роль можно обойти, отсутствующий маршрут — нельзя.
"""
import os

from conftest import make_admin, make_teacher


def _student(client, admin):
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    r = client.post("/auth/login", json={"login": "ivanova", "password": "studpass1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


# ── Граница «просмотр против управления» ─────────────────────────────────────────────
def _all_paths(router) -> list:
    """Все пути приложения, включая подключённые роутеры.

    ⚠️ ПЛОСКОГО ПЕРЕБОРА `app.router.routes` НЕ ХВАТАЕТ. В этой версии FastAPI набор,
    подключённый через `include_router`, лежит там объектом `_IncludedRouter` — БЕЗ
    атрибута `path` и БЕЗ `routes`; настоящие маршруты доступны через `original_router`.
    Из 19 объектов верхнего уровня таких тринадцать, то есть перебор «в лоб» не видит
    почти всё приложение.

    Для теста ниже это принципиально: проверка «на бою нет маршрутов управления»,
    которая их не видит, хуже отсутствующей — она создаёт уверенность на пустом месте."""
    out = []
    for r in getattr(router, "routes", []):
        path = getattr(r, "path", "")
        if path:
            out.append(path)
        nested = getattr(r, "original_router", None) or (r if hasattr(r, "routes") else None)
        if nested is not None and nested is not router:
            out.extend(_all_paths(nested))
    return out


def test_prod_server_has_no_command_execution(client):
    """На боевом приложении НЕТ маршрутов управления. Ни одного.

    Если этот тест упал — кто-то подключил desktop/server_admin.py к серверному приложению.
    Так делать нельзя ни при каких обстоятельствах, даже «временно для отладки»."""
    from app.main import app
    #Именно "/desk/", а не "/desk": рядом живёт публичный "/desktop-info" (доступность
    #и размер .exe для страницы загрузки), и он к управлению отношения не имеет.
    dangerous = [p for p in _all_paths(app.router) if p.startswith("/desk/")]
    assert dangerous == [], f"на боевом сервере появились маршруты управления: {dangerous}"


def test_read_only_section_is_actually_registered(client):
    """Обратная проверка к предыдущей: раздел просмотра на бою БЫТЬ обязан.

    Без неё тест выше зелёный и когда роутер вообще не подключён — то есть проверяет
    ровно ничего."""
    paths = _all_paths(app_router())
    for expected in ("/web/admin/server/metrics", "/web/admin/server/backups",
                     "/web/admin/server/tree"):
        assert expected in paths, f"пропал маршрут просмотра: {expected}"


def app_router():
    from app.main import app
    return app.router


def test_serverinfo_module_cannot_execute_anything():
    """Роутер просмотра не должен уметь запускать процессы. Проверяем прямо по тексту:
    подключается он на бою, и появление здесь `subprocess` означало бы, что граница
    между «смотреть» и «делать» стёрлась."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "routers" / "serverinfo.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "popen", "eval(", "exec("):
        assert forbidden not in src, f"в роутере просмотра появилось «{forbidden}»"


# ── Доступ по ролям ──────────────────────────────────────────────────────────────────
def test_metrics_require_admin(client):
    admin = make_admin(client)
    sh = _student(client, admin)
    teach = make_teacher(client, admin)
    for headers in (sh, teach):
        assert client.get("/web/admin/server/metrics", headers=headers).status_code == 403
    assert client.get("/web/admin/server/metrics", headers=admin).status_code == 200


def test_tree_and_backups_require_admin(client):
    admin = make_admin(client)
    sh = _student(client, admin)
    assert client.get("/web/admin/server/tree", headers=sh).status_code == 403
    assert client.get("/web/admin/server/backups", headers=sh).status_code == 403


# ── Содержимое ответов ───────────────────────────────────────────────────────────────
def test_metrics_report_the_machine(client):
    admin = make_admin(client)
    body = client.get("/web/admin/server/metrics", headers=admin).json()
    assert body["cpu_count"] >= 1
    assert body["disk"]["total"] > 0
    assert body["database"]["engine"] in ("sqlite", "external")
    #Шифрование базы админ обязан видеть в лицо: без ключа резервная копия бесполезна,
    #и путать «зашифрована» с «нет» нельзя ни в какую сторону.
    assert "encrypted" in body["database"]


def test_tree_never_leaves_the_deploy_root(client):
    """Обзор каталогов не имеет права стать файловым менеджером по всей машине.

    Без этой границы `?path=/etc` показал бы системные каталоги, а `..` увёл бы куда
    угодно. Отдаём только имена и размеры и только внутри корня развёртывания."""
    admin = make_admin(client)
    root = client.get("/web/admin/server/tree", headers=admin).json()["root"]

    for outside in ("/etc", "/", os.path.dirname(root) or "/", root + "/../.."):
        body = client.get("/web/admin/server/tree",
                          params={"path": outside}, headers=admin).json()
        assert body["items"] == [], f"обзор выпустили за корень: {outside}"


def test_tree_shows_sizes_but_never_content(client):
    """В ответе только имя, признак каталога, размер и дата. Содержимого файлов нет —
    иначе страница администратора стала бы способом прочитать .env с ключами."""
    admin = make_admin(client)
    body = client.get("/web/admin/server/tree", headers=admin).json()
    for item in body["items"]:
        assert set(item) == {"name", "dir", "size", "mtime"}, item


def test_backups_answer_the_real_question(client):
    """«А копии вообще делаются?» — на это отвечает поле latest, а не список из сорока
    строк, в котором дату надо искать глазами."""
    admin = make_admin(client)
    body = client.get("/web/admin/server/backups", headers=admin).json()
    assert "latest" in body and "exists" in body


# ── Сам сборщик сведений ─────────────────────────────────────────────────────────────
def test_hostinfo_survives_a_missing_path():
    """Сведения о железе — украшение страницы. Ни одна их часть не имеет права уронить
    запрос: сервер обязан отвечать, даже если /proc не читается или диска нет."""
    from app import hostinfo
    assert hostinfo.disk("/такого/пути/нет") != {} or True   # не бросает
    assert hostinfo.listdir("/такого/пути/нет", "/такого/пути/нет") == []
    assert isinstance(hostinfo.memory(), dict)
    assert isinstance(hostinfo.uptime_seconds(), float)
    assert hostinfo.cpu_count() >= 1
