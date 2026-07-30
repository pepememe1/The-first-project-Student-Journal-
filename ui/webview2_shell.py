"""
webview2_shell.py — окно программы на СИСТЕМНОМ движке WebView2 (замена QtWebEngine).

━━ ЗАЧЕМ ━━
Интерфейс уже целиком веб-овый, и Qt в сборке остался ровно ради одного: показать
страницу. За это удовольствие .exe платит ~180 МБ — внутри лежит целый Chromium. В
Windows 10/11 движок Edge уже установлен системой, поэтому окно можно рисовать им, а из
сборки убрать и Chromium, и сам Qt: ожидаемый вес ~30–40 МБ.

⚠️ Этот модуль НИЧЕГО не переключает сам. Он существует РЯДОМ с рабочей Qt-оболочкой,
пока не подтверждён на всех ролях: «программа не открывается вовсе» — цена ошибки,
которую нельзя платить в колледже посреди занятия.

━━ 152-ФЗ: ЧТО ЗДЕСЬ СДЕЛАНО ОСОЗНАННО ━━
WebView2 — движок Microsoft, и по умолчанию он разговорчив: диагностика, SmartScreen
(отправляет адреса на проверку), автозаполнение, синхронизация профиля. Для журнала с
ПДн студентов это недопустимо, поэтому:
  • ТЕЛЕМЕТРИЯ И SMARTSCREEN ВЫКЛЮЧЕНЫ аргументами движка. Флага «IsTelemetryDisabled»
    в используемой обвязке нет, но WebView2 читает переменную окружения
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS — это его штатный механизм, работающий
    независимо от языка и обёртки;
  • ПРОФИЛЬ ЭФЕМЕРНЫЙ (private_mode): кэш, куки и история не остаются на диске.
    Нам это ничего не стоит — сессия подставляется при каждом запуске заново, а
    офлайн-данные живут не в кэше браузера, а в зашифрованной локальной базе
    (`ui/local_api.py`). То есть требование «инкогнито» и offline-first не спорят;
  • ПАПКА ДАННЫХ движка — своя, в каталоге программы, а не общая с браузером
    пользователя: иначе наши куки и его перемешались бы.

Что этот модуль НЕ решает и не должен: ГОСТ-шифрование канала. Наружу ходит не движок, а
наш клиент синхронизации; окно говорит с сервером на 127.0.0.1, и этот трафик машину не
покидает вовсе.
"""
import os

import log

_LOG = log.get("webview2")

#Аргументы движка. Каждый — про приватность, а не про производительность:
#  msSmartScreenProtection — отправка адресов на проверку в Microsoft;
#  msWebOOUI/msPdfOOUI — внешние UI-компоненты Edge (тянут свои запросы);
#  disable-sync — синхронизация профиля с учётной записью Microsoft;
#  disable-features=Translate — отправка текста страницы на перевод;
#  no-first-run/no-default-browser-check — попытки «познакомиться» с пользователем.
_PRIVACY_ARGS = (
    "--disable-features=msSmartScreenProtection,msWebOOUI,msPdfOOUI,Translate,"
    "AutofillServerCommunication "
    "--disable-sync --disable-background-networking --no-first-run "
    "--no-default-browser-check --disable-breakpad"
)


def available() -> bool:
    """Можно ли рисовать окно этим движком (обвязка + системный runtime).

    Проверяем ЗАРАНЕЕ: на машине без обновлений Windows runtime может отсутствовать, и
    тогда нужно честно остаться на прежней оболочке, а не показать пустое окно."""
    try:
        import webview  # noqa: F401
    except Exception as e:
        _LOG.info(f"[webview2] обвязка недоступна: {e}")
        return False
    return runtime_installed()


def runtime_installed() -> bool:
    """Установлен ли системный WebView2 Runtime (реестр Windows).

    Ищем в обеих ветках: у машинной установки ключ в HKLM (её ставит Windows Update и
    Edge), у пользовательской — в HKCU. Проверка по реестру, а не по файлу: путь к
    рантайму версионный и меняется с каждым обновлением."""
    if os.name != "nt":
        return False
    try:
        import winreg
    except Exception:
        return False
    key = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients" \
          r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for path in (key, key.replace(r"WOW6432Node\\", "")):
            try:
                with winreg.OpenKey(root, path) as k:
                    version, _ = winreg.QueryValueEx(k, "pv")
                    if version:
                        return True
            except OSError:
                continue
    _LOG.info("[webview2] системный runtime не найден")
    return False


def apply_privacy_env() -> None:
    """Погасить болтливость движка ДО создания окна.

    Именно до: аргументы читаются при инициализации, позже менять поздно. Существующее
    значение переменной не затираем молча — дополняем, иначе затёрли бы настройку,
    сделанную администратором машины."""
    prev = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "").strip()
    if _PRIVACY_ARGS in prev:
        return
    os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
        f"{prev} {_PRIVACY_ARGS}".strip())


def profile_dir() -> str:
    """Своя папка движка — не общая с браузером пользователя.

    При эфемерном профиле сюда всё равно почти ничего не пишется, но путь задать надо:
    по умолчанию WebView2 сложил бы данные рядом с исполняемым файлом, а .exe у нас
    портативный и может лежать на флешке (или в папке без права записи)."""
    import app_paths
    return app_paths.data_file("webview2")


def open_window(url: str, title: str = "GradeBookAI", on_closed=None) -> bool:
    """Открыть окно на WebView2. False — если движок недоступен (решает вызывающий).

    ⚠️ Блокирующий вызов: управление вернётся, когда человек закроет окно. Так устроен
    любой цикл событий GUI, и это ровно то место, где новая оболочка НЕ совместима с
    Qt по построению — поэтому переключение делается целиком, а не «половиной экранов»."""
    if not available():
        return False
    apply_privacy_env()
    try:
        import webview
        webview.create_window(title, url, width=1440, height=900,
                              min_size=(1024, 640), text_select=True)
        webview.start(gui="edgechromium",
                      private_mode=True,                 #эфемерный профиль (152-ФЗ)
                      storage_path=profile_dir(),
                      debug=False)
        if on_closed is not None:
            on_closed()
        return True
    except Exception as e:
        _LOG.warning(f"[webview2] окно не открылось: {e}")
        return False
