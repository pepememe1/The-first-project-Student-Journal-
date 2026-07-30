"""
test_vue_shell.py — правила показа ОБЩЕГО Vue-интерфейса внутри десктопа.

Проверяем не отрисовку (для этого нужен полноценный веб-движок), а решения, из-за
которых человек уже видел форму входа вместо своей статистики: КОГДА грузим страницу,
КАКОЙ логин берём и ЧТО делаем, если локальная копия базы ещё не готова.
"""
import inspect
import json
import re

import vue_shell


def _shell(role="student"):
    """VueShell без Qt-конструктора: проверяем решения, а не отрисовку."""
    sh = vue_shell.VueShell.__new__(vue_shell.VueShell)
    sh._role = role
    sh._embed = True
    sh._api_base = ""
    sh._local_tokens = ("acc", "ref")
    return sh


def test_user_goes_to_storage_as_string(monkeypatch):
    """`gb.user` обязан лечь в localStorage СТРОКОЙ.

    Ловит опечатку ценой в целую вкладку: с одним json.dumps в страницу попадал
    объектный литерал JS, браузер сохранял его как «[object Object]», разбор падал —
    и SPA показывала форму входа человеку, который уже вошёл. Внешне это выглядело как
    «локальный сервер не пускает», хотя сервер был совершенно ни при чём."""
    monkeypatch.setattr(vue_shell.VueShell, "_current_login", staticmethod(lambda: "ivanov"))
    js = _shell()._bootstrap_js()
    raw = re.search(r"localStorage\.setItem\('gb\.user',(.+?)\);", js).group(1)
    assert raw.startswith('"'), "значение обязано быть строковым литералом JS"
    user = json.loads(json.loads(raw))          # как это сделает сама SPA
    assert user["login"] == "ivanov" and user["role"] == "student"


def test_embed_mode_is_a_known_string(monkeypatch):
    """Режимов встраивания ТРИ, и SPA различает их по строке: '1' — одна страница,
    'nav' — весь кабинет (меню своё, шапка от окна), '0' — обычный сайт. Булево значение
    сюда попасть не должно: в JS оно превратится в `true`, а такого режима нет."""
    monkeypatch.setattr(vue_shell.VueShell, "_current_login", staticmethod(lambda: "ivanov"))
    for given, expected in ((True, "1"), ("nav", "nav"), (False, "0")):
        sh = _shell()
        sh._embed = vue_shell.VueShell._embed_mode(given)
        js = sh._bootstrap_js()
        assert f"localStorage.setItem('gb.embed',\"{expected}\")" in js


def test_page_loads_lazily_on_first_show():
    """Вкладки собираются сразу после входа — в этот момент живого токена может ещё не
    быть, и локальная сессия выпускалась на пустой логин. Грузим при первом ПОКАЗЕ."""
    assert hasattr(vue_shell.VueShell, "showEvent")
    src = inspect.getsource(vue_shell.VueShell.showEvent)
    assert "_build()" in src, "страница обязана грузиться при показе, а не в конструкторе"
    init = inspect.getsource(vue_shell.VueShell.__init__)
    assert "self._build()" not in init, "загрузка в конструкторе возвращает старый баг"


def test_login_falls_back_to_saved_session(monkeypatch):
    """Живого токена может не быть вовсе (офлайн). Сохранённая сессия есть всегда,
    когда человек в программу вошёл, — на неё и опираемся."""
    import app_settings
    monkeypatch.setattr("sync_runner.fresh_auth", lambda: ("", ""))
    monkeypatch.setattr(app_settings, "get_saved_session", lambda: {"login": "ivanov",
                                                                    "role": "student"})
    assert vue_shell.VueShell._current_login() == "ivanov"


def test_no_local_user_means_no_local_session(monkeypatch):
    """Нет человека в локальной копии — локальную сессию НЕ выпускаем: вкладка уйдёт на
    боевой сервер и покажет данные, а не форму входа."""
    import local_api
    monkeypatch.setattr(vue_shell.VueShell, "_current_login", staticmethod(lambda: "ivanov"))
    monkeypatch.setattr(local_api, "user_exists", lambda login: False)
    called = []
    monkeypatch.setattr(local_api, "issue_local_session",
                        lambda *a: called.append(a) or ("a", "r"))
    shell = vue_shell.VueShell.__new__(vue_shell.VueShell)
    shell._role = "student"
    assert shell._issue_local_session() == ("", "")
    assert not called, "сессию для отсутствующего человека выпускать бессмысленно"
