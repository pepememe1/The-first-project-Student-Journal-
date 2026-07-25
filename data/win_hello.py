"""
win_hello.py — вход по учётной записи Windows (пароль/ПИН/Windows Hello).

Зачем: на рабочем ПК преподаватель уже вошёл в Windows, и вводить логин с паролем
журнала каждый раз — лишний шаг. Здесь мы показываем СИСТЕМНОЕ окно Windows («Безопасность
Windows»), где человек подтверждает себя тем же способом, что и вход в систему: ПИН, лицо/
отпечаток (Windows Hello) либо пароль. Если Windows подтвердила — открываем сохранённую
сессию журнала.

⚠️ ЧТО ЭТО НЕ ДЕЛАЕТ: пароль от аккаунта журнала здесь не хранится и не проверяется —
инвариант «пароль не хранится» (§4.7 внутренних правил) в силе. Windows-проверка лишь ОТКРЫВАЕТ
доступ к уже сохранённой JWT-сессии этого ПК, как «замок» поверх неё. Поэтому включать
такой вход имеет смысл на ЛИЧНОМ компьютере: кто вошёл в Windows — тот и попадёт в журнал.

Реализация — ctypes поверх Win32 (credui + advapi32), без внешних зависимостей:
  1. CredUIPromptForWindowsCredentials — системное окно подтверждения;
  2. CredUnPackAuthenticationBuffer     — достаём логин/пароль из защищённого буфера;
  3. LogonUser                          — ПРОВЕРЯЕМ их у самой Windows.
Без шага 3 диалог был бы бутафорией: он лишь собирает ввод, но ничего не проверяет.
Пароль Windows живёт в памяти считаные миллисекунды и затирается (см. _zero).
"""
import ctypes
import sys
from ctypes import wintypes

_IS_WIN = sys.platform == "win32"

#Флаги CredUIPromptForWindowsCredentials
_CREDUIWIN_GENERIC = 0x00000001              #обычное окно ввода, без «карт»
_CREDUIWIN_ENUMERATE_CURRENT_USER = 0x00000200   #предлагать ТЕКУЩЕГО пользователя Windows
#LogonUser
_LOGON32_LOGON_INTERACTIVE = 2
_LOGON32_LOGON_NETWORK = 3
_LOGON32_PROVIDER_DEFAULT = 0
_ERROR_CANCELLED = 1223


def available() -> bool:
    """Доступен ли такой вход (только Windows и только если библиотеки на месте)."""
    if not _IS_WIN:
        return False
    try:
        ctypes.WinDLL("credui.dll")
        ctypes.WinDLL("advapi32.dll")
        return True
    except OSError:
        return False


def current_user() -> str:
    """Имя текущего пользователя Windows (для подписи кнопки). '' — не удалось."""
    if not _IS_WIN:
        return ""
    try:
        size = wintypes.DWORD(0)
        ctypes.WinDLL("advapi32.dll").GetUserNameW(None, ctypes.byref(size))
        buf = ctypes.create_unicode_buffer(size.value or 256)
        if ctypes.WinDLL("advapi32.dll").GetUserNameW(buf, ctypes.byref(size)):
            return buf.value or ""
    except Exception:
        pass
    return ""


def _zero(buf) -> None:
    """Затереть буфер с паролем — не оставляем секрет в памяти процесса дольше нужного."""
    try:
        ctypes.memset(ctypes.addressof(buf), 0, ctypes.sizeof(buf))
    except Exception:
        pass


class _CREDUI_INFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("hwndParent", wintypes.HWND),
                ("pszMessageText", wintypes.LPCWSTR),
                ("pszCaptionText", wintypes.LPCWSTR),
                ("hbmBanner", wintypes.HBITMAP)]


def verify(message: str = "Подтвердите вход в GradeBookAI",
           caption: str = "GradeBookAI", hwnd: int = 0) -> bool:
    """Показать системное окно Windows и вернуть True, если Windows подтвердила личность.

    Отмена пользователем и любая ошибка — False (никогда не бросает: вход не должен
    падать из-за необязательной возможности)."""
    if not available():
        return False
    credui = ctypes.WinDLL("credui.dll")
    advapi = ctypes.WinDLL("advapi32.dll")

    info = _CREDUI_INFO()
    info.cbSize = ctypes.sizeof(_CREDUI_INFO)
    info.hwndParent = wintypes.HWND(hwnd) if hwnd else None
    info.pszMessageText = message
    info.pszCaptionText = caption
    info.hbmBanner = None

    auth_package = wintypes.ULONG(0)
    out_buf = ctypes.c_void_p()
    out_size = wintypes.ULONG(0)
    save = wintypes.BOOL(False)

    rc = credui.CredUIPromptForWindowsCredentialsW(
        ctypes.byref(info), 0, ctypes.byref(auth_package), None, 0,
        ctypes.byref(out_buf), ctypes.byref(out_size), ctypes.byref(save),
        _CREDUIWIN_GENERIC | _CREDUIWIN_ENUMERATE_CURRENT_USER)
    if rc != 0:                       #0 = ERROR_SUCCESS; 1223 = пользователь отменил
        return False

    user = ctypes.create_unicode_buffer(513)
    domain = ctypes.create_unicode_buffer(513)
    password = ctypes.create_unicode_buffer(513)
    lu = wintypes.DWORD(513)
    ld = wintypes.DWORD(513)
    lp = wintypes.DWORD(513)
    ok = False
    try:
        if credui.CredUnPackAuthenticationBufferW(
                0, out_buf, out_size, user, ctypes.byref(lu),
                domain, ctypes.byref(ld), password, ctypes.byref(lp)):
            token = wintypes.HANDLE()
            #Логин может прийти как «DOMAIN\user» или «user@domain» — тогда домен отдельно
            #не нужен, Windows разберёт сама (передаём None).
            dom = domain.value or None
            if "\\" in (user.value or "") or "@" in (user.value or ""):
                dom = None
            for logon_type in (_LOGON32_LOGON_INTERACTIVE, _LOGON32_LOGON_NETWORK):
                if advapi.LogonUserW(user.value, dom, password.value, logon_type,
                                     _LOGON32_PROVIDER_DEFAULT, ctypes.byref(token)):
                    ok = True
                    try:
                        ctypes.windll.kernel32.CloseHandle(token)
                    except Exception:
                        pass
                    break
    except Exception:
        ok = False
    finally:
        _zero(password)
        _zero(user)
        _zero(domain)
        try:                          #буфер выделяла система — освобождаем её же вызовом
            ctypes.windll.ole32.CoTaskMemFree(out_buf)
        except Exception:
            pass
    return ok
