"""
student_link.py — привязка оценок к НЕИЗМЕНЯЕМОМУ id студента (этап 2 миграции).

Оценки исторически ключуются по написанию ФИО (§10). Студентка выходит замуж, админ
правит фамилию — и вся история остаётся висеть на старом ключе. id строки users не
меняется никогда, поэтому связь по нему такой проблемы не имеет.

Здесь живёт ЛОГИКА сопоставления (общая для всех вызывающих):
  • tools/backfill_student_id_desktop.py — ручной прогон с подробным отчётом;
  • sync_runner — тихая до-клейка после каждого удачного синка.

Почему логика в приложении, а не в скрипте: скрипты в tools/ не попадают в .exe, а
преподаватель в колледже не станет запускать python руками. Значит доклеивать id
десктоп обязан сам.

Почему это не делает сервер за всех: серверный бэкофилл намеренно НЕ бампает
updated_at (иначе каждая оценка объявляется изменённой, весь парк выкачивает базу
заново, а серверная метка может перебить более свежую офлайн-правку). Без бампа
дельта проставленный id на клиента не привезёт — поэтому каждый ПК клеит себе сам.
"""
from collections import defaultdict
from contextlib import closing

import log

_log = log.get("student_link")

#Формулировки причин совпадают с серверным backfill_student_id.py дословно — отчёты
#двух платформ читаются рядом и сравниваются глазами без перевода.
REASON_NOT_FOUND = "студента с таким ФИО нет в справочнике"
REASON_AMBIGUOUS = "несколько студентов с одинаковым ФИО, группа не различила"
REASON_NO_GROUP = "занятие не найдено — не по чему различить однофамильцев"
REASON_TERM_NO_GROUP = "однофамильцы, а у итоговой оценки нет группы для различения"


def students_index() -> dict:
    """(фамилия, имя) → список студентов. Надгробия отфильтрованы get_students():
    привязывать живую оценку к удалённому аккаунту бессмысленно."""
    from data.data_store import get_store
    index = defaultdict(list)
    for s in (get_store().get_students() or []):
        index[((s.get("surname") or "").strip(), (s.get("name") or "").strip())].append(s)
    return index


def resolve(candidates: list, group: str) -> tuple:
    """Кандидаты + группа → (id, причина_отказа). Пустой id = не склеилось.

    Однофамильцев разводим по группе. Если и после этого их несколько — ОТКАЗЫВАЕМСЯ.
    Приписать оценку не тому студенту хуже, чем оставить строку на ФИО: второе чинится
    руками, первое молча портит данные и всплывёт через семестр."""
    if not candidates:
        return "", REASON_NOT_FOUND
    if len(candidates) == 1:
        return candidates[0].get("id", ""), ""
    if not group:
        return "", REASON_NO_GROUP
    same = [s for s in candidates if (s.get("group") or "").strip() == group]
    if len(same) == 1:
        return same[0].get("id", ""), ""
    return "", REASON_AMBIGUOUS


def scan(conn, index: dict) -> tuple:
    """Строки без student_id → (оценки, итоговые). Элемент:
    (ключ_для_UPDATE, фамилия, имя, группа, id, причина, надгробие?)."""
    cur = conn.cursor()
    #Группу берём у ЗАНЯТИЯ — именно она различает однофамильцев (двух полных тёзок
    #в одну группу не заводят).
    cur.execute("SELECT id, COALESCE(group_name,'') FROM lessons")
    lesson_group = {r[0]: (r[1] or "").strip() for r in cur.fetchall()}

    cur.execute("SELECT student_f,student_n,lesson_id,COALESCE(deleted,0) FROM grades "
                "WHERE COALESCE(student_id,'')=''")
    grades = []
    for f, n, lid, deleted in cur.fetchall():
        f, n = (f or "").strip(), (n or "").strip()
        group = lesson_group.get(lid, "")
        sid, reason = resolve(index.get((f, n), []), group)
        grades.append(((f, n, lid), f, n, group, sid, reason, bool(deleted)))

    cur.execute("SELECT id,student_f,student_n,COALESCE(deleted,0) FROM term_grades "
                "WHERE COALESCE(student_id,'')=''")
    terms = []
    for gid, f, n, deleted in cur.fetchall():
        f, n = (f or "").strip(), (n or "").strip()
        sid, reason = resolve(index.get((f, n), []), "")
        if reason == REASON_NO_GROUP:
            reason = REASON_TERM_NO_GROUP      #у итоговой занятия нет вовсе
        terms.append(((gid,), f, n, "", sid, reason, bool(deleted)))
    return grades, terms


