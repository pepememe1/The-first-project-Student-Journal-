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
#
#🔥 `config` НЕ ПУШИТ НИКТО, включая админа (17.08.2026). Настройки — СЕРВЕРНЫЕ: их
#правят на сайте, а десктоп только читает их на pull (методика оценок нужна офлайн-
#расчёту). Обратное направление было чистым вредом: локальный `config` на десктопе
#пополняется ТОЛЬКО приёмом с сервера и ключи из него никогда не удаляются, а push
#применяет правку сравнением СОДЕРЖИМОГО, не глядя на метку, — то есть однажды увиденный
#ключ десктоп возвращал на сервер вечно, отменяя правки, сделанные на сайте. Ровно этим
#объясняется «воскресший оверрайд термина», который чистили руками ДВАЖДЫ (3.6.1 и 3.7.4)
#и оба раза не нашли, кто создаёт его заново.
#⚠️ Запрет нужен ИМЕННО на сервере, а не только в клиенте: в поле стоят .exe прежних
#версий, и они будут досылать свой config ещё месяцами. Держит
#`tests/test_sync_config_clobber.py`.
#🔥 `subjects` — ТА ЖЕ БОЛЕЗНЬ, что у `config`, найдена адверсариальным ревью в тот же
#день. Десктоп шлёт весь список предметов каждым циклом и ВСЕГДА с `deleted: False`
#(`sync_engine.subjects_to_rows` иначе не умеет — тумбстоуна у него нет), а push решает
#по содержимому: `existing.deleted=True != False` → строка оживает. То есть предмет,
#удалённый администратором на сайте, воскресал у него же через ~30 секунд, и так
#бесконечно — из `subjects.json` имя не уходит никогда. Отдельно неприятно, что у
#`subjects.py` есть ВСТРОЕННЫЙ список по умолчанию: свежая установка досылала на бой
#предметы, которых туда никто не заводил.
#Десктоп предметы не авторствует (локально `save_subjects` зовут только очистка кэша и
#наполнение встроенным дефолтом), каталог ведут на сайте — значит это направление обмена,
#как и у `config`, могло только откатывать чужое.
PUSH_SCOPE = {
    "admin": set(SYNC_MODELS.keys()) - {"config", "subjects"},
    "teacher": {"lessons", "grades", "term_grades"},
    "student": set(),
}


