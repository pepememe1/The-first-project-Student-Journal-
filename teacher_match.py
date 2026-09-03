# -*- coding: utf-8 -*-
"""
teacher_match.py — сопоставление ФИО преподавателя С ПОРТАЛА с нашими аккаунтами.

КОРНЕВОЙ общий модуль (как `grading.py`, `study_hours.py`, `vector_nlu.py`): чистый
stdlib, без импортов сервера и без обращений к БД. Импортируют и сервер (подсказки
администратору), и — при необходимости — десктоп.
⚠️ Едет на бой ОТДЕЛЬНЫМ `scp`, а не вместе с `server/app` (§8.1 CLAUDE.md).

━━ ЗАЧЕМ ━━
Портал ВСГУТУ в каждой ячейке расписания пишет, КТО ведёт пару. У нас же связь
«преподаватель ↔ (группа, предмет)» ведётся отдельно и руками: админ проставляет
`SubjectHours.teacher_id`. Поэтому при смене расписания предметы у группы менялись, а
у преподавателя — нет: связь никто не пересобирал (жалоба Ярослава 28.08.2026).

━━ ПОЧЕМУ СОПОСТАВЛЕНИЕ, А НЕ АВТОМАТИЧЕСКОЕ НАЗНАЧЕНИЕ ━━
🔥 Разбор ячейки на портале — best-effort (`schedule/model.py::Lesson`), и это видно на
живых данных: из 127 занятий четырёх групп колледжа ФИО распозналось у 112 (88 %), но
среди них встречается «АФХД ИМТЕНОВА Л.Ф.» — к фамилии прилипла аббревиатура предмета.
Назначать журнал по такой строке МОЛЧА нельзя: цена ошибки — чужой преподаватель
получает доступ к оценкам и посещаемости чужой группы, то есть к ПДн студентов.
Поэтому модуль ничего не назначает. Он ОТВЕЧАЕТ НА ВОПРОС «на кого это похоже и
насколько уверенно», а решение принимает администратор.

━━ ФОРМАТЫ ━━
Портал: «ФАМИЛИЯ И.О.» заглавными, иногда с мусором перед фамилией.
У нас: `surname` + `name` («Имя Отчество») либо `full_name` целиком.
"""
from __future__ import annotations

import re
import unicodedata

#Токен-инициалы: «И.О.», «И.О», «И.» — точки могут отсутствовать у последней буквы.
_INITIALS_RE = re.compile(r"^([А-ЯЁA-Z])\.?\s*([А-ЯЁA-Z])?\.?$", re.IGNORECASE)

#Короче трёх букв фамилий не бывает. Нужно, чтобы аббревиатура в конце названия
#предмета («…разработки ПО», «Основы БЖ») не становилась фамилией, когда преподавателя
#в строке нет вовсе.
_MIN_SURNAME_LEN = 3


def _is_initials(tok: str) -> bool:
    """Инициалы ли это.

    🔥 КУПЛЕНО ДЕФЕКТОМ (03.09.2026): одной регулярки МАЛО. «ПО» в «Технология
    разработки ПО» подходило под неё идеально — две заглавные подряд, — и разбор давал
    фамилию «РАЗРАБОТКИ» с инициалами «П.О.». Дальше это ехало в подсказку назначения
    преподавателя, то есть ломалось ровно то, ради чего разбор и заведён.

    Отличие ровно одно и оно надёжное: **у инициалов есть точка**. «И.И.», «И. И.»,
    «И.» — везде; у аббревиатуры предмета её нет никогда. Поэтому две буквы без единой
    точки инициалами не считаются.

    ⚠️ Одинокая буква принимается и БЕЗ точки («СИДОРОВ С»): фамилией она быть не может
    по длине, и отвергнуть её значило бы сделать фамилией саму эту букву — обмен
    заметного дефекта на менее заметный.
    """
    m = _INITIALS_RE.match(tok)
    if not m:
        return False
    if m.group(2) and "." not in tok:
        return False          #«ПО», «АСУ»-подобное: две буквы без точки — не инициалы
    return True

