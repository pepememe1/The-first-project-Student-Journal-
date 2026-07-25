"""
win_login.py — «Вход по Windows» на десктопе (ОПЦИОНАЛЬНО, только по согласию пользователя).

Задача: перестать вводить логин и пароль журнала на своём компьютере. Персистентная
сессия по JWT это решает лишь частично — токен живёт жёстко 5 часов (CLAUDE.md §6), после
чего для получения нового токена нужен пароль. Поэтому здесь пароль СОХРАНЯЕТСЯ, но:

  • шифруется Windows DPAPI (security.os_protect) — ключ производный от учётной записи
    Windows, файл бесполезен на другом ПК и под другим пользователем Windows;
  • достаётся ТОЛЬКО после подтверждения личности самой Windows (win_hello.verify —
    ПИН/лицо/отпечаток/пароль Windows);
  • включается исключительно вручную, с явным предупреждением (см. UI), и выключается
    одним действием (disable() стирает секрет).

⚠️ ЭТО ОСОЗНАННОЕ ИСКЛЮЧЕНИЕ из инварианта «пароль не хранится» (CLAUDE.md §4.7): по
умолчанию ВЫКЛЮЧЕНО, и включать имеет смысл только на ЛИЧНОМ компьютере. На общем ПК
колледжа включать нельзя — тогда любой, кто знает пароль Windows этого рабочего места,
войдёт в журнал под чужой учётной записью.
"""
import base64

import log
import win_hello
from data_store import local_get, local_set

_KEY = "win_login"          #{'login': str, 'blob': base64(DPAPI), 'win_user': str}


def available() -> bool:
    """Поддерживает ли ПК такой вход (Windows + системный диалог подтверждения)."""
    return win_hello.available()


def _rec() -> dict:
    rec = local_get(_KEY, None)
    return rec if isinstance(rec, dict) else {}


def enabled_login() -> str:
    """Логин журнала, для которого включён вход по Windows ('' — выключен)."""
    rec = _rec()
    return rec.get("login", "") if rec.get("blob") else ""


def is_enabled_for(login: str) -> bool:
    return bool(login) and enabled_login() == login


def enable(login: str, password: str) -> bool:
    """Включить: зашифровать пароль DPAPI и запомнить. Зовётся ТОЛЬКО после явного
    согласия пользователя (диалог с предупреждением) и удачного входа этим паролем."""
    if not available() or not login or not password:
        return False
    try:
        from security import os_protect
        blob = os_protect(password.encode("utf-8"))
        return local_set(_KEY, {
            "login": login,
            "blob": base64.b64encode(blob).decode("ascii"),
            "win_user": win_hello.current_user(),
        })
    except Exception as e:
        log.get("win_login").warning(f"[win_login] включение не удалось: {e}")
        return False


def disable() -> bool:
    """Выключить и СТЕРЕТЬ сохранённый пароль."""
    return local_set(_KEY, {})


def unlock(hwnd: int = 0):
    """Подтвердить личность через Windows и вернуть (login, password).

    ('', '') — не включено, пользователь отменил, Windows не подтвердила или расшифровать
    не удалось (например, файл перенесли на другой ПК — DPAPI его не откроет)."""
    rec = _rec()
    login, blob = rec.get("login", ""), rec.get("blob", "")
    if not login or not blob or not available():
        return "", ""
    who = rec.get("win_user") or win_hello.current_user()
    if not win_hello.verify(
            message=f"Подтвердите вход в GradeBookAI как «{login}»",
            caption=f"GradeBookAI · {who}", hwnd=hwnd):
        return "", ""
    try:
        from security import os_unprotect
        password = os_unprotect(base64.b64decode(blob)).decode("utf-8")
        return login, password
    except Exception as e:
        #Чужой ПК/другая учётка Windows — DPAPI не расшифрует. Не оставляем «мёртвую»
        #настройку: гасим её, чтобы человек вошёл обычным способом и включил заново.
        log.get("win_login").warning(f"[win_login] расшифровка не удалась: {e}")
        disable()
        return "", ""
