"""
main.py — единая точка входа GradeBookAI.

Окно рисует системный движок Edge (WebView2) поверх ЛОКАЛЬНОГО серверного приложения
на 127.0.0.1 — того же `server/app`, что работает на бою (§11 «один интерфейс»).

⚠️ Здесь БОЛЬШЕ НЕТ `import _bootstrap`. Тот модуль подкладывал `desktop/ sync/ data/` в
sys.path, чтобы работали плоские импорты (`from core import ...`) — приём рабочий, но
у него три цены, и все три мы платили: порядок импортов становился значимым (забыл
строку в новой точке входа — ImportError на ровном месте), сборщики .exe не видят
sys.path и требовали перечислять модули руками, а один и тот же файл, импортированный
и как `core`, и как `data.core`, давал ДВА разных объекта модуля со своим состоянием.
Теперь `data/`, `sync/` и `desktop/` — обычные пакеты, импорты явные. (Папка `ui/`
переименована в `desktop/` вместе с удалением Qt: интерфейса в ней не осталось —
там локальный сервер, окно на движке Edge и раздел «Сервер».)
"""
import sys
import log
import os

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


#⚠️ Qt в программе БОЛЬШЕ НЕТ (см. комментарий у выбора окна ниже). Проверить, что он не
#вернулся случайным импортом, можно так — должно печатать False:
#   python -c "import main, sys; print(any(m.startswith('PySide6') for m in sys.modules))"
#Один такой импорт на уровне модуля затянул бы в сборку Chromium внутри Qt (~150 МБ):
#сборщик ориентируется на реальные импорты, а не на намерения.


def _get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _apply_pending_update():
    """Установить обновление, оставшееся СО ВСЕХ ПРЕЖНИХ запусков (страховка на случай
    прерванного цикла — обычный путь теперь `_check_update_interactive`/`updater.
    check_and_prompt`, который качает-ставит-перезапускается одним циклом и ничего не
    оставляет «на потом»; сюда попадают только осколки от процесса, убитого МЕЖДУ
    закачкой и установкой).

    Обновления — не условие работы журнала: любая ошибка здесь глушится, программа
    просто продолжает запускаться на текущей версии. Перезапуск — САМ (relaunch), а
    не просьба «запустите ещё раз»: та просьба уходила бы в print(), который в
    windowed-сборке никто не видит (--windows-console-mode=disable)."""
    try:
        from data.core import APP_VERSION
        from data import updater
        if updater.apply_pending(APP_VERSION):
            log.get("main").info("[update] установлено, перезапускаюсь")
            updater.relaunch()
            raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as e:      # noqa: BLE001 — обновление не имеет права мешать запуску
        log.get("main").warning(f"[update] пропускаю установку обновления: {e}")


def _check_update_interactive() -> bool:
    """Проверка новой версии ДО открытия окна — с диалогом да/нет.

    🔥 Раньше проверка была ТИХОЙ фоновой (качала про запас, подмена ставилась молча
    на СЛЕДУЮЩЕМ запуске с сообщением в консоль, которой в windowed-сборке НЕТ,
    --windows-console-mode=disable) — человек видел необъяснимое закрытие программы.
    Теперь: спрашиваем явно и, если человек согласился, качаем/ставим/перезапускаемся
    сразу, одним циклом. Вся логика — в `updater.check_and_prompt` (тестируется там
    без реального диалога/сети); здесь только чтение конфига и глушение ошибок —
    обновление не имеет права помешать открыть журнал.

    True — процесс должен завершиться прямо сейчас (либо переоткрылись новой версией,
    либо человек отказался и программа закрывается)."""
    try:
        from data.core import APP_VERSION
        from data import app_settings
        from data import updater
        url = app_settings.get_api_url()
        if not url:
            return False
        return updater.check_and_prompt(url, APP_VERSION)
    except Exception as e:      # noqa: BLE001
        print(f"[update] проверка обновления не удалась: {e}")
        return False