#Что в строке портала НЕ является частью имени. Список намеренно КОРОТКИЙ и состоит из
#разделителей, а не из «подозрительных слов»: угадывать аббревиатуры предметов нельзя —
#их сотни, и первый неугаданный испортил бы фамилию.
_JUNK_CHARS = str.maketrans({"_": " ", ",": " ", ";": " ", "/": " ", "\\": " "})


def normalize(s: str) -> str:
    """Схлопывает пробелы и убирает разделители. Регистр НЕ трогаем — он значим ниже."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).translate(_JUNK_CHARS)
    return " ".join(s.split())


def parse_portal_name(raw: str) -> tuple:
    """Разбирает строку портала в `(фамилия, инициал_имени, инициал_отчества)`.

    Возвращает `("", "", "")`, если фамилию выделить не удалось — это честный отказ, а
    не догадка: строка без фамилии не должна превратиться в назначение.

    🔥 ФАМИЛИЯ — ЭТО ТОКЕН ПЕРЕД ИНИЦИАЛАМИ, А НЕ ПЕРВОЕ СЛОВО. Именно поэтому «АФХД
    ИМТЕНОВА Л.Ф.» разбирается верно: инициалы «Л.Ф.» стоят последними, перед ними
    «ИМТЕНОВА» — она и фамилия, а «АФХД» отбрасывается как приставший мусор. Разбор по
    первому слову дал бы фамилию «АФХД» и сопоставление в никуда.

    ⚠️ Строка вообще без инициалов («ИВАНОВ») тоже принимается: фамилия есть, инициалов
    нет. Такое сопоставление заведомо слабее — на однофамильцах оно неоднозначно, и
    вызывающий обязан это учитывать (см. `match_teacher`).
    """
    s = normalize(raw)
    if not s:
        return ("", "", "")
    parts = s.split()

    #ХВОСТ ИНИЦИАЛОВ, а не один токен. Портал пишет и «Л.Ф.», и «Л. Ф.» — во втором
    #случае поиск «последнего токена-инициалов» дал бы фамилию «Л.», то есть первый же
    #разнесённый вариант сопоставлялся бы в никуда. Отступаем влево, пока идут инициалы.
    tail = len(parts)
    while tail > 0 and _is_initials(parts[tail - 1]):
        tail -= 1

    if tail < len(parts) and tail > 0:
        letters = []
        for tok in parts[tail:]:
            m = _INITIALS_RE.match(tok)
            letters.append((m.group(1) or "").upper())
            if m.group(2):
                letters.append(m.group(2).upper())
        first = letters[0] if letters else ""
        patr = letters[1] if len(letters) > 1 else ""
        return (parts[tail - 1].upper(), first, patr)

    #Инициалов нет вовсе (или строка из одних инициалов) — фамилией считаем последний
    #«словесный» токен: у портала мусор липнет СЛЕВА, а не справа.
    #⚠️ Куски короче трёх букв отбрасываем: в строке «Технология разработки ПО»
    #преподавателя НЕТ вовсе, и «ПО» здесь — хвост названия предмета. Без этого условия
    #оно становилось бы фамилией, а честный отказ («не разобрал») превращался бы в
    #уверенную ошибку — то есть ровно в то, чего разбор избегает по построению.
    words = [w for w in parts
             if any(ch.isalpha() for ch in w) and not _is_initials(w)
             and len([ch for ch in w if ch.isalpha()]) >= _MIN_SURNAME_LEN]
    return (words[-1].upper(), "", "") if words else ("", "", "")


def account_key(surname: str, name: str, patronymic: str = "") -> tuple:
    """`(ФАМИЛИЯ, инициал имени, инициал отчества)` из полей нашего аккаунта.

    `name` у нас хранит «Имя Отчество» одной строкой (исторически — это ключ оценок),
    поэтому отчество берём либо из отдельного поля, либо из хвоста `name`.
    """
    sur = normalize(surname).upper()
    nm = normalize(name)
    patr = normalize(patronymic)
    if not patr and " " in nm:
        nm, patr = nm.split(" ", 1)
    first_i = nm[:1].upper()
    patr_i = patr[:1].upper()
    return (sur, first_i, patr_i)


def account_key_from_full_name(full_name: str) -> tuple:
    """То же, но из одной строки «Фамилия Имя Отчество» — когда полей нет."""
    parts = normalize(full_name).split()
    if not parts:
        return ("", "", "")
    sur = parts[0].upper()
    first_i = parts[1][:1].upper() if len(parts) > 1 else ""
    patr_i = parts[2][:1].upper() if len(parts) > 2 else ""
    return (sur, first_i, patr_i)


def score(portal_key: tuple, acc_key: tuple) -> int:
    """Насколько уверенно строка портала указывает на этот аккаунт: 0 | 1 | 2 | 3.

        3 — фамилия и ОБА инициала совпали (уверенно);
        2 — фамилия и один инициал (второго нет ни там, ни там);
        1 — совпала только фамилия (инициалов у портала нет);
        0 — не тот человек.

    ⚠️ Разные инициалы при одной фамилии — это НОЛЬ, а не «почти совпало». Иванов И.И. и
    Иванов П.С. — разные люди, и «похожесть» фамилии здесь не смягчающее обстоятельство:
    именно на этом месте ошибка выдала бы чужой журнал.
    """
    p_sur, p_first, p_patr = portal_key
    a_sur, a_first, a_patr = acc_key
    if not p_sur or not a_sur or p_sur != a_sur:
        return 0
    if p_first and a_first and p_first != a_first:
        return 0
    if p_patr and a_patr and p_patr != a_patr:
        return 0
    if p_first and a_first and p_patr and a_patr:
        return 3
    if p_first and a_first:
        return 2
    return 1


def match_teacher(raw_portal_name: str, accounts) -> dict:
    """Сопоставляет строку портала со списком аккаунтов.

    `accounts` — последовательность словарей `{id, surname, name, patronymic, full_name}`
    (лишние ключи игнорируются). Возвращает:

        {"portal": исходная строка,
         "parsed": (фамилия, И, О),
         "status": "matched" | "ambiguous" | "unknown" | "unparsed",
         "teacher_id": id единственного кандидата (только при "matched"),
         "confidence": 1..3,
         "candidates": [{id, name, confidence}, ...]}

    ⚠️ ДВА кандидата с ОДИНАКОВЫМ лучшим счётом — это `ambiguous`, а не «берём первого».
    Однофамильцы в колледже есть, и молчаливый выбор первого по списку — ровно тот способ
    выдать чужой журнал, от которого весь модуль и написан.
    """
    parsed = parse_portal_name(raw_portal_name)
    out = {"portal": raw_portal_name or "", "parsed": parsed,
           "status": "unparsed", "teacher_id": "", "confidence": 0, "candidates": []}
    if not parsed[0]:
        return out

    scored = []
    for a in accounts or []:
        key = account_key(a.get("surname", ""), a.get("name", ""), a.get("patronymic", ""))
        if not key[0]:
            key = account_key_from_full_name(a.get("full_name", ""))
        c = score(parsed, key)
        if c:
            scored.append({"id": a.get("id", ""), "name": a.get("full_name", "")
                           or f"{a.get('surname', '')} {a.get('name', '')}".strip(),
                           "confidence": c})
    if not scored:
        out["status"] = "unknown"
        return out

    scored.sort(key=lambda x: -x["confidence"])
    out["candidates"] = scored
    best = scored[0]["confidence"]
    top = [x for x in scored if x["confidence"] == best]
    if len(top) == 1:
        out.update(status="matched", teacher_id=top[0]["id"], confidence=best)
    else:
        out.update(status="ambiguous", confidence=best)
    return out
