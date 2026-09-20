"""
_common.py — общая часть пакета `routers/web`: роутер, импорты и разделяемые хелперы.

━━ ЗАЧЕМ ПАКЕТ ВМЕСТО ОДНОГО ФАЙЛА (3.6) ━━
`routers/web.py` вырос до 4288 строк и принял 62 коммита за полгода — по обоим
показателям это был САМЫЙ горячий файл репозитория. Любая серверная задача (студент,
преподаватель, расписание, Вектор, админка) правила его же, поэтому двое работающих
одновременно почти гарантированно расходились в одном файле. Разрез сделан по РОЛЯМ,
а не по техническим слоям: задачи в этом продукте приходят именно ролями («сделать
кураторам X»), и разные люди естественным образом оказываются в разных файлах.

━━ ЧТО ЛЕЖИТ ЗДЕСЬ, А ЧТО В МОДУЛЯХ РОЛЕЙ ━━
Здесь — то, чем пользуются НЕСКОЛЬКО ролей: сам `router`, проверки доступа и мелкие
утилиты. Всё остальное живёт в своём модуле. Правило простое: понадобилось из двух
модулей — переезжает сюда; нужно одному — остаётся у него. Так `_common.py` не
превращается во второй god-file, ради ухода от которого всё и затевалось.

⚠️ Модули ролей подключаются `from ._common import *`, поэтому здесь ОБЯЗАТЕЛЕН явный
`__all__`: обычный звёздочный импорт пропускает имена с подчёркиванием, а почти все
наши хелперы именно такие.
"""
import os
import re
from datetime import datetime, timezone, timedelta

from fastapi import (APIRouter, Body, Depends, HTTPException, Query, Request,
                     UploadFile, File, Form)
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import get_current_user, require_admin, current_jti
from ...models import (User, Group, Subject, Lesson, Grade, RegistrationRequest,
                       AuthSession, ConfigKV, TermGrade, ScheduleOverride,
                       ScheduleJointMark, schedule_override_id, joint_mark_id,
                       SubjectHours, subject_hours_id, ZetThreshold, zet_threshold_id,
                       NotifyEvent, StudentSubgroup, student_subgroup_id,
                       set_user_password, UserAchievement, StudentInvite)
from ... import webdata as W
from ... import schedule_web
from ... import reg_utils, mailer, gost, audit, vector_llm, translate_service
from ...parsers import esstu_parser
import vector_nlu   # общий с десктопом лексикон/классификатор (корень в sys.path через webdata)
import teacher_match   # корневой общий модуль: ФИО с портала -> наш аккаунт преподавателя
from schedule import parser as schedule_parser   # CATEGORIES — реестр категорий портала

router = APIRouter(prefix="/web", tags=["web"])


def _now_iso() -> str:
    """Серверная UTC-метка updated_at для LWW (как в /sync/push)."""
    return datetime.now(timezone.utc).isoformat()


def _contact_info(db: Session, logins: list) -> dict:
    """Для админ-списков: по логинам собираем телефон (из заявки на регистрацию) и данные
    последнего входа (время/IP/устройство из AuthSession). Возвращает {login: {...}}."""
    logins = [x for x in logins if x]
    if not logins:
        return {}
    out = {x: {"phone": "", "last_login": "", "ip": "", "device": ""} for x in logins}
    #последняя по времени сессия каждого логина
    for s in (db.query(AuthSession).filter(AuthSession.login.in_(logins))
              .order_by(AuthSession.issued_at.desc()).all()):
        rec = out.get(s.login)
        if rec is not None and not rec["last_login"]:
            rec["last_login"] = s.issued_at or ""
            rec["ip"] = s.ip or ""
            rec["device"] = (s.device_id or "")[:8]
    #телефон из заявки (у самостоятельно зарегистрированных студентов логин = email)
    for r in db.query(RegistrationRequest).filter(RegistrationRequest.email.in_(logins)).all():
        if r.phone and r.email in out and not out[r.email]["phone"]:
            out[r.email]["phone"] = gost.decrypt(r.phone)   # телефон хранится в ГОСТ-шифре
    return out


# ── Проверки доступа. Живут здесь, потому что нужны нескольким ролям сразу ──────────
def _require(role: str, user: User):
    if user.role != role:
        raise HTTPException(status_code=403, detail=f"Доступно только для роли «{role}»")


