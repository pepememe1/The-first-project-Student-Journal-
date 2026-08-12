"""
test_app_paths.py — is_frozen()/app_dir() под PyInstaller И Nuitka.

Живой баг (Release-3.6.2, «автообновление не работает»): is_frozen() проверял
ТОЛЬКО sys.frozen (ставит PyInstaller) — Nuitka, ЕДИНСТВЕННЫЙ релизный сборщик
(§8.1 CLAUDE.md), его не выставляет вовсе, и is_frozen() под релизным .exe всегда
возвращал False. Проверено отдельной пробной Nuitka-сборкой: sys.frozen отсутствует,
а __compiled__ — есть в globals(), и sys.executable указывает на временный
bootstrap-интерпретатор в %TEMP%, а не на настоящий .exe.
"""
import os
import sys

import app_paths


def test_is_frozen_false_by_default():
    assert app_paths.is_frozen() is False


def test_is_frozen_true_for_pyinstaller_style(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert app_paths.is_frozen() is True


def test_is_frozen_true_for_nuitka_style(monkeypatch):
    """Nuitka не ставит sys.frozen — компилятор инжектит __compiled__ прямо в globals()
    КАЖДОГО скомпилированного модуля (см. уже существующий приём в
    ui/webview2_app.py::_is_compiled()). Эмулируем это подсовыванием имени в globals
    самого app_paths, а не через monkeypatch sys — иначе тест ничего не проверял бы."""
    monkeypatch.setitem(app_paths.__dict__, "__compiled__", True)
    assert app_paths.is_frozen() is True


def test_app_dir_nuitka_onefile_uses_env_not_sys_executable(monkeypatch, tmp_path):
    """Живой баг: sys.executable под Nuitka onefile — временный python.exe в %TEMP%,
    а не настоящий .exe. app_dir() обязан брать NUITKA_ONEFILE_DIRECTORY, если она
    есть, а не dirname(sys.executable)."""
    monkeypatch.delenv("GRADEBOOK_APP_DIR", raising=False)
    monkeypatch.setitem(app_paths.__dict__, "__compiled__", True)
    real_dir = str(tmp_path / "real_install_dir")
    bogus_temp_python = str(tmp_path / "onefile_123_456_abc" / "python.exe")
    monkeypatch.setenv("NUITKA_ONEFILE_DIRECTORY", real_dir)
    monkeypatch.setattr(sys, "executable", bogus_temp_python)
    assert app_paths.app_dir() == real_dir


def test_app_dir_pyinstaller_falls_back_to_sys_executable(monkeypatch, tmp_path):
    """PyInstaller не знает NUITKA_ONEFILE_DIRECTORY — там sys.executable ужЕ верный,
    поведение не должно меняться."""
    monkeypatch.delenv("GRADEBOOK_APP_DIR", raising=False)
    monkeypatch.delenv("NUITKA_ONEFILE_DIRECTORY", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    exe = str(tmp_path / "install_dir" / "GradeBookAI.exe")
    monkeypatch.setattr(sys, "executable", exe)
    assert app_paths.app_dir() == str(tmp_path / "install_dir")


def test_app_dir_override_wins_over_frozen_detection(monkeypatch, tmp_path):
    """GRADEBOOK_APP_DIR (тестовый override, см. докстринг app_dir()) обязан
    побеждать даже когда is_frozen() истинен — иначе тесты, которые его выставляют,
    поймали бы на себе живой Nuitka-путь случайно."""
    override = str(tmp_path / "override_dir")
    monkeypatch.setenv("GRADEBOOK_APP_DIR", override)
    monkeypatch.setitem(app_paths.__dict__, "__compiled__", True)
    assert app_paths.app_dir() == override


# ── «Загрузки» — живой баг (скриншот от Влада: data.key/vsgutu_grades.db/          ──
# ── local_app.key легли прямо в Downloads, программа при этом не запускалась) ────
def test_is_risky_run_location_detects_downloads(monkeypatch, tmp_path):
    home = tmp_path / "profile"
    downloads = home / "Downloads"
    downloads.mkdir(parents=True)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home) if p == "~" else p)
    assert app_paths._is_risky_run_location(str(downloads)) is True


def test_is_risky_run_location_ignores_ordinary_folder(monkeypatch, tmp_path):
    home = tmp_path / "profile"
    (home / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home) if p == "~" else p)
    assert app_paths._is_risky_run_location(str(tmp_path / "GradeBookAI-install")) is False


def test_data_dir_redirects_away_from_downloads(monkeypatch, tmp_path):
    """Живой баг: .exe скачан и запущен прямо из «Загрузки» — data_dir() обязана
    увести базу/ключи/логи в постоянное место, а НЕ рассыпать их вперемешку с
    другими скачанными файлами. app_dir() при этом (проверено ниже отдельно) не
    меняется — апдейтеру и поиску ресурсов всё ещё нужен РЕАЛЬНЫЙ путь к .exe."""
    monkeypatch.delenv("GRADEBOOK_APP_DIR", raising=False)
    downloads = tmp_path / "profile" / "Downloads"
    downloads.mkdir(parents=True)
    local_appdata = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: str(tmp_path / "profile") if p == "~" else p)
    monkeypatch.setitem(app_paths.__dict__, "__compiled__", True)
    monkeypatch.setenv("NUITKA_ONEFILE_DIRECTORY", str(downloads))
    assert app_paths.app_dir() == str(downloads), "app_dir() не должен меняться"
    assert app_paths.data_dir() == str(local_appdata / "GradeBookAI")