def _build_lesson_pair_map(db: Session, changes: dict, allowed_pairs: set,
                           allowed_subjects: set) -> dict:
    """Карта lesson_id → (группа, предмет) для построчной проверки оценок преподавателя.

    Берём пары из уже сохранённых на сервере занятий И из занятий этого же пуша,
    которые прошли проверку. Второе нужно, чтобы оценка к НОВОМУ занятию преподавателя
    принималась в одном пуше вместе с самим занятием (а не отвергалась только потому,
    что занятие сервер ещё не видел) — сюда пускаем и по паре, и (для преподавателя без
    назначений) по одному предмету, тем же мостом, что и `_teacher_may_write`."""
    m = {row[0]: (row[1], row[2])
         for row in db.query(Lesson.id, Lesson.group_name, Lesson.subject).all()}
    for item in (changes.get("lessons") or []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        pair = (item.get("group_name", ""), item.get("subject", ""))
        if pair in allowed_pairs or (not allowed_pairs and pair[1] in allowed_subjects):
            m[item["id"]] = pair
    return m


def _teacher_may_write(name: str, item: dict, allowed_pairs, allowed_subjects: set,
                       lesson_pairs: dict, student_group: dict) -> bool:
    """Построчная авторизация преподавателя: он вправе менять только СВОИ (группа, предмет).

    ⚠️ Раньше проверка шла ТОЛЬКО по предмету, и это было слабее, чем на сайте: препод
    «Математики» мог отправить синком оценки в ЛЮБУЮ группу колледжа, где эта математика
    вообще числится, — включая группы, которых он в глаза не видел. На вебе тот же
    сценарий закрыт с 3.3.1 (`_teacher_check_assignment`), а синк остался с прежним,
    более слабым правилом: явных назначений тогда попросту не существовало.

    Теперь источник прав ОДИН и тот же на обеих дверях — `webdata.teacher_assignments`
    (SubjectHours.teacher_id).

    ⚠️ `allowed_pairs is None` означает «у этого преподавателя нет НИ ОДНОГО назначения»,
    и тогда работает ПРЕЖНЕЕ правило по предмету. Это тот же мост, что уже стоит в
    `teacher_assignments` (allow_fallback), и он здесь обязателен: у колледжа, где админ
    ещё не расставил нагрузку, строгая проверка молча отвергала бы офлайн-правки — а
    потерянная оценка хуже лишнего разрешения. Мост односторонний: появилось хоть одно
    назначение — работают ТОЛЬКО назначения, вернуться к слабому правилу нельзя."""
    if allowed_pairs is None:
        if name == "lessons":
            return item.get("subject", "") in allowed_subjects
        if name == "grades":
            return (lesson_pairs.get(item.get("lesson_id", "")) or ("", ""))[1] in allowed_subjects
        if name == "term_grades":
            return item.get("subject", "") in allowed_subjects
        return False
    if name == "lessons":
        return (item.get("group_name", ""), item.get("subject", "")) in allowed_pairs
    if name == "grades":
        return lesson_pairs.get(item.get("lesson_id", "")) in allowed_pairs
    #Итоговая оценка за семестр несёт предмет, но НЕ группу — группу студента достаём
    #по ФИО (та же схема, что и в скоупе выдачи для преподавателя).
    if name == "term_grades":
        group = student_group.get((item.get("student_f", ""), item.get("student_n", "")))
        return (group, item.get("subject", "")) in allowed_pairs
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


#Поля, которые синк НЕ ВПРАВЕ МЕНЯТЬ у уже существующей строки (см. место применения).
#Только секреты: обычные поля пустыми бывают законно (нет отчества, нет группы).
#
#⚠️ Имя историческое: правило начиналось как «не обнулять пустотой» (потеря входа у 10
#студентов 30.07.2026) и 17.08.2026 РАСШИРЕНО до «не менять вовсе». Причина — второй,
#более тихий случай той же болезни: десктоп администратора каждый цикл досылал строку
#`admin:{логин}` с хешем из своего локального config, а push применяет правку по
#СРАВНЕНИЮ СОДЕРЖИМОГО, не глядя на метку. Смена пароля админа на сайте откатывалась за
#полминуты, причём `password_set_at` оставался новым — карточка уверяла, что пароль выдан
#только что, а работал прежний. Заполнить ПУСТОЙ хеш синк по-прежнему может (законный
#перенос учётных данных на новый узел, `test_push_can_still_set_a_real_hash`), а вот
#подменить существующий — нет: смена пароля идёт своими эндпоинтами
#(`models.set_user_password`), и у синка нет способа доказать, что его копия свежее.
_NEVER_BLANK = {"password_hash"}


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
    #student_subgroups: студенту нужна ТОЛЬКО СВОЯ подгруппа. Раньше уходила роспись
    #подгрупп ВСЕХ студентов колледжа (по неизменяемому student_id) — чужая ростер-
    #структура мимо скоупа. Ключуем по своему user.id (id студента не меняется, §12).
    changes["student_subgroups"] = [s for s in (changes.get("student_subgroups") or [])
                                    if s.get("student_id") == (user.id or "")]
    #subjects — справочник имён (не ПДн), оставляем как есть.


def _scope_for_teacher(changes: dict, user: User, db: Session) -> None:
    """Преподаватель получает свою строку + студентов СВОИХ групп (ростер журнала) и
    занятия/оценки/итоги только НАЗНАЧЕННЫХ ему пар (группа,предмет) — не «любая группа,
    где просто числится его предмет» (баг 3.3.1, утекал и офлайн через этот самый пулл:
    десктоп-журнал показывал чужие группы с совпавшим названием предмета). Хеши студентов
    вырезаем (нужны только имена/группы)."""
    from ..models import Lesson
    from .. import webdata as W
    login = user.login or ""
    ty, ts = W.current_term(W.load_config(db))
    #⚠️ БЕЗ моста (allow_fallback=False), в отличие от журнала. Здесь скоуп не «что
    #показать», а «что отдать на чужой компьютер»: без назначения офлайн-копия не должна
    #привозить группы и занятия вовсе. Мост существует ради видимости журнала, и
    #распространять его на выгрузку данных нельзя.
    pairs = set(W.teacher_assignments(db, user.id, ty, ts, allow_fallback=False))
    groups = {g for g, _s in pairs}
    changes["users"] = [u for u in (changes.get("users") or [])
                        if u.get("login") == login
                        or (u.get("role") == "student" and u.get("group_name") in groups)]
    _strip_other_hashes(changes["users"], login)
    changes["groups"] = [g for g in (changes.get("groups") or []) if g.get("name") in groups]
    changes["lessons"] = [l for l in (changes.get("lessons") or [])
                          if (l.get("group_name"), l.get("subject")) in pairs]
    lesson_gs = {row[0]: (row[1], row[2]) for row in
                db.query(Lesson.id, Lesson.group_name, Lesson.subject).all()}
    changes["grades"] = [gr for gr in (changes.get("grades") or [])
                         if lesson_gs.get(gr.get("lesson_id")) in pairs]
    #TermGrade хранит только студента+предмет, без группы — группу студента достаём
    #отдельно (та же схема, что и Grade выше через lesson_gs, только по студенту).
    student_group = {(row[0], row[1]): row[2] for row in
                     db.query(User.surname, User.name, User.group_name)
                     .filter(User.role == "student").all()}
    changes["term_grades"] = [
        t for t in (changes.get("term_grades") or [])
        if (student_group.get((t.get("student_f"), t.get("student_n"))), t.get("subject")) in pairs]
    #student_subgroups: только по НАЗНАЧЕННЫМ парам (как lessons/grades выше). Без фильтра
    #препод получал роспись подгрупп всех групп колледжа — чужая ростер-структура.
    changes["student_subgroups"] = [s for s in (changes.get("student_subgroups") or [])
                                    if (s.get("group_name"), s.get("subject")) in pairs]


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
    elif user.role == "student":
        _scope_for_student(changes, user)
    else:
        #🔒 Любая ОСТАЛЬНАЯ роль (сегодня это `parent`) не получает НИЧЕГО.
        #Раньше сюда падал общий студенческий скоуп — и это была настоящая, пусть и
        #узкая, утечка: _scope_for_student отбирает оценки по совпадению ФАМИЛИИ И
        #ИМЕНИ владельца токена, а у родителя они свои. Родитель-однофамилец (в семье
        #это буквально норма: «Иванов Пётр» отец и «Иванов Пётр» сын, да и просто
        #совпадение ФИО с ЧУЖИМ студентом) выкачал бы чужие оценки целиком.
        #Родителю офлайн-синк не нужен по построению: его кабинет — это веб (§14), а
        #веб-клиенты сюда и так не допускаются (_deny_web). Пустая выдача — это не
        #ограничение функции, а честное «этой роли здесь делать нечего».
        for name in list(changes.keys()):
            changes[name] = []


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

    #Построчная авторизация преподавателя — по его НАЗНАЧЕНИЯМ (группа, предмет), тем же
    #источником, что и на сайте. Для admin проверки нет (он вправе писать всё). Карты
    #строим по одному разу на запрос.
    is_teacher = user.role == "teacher"
    teacher_pairs = None          #None = назначений нет вовсе → прежнее правило по предмету
    teacher_subjects = set()
    lesson_pairs = {}
    student_group = {}
    if is_teacher:
        from ..webdata import teacher_assignments, current_term, load_config
        _ty, _ts = current_term(load_config(db))
        #allow_fallback=False: мост нам нужен ЯВНЫЙ (ниже), а не спрятанный внутри —
        #иначе не отличить «назначений нет» от «назначения есть» и не написать про это
        #в ответе честно.
        pairs = set(teacher_assignments(db, user.id, _ty, _ts, allow_fallback=False))
        teacher_pairs = pairs or None
        teacher_subjects = {s for s in (user.subjects or []) if s}
        lesson_pairs = _build_lesson_pair_map(db, changes, pairs, teacher_subjects)
        if changes.get("term_grades"):
            student_group = {(r[0], r[1]): r[2] for r in
                             db.query(User.surname, User.name, User.group_name)
                             .filter(User.role == "student").all()}

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
            #Преподаватель не вправе трогать чужую пару (группа, предмет) — отбрасываем.
            if is_teacher and not _teacher_may_write(
                    name, item, teacher_pairs, teacher_subjects, lesson_pairs, student_group):
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
            #🔒 НИКОГДА не затираем секрет ПУСТЫМ значением. Это стоило потери входа у
            #10 студентов на бою 30.07.2026, и механизм коварный: на pull сервер САМ
            #вырезает чужие хеши (_strip_other_hashes — правильно, на чужом ПК их быть не
            #должно), десктоп сохраняет строки уже с пустым полем и на следующем push
            #честно возвращает их обратно. Пустота записывалась поверх настоящего хеша, а
            #восстановить его нельзя — он невыводим, только из бэкапа.
            #Правило общее: клиент может ЗАДАТЬ секрет, которого ещё нет, но не может
            #ТРОГАТЬ уже существующий — ни обнулить, ни подменить. Смена пароля идёт
            #своими эндпоинтами, а не попутно синхронизацией (см. _NEVER_BLANK).
            item = {k: v for k, v in item.items()
                    if not (k in _NEVER_BLANK and getattr(existing, k, ""))}
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