def _teacher_check_assignment(db, user: User, group: str, subject: str, year: str, semester):
    """Преподаватель работает только со СВОИМИ назначениями (группа+предмет за термин),
    а не с любой группой, где просто числится его предмет — см. teacher_assignments."""
    pairs = W.teacher_assignments(db, user.id, year, semester)
    if (group, subject) not in pairs:
        raise HTTPException(status_code=403, detail="Эта группа/предмет вам не назначены")


def _teacher_check_subgroup(db, user: User, lesson):
    """Преподаватель одной подгруппы не трогает объекты ЧУЖОЙ подгруппы (находка J07).

    🔥 ЗАЧЕМ ОТДЕЛЬНАЯ ПРОВЕРКА, если назначение уже проверено. `_teacher_check_assignment`
    отвечает на вопрос «твоя ли это пара (группа, предмет)», и при РАЗДЕЛЬНОМ обучении
    ответ «да» у обоих преподавателей сразу — они ведут одну пару, но разные половины
    группы. Чтение это учитывало с самого начала (`teacher.py` фильтрует занятия по
    `teacher_owned_subgroups`), а запись — нет: зная id занятия соседней подгруппы,
    преподаватель менял его тему, ставил оценки и удалял колонку. То есть ограничение
    существовало ровно до тех пор, пока человек пользовался интерфейсом.

    ⚠️ Занятие «Совместно» (`subgroup == 0`) НЕ ограничиваем. Создать такое может только
    ведущий обе подгруппы, но существующие общие занятия есть и у тех, кто ведёт одну:
    они заведены до разделения либо администратором. Запретить их правку значило бы
    отнять у преподавателя его же журнал ради защиты, которой в этом месте не требуется.

    ⚠️ Нет строки `SubjectHours` или разделения нет — ограничивать нечего: подгрупп в
    этой паре не существует, и выдумывать их по полю занятия нельзя.
    """
    if lesson is None:
        return
    sub = int(getattr(lesson, "subgroup", 0) or 0)
    if sub not in (1, 2):
        return
    sh_row = W.subject_hours_row(db, lesson.group_name, lesson.subject,
                                 lesson.year, lesson.semester)
    if not sh_row or not getattr(sh_row, "split", False):
        return
    owned = W.teacher_owned_subgroups(sh_row, user.id)
    if sub not in owned:
        raise HTTPException(status_code=403,
                            detail=f"Подгруппа {sub} вам не назначена")


def _curator_check(user: User, group: str):
    """Row-level: куратор видит только свои курируемые группы, иначе 403."""
    if group not in (user.curated_groups or []):
        raise HTTPException(status_code=403, detail="Группа вне вашего кураторства")


def _admin_or_curator_check(user: User, group: str):
    """Порог перевода и сама кнопка «Перевести» (docs/done/PLAN-ZET.md) — админ ИЛИ КУРАТОР
    именно этой группы. В отличие от журнала (куратор строго read-only), решение о
    переводе на курс — то, что куратор принимает по своим студентам каждый семестр;
    держать его только за админом означало бы гонять администратора за каждой группой."""
    if user.role == "admin":
        return
    if user.role == "teacher" and group in (user.curated_groups or []):
        return
    raise HTTPException(status_code=403, detail="Доступно администратору или куратору группы")


# ── Учебный период ──────────────────────────────────────────────────────────────────
def _mood_by_avg(avg: float) -> str:
    #Настроение маскота по среднему баллу (как эмоции Вектора в десктопе).
    if avg <= 0:
        return "neutral"
    if avg < 3:
        return "sad"
    if avg < 4:
        return "neutral"
    return "happy"


def _resolve_term(cfg: dict, year: str = "", semester=None) -> tuple:
    """Термин запроса: явные year+semester (просмотр архива) или ТЕКУЩИЙ из config.
    Так журнал/статистика по умолчанию показывают активный семестр, а прошлые —
    по явному выбору."""
    year = (year or "").strip()
    if year and semester:
        try:
            return year, int(semester)
        except (TypeError, ValueError):
            pass
    return W.current_term(cfg)


def _ensure_current_term(cfg: dict, lesson):
    """Защита от правки АРХИВА: писать (оценки/занятия) можно только в ТЕКУЩИЙ термин.
    Прошлые семестры — только чтение (перевод на курс их «замораживает»). Занятие без
    периода (легаси/десктоп до штампа) считаем текущим — не блокируем."""
    if lesson is None:
        return
    ly = (getattr(lesson, "year", "") or "").strip()
    if not ly:
        return
    cy, cs = W.current_term(cfg)
    if ly != cy or int(getattr(lesson, "semester", 0) or 0) != cs:
        raise HTTPException(
            status_code=409,
            detail="Этот семестр уже в архиве (только чтение). Правки возможны только "
                   "в текущем учебном периоде.")


