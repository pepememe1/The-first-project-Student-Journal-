"""
main.py — единая точка входа GradeBookAI (Release 2.2).
Модульная архитектура: main_window.MainAppWindow.
"""
import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from main_window import MainAppWindow


def _get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_icon() -> QIcon:
    base_dir = _get_app_dir()
    for name in ("icon.ico", "icon.png", "icon.jpg"):
        path = os.path.join(base_dir, name)
        if os.path.exists(path):
            return QIcon(path)
    return QIcon()


def main():
    # Инициализация базы данных (SQLite + опционально PostgreSQL)
    from core import DBManager
    if DBManager.init():
        print("✅ Работаем с PostgreSQL")
    else:
        print("ℹ️  Работаем с локальным SQLite")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Шрифты Syne + DM Sans (фирменный стиль Synapse)
    try:
        from fonts import load_fonts
        load_fonts()
    except Exception as e:
        print(f"[Fonts] {e}")

    icon = get_icon()
    app.setWindowIcon(icon)

    window = MainAppWindow()
    window.setWindowIcon(icon)
    window.show()
    window.raise_()
    window.activateWindow()

    # Авто-бэкап локальной базы при выходе + аккуратная остановка синхронизации
    def _on_quit():
        try:
            from core import DBManager, _syncer
            DBManager.backup(reason="on_exit")
            _syncer.stop()
        except Exception as _e:
            print(f"[exit] {_e}")
    app.aboutToQuit.connect(_on_quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
