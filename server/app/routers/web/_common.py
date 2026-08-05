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
from ...deps import get_current_user, require_admin
from ...models import (User, Group, Subject, Lesson, Grade, RegistrationRequest,
                       AuthSession, ConfigKV, TermGrade, ScheduleOverride,
                       ScheduleJointMark, schedule_override_id, joint_mark_id,
                       SubjectHours, subject_hours_id, ZetThreshold, zet_threshold_id,
                       NotifyEvent, StudentSubgroup, student_subgroup_id)
from ... import webdata as W
from ... import schedule_web
from ... import reg_utils, mailer, gost, audit, vector_llm, translate_service
from ...parsers import esstu_parser
import vector_nlu   # общий с десктопом лексикон/классификатор (корень в sys.path через webdata)
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


def _curator_check(user: User, group: str):
    """Row-level: куратор видит только свои курируемые группы, иначе 403."""
    if group not in (user.curated_groups or []):
        raise HTTPException(status_code=403, detail="Группа вне вашего кураторства")


def _admin_or_curator_check(user: User, group: str):
    """Порог перевода и сама кнопка «Перевести» (docs/PLAN-ZET.md) — админ ИЛИ КУРАТОР
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
    "get_db", "get_current_user", "require_admin",
    "User", "Group", "Subject", "Lesson", "Grade", "RegistrationRequest",
    "AuthSession", "ConfigKV", "TermGrade", "ScheduleOverride", "ScheduleJointMark",
    "schedule_override_id", "joint_mark_id", "SubjectHours", "subject_hours_id",
    "ZetThreshold", "zet_threshold_id", "NotifyEvent",
    "StudentSubgroup", "student_subgroup_id",
    "W", "schedule_web", "reg_utils", "mailer", "gost", "audit", "vector_llm",
    "translate_service", "esstu_parser", "vector_nlu", "schedule_parser",
    # роутер и общие хелперы
    "router", "_now_iso", "_contact_info", "_require", "_teacher_check_assignment",
    "_curator_check", "_admin_or_curator_check", "_mood_by_avg", "_resolve_term",
    "_ensure_current_term", "_XLSX_MEDIA", "_DOCX_MEDIA", "_file_response",
]
