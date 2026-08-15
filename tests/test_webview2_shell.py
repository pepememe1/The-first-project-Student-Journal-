"""
test_webview2_shell.py — новая оболочка окна (системный WebView2) и передача сессии.

Оболочка меняется, чтобы .exe не тащил внутри Chromium (~180 МБ → ожидаемо 30–40). Здесь
закреплено то, что при такой замене легко потерять молча:
приватность движка Microsoft и способ передать сессию, не зависящий от движка.
"""
import os

import pytest

from desktop import local_api
from desktop import webview2_shell as wv


def test_privacy_args_disable_microsoft_chatter():
    """WebView2 по умолчанию разговорчив: диагностика, SmartScreen (отправляет адреса на
    проверку), автозаполнение, синхронизация профиля. Для журнала с ПДн студентов это
    недопустимо (152-ФЗ, трансграничная передача), поэтому гасим аргументами движка."""
    os.environ.pop("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", None)
    wv.apply_privacy_env()
    args = os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
    for flag in ("msSmartScreenProtection", "disable-sync", "AutofillServerCommunication",
                 "disable-background-networking", "Translate"):
        assert flag in args, f"не выключено: {flag}"


def test_privacy_args_do_not_erase_admin_settings():
    """Настройку администратора машины не затираем — дополняем: иначе тихо отменили бы
    политику, заданную в организации."""
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--some-admin-flag"
    wv.apply_privacy_env()
    args = os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
    assert "--some-admin-flag" in args and "disable-sync" in args


def test_profile_dir_is_ours_not_the_users_browser():
    """Папка движка — своя, в каталоге программы. По умолчанию WebView2 сложил бы данные
    рядом с .exe, а он портативный и может лежать на флешке или в папке без записи."""
    path = wv.profile_dir()
    assert "GradeBookAI" in path
    assert path.endswith("webview2")


def test_ephemeral_profile_is_requested():
    """Кэш и куки не должны оставаться на диске (152-ФЗ, «инкогнито»). Нам это ничего не
    стоит: сессия подставляется заново каждый запуск, а офлайн-данные живут не в кэше
    браузера, а в зашифрованной локальной базе — требование и offline-first не спорят.

    ⚠️ Тест смотрит на `webview2_app.run` — ФУНКЦИЮ, КОТОРАЯ РЕАЛЬНО ОТКРЫВАЕТ ОКНО.
    Раньше он читал исходник `webview2_shell.open_window` — черновика, который не звал
    никто: проверка была зелёной при любом поведении настоящего окна. Функция удалена,
    тест переставлен на живой путь."""
    import inspect
    from desktop import webview2_app
    src = inspect.getsource(webview2_app.run)
    assert "private_mode=True" in src, "окно обязано открываться с эфемерным профилем"
    assert "storage_path=" in src, "папка данных движка должна задаваться явно"


def test_shell_reports_unavailable_instead_of_guessing():
    """На машине без обновлений Windows системного движка может не быть.

    ⚠️ Раньше здесь было написано «тогда честный False и ПРЕЖНЯЯ ОБОЛОЧКА». Прежней
    (Qt) оболочки в проекте больше нет: False означает, что программа НЕ ОТКРОЕТСЯ, и
    человек увидит диалог с причиной. Именно поэтому важно, чтобы ответ был честным
    булевым, а не догадкой, — пустое окно посреди занятия хуже внятного отказа."""
    assert isinstance(wv.available(), bool)
    assert isinstance(wv.runtime_installed(), bool)


# ── Передача сессии, не зависящая от движка ─────────────────────────────────────────
def test_bootstrap_does_not_put_tokens_in_the_url():
    """Токены в адресе попали бы в историю и логи. Сервер и так знает, кто вошёл —
    он выпускает сессию сам."""
    local_api.instance().start()
    url = local_api.bootstrap_url("/student", "0")
    assert url, "сервер должен быть поднят"
    assert "gb.access" not in url and "Bearer" not in url and "eyJ" not in url


