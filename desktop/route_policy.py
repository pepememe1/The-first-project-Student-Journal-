"""
route_policy.py — что программа делает с КАЖДЫМ запросом ЗАПИСИ интерфейса.

━━ ЗАЧЕМ (аудит 22.09.2026, находка F-02, P1) ━━
Внутри программы SPA говорит с ЛОКАЛЬНЫМ сервером (`desktop/local_api.py`), который
поднимает настоящий `server/app` на локальной копии базы. Читать из копии — правильно:
это и есть offline-first. А вот писать в неё было дефектом, и очень тихим: копия
наполняется зеркалом ТОЛЬКО с боя в сторону ПК (`local_mirror.py`), а старый синк
собирал правки из ДРУГОЙ базы (`vsgutu_grades.db`), в которую интерфейс не пишет с
удаления Qt. Итог: оценка, выставленная в программе, получала «сохранено», жила в копии
и НЕ ДОЕЗЖАЛА НА БОЙ НИКОГДА. Из 193 маршрутов записи сервера 86 обслуживались так —
оценки, расписание, курсы, согласие на доступ родителя, второй фактор, импорт данных.

━━ ТРИ ПОЛИТИКИ ━━
  • REPLAY — журнал преподавателя. Обязан работать без сети (§4.1): правка ложится в
    копию мгновенно и тут же встаёт в надёжную очередь (`desk_outbox.py`), которая
    досылает её на бой ПО ПОРЯДКУ, с версией, которую человек видел (конфликт — на экран,
    а не молча).
  • LOCAL — обслуживается копией НАМЕРЕННО, у каждой строки названа причина.
  • всё остальное — PROXY: запрос уходит на бой, после успешной записи зеркало
    подтягивается сразу, без сети — честный отказ, а не «сохранено» в пустоту.

⚠️ УМОЛЧАНИЕ — PROXY, и это не случайность. Новый маршрут записи, о котором здесь не
подумали, должен работать онлайн и честно отказывать офлайн, а не молча оседать в копии:
ровно этот исход и был дефектом. Сторож `tests/test_route_policy.py` проверяет, что у
каждой строки REPLAY/LOCAL есть живой маршрут сервера (мёртвых записей нет) и что
разделы с незеркалируемыми таблицами пересылаются целиком.
"""
import re

#Журнал преподавателя — единственное, что пишется офлайн. Шаблоны пути — полные, без
#«начинается с»: иначе будущий `/web/teacher/grade-import` молча стал бы офлайновым.
#  table — таблица копии, строку которой правка меняет (зеркало не перезапишет эту
#          строку, пока правка не дошла до боя: иначе человек видел бы, как его оценка
#          «откатилась» у него на глазах);
#  base  — досылать ли версию, которую человек видел (`base_updated_at`): бой по ней
#          отличает правку на свежей версии от затирания чужой (конфликт → на экран).
#          У создания базы нет — строки ещё не существовало; у удаления сервер её не
#          сверяет (см. `teacher_delete_lesson`).
#  term  — обработчик штампует запись ТЕКУЩИМ периодом; период, названный копией в
#          ответе, досылается на бой, и тот откажет, если период за это время сменился
#          (J10, исследование синка 25.09.2026, W-08). Без него занятие, созданное офлайн
#          30 декабря и досланное 12 января, легло бы на бою в другой семестр.
REPLAY = (
    {"method": "POST", "path": r"/web/teacher/grade", "table": "grades", "base": True},
    {"method": "POST", "path": r"/web/teacher/lesson", "table": "lessons", "base": False,
     "create": True, "term": True},
    {"method": "PUT", "path": r"/web/teacher/lesson/[^/]+", "table": "lessons", "base": True},
    {"method": "DELETE", "path": r"/web/teacher/lesson/[^/]+", "table": "lessons",
     "base": False},
    {"method": "POST", "path": r"/web/teacher/term-grade", "table": "term_grades",
     "base": True, "term": True},
)

#Обслуживается локальной копией НАМЕРЕННО. Причина у каждой строки обязательна: без неё
#это не решение, а забытый случай (урок сторожа `/public/*`, §«исключение без причины»).
LOCAL = {
    ("POST", r"/auth/login"):
        "мост входа программы: сначала локальная копия, затем бой (install_login_bridge)",
    ("POST", r"/auth/mfa/verify"):
        "второй шаг входа: мост проверяет код на бою, а сессию выдаёт локальную",
    ("POST", r"/auth/refresh"): "продление ЛОКАЛЬНОЙ сессии программы",
    ("POST", r"/auth/logout"): "выход из ЛОКАЛЬНОЙ сессии программы",
    ("POST", r"/connect/request"):
        "мост подтверждения устройства сам пересылает на бой с машинным id",
    ("POST", r"/connect/verify"): "то же — мост подтверждения устройства",
    ("POST", r"/web/vector/ask"):
        "Вектор отвечает по локальной копии — это и есть его офлайн-режим",
    ("POST", r"/web/vector/voice/command"):
        "только РАЗБИРАЕТ команду (§4.14); записывает её потом /web/teacher/grade",
    ("POST", r"/web/vector/stt"):
        "распознавание на своей машине: звук с ПДн не покидает ПК (152-ФЗ)",
    ("POST", r"/web/vector/tts"): "озвучка на своей машине",
    ("POST", r"/vector/voice"): "переформулировка фактов Вектора, данных не пишет",
    ("POST", r"/sync/push"):
        "протокол синка самого сервера; интерфейс программы его не вызывает",
}

