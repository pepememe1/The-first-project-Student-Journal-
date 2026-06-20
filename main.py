"""
main.py — единая точка входа GradeBookAI (Release 2.2).
Модульная архитектура: main_window.MainAppWindow.
"""
import sys
import os


# Безопасный вывод. В собранном .exe (windowed) sys.stdout может быть None, а в
# консоли с кодировкой cp1251 эмодзи (✅, ℹ️ и т.п.) в print() роняют программу
# (UnicodeEncodeError). По всему проекту есть такие print — делаем вывод
# неубиваемым ОДИН раз здесь, до любых сообщений.
def _safe_stream(stream):
    if stream is None:
        try:
            return open(os.devnull, "w", encoding="utf-8")
        except Exception:
            return None
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return stream


sys.stdout = _safe_stream(sys.stdout)
sys.stderr = _safe_stream(sys.stderr)

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
    # Инициализация локальной базы (SQLite). Обмен с сервером — по сети через API
    # (см. sync_runner). Сообщение о режиме печатает сам DBManager.init().
    from core import DBManager
    DBManager.init()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    #Проверка криптографии: без пакета cryptography шифрование ПДн недоступно.
    #Раньше приложение молча откатывалось на слабый самописный шифр — для боевой
    #эксплуатации (152-ФЗ) это недопустимо, поэтому честно останавливаемся.
    try:
        from security import CRYPTO_AVAILABLE
    except Exception:
        CRYPTO_AVAILABLE = False
    if not CRYPTO_AVAILABLE:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None, "Не установлен компонент защиты",
            "Для работы с персональными данными требуется пакет «cryptography».\n\n"
            "Установите его командой:\n    pip install cryptography\n\n"
            "Без него запуск невозможен: данные нельзя зашифровать надёжно.")
        sys.exit(1)

    #Шрифты Syne + DM Sans (фирменный стиль Synapse)
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

    #Авто-бэкап локальной базы при выходе + аккуратная остановка синхронизации
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