def _resolve_student(db, group: str, surname: str, name: str, payload: dict):
    """Студент, которому адресована запись, — точно или с честным отказом (J08).

    🔥 ЗАЧЕМ (20.09.2026). Оба места записи (текущая оценка и итоговая) искали студента
    `.first()` по паре (фамилия, имя) в группе. При ПОЛНЫХ ТЁЗКАХ балл доставался
    первому найденному, и заметить это было нечем: в журнале две одинаковые строки,
    оценка появлялась не в той. Полные тёзки в одной группе — редкость, но не выдумка, а
    цена ошибки — оценка не тому человеку, вплоть до отчисления по чужим долгам.

    Порядок: пришёл `student_id` — адрес известен точно (сверяем роль, группу и что
    студент жив). Не пришёл (старый клиент, десктоп, запись из офлайн-очереди прежней
    сборки) — ищем по ФИО, и если таких ДВОЕ, честно отказываемся.

    ⚠️ Отказ, а не «возьмём первого». Это то же правило, по которому однофамильцы при
    сопоставлении преподавателя из расписания остаются `ambiguous`: лучше не записать,
    чем записать не тому. Текст отказа называет, что делать — обновить страницу: журнал
    с этого захода отдаёт `student_id` в каждой строке.
    """
    student_id = (payload.get("student_id") or "").strip()
    if student_id:
        stud = db.get(User, student_id)
        if (stud is None or stud.deleted or stud.role != "student"
                or (stud.group_name or "") != group):
            raise HTTPException(status_code=400, detail="Студент не найден в группе")
        return stud
    found = W.students_by_name(db, group, surname, name)
    if not found:
        raise HTTPException(status_code=400, detail="Студент не найден в группе")
    if len(found) > 1:
        raise HTTPException(
            status_code=409,
            detail=(f"В группе {group} двое студентов с именем {surname} {name}. "
                    f"Обновите страницу — журнал подставит, кому именно ставится оценка."))
    return found[0]


def _require_intended_term(cfg: dict, payload: dict) -> None:
    """Операция исполняется в ТОМ периоде, для которого её задумали, или не исполняется
    вовсе (20.09.2026, находка ревью J10).

    🔥 ЗАЧЕМ. Итоговая оценка и новое занятие штампуются `current_term` В МОМЕНТ
    ИСПОЛНЕНИЯ. Онлайн это одно и то же мгновение, а у офлайн-очереди между нажатием и
    доставкой лежит произвольный срок — ночь, каникулы, выходные. Преподаватель
    закрывает первый семестр без сети 30 декабря, очередь уходит 12 января: сервер
    записывает итоговую во ВТОРОЙ семестр и запирает им не тот период (наличие итоговой
    закрывает текущие оценки по предмету). Ни ошибки, ни следа — оценка есть, просто не
    там, где её поставили.

    ⚠️ Отказ, а не «перенесём в текущий». Куда девать работу, сделанную для закрытого
    периода, решает человек: открыть семестр обратно (это законное действие админа) или
    отказаться от записи. Молчаливый перенос — это решение за него, причём невидимое.
    Отказ виден: очередь кладёт такие записи в `rejected`, и плашка их показывает.

    ⚠️ Период НЕОБЯЗАТЕЛЕН, и это не дыра. Его не шлют онлайн-веб, десктоп и старые
    сборки мобильного приложения; требовать его — значит сломать их все ради случая,
    который у них не возникает (у онлайна постановка и доставка — одно мгновение).
    Прислал — сверяем; не прислал — прежнее поведение.
    """
    year = (payload.get("year") or "").strip()
    try:
        semester = int(payload.get("semester") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="semester должен быть числом 1 или 2")
    if not year or semester not in (1, 2):
        return
    cy, cs = W.current_term(cfg)
    if year != cy or semester != cs:
        raise HTTPException(
            status_code=409,
            detail=(f"Запись сделана для периода {year}·{semester}, а сейчас идёт "
                    f"{cy}·{cs}. Прошлый семестр в архиве — перенести её туда автоматически "
                    f"нельзя: откройте период или откажитесь от записи."))


