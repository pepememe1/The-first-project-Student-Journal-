"""
main.py — единая точка входа GradeBookAI (Release 3.0).
Модульная архитектура: main_window.MainAppWindow.
"""
import sys
import log
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


#⚠️ Qt импортируется ЛЕНИВО, внутри запасного пути (`_run_qt_shell`). На основном пути
#(окно на системном движке Edge) он не нужен вовсе, а импорт на уровне модуля затянул бы
#PySide6 и Chromium внутри него в сборку — то есть ~150 МБ ради кода, который не
#выполняется. Сборщик ориентируется на реальные импорты, а не на намерения.


def _get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_icon():
    """Иконка приложения для Qt-оболочки (QIcon). Импорт Qt внутри — см. выше."""
    from PySide6.QtGui import QIcon
    #onefile: иконка распакована рядом со скомпилированным модулем (Nuitka) или в
    #sys._MEIPASS (PyInstaller); рядом с .exe её нет. Проверяем все базы.
    bases = [_get_app_dir(), os.path.dirname(os.path.abspath(__file__))]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bases.append(meipass)
    for base_dir in bases:
        for name in ("icon.ico", "icon.png", "icon.jpg"):
            path = os.path.join(base_dir, name)
            if os.path.exists(path):
                return QIcon(path)
    return QIcon()


def _start_local_api_background():
    """Поднять локальное серверное приложение (общий Vue-интерфейс, §11 CLAUDE.md) в фоне.

    Почему в фоне: на первом запуске создаётся локальная база, и это занимает секунду-
    другую — держать на этом окно нельзя. Почему молча: сбой здесь НЕ авария, десктоп
    просто останется на нативных экранах (vue_shell это учитывает), а пугать
    пользователя ошибкой про сервер, которого он не просил, незачем.

    ⚠️ Не путать с `--run-server` выше: там ФОНОВЫЙ сервер ХОСТА для всего колледжа
    (отдельный процесс, слушает сеть, server_control.py). Здесь — личный, только 127.0.0.1."""
    import threading

    def _boot():
        try:
            import local_api
            local_api.instance().start()
        except Exception as e:
            log.get("main").warning(f"[local-api] не удалось поднять локальный сервер: {e}")

    threading.Thread(target=_boot, name="gb-local-api-boot", daemon=True).start()


def _run_qt_shell():
    """ЗАПАСНАЯ оболочка на Qt: нативные экраны, как до перехода на системный движок.

    Открывается, только если WebView2 недоступен (нет Runtime) или не запустился. Весь
    Qt импортируется ЗДЕСЬ, а не на уровне модуля: на основном пути он не нужен, и
    сборщик не должен тянуть PySide6 с Chromium внутри (~150 МБ) ради кода, который не
    выполняется."""
    from PySide6.QtWidgets import QApplication
    from main_window import MainAppWindow

    #Локальное серверное приложение для ОБЩЕГО Vue-интерфейса (см. ui/local_api.py).
    #Поднимаем ФОНОМ и не ждём результата: первый запуск инициализирует базу и занимает
    #секунду-другую, а окно должно появиться сразу. Вкладки на Vue сами дождутся
    #готовности, а если сервер не поднимется — продолжат работать нативные экраны.
    #Отдельным ПОТОКОМ, не процессом: никаких вспышек консоли (см. шапку local_api).
    _start_local_api_background()

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
        log.get("main").warning(f"[Fonts] {e}")

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
        #Перед закрытием ДО-ОТПРАВЛЯЕМ накопленные правки на сервер (синхронно), чтобы
        #данные не «застряли» локально до следующего запуска. Без авторизации flush
        #выходит сразу (не вешает закрытие). Только потом — локальный бэкап.
        try:
            import sync_runner
            sync_runner.flush()
        except Exception as _e:
            log.get("main").warning(f"[exit sync] {_e}")
        try:
            from core import DBManager
            DBManager.backup(reason="on_exit")
        except Exception as _e:
            log.get("main").warning(f"[exit] {_e}")
    app.aboutToQuit.connect(_on_quit)

    sys.exit(app.exec())


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

    #━━ ВЫБОР ОБОЛОЧКИ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #Интерфейс целиком веб-овый, поэтому окно можно рисовать СИСТЕМНЫМ движком Edge
    #(WebView2) вместо Chromium внутри Qt — это ~150 МБ разницы в .exe.
    #
    #Системный движок — УМОЛЧАНИЕ. Qt остаётся запасным путём: если WebView2 недоступен
    #(нет Runtime на старой машине) или не запустился, ниже открывается прежняя оболочка.
    #Откат делается ТОЛЬКО до появления окна — `webview.start()` забирает поток, и после
    #показа окна второй интерфейс в одном запуске уже невозможен.
    #Принудительно вернуться на Qt: `GRADEBOOK_UI=qt` (пригодится, если что-то поедет).
    if (os.environ.get("GRADEBOOK_UI") or "").strip().lower() not in ("qt", "qt5", "qt6",
                                                                     "native"):
        try:
            import webview2_app
            if webview2_app.run():
                return                      #окно закрыто — программа отработала
            print("[ui] WebView2 недоступен — открываем прежнюю оболочку")
        except Exception as e:      # noqa: BLE001 — отказ движка не имеет права
            print(f"[ui] WebView2 не запустился ({e}) — открываем прежнюю оболочку")

    _run_qt_shell()


if __name__ == "__main__":
    main()