def _require_crypto_or_exit() -> None:
    """Без пакета `cryptography` не запускаемся — молча работать с ПДн нельзя (152-ФЗ).

    🔥 Проверка жила ТОЛЬКО в запасной Qt-оболочке, которой нет в релизной сборке
    (PySide6 в неё не входит, §8.1) — то есть в поставляемом .exe она не выполнялась ни
    разу. Сам `security._require_crypto()` падает громко при первом же шифровании, так
    что незашифрованных данных на диске быть не могло; но человек получал трейсбек
    посреди работы вместо внятного сообщения на старте. Диалог — нативный
    (`updater.show_info`, обычный MessageBoxW): он не требует ни Qt, ни готового окна.
    """
    try:
        from data.security import CRYPTO_AVAILABLE
    except Exception:
        CRYPTO_AVAILABLE = False
    if CRYPTO_AVAILABLE:
        return
    msg = ("Для работы с персональными данными требуется пакет «cryptography».\n\n"
           "Установите его командой:\n    pip install cryptography\n\n"
           "Без него запуск невозможен: данные нельзя зашифровать надёжно.")
    log.get("main").error(f"[crypto] {msg}")
    try:
        from data import updater
        updater.show_info("GradeBookAI — не установлен компонент защиты", msg)
    except Exception:               # noqa: BLE001 — диалог best-effort
        pass
    sys.exit(1)


def main():
    #Фоновый сервер для собранного .exe: если запущены с --run-server, поднимаем сам
    #сервер (uvicorn) и НЕ открываем GUI. Проверяем это ПЕРВЫМ делом.
    if "--run-server" in sys.argv:
        _run_server_entrypoint()
        return

    #━━ АВТООБНОВЛЕНИЕ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #Ставим скачанное в ПРОШЛЫЙ раз обновление — здесь и только здесь: файл программы
    #нельзя подменять под работающим окном, а на этой строке ещё ничего не открыто и
    #база не тронута.
    _apply_pending_update()

    #Проверка новой версии — СИНХРОННО, ДО базы и окна: манифест — доли секунды при
    #рабочей сети (укороченный таймаут внутри check_and_prompt), а диалог да/нет
    #должен появиться раньше, чем человек увидит журнал, а не посреди работы с ним.
    #Согласился — программа уже перезапускается новой версией, здесь делать нечего.
    #Отказался — по прямому решению программа закрывается, а не продолжает молча.
    if _check_update_interactive():
        return

    #Шифрование ПДн — условие запуска, а не украшение. Проверяем ДО открытия базы.
    _require_crypto_or_exit()

    #Инициализация локальной базы (SQLite). Обмен с сервером — по сети через API
    #(см. sync_runner). Сообщение о режиме печатает сам DBManager.init().
    from data.core import DBManager
    DBManager.init()

    #━━ ОКНО ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #Интерфейс целиком веб-овый, поэтому окно рисует СИСТЕМНЫЙ движок Edge (WebView2):
    #Chromium внутри Qt стоил бы ~150 МБ в .exe ради того же самого.
    #
    #⚠️ ЗАПАСНОЙ Qt-ОБОЛОЧКИ БОЛЬШЕ НЕТ. Она и раньше не входила в релизную сборку
    #(--nofollow-import-to=PySide6), то есть у людей не исполнялась никогда — но
    #продолжала жить в исходниках отдельным кабинетом на ~20 тыс. строк, который никто
    #не открывал и в котором поэтому молча копились поломки (например, «Добавить
    #группу» падала NameError). Нативные экраны заменены тем же Vue-SPA, который
    #поднимает локальный сервер (§11 «один интерфейс»), поэтому вторая реализация
    #кабинета не нужна ни офлайн, ни онлайн. Исходники убраны в WORK/GB-legacy-qt.
    try:
        from desktop import webview2_app
        if webview2_app.run():
            return                      #окно закрыто — программа отработала
        reason = "движок Edge (WebView2) недоступен или локальный сервер не поднялся"
    except Exception as e:              # noqa: BLE001 — причину показываем, а не роняем
        reason = str(e)

    #Окна нет — человек обязан увидеть ПРИЧИНУ глазами, а не пустоту: в windowed-сборке
    #консоли нет вовсе (--windows-console-mode=disable), и «программа не запускается»
    #без единого сообщения мы уже проходили (см. ensure_server_path в desktop/local_api.py).
    msg = ("Не удалось открыть окно программы.\n\n"
           "Чаще всего не хватает системного движка Microsoft Edge WebView2 Runtime — "
           "установите его и запустите программу снова.\n\n"
           f"Причина: {reason}")
    log.get("main").warning(f"[ui] окно не открылось: {reason}")
    try:
        from data import updater
        updater.show_info("GradeBookAI — окно не открылось", msg)
    except Exception:                   # noqa: BLE001 — диалог best-effort
        pass
    sys.exit(1)


if __name__ == "__main__":
    main()
