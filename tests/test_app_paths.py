"""
test_app_paths.py — is_frozen()/app_dir() под PyInstaller И Nuitka.

Живой баг (Release-3.6.2, «автообновление не работает»): is_frozen() проверял
ТОЛЬКО sys.frozen (ставит PyInstaller) — Nuitka, ЕДИНСТВЕННЫЙ релизный сборщик
(§8.1 CLAUDE.md), его не выставляет вовсе, и is_frozen() под релизным .exe всегда
возвращал False. Проверено отдельной пробной Nuitka-сборкой: sys.frozen отсутствует,
а __compiled__ — есть в globals(), и sys.executable указывает на временный
bootstrap-интерпретатор в %TEMP%, а не на настоящий .exe.
"""
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
