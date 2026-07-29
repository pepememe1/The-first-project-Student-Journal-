"""
test_vue_shell.py — правила показа ОБЩЕГО Vue-интерфейса внутри десктопа.

Проверяем не отрисовку (для этого нужен полноценный веб-движок), а решения, из-за
которых человек уже видел форму входа вместо своей статистики: КОГДА грузим страницу,
КАКОЙ логин берём и ЧТО делаем, если локальная копия базы ещё не готова.
"""
import inspect

import vue_shell


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