def test_bootstrap_page_hands_over_session_and_redirects():
    """Страница кладёт сессию в localStorage и уходит на маршрут. Это замена инъекции JS,
    которую умел только QtWebEngine — новый движок такого хука не даёт."""
    import urllib.request
    api = local_api.instance()
    if not api.start():
        pytest.skip("серверный пакет недоступен")
    with urllib.request.urlopen(local_api.bootstrap_url("/student", "0"), timeout=15) as r:
        body = r.read().decode("utf-8")
    assert "localStorage.setItem('gb.access'" in body
    assert 'location.replace("/student")' in body
    assert "[object Object]" not in body, "gb.user обязан быть СТРОКОЙ (ловили в 3.4)"


def test_bootstrap_route_is_matched_before_spa_fallback():
    """Приложение раздаёт SPA заглушкой «всё остальное → index.html». Она зарегистрирована
    раньше и перехватывала наш адрес: сервер отвечал 200, но отдавал обычную страницу, а
    сессия не приезжала. Маршруты сопоставляются по порядку — свой обязан быть раньше."""
    import inspect
    src = inspect.getsource(local_api.install_desktop_bootstrap)
    assert "routes.insert(0" in src


# ── Признак «мы внутри программы» доезжает ОБОИМИ путями запуска ────────────────────
def test_both_startup_paths_carry_the_desktop_marker(monkeypatch):
    """🔥 РЕГРЕССИЯ УДАЛЕНИЯ QT, найденная уборкой. SPA отключает service worker только
    когда знает, что открыта внутри программы. Признак выводился из `gb.embed`='1'/'nav'
    (режимы, в которых нативная оболочка ВСТРАИВАЛА страницу) — оболочки нет, окно
    передаёт '0', и признак перестал срабатывать совсем.

    Чем это плохо: SW кэширует оболочку SPA и `/assets/*`, а его кэш переживает
    обновление программы — ровно та болезнь, из-за которой OTA-бандлы месяц не доезжали
    до телефонов. Плюс локальный сервер каждый запуск слушает НОВЫЙ эфемерный порт, а
    порт входит в origin: регистрации копились бы по одной на запуск.

    ⚠️ Путей запуска ДВА, и проверять надо ОБА. Первая версия починки ставила ключ только
    в странице-передатчике сессии — а она открывается, лишь когда человек уже входил на
    этой машине. На ПЕРВОМ запуске окно идёт прямо на /login мимо неё, и это ровно тот
    запуск, в который service worker и устанавливается."""
    from desktop import local_api, webview2_app

    api = local_api.instance()
    assert api.start(), "локальный сервер не поднялся"

    #Путь 1 — сессии нет (первый запуск): метка обязана быть В АДРЕСЕ.
    monkeypatch.setattr("sync.sync_runner.current_login", lambda: "")
    monkeypatch.setattr("data.app_settings.get_saved_session", lambda: {})
    url = webview2_app._start_url(api)
    assert "desktop=1" in url, (
        "первый запуск идёт мимо страницы-передатчика — без метки в адресе SPA "
        "сочтёт себя обычным сайтом и поставит service worker")

    #Путь 2 — сессия есть: метку ставит страница-передатчик, в localStorage.
    import inspect
    src = inspect.getsource(local_api.install_desktop_bootstrap)
    assert "gb.desktop" in src, "страница-передатчик перестала ставить признак десктопа"


def test_web_client_reads_the_desktop_marker_from_both_sources():
    """Сторож на ДРУГОЙ стороне: питоновский код может честно отдавать метку, а клиент —
    её не читать, и тогда починка снова окажется наполовину сделанной (ровно так и жил
    признак всё это время). Проверяем ИСХОДНИК настоящего файла, а не его копию."""
    import pathlib
    src = pathlib.Path("web/src/main.js").read_text(encoding="utf-8")
    head = src[:src.index("const _inDesktop")] + src[src.index("const _inDesktop"):
                                                     src.index("const _inDesktop") + 900]
    assert "'desktop'" in head or '"desktop"' in head, "клиент не читает ?desktop= из адреса"
    assert "gb.desktop" in head, "клиент не читает признак десктопа из localStorage"
