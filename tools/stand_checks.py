# -*- coding: utf-8 -*-
"""stand_checks.py — проверки по ролям на стенде с выдуманным колледжем (28.10.2026).

Зовёт `qa_stand.py --check` (в CI — задача «Артефакт релиза»). Смоук отвечает «поднялось
ли»; здесь — видит ли каждая роль СВОИ данные и не видит ли чужих: вход каждой учёткой,
кабинет роли с данными стенда, отказ в чужом кабинете, ответ Вектора из базы. Всё — по
живым адресам сервера, собранного из того же архива, что едет на бой.

Набор короткий намеренно: это не замена серверным тестам, а проверка, что они проверяли
тот продукт, который соберётся и поедет.
"""
from __future__ import annotations

import json

from smoke_release import _request


def _login(base: str, login: str, password: str) -> tuple[int, str]:
    code, body = _request(base + "/auth/login", data={"login": login, "password": password})
    try:
        return code, json.loads(body).get("access_token", "") if code == 200 else ""
    except ValueError:
        return code, ""


def _get(base: str, token: str, path: str) -> tuple[int, str]:
    code, body = _request(base + path, headers={"Authorization": "Bearer " + token})
    return code, body.decode("utf-8", "replace")


def _post(base: str, token: str, path: str, data: dict) -> tuple[int, str]:
    code, body = _request(base + path, data=data, headers={"Authorization": "Bearer " + token})
    return code, body.decode("utf-8", "replace")


def run(base: str, accounts: list) -> list[tuple[str, bool, str]]:
    """[(что проверяли, прошло ли, подробность)] — accounts как qa_stand.ACCOUNTS."""
    out: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        out.append((name, ok, detail))

    tokens = {}
    for login, password, role, *_ in accounts:
        code, token = _login(base, login, password)
        add("вход: %s (%s)" % (login, role), bool(token), "код %s" % code)
        tokens[role] = tokens.get(role) or token

    def own(role: str, path: str, must: str = "") -> None:
        token = tokens.get(role)
        if not token:
            add("%s видит %s" % (role, path), False, "нет входа")
            return
        code, body = _get(base, token, path)
        ok = code == 200 and (not must or must in body)
        add("%s видит %s" % (role, path), ok,
            "код %s%s" % (code, "" if ok or not must else ", нет «%s» в ответе" % must))

    def denied(role: str, path: str) -> None:
        token = tokens.get(role)
        code, _ = _get(base, token, path) if token else (0, "")
        add("%s не пускают в %s" % (role, path), code in (401, 403, 404), "код %s" % code)

    own("student", "/web/student/overview")
    own("student", "/web/student/journal", "Разработка программных модулей")
    own("teacher", "/web/teacher/overview")
    own("teacher", "/web/curator/groups", "К74/1")
    own("admin", "/web/admin/overview")
    own("admin", "/web/admin/groups", "К64/2")
    own("admin", "/web/admin/teachers", "Семёнова")
    own("parent", "/web/parent/children", "Петров")
    denied("student", "/web/admin/overview")
    denied("student", "/web/teacher/overview")
    denied("teacher", "/web/admin/teachers")
    denied("parent", "/web/student/journal")

    #Вектор отвечает из базы и без модели (на стенде LLM нет): пустой ответ — поломка.
    token = tokens.get("student")
    if token:
        code, body = _post(base, token, "/web/vector/ask", {"message": "какой у меня средний балл"})
        try:
            text = json.loads(body).get("text", "") if code == 200 else ""
        except ValueError:
            text = ""
        add("Вектор отвечает студенту из базы", bool(text.strip()), "код %s" % code)

    #Страницы сайта отдаются с того же адреса (SPA), в том числе глубокие ссылки.
    for path in ("/", "/login", "/student/journal"):
        code, body = _request(base + path)
        add("страница %s" % path, code == 200 and b"<div id=\"app\"" in body, "код %s" % code)
    return out