REPLAY_RE = tuple((spec["method"], re.compile(spec["path"] + r"\Z"), spec)
                  for spec in REPLAY)
LOCAL_RE = tuple((m, re.compile(p + r"\Z")) for m, p in LOCAL)

#Чтение не меняет ничего и всегда идёт из копии (кроме разделов `_PROXY_PREFIXES`).
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def replay_spec(method: str, path: str) -> dict:
    """Описание строки REPLAY для запроса ({} — запрос не из журнала)."""
    m = (method or "").upper()
    for mm, rx, spec in REPLAY_RE:
        if mm == m and rx.match(path or ""):
            return spec
    return {}


def replay_tables() -> frozenset:
    """Таблицы копии, которые правит журнал (их строки знает очередь досылки)."""
    return frozenset(spec["table"] for spec in REPLAY)


def row_key_hint(method: str, path: str, body: bytes) -> str:
    """Ключ строки, которую правка изменит, — ДО обработчика, если его можно вывести из
    самого запроса ('' — нельзя).

    🔒 Зачем (исследование синка 25.09.2026, W-07). Раньше ключ появлялся только из
    ОТВЕТА обработчика, и всё время между постановкой в очередь и ответом строка не была
    защищена от зеркала: оно успевало перезаписать только что выставленную оценку старым
    серверным значением, и человек видел «откат» у себя на глазах. Ключ правки журнала
    почти всегда виден в запросе: id занятия — в пути, у оценки — id студента и занятия,
    у нового занятия — UUID от клиента (F-05). Где не виден (старый клиент без
    `student_id`, итоговая без периода), зеркало не трогает копию, пока правка в полёте
    (`desk_outbox.mirror_guard()['in_flight']`).

    ⚠️ Формат ключей — ТОЛЬКО из `app.models` (`grade_id`/`term_grade_id`): вторая копия
    формата разошлась бы с сервером молча, и защита промахивалась бы мимо строки."""
    import json
    spec = replay_spec(method, path)
    if not spec:
        return ""
    m = (method or "").upper()
    if m in ("PUT", "DELETE"):
        return (path or "").rstrip("/").rsplit("/", 1)[-1]
    try:
        data = json.loads(bytes(body or b"") or b"{}")
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    if spec.get("create"):
        #Сервер принимает id занятия только UUID и хранит его в нижнем регистре.
        return str(data.get("id") or "").strip().lower()
    sid = str(data.get("student_id") or "").strip()
    if not sid:
        return ""
    from app.models import grade_id, term_grade_id
    if spec["table"] == "grades":
        lesson_id = str(data.get("lesson_id") or "").strip()
        return grade_id(sid, lesson_id) if lesson_id else ""
    if spec["table"] == "term_grades":
        subject = str(data.get("subject") or "").strip()
        year = str(data.get("year") or "").strip()
        try:
            semester = int(data.get("semester") or 0)
        except (TypeError, ValueError):
            return ""
        if subject and year and semester in (1, 2):
            return term_grade_id(sid, subject, year, semester)
    return ""


#Собственные маршруты ПРОГРАММЫ (раздел «Сервер», состояние синка, передача сессии) —
#их нет в `server/app` вовсе, они живут только в локальном сервере (`desktop/*`). Отправить
#их «на бой» по умолчанию значило бы получить там 404, а здесь — неработающий раздел:
#ровно это поймал тест раздела «Сервер» при первом прогоне политики.
DESKTOP_OWN_PREFIXES = ("/desk/", "/desktop/")


def classify(method: str, path: str) -> str:
    """'read' | 'replay' | 'local' | 'proxy' — что делать с запросом."""
    m = (method or "").upper()
    if m in READ_METHODS:
        return "read"
    p = path or ""
    if p.startswith(DESKTOP_OWN_PREFIXES):
        return "local"
    if replay_spec(m, p):
        return "replay"
    for mm, rx in LOCAL_RE:
        if mm == m and rx.match(p):
            return "local"
    return "proxy"
