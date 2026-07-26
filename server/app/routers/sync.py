"""
sync.py — Сердце offline-first: дельта-синхронизация десктопа с сервером.

Идея:
  • GET  /sync/pull?since=<ISO> — сервер отдаёт все записи, изменённые ПОЗЖЕ since
    (по каждой сущности). Десктоп вливает их в локальный SQLite.
  • POST /sync/push — десктоп присылает свои изменения (накопленные офлайн).
    Сервер применяет их по правилу «последний по времени побеждает» (LWW по
    updated_at). Удаления приходят как deleted=true (надгробия), а не пропажа строк.

Десктоп хранит метку последней успешной синхронизации и в следующий раз тянет
только дельту. Так связь нужна редко и кратко — это и даёт работу «без интернета».

Авторизация (важно для безопасности). Полный дельта-синк выгружает ВСЕ строки всех
таблиц — включая password_hash всех пользователей и таблицу config (в т.ч. ключи ИИ).
Это допустимо только для ДЕСКТОП-клиента на ПОДТВЕРЖДЁННОМ устройстве, поэтому /sync:
  • закрыт для ВЕБ-клиентов (X-Client: web) — из браузера синк не нужен (там role-
    scoped /web/* и /me/*), а web-клиент в обход барьера устройства был единственным
    вектором массовой выгрузки чужих данных (студент → весь дамп БД). Теперь — 403;
  • для не-веба (десктоп) get_current_user применяет БАРЬЕР УСТРОЙСТВА: пускаются
    только одобренные администратором ПК. Роли admin/teacher/student на таком ПК
    синхронизируются штатно; неодобренный ПК получает 403 ещё в get_current_user.
Что роль вправе ПУШИТЬ — дополнительно ограничено PUSH_SCOPE (admin — всё; teacher —
занятия и оценки СВОИХ предметов; student — ничего, только тянет).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, is_web_client
from ..models import (SYNC_MODELS, User, Lesson, grade_id, term_grade_id,
                      is_new_style_key)
from .. import events

router = APIRouter(prefix="/sync", tags=["sync"])


def _deny_web(request: Request):
    """Синк — десктоп-протокол. Веб-клиенту (браузеру) он недоступен: из браузера
    выгружать полный дамп БД (хеши паролей, config с ключами) нельзя. Веб работает
    через role-scoped /web/* и /me/*. Возвращаем 403 ДО любой работы с БД."""
    if is_web_client(request):
        raise HTTPException(
            status_code=403,
            detail="Синхронизация доступна только десктоп-клиенту на подтверждённом "
                   "устройстве. В браузере используйте разделы сайта.")


#Что какая роль имеет право отправлять на сервер (ограничение по ТИПУ сущности).
PUSH_SCOPE = {
    "admin": set(SYNC_MODELS.keys()),
    "teacher": {"lessons", "grades", "term_grades"},
    "student": set(),
}


def _build_lesson_subject_map(db: Session, changes: dict, allowed_subjects: set) -> dict:
    """Карта lesson_id → subject для построчной проверки оценок преподавателя.

    Берём предметы из уже сохранённых на сервере занятий И из занятий этого же пуша,
    которые прошли проверку по предмету. Второе нужно, чтобы оценка к НОВОМУ занятию
    преподавателя принималась в одном пуше вместе с самим занятием (а не отвергалась
    только потому, что занятие сервер ещё не видел)."""
    m = {row[0]: row[1] for row in db.query(Lesson.id, Lesson.subject).all()}
    for item in (changes.get("lessons") or []):
        if isinstance(item, dict) and item.get("id") and item.get("subject", "") in allowed_subjects:
            m[item["id"]] = item.get("subject", "")
    return m


def _teacher_may_write(name: str, item: dict, allowed_subjects: set,
                       lesson_subject: dict) -> bool:
    """Построчная авторизация преподавателя: он вправе менять только СВОИ предметы.

    Ограничиваем по предмету, а не по группе: `subjects` у преподавателя реально
    заполняется при заведении (admin_dashboard), а `group_assignments` часто пусто —
    проверка по группам отвергала бы и легитимные правки. Это не даёт преподавателю
    править чужой предмет; разграничение по конкретным группам внутри одного предмета —
    осознанно вне области этой проверки (нет надёжных данных о владении группой)."""
    if name == "lessons":
        return item.get("subject", "") in allowed_subjects
    if name == "grades":
        return lesson_subject.get(item.get("lesson_id", "")) in allowed_subjects
    #Итоговая оценка за семестр несёт свой предмет — проверяем прямо по нему.
    if name == "term_grades":
        return item.get("subject", "") in allowed_subjects
    return False


def _now() -> str:
    #UTC + смещение (+00:00), с микросекундами. Сервер — ЕДИНЫЙ источник меток
    #времени для синка (см. push): так LWW не зависит от часов клиентов.
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row, model) -> dict:
    return {c.name: getattr(row, c.name) for c in model.__table__.columns}


#Ключи config, которые НЕ должны покидать сервер к не-админам: секреты провайдеров ИИ
#(токен GigaChat и т.п.). Паттерн, а не точный список — чтобы новый секретный ключ не
#«протёк» по недосмотру. Методику оценок, тему, выбор провайдера НЕ трогаем (не секреты).
_SECRET_CFG_PATTERNS = ("credential", "token", "secret", "api_key", "apikey", "password")


def _is_secret_config_key(key: str) -> bool:
    k = (key or "").lower()
    return any(p in k for p in _SECRET_CFG_PATTERNS)


def _strip_other_hashes(users: list, own_login: str) -> None:
    """Хеш пароля оставляем ТОЛЬКО владельцу (нужен для офлайн-входа на его ПК);
    у остальных строк вырезаем — на клиентском ПК чужих хешей быть не должно."""
    for u in users:
        if u.get("login") != own_login:
            u["password_hash"] = ""


def _scope_for_student(changes: dict, user: User) -> None:
    """Студент получает ТОЛЬКО своё: свою строку user, свои оценки/итоги, занятия своей
    группы и саму группу. Чужих студентов (ПДн) и чужих занятий он не видит вовсе."""
    login = user.login or ""
    f, n, grp = (user.surname or ""), (user.name or ""), (user.group_name or "")
    changes["users"] = [u for u in (changes.get("users") or []) if u.get("login") == login]
    changes["groups"] = [g for g in (changes.get("groups") or []) if g.get("name") == grp]
    changes["lessons"] = [l for l in (changes.get("lessons") or []) if l.get("group_name") == grp]
    changes["grades"] = [gr for gr in (changes.get("grades") or [])
                         if gr.get("student_f") == f and gr.get("student_n") == n]
    changes["term_grades"] = [t for t in (changes.get("term_grades") or [])
                              if t.get("student_f") == f and t.get("student_n") == n]
    #subjects — справочник имён (не ПДн), оставляем как есть.


def _scope_for_teacher(changes: dict, user: User, db: Session) -> None:
    """Преподаватель получает свою строку + студентов СВОИХ групп (ростер журнала) и
    занятия/оценки/итоги только СВОИХ предметов. Чужие группы/предметы и чужих
    преподавателей — не видит. Хеши студентов вырезаем (нужны только имена/группы)."""
    from ..models import Lesson
    from .. import webdata as W
    login = user.login or ""
    subjects = set(user.subjects or [])
    groups = set(W.teacher_groups(db, subjects))
    changes["users"] = [u for u in (changes.get("users") or [])
                        if u.get("login") == login
                        or (u.get("role") == "student" and u.get("group_name") in groups)]
    _strip_other_hashes(changes["users"], login)
    changes["groups"] = [g for g in (changes.get("groups") or []) if g.get("name") in groups]
    changes["lessons"] = [l for l in (changes.get("lessons") or [])
                          if l.get("subject") in subjects]
    lesson_subj = {row[0]: row[1] for row in db.query(Lesson.id, Lesson.subject).all()}
    changes["grades"] = [gr for gr in (changes.get("grades") or [])
                         if lesson_subj.get(gr.get("lesson_id")) in subjects]
    changes["term_grades"] = [t for t in (changes.get("term_grades") or [])
                              if t.get("subject") in subjects]


def _scope_pull_for_role(changes: dict, user: User, db: Session) -> None:
    """Минимизация выгрузки по роли (152-ФЗ, снижение радиуса поражения одного ПК).

    Админ получает всё (нужны хеши для правки юзеров, секреты ИИ для настроек; админ-ПК
    доверенные и малочисленные). Не-админам:
      • секретные ключи config (токен GigaChat и пр.) не отдаём вовсе — озвучку ИИ
        десктоп получает через сервер (/vector/voice), токен остаётся на сервере;
      • row-scope ПДн: студент видит только себя, преподаватель — только свои группы/
        предметы. Свой хеш пароля пользователь получает (нужен для офлайн-входа)."""
    if user.role == "admin":
        return
    changes["config"] = [c for c in (changes.get("config") or [])
                         if not _is_secret_config_key(c.get("key", ""))]
    if user.role == "teacher":
        _scope_for_teacher(changes, user, db)
    else:
        #student и любая иная не-админ-роль — по минимуму «только своё».
        _scope_for_student(changes, user)


@router.get("/pull")
def pull(since: str = "", request: Request = None,
         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Отдать изменения позже метки since (пусто — отдать всё)."""
    _deny_web(request)   #браузеру полный дамп БД не отдаём (см. модульный docstring)
    #Метку времени фиксируем ДО выборки, а не после. Клиент сохранит её как новую
    #границу дельты (следующий pull попросит since=server_time). Если взять метку
    #ПОСЛЕ выборки, запись, попавшая в БД между выборкой и взятием метки, не вошла
    #бы в этот ответ и была бы пропущена следующим pull. Беря метку раньше, мы в
    #худшем случае повторно отдадим пограничную запись (применение идемпотентно),
    #но НЕ потеряем её.
    server_time = _now()
    changes = {}
    for name, model in SYNC_MODELS.items():
        q = db.query(model)
        if since:
            #СТРОГО >= , а не > : запись, чья метка совпала с меткой прошлого pull (обе
            #операции попали в один тик часов — на Windows это реально), при строгом «>»
            #выпадала из дельты НАВСЕГДА, до своего следующего изменения. Это ровно та
            #потеря, которую docstring выше обещает не допускать. С «>=» пограничная
            #запись максимум придёт повторно — а применение идемпотентно (см. push).
            q = q.filter(model.updated_at >= since)
        changes[name] = [_row_to_dict(r, model) for r in q.all()]
    #Минимизация по роли: чужие ПДн/хеши и секреты config не покидают сервер к не-админам.
    _scope_pull_for_role(changes, user, db)
    return {"server_time": server_time, "changes": changes}



def _student_id_by_name(db, f: str, n: str, group: str = "") -> str:
    """ФИО (+группа) → id студента. '' — не нашли или тёзки неразличимы.

    Та же логика, что в backfill_student_id.py: при неоднозначности ОТКАЗЫВАЕМСЯ.
    Приписать оценку не тому студенту хуже, чем отвергнуть строку."""
    q = db.query(User).filter(User.role == "student", User.surname == (f or "").strip(),
                              User.name == (n or "").strip(),
                              User.deleted == False)      # noqa: E712
    if group:
        q = q.filter(User.group_name == group)
    hits = q.all()
    return hits[0].id if len(hits) == 1 else ""


def _normalize_grade_key(db, name: str, item: dict, lesson_group: dict) -> str:
    """Канонический ключ строки оценки — ЭТАП 3 миграции.

    Зачем: ключом стал student_id, но клиент старой версии продолжает слать
    `Иванова|Мария|L1`. Без нормализации такая строка легла бы РЯДОМ с
    `stud:ivanova|L1` — две записи одной и той же оценки, и журнал показал бы
    дубль. Поэтому ключ на приёме пересчитываем сами и клиенту на слово не верим.

    Порядок: готовый student_id из payload → иначе резолв по ФИО.

    Не разрешилось — возвращаем ИСХОДНЫЙ ключ, а не отбрасываем строку. Это важно:
    ростер преподавателя ведётся отдельно от справочника, и оценка студенту, которого
    админ ещё не завёл, — законная ситуация (см. REASON_NOT_FOUND в бэкофилле).
    Отвергать такие строки значило бы ТЕРЯТЬ выставленные оценки, а потеря данных
    несоразмерно хуже дубля. Строка синхронизируется на старом ключе и доклеится
    позже, когда студент появится.
    """
    key = item.get("id") or ""
    if is_new_style_key(key):
        return key                       #уже новый формат — доверяем
    sid = (item.get("student_id") or "").strip()
    if not sid:
        group = lesson_group.get(item.get("lesson_id", ""), "") if name == "grades" else ""
        sid = _student_id_by_name(db, item.get("student_f", ""),
                                  item.get("student_n", ""), group)
    if not sid:
        return key                       #не опознали — оставляем как есть, но не теряем
    if name == "grades":
        return grade_id(sid, item.get("lesson_id", ""))
    return term_grade_id(sid, item.get("subject", ""), item.get("year", ""),
                         item.get("semester", 0))


def _notify_homework_from_sync(db: Session, lesson: dict) -> None:
    """Разослать студентам группы уведомление о ДЗ, приехавшем с десктопа.

    Полностью в try/except: изменения УЖЕ приняты и закоммичены, и сбой рассылки не имеет
    права превратить успешный синк в ошибку — клиент решил бы, что push не прошёл, и
    отправил бы всё заново."""
    try:
        from .. import rustore_push
        from ..webdata import students_in_group
        group = lesson.get("group_name") or ""
        if not group:
            return
        for stud in students_in_group(db, group):
            if not stud.login:
                continue
            rustore_push.notify_homework(
                db, stud.login, subject=lesson.get("subject") or "",
                lesson_id=lesson.get("id") or "", task=lesson.get("topic") or "",
                number=int(lesson.get("number") or 0))
    except Exception as e:      # noqa: BLE001 — рассылка не должна ронять синк
        print(f"[homework] рассылка уведомлений о ДЗ из синка не удалась: {e}")


@router.post("/push")
def push(payload: dict = Body(...), request: Request = None,
         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Принять изменения от клиента. Права — по роли (PUSH_SCOPE).

    Метку времени ставит СЕРВЕР (server_ts), а не клиент: так разрешение конфликтов
    не зависит от часов на машинах преподавателей (clock skew). Правило получается
    «последняя успешно дошедшая до сервера правка побеждает».

    Чтобы дельта-синк не гонял все записи каждый цикл, штампуем и применяем только
    те записи, чьё содержимое реально изменилось (клиент шлёт полный снимок)."""
    _deny_web(request)   #браузер не пушит в общий синк (у него /web/*, /me/*)
    allowed = PUSH_SCOPE.get(user.role, set())
    changes = (payload or {}).get("changes", {}) or {}
    #Занятия с десктопа приходят БЕЗ учебного периода (десктоп его не знает). Штампуем
    #текущим термином, иначе они выпадут из фильтра журнала по семестру.
    if isinstance(changes.get("lessons"), list) and changes["lessons"]:
        from ..webdata import load_config, current_term
        _ty, _ts = current_term(load_config(db))
        for _it in changes["lessons"]:
            if isinstance(_it, dict) and not (_it.get("year") or "").strip():
                _it["year"], _it["semester"] = _ty, _ts
    server_ts = _now()
    applied = {}
    rejected = {}
    new_homework = []    #ДЗ, впервые приехавшие с клиента — разослать после commit

    #Построчная авторизация преподавателя — по его предметам. Для admin проверки нет
    #(он вправе писать всё). Карту lesson→subject строим один раз на запрос.
    teacher_subjects = None
    lesson_subject = {}
    if user.role == "teacher":
        teacher_subjects = set(user.subjects or [])
        lesson_subject = _build_lesson_subject_map(db, changes, teacher_subjects)

    #Карта занятие→группа: нужна, чтобы развести ПОЛНЫХ ТЁЗОК при нормализации ключа
    #оценки, пришедшей от старого клиента (без student_id). Двух Ивановых Иванов в одну
    #группу не заводят, поэтому занятие однозначно указывает на нужного. Строим один раз
    #на запрос и только если оценки в payload вообще есть.
    lesson_group = {}
    if changes.get("grades"):
        lesson_group = {r[0]: (r[1] or "") for r in db.query(Lesson.id, Lesson.group_name)}

    for name, items in changes.items():
        model = SYNC_MODELS.get(name)
        if model is None or name not in allowed or not isinstance(items, list):
            continue
        pk = list(model.__table__.primary_key.columns)[0].name
        cols = {c.name for c in model.__table__.columns}
        #Поля, по которым решаем «изменилось ли»: всё, кроме PK и служебной метки.
        compare_cols = cols - {pk, "updated_at"}
        count = 0
        rej = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item.get(pk)
            #Оценки ключуются по НЕИЗМЕНЯЕМОМУ student_id (этап 3). Клиенту на слово не
            #верим: старая версия шлёт ФИО-ключ, и без пересчёта строка легла бы РЯДОМ
            #с новой — дубль одной и той же оценки в журнале.
            if name in ("grades", "term_grades") and key:
                key = _normalize_grade_key(db, name, item, lesson_group)
                item = dict(item, id=key)
            if not key:
                continue
            #Преподаватель не вправе трогать чужой предмет — отбрасываем такие строки.
            if teacher_subjects is not None and not _teacher_may_write(
                    name, item, teacher_subjects, lesson_subject):
                rej += 1
                continue
            existing = db.get(model, key)
            if existing is None:
                data = {k: v for k, v in item.items() if k in cols}
                data[pk] = key
                data["updated_at"] = server_ts   #метка — серверная
                db.add(model(**data))
                count += 1
                #Домашнее задание, созданное на десктопе, доезжает сюда обычным push'ем —
                #и студентов надо уведомить так же, как при создании с сайта. Копим и
                #рассылаем ПОСЛЕ commit: рассылка не должна ни удлинять транзакцию, ни
                #уронить приём изменений. Условие «строки ещё не было» и есть защита от
                #повторов: полный снимок push'ится заново каждые N циклов, и без него
                #группа получала бы одно и то же ДЗ снова и снова.
                if name == "lessons" and (data.get("type") or "") == "ДЗ" and not data.get("deleted"):
                    new_homework.append(data)
                continue
            #Применяем, только если контент реально отличается от хранимого —
            #иначе не трогаем (иначе каждая синхронизация бы «омолаживала» всё).
            changed = any(k in item and getattr(existing, k) != item[k]
                          for k in compare_cols)
            if changed:
                for k, v in item.items():
                    if k in compare_cols:
                        setattr(existing, k, v)
                existing.updated_at = server_ts   #метку обновляет сервер
                count += 1
        applied[name] = count
        if rej:
            rejected[name] = rej

    db.commit()
    for hw in new_homework:
        _notify_homework_from_sync(db, hw)
    #Преподаватель попытался записать НЕ свой предмет — это нарушение прав, поэтому
    #видно в админской консоли (а не молча игнорируется).
    if rejected:
        events.record("warn", "push_rejected",
                      f"отклонены чужие записи: {rejected}", user.login)
    result = {"server_time": server_ts, "applied": applied}
    #rejected включаем, только если что-то отвергли — клиенту видно, что часть
    #правок не его (не молчим, но и не шумим в обычном случае).
    if rejected:
        result["rejected"] = rejected
    return result