def test_data_dir_stays_portable_outside_downloads(monkeypatch, tmp_path):
    """Обычная («не установил, а скопировал») папка — портативность как была: данные
    рядом с .exe, редирект не срабатывает."""
    monkeypatch.delenv("GRADEBOOK_APP_DIR", raising=False)
    install_dir = tmp_path / "GradeBookAI-test1"
    install_dir.mkdir()
    monkeypatch.setitem(app_paths.__dict__, "__compiled__", True)
    monkeypatch.setenv("NUITKA_ONEFILE_DIRECTORY", str(install_dir))
    assert app_paths.data_dir() == str(install_dir)


# ── safe_app_dir()/safe_app_file() — живой баг: subjects.json качался в «Загрузки» ──
def test_safe_app_dir_matches_app_dir_in_dev():
    """Dev-режим (не frozen) — safe_app_dir() обязана совпадать с app_dir() один в
    один: тестовый override GRADEBOOK_APP_DIR читает именно app_dir(), и ничего не
    должно перестать работать для существующих потребителей (subjects.py и др.)."""
    assert app_paths.safe_app_dir() == app_paths.app_dir()


def test_safe_app_dir_stays_portable_outside_downloads(monkeypatch, tmp_path):
    monkeypatch.delenv("GRADEBOOK_APP_DIR", raising=False)
    install_dir = tmp_path / "GradeBookAI-test1"
    install_dir.mkdir()
    monkeypatch.setitem(app_paths.__dict__, "__compiled__", True)
    monkeypatch.setenv("NUITKA_ONEFILE_DIRECTORY", str(install_dir))
    assert app_paths.safe_app_dir() == str(install_dir)
    assert app_paths.app_dir() == str(install_dir), "app_dir() не трогаем — нужен апдейтеру"


def test_safe_app_dir_redirects_away_from_downloads(monkeypatch, tmp_path):
    """Живой баг: subjects.json скачивался вместе с .exe прямо в «Загрузки». safe_app_dir()
    обязана увести его в то же место, что и data_dir() — а app_dir() остаться нетронутой
    (нужна апдейтеру/поиску бандл-ресурсов, см. её докстрин)."""
    monkeypatch.delenv("GRADEBOOK_APP_DIR", raising=False)
    downloads = tmp_path / "profile" / "Downloads"
    downloads.mkdir(parents=True)
    local_appdata = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: str(tmp_path / "profile") if p == "~" else p)
    monkeypatch.setitem(app_paths.__dict__, "__compiled__", True)
    monkeypatch.setenv("NUITKA_ONEFILE_DIRECTORY", str(downloads))
    assert app_paths.safe_app_dir() == str(local_appdata / "GradeBookAI")
    assert app_paths.app_dir() == str(downloads), "app_dir() не должен меняться"
    assert app_paths.safe_app_file("subjects.json") == str(local_appdata / "GradeBookAI" / "subjects.json")


# ── Строка версии продукта ───────────────────────────────────────────────────────────
def test_version_string_has_exactly_one_source():
    """Версия обязана жить в ОДНОМ месте и совпадать везде, где её показывают.

    До 3.7 она была литералом в трёх файлах, и два отставали ОДНОВРЕМЕННО: заголовок
    окна показывал 3.6.9 на ветке 3.7, а инфо-панель сайта — 3.6.1, то есть отстала на
    шесть релизов. Над вторым литералом при этом стоял комментарий «правь руками при
    каждом релизе» — просьба помнить не сработала ни разу за год.

    Тест держит именно СВЯЗЬ, а не конкретное значение: сверять его с номером ветки
    было бы вторым местом, которое надо не забыть поправить."""
    import desktop_update
    from core import APP_VERSION

    assert APP_VERSION is desktop_update.APP_VERSION, (
        "core.APP_VERSION обязан быть ре-экспортом, а не собственным литералом")
    assert desktop_update.parse_version(APP_VERSION), (
        f"версия {APP_VERSION!r} не разбирается собственным parse_version — "
        "автообновление не сможет сравнить её со сборкой на сервере")


def test_site_info_reports_the_same_version_as_the_desktop():
    """Инфо-панель сайта («Сервер» у админа) обязана называть ту же версию, что и
    заголовок окна программы. Именно здесь литерал отстал на шесть релизов, и заметить
    это было нечем: тест той панели проверял только, что поле непустое."""
    import pathlib
    import re

    import desktop_update

    src = pathlib.Path(__file__).resolve().parents[1] / "server" / "app" / "routers" / "web" / "siteinfo.py"
    text = src.read_text(encoding="utf-8")
    line = next((ln for ln in text.splitlines() if '"version":' in ln), "")
    assert line, "в siteinfo.py пропало поле version"
    assert not re.search(r'"version":\s*"', line), (
        f"версия снова захардкожена литералом: {line.strip()!r} — "
        f"должна браться из desktop_update.APP_VERSION ({desktop_update.APP_VERSION})")
