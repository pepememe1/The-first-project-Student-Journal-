"""Окно программы обязано разрешать загрузки — иначе выгрузки Excel/Word молча пропадают.

Живой прогон 01.10.2026: «Экспорт → Excel» в программе отрабатывал без ошибки, файл не
появлялся. pywebview по умолчанию держит `settings['ALLOW_DOWNLOADS'] = False` и отменяет
каждую загрузку. Проверено живым окном WebView2 02.10.2026: без флага файла нет, с флагом
blob-выгрузка (ровно `saveBlob` журнала, с немедленным `revokeObjectURL`) доходит до диска.
"""
import ast
import collections
import inspect
import textwrap
import types

from desktop import webview2_app


class _ImmutableDictLike(collections.UserDict):
    """Как `webview.util.ImmutableDict`: НЕ подкласс dict. Первая версия правки проверяла
    `isinstance(settings, dict)` и на настоящем pywebview не срабатывала вовсе."""


def _fake_webview():
    return types.SimpleNamespace(settings=_ImmutableDictLike({"ALLOW_DOWNLOADS": False}))


def test_downloads_are_enabled_on_a_userdict_settings_object():
    wv = _fake_webview()
    assert webview2_app._enable_downloads(wv) is True
    assert wv.settings["ALLOW_DOWNLOADS"] is True


def test_missing_settings_does_not_break_the_window():
    #Без исключения — и с честным «не вышло»: окно важнее выгрузок, но молчать нельзя.
    assert webview2_app._enable_downloads(types.SimpleNamespace()) is False


def test_run_enables_downloads_before_the_window_is_created():
    """Обещание без вызывающего — наш самый частый дефект: функция есть, а окно её не зовёт."""
    src = textwrap.dedent(inspect.getsource(webview2_app.run))
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)]
    names = [getattr(c.func, "id", getattr(c.func, "attr", "")) for c in calls]
    assert "_enable_downloads" in names, "run() не разрешает загрузки"
    assert names.index("_enable_downloads") < names.index("create_window"), \
        "загрузки разрешаются после создания окна"


def test_reverse_run_the_old_check_misses_the_real_settings_type():
    """Обратный ход: проверка `isinstance(…, dict)` на таком объекте флаг не ставит —
    тест выше обязан это различать, иначе он не отличил бы дефект от починки."""
    wv = _fake_webview()
    if isinstance(wv.settings, dict):
        wv.settings["ALLOW_DOWNLOADS"] = True
    assert wv.settings["ALLOW_DOWNLOADS"] is False