def _final_grade_row(db, student_id: str, subject: str, year: str, semester: int):
    """Живая итоговая оценка студента по предмету за термин (None — её нет).

    «Живая» = не надгробие: снятая итоговая (`grade == ""`, `deleted`) семестр не
    закрывает, иначе исправить ошибку было бы нечем."""
    from ...models import term_grade_id
    row = db.get(TermGrade, term_grade_id(student_id, subject, year, semester))
    if row is None or row.deleted or not (row.grade or "").strip():
        return None
    return row


def _ensure_term_open(db, student_id: str, subject: str, year: str, semester: int):
    """🔒 ЗАМОК ЗАЧЁТКИ: выставлена итоговая — текущие оценки по предмету больше не пишутся.

    Требование Ярослава (28.08.2026): «если это поле есть, то препод не сможет новые
    ставить». Смысл не в удобстве: итоговая уходит в зачётку, и балл, дописанный ПОСЛЕ
    неё, меняет средний, по которому итоговую и выводили, — то есть документ перестаёт
    соответствовать журналу, и заметить это можно только сверив их вручную.

    ⚠️ Проверка живёт НА СЕРВЕРЕ, а не в интерфейсе. Спрятать поле — не защита: тот же
    запрос уходит из десктопа, из офлайн-очереди (`outbox.js`) и голосом.
    ⚠️ Дверь наружу есть и она одна: снять итоговую (пустое значение) — семестр снова
    открыт. Замок без выхода означал бы, что опечатка в оценке неисправима навсегда.
    ⚠️ Посещаемость («Н», «Б», «О») запирается ТОЖЕ, и это осознанно: она входит в тот
    же расчёт (пропуски, допуск), и «оценки закрыты, а пропуски дописываются» —
    полузакрытый семестр, худший из вариантов.
    """
    row = _final_grade_row(db, student_id, subject, year, semester)
    if row is not None:
        raise HTTPException(
            status_code=409,
            detail=f"По предмету «{subject}» уже выставлена итоговая оценка "
                   f"«{row.grade}» — семестр закрыт. Чтобы править текущие оценки, "
                   f"сначала снимите итоговую.")


# ── Выгрузка файлов (xlsx/docx) — общая для ведомостей, журналов и отчётов ──────────
_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _file_response(data: bytes, base_name: str, fmt: str):
    from fastapi.responses import Response
    from urllib.parse import quote
    ext = "docx" if fmt == "docx" else "xlsx"
    media = _DOCX_MEDIA if fmt == "docx" else _XLSX_MEDIA
    fname = f"{base_name}.{ext}".replace(" ", "_").replace("/", "-")
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition":
                             f"attachment; filename=export.{ext}; filename*=UTF-8''{quote(fname)}"})


#⚠️ Явный __all__ обязателен: `from ._common import *` иначе не принесёт ни одного
#имени с подчёркиванием, а на них держится половина модулей ролей.
__all__ = [
    # стандартная библиотека и внешние пакеты
    "os", "re", "datetime", "timezone", "timedelta",
    "APIRouter", "Body", "Depends", "HTTPException", "Query", "Request",
    "UploadFile", "File", "Form", "Session",
    # приложение
    "get_db", "get_current_user", "require_admin", "current_jti",
    "User", "Group", "Subject", "Lesson", "Grade", "RegistrationRequest",
    "StudentInvite",
    "AuthSession", "ConfigKV", "TermGrade", "ScheduleOverride", "ScheduleJointMark",
    "_final_grade_row", "_ensure_term_open",
    "schedule_override_id", "joint_mark_id", "SubjectHours", "subject_hours_id",
    "ZetThreshold", "zet_threshold_id", "NotifyEvent",
    "StudentSubgroup", "student_subgroup_id", "set_user_password", "UserAchievement",
    "W", "schedule_web", "reg_utils", "mailer", "gost", "audit", "vector_llm",
    "translate_service", "esstu_parser", "vector_nlu", "teacher_match", "schedule_parser",
    # роутер и общие хелперы
    "router", "_now_iso", "_contact_info", "_require", "_teacher_check_assignment", "_teacher_check_subgroup",
    "_curator_check", "_admin_or_curator_check", "_mood_by_avg", "_resolve_term",
    "_ensure_current_term", "_require_intended_term", "_resolve_student",
    "_XLSX_MEDIA", "_DOCX_MEDIA", "_file_response",
]