def apply_matches(conn, grades: list, terms: list) -> int:
    """Проставляет найденные id. Возвращает число обновлённых строк.

    updated_at НЕ трогаем: это техническая простановка связи, а не правка оценки. Бамп
    метки отправил бы всю базу в push и мог бы перебить более свежую правку с другого ПК."""
    cur = conn.cursor()
    written = 0
    for (f, n, lid), _f, _n, _g, sid, _r, _d in grades:
        if not sid:
            continue
        cur.execute("UPDATE grades SET student_id=? WHERE student_f=? AND student_n=? "
                    "AND lesson_id=?", (sid, f, n, lid))
        written += 1
    for (gid,), _f, _n, _g, sid, _r, _d in terms:
        if not sid:
            continue
        cur.execute("UPDATE term_grades SET student_id=? WHERE id=?", (sid, gid))
        written += 1
    conn.commit()
    return written


def backfill(apply: bool = True) -> tuple:
    """Один проход бэкофилла. Возвращает (записано, всего_без_id, не_склеилось_живых).

    Идемпотентен и дешёв: выбираются ТОЛЬКО строки с пустым student_id, поэтому после
    первого прохода работы нет и запрос отрабатывает вхолостую. Именно поэтому его можно
    звать после каждого синка, не заводя флаг «уже сделано» — флаг соврал бы на свежей
    установке, где справочник ещё не приехал и клеить было не с чем."""
    from data.core import DBManager
    with closing(DBManager.get_conn()) as conn:
        index = students_index()
        grades, terms = scan(conn, index)
        total = len(grades) + len(terms)
        if not total:
            return 0, 0, 0
        live_failed = sum(1 for r in grades + terms if not r[4] and not r[6])
        written = apply_matches(conn, grades, terms) if apply else 0
        return written, total, live_failed


def backfill_quietly() -> int:
    """Обёртка для фонового вызова из sync_runner: никогда не бросает и не мешает синку.

    Привязка id — улучшение, а не условие работы программы: если она не удалась, оценки
    продолжают жить на ФИО-ключах ровно как раньше. Ронять из-за неё цикл синхронизации
    было бы несоразмерно."""
    try:
        written, total, live_failed = backfill(apply=True)
        #Сразу за доклейкой — перевод ключей итоговых (этап 3). Порядок важен: без
        #student_id переводить нечего, поэтому только ПОСЛЕ бэкофилла.
        from contextlib import closing as _closing
        from data.core import DBManager as _DB
        with _closing(_DB.get_conn()) as _c:
            moved = migrate_local_term_keys(_c)
        if moved:
            _log.info("ключи итоговых оценок переведены на student_id: %s", moved)
        if written:
            _log.info("привязка оценок к id студентов: проставлено %s из %s", written, total)
        if live_failed:
            #Не WARNING на каждый цикл: это ожидаемое состояние (студента могли ещё не
            #завести), а лог не должен превращаться в шум. Но знать об этом надо.
            _log.info("оценок без владельца (живых): %s — разобрать вручную перед "
                      "переходом на ключи по id", live_failed)
        return written
    except Exception as e:
        _log.warning("привязка оценок к id не удалась (не критично): %s", e)
        return 0


def migrate_local_term_keys(conn) -> int:
    """ЭТАП 3: переводит id итоговых оценок с ФИО-ключа на student_id. Возвращает число
    переведённых строк.

    Почему только term_grades. У оценок за занятия локальный ключ — (ФИО, занятие), и
    поле `id` в таблице вообще не хранится: его считает _collect_grades при отправке.
    А у итоговых `id` лежит в таблице И приходит с сервера при pull — поэтому, не
    переведи мы их здесь, после серверной миграции рядом со старой строкой
    `Иванова|Мария|Мат|…` легла бы новая `stud:ivanova|Мат|…`: ДУБЛЬ в ведомости.

    updated_at не трогаем: это техническая смена ключа, а не правка оценки (см. backfill).
    Конфликт (целевой id уже занят) разрешаем в пользу СУЩЕСТВУЮЩЕЙ строки и просто
    убираем дубликат — данные в них одинаковы, это две записи одной оценки.
    """
    from data.core import term_grade_id
    cur = conn.cursor()
    cur.execute("SELECT id,subject,COALESCE(year,''),COALESCE(semester,0),"
                "COALESCE(student_id,'') FROM term_grades WHERE COALESCE(student_id,'')<>''")
    rows = cur.fetchall()
    existing = {r[0] for r in rows}
    moved = 0
    for old_id, subject, year, semester, sid in rows:
        new_id = term_grade_id(sid, subject, year, semester)
        if new_id == old_id:
            continue                       #уже переведена
        if new_id in existing:
            cur.execute("DELETE FROM term_grades WHERE id=?", (old_id,))
        else:
            cur.execute("UPDATE term_grades SET id=? WHERE id=?", (new_id, old_id))
            existing.add(new_id)
        existing.discard(old_id)
        moved += 1
    if moved:
        conn.commit()
    return moved
