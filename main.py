"""
main.py — единая точка входа GradeBookAI (Release 2.2).
Модульная архитектура: main_window.MainAppWindow.
"""
import sys
import os

#Раскладка по папкам ui/ sync/ data/ — выполнить ДО любого клиентского импорта,
#иначе плоские импорты (from main_window import ...) не найдут перенесённые модули.
import _bootstrap  # noqa: F401,E402

#Безопасный вывод. В собранном .exe (windowed) sys.stdout может быть None, а в
#консоли с кодировкой cp1251 эмодзи (✅, ℹ️ и т.п.) в print() роняют программу
#(UnicodeEncodeError). По всему проекту есть такие print — делаем вывод
#неубиваемым ОДИН раз здесь, до любых сообщений.
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


def _run_server_entrypoint():
    """Режим «фонового сервера» для СОБРАННОГО .exe: тот же исполняемый файл,
    запущенный с флагом --run-server, поднимает uvicorn вместо GUI.

    Зачем так. Фоновый сервер хоста — отдельный процесс (переживает закрытие
    программы). В dev его можно запустить как `python server/run.py`, но в собранном
    .exe внешнего python НЕТ, поэтому отдельным процессом сервера выступает наш же exe
    с этим флагом. Порт берём из GRADEBOOK_PORT (его выставляет server_control)."""
    here = _get_app_dir()
    server_dir = os.path.join(here, "server")
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    os.chdir(server_dir)
    port = int(os.environ.get("GRADEBOOK_PORT", "8000"))
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)


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
    #Фоновый сервер для собранного .exe: если запущены с --run-server, поднимаем сам
    #сервер (uvicorn) и НЕ открываем GUI. Проверяем это ПЕРВЫМ делом.
    if "--run-server" in sys.argv:
        _run_server_entrypoint()
        return

    #Инициализация локальной базы (SQLite). Обмен с сервером — по сети через API
    #(см. sync_runner). Сообщение о режиме печатает сам DBManager.init().
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

    #Авто-бэкап локальной базы при выходе.
    #ВАЖНО: сервер и ssh-туннель — ФОНОВЫЕ процессы, и при закрытии программы мы их
    #НАМЕРЕННО НЕ гасим: связь должна жить без программы (хост сменил аккаунт/закрыл —
    #клиенты продолжают синкаться). Останавливаются они только кнопкой «Остановить» в
    #админке (server_control.stop_processes) или вручную.
    def _on_quit():
        try:
            from core import DBManager
            DBManager.backup(reason="on_exit")
        except Exception as _e:
            print(f"[exit] {_e}")
    app.aboutToQuit.connect(_on_quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
