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
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

import re as _re

from ..db import get_db, SessionLocal
from ..deps import get_current_user, is_web_client
from ..models import (SYNC_MODELS, User, Lesson, SyncDelete, SERVER_ONLY_COLUMNS,
                      grade_id, term_grade_id, is_new_style_key, row_student_id)
from .. import events, sync_clock, sync_notify
from ..versioning import based_on_older_version as _based_on_older_version

router = APIRouter(prefix="/sync", tags=["sync"])
#Будильник долгого опроса `/sync/head` — слушатели на фабрике сессий (см. `sync_notify`).
sync_notify.install(SessionLocal)


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


def _chunks(seq, size: int):
    """Режет список на куски. Нужно из-за жёсткого предела SQLite на число параметров
    в `IN (...)` — по умолчанию 999. Пакет синхронизации бывает и на тысячи оценок,
    и один огромный `IN` упал бы «too many SQL variables» ровно на большом пуше, то
    есть там, где ошибка дороже всего."""
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _incoming_lesson_ids(changes: dict) -> set:
    """Идентификаторы занятий, упомянутые ВО ВХОДЯЩЕМ пакете, — и только они.

    🔥 Ради этого набора всё и затевалось. Обе карты ниже (`lesson_id → пара` и
    `lesson_id → группа`) строились выборкой ВСЕЙ таблицы занятий на КАЖДЫЙ push. У
    колледжа на 8 000 человек это десятки тысяч строк, которые расшифровываются
    SQLCipher-ом и материализуются в память одноядерной машины — по нескольку раз в
    минуту, потому что каждый преподаватель синхронизируется раз в 30 секунд. А нужны
    из них ровно те, на которые ссылаются пришедшие оценки: обе карты читаются
    ИСКЛЮЧИТЕЛЬНО как `.get(item["lesson_id"])`.

    ⚠️ Занятия из ЭТОГО ЖЕ пакета сюда не входят намеренно: их в базе ещё нет, и
    доклеиваются они отдельно, из самого пакета (см. вызывающего).
    """
    out = set()
    for g in (changes.get("grades") or []):
        if isinstance(g, dict):
            lid = g.get("lesson_id")
            if lid:
                out.add(lid)
    return out


def _build_lesson_pair_map(db: Session, changes: dict, allowed_pairs: set,
                           allowed_subjects: set) -> dict:
    """Карта lesson_id → (группа, предмет) для построчной проверки оценок преподавателя.

    Берём пары из уже сохранённых на сервере занятий И из занятий этого же пуша,
    которые прошли проверку. Второе нужно, чтобы оценка к НОВОМУ занятию преподавателя
    принималась в одном пуше вместе с самим занятием (а не отвергалась только потому,
    что занятие сервер ещё не видел) — сюда пускаем и по паре, и (для преподавателя без
    назначений) по одному предмету, тем же мостом, что и `_teacher_may_write`."""
    #Берём из базы ТОЛЬКО те занятия, на которые ссылаются пришедшие оценки. Пустой
    #набор — в базу не ходим вовсе: карту всё равно спросят лишь по этим ключам.
    wanted = _incoming_lesson_ids(changes)
    m = {}
    if wanted:
        for chunk in _chunks(sorted(wanted), 500):
            m.update({row[0]: (row[1], row[2])
                      for row in db.query(Lesson.id, Lesson.group_name, Lesson.subject)
                                   .filter(Lesson.id.in_(chunk)).all()})
    for item in (changes.get("lessons") or []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        pair = (item.get("group_name", ""), item.get("subject", ""))
        if pair in allowed_pairs or (not allowed_pairs and pair[1] in allowed_subjects):
            m[item["id"]] = pair
    return m


class _Students:
    """Кто есть кто среди студентов — ОДНА дверь «чья это строка» для синка (W-04).

    🔥 Раньше выдача и приём итоговых держали карту «(фамилия, имя) → группа», и у
    полных тёзок из РАЗНЫХ групп словарь молча оставлял одного из них: итоговая уезжала
    преподавателю чужой группы, а свой её не получал. Правило теперь одно, то же, что
    у записи на сайте (J08): id в строке есть — только по нему; нет — по ФИО, и ТОЛЬКО
    если такое ФИО у студентов одно. «Не узнали» — это отказ, а не «первый найденный»:
    оценка не тому человеку хуже, чем оценка, которую пришлось переставить.

    ⚠️ Уникальность считается по ВСЕМ студентам, включая удалённых: у удалённого тёзки
    остались строки, и отдать их живому значило бы отдать чужое.
    ⚠️ Выбирается не весь справочник, а нужные id и фамилии: push идёт от каждого
    преподавателя раз в полминуты, и полная таблица на одном ядре дорога (та же
    причина, что у карт занятий выше). По фамилии грузятся ВСЕ её носители — иначе
    уникальность ФИО нечем было бы проверить.
    ⚠️ Ключ карты — значения ИЗ БАЗЫ, спрашивают по значениям ИЗ ПАКЕТА без обрезки, а
    грузим И сырую, И обрезанную фамилию (урок краевого пробела, нашёл Полковник)."""

    def __init__(self):
        self._group_by_id = {}
        self._ids_by_fio = {}
        self._ids = set()
        self._surnames = set()
        self._everyone = False

    def _add(self, rows) -> None:
        for sid, f, n, g in rows:
            self._group_by_id[sid] = g or ""
            self._ids_by_fio.setdefault((f or "", n or ""), set()).add(sid)

    def _base(self, db):
        return (db.query(User.id, User.surname, User.name, User.group_name)
                  .filter(User.role == "student"))

    def load_all(self, db) -> "_Students":
        if not self._everyone:
            self._add(self._base(db).all())
            self._everyone = True
        return self

    def load(self, db, ids=(), surnames=()) -> "_Students":
        if self._everyone:
            return self
        want_ids = {i for i in ids if i} - self._ids
        want_sn = set()
        for s in surnames:
            if s:
                want_sn.update({s, s.strip()})
        want_sn = {s for s in want_sn if s} - self._surnames
        for chunk in _chunks(sorted(want_ids), 500):
            self._add(self._base(db).filter(User.id.in_(chunk)).all())
        for chunk in _chunks(sorted(want_sn), 500):
            self._add(self._base(db).filter(User.surname.in_(chunk)).all())
        self._ids |= want_ids
        self._surnames |= want_sn
        return self

    def owner(self, row: dict) -> str:
        """Id студента, которому принадлежит строка; '' — не опознан или тёзки."""
        sid = row_student_id(row.get("student_id"), row.get("id"))
        if sid:
            return sid
        ids = self._ids_by_fio.get((row.get("student_f") or "", row.get("student_n") or ""))
        return next(iter(ids)) if ids and len(ids) == 1 else ""

    def group_of(self, row: dict):
        """Группа студента этой строки; None — если студент не опознан однозначно."""
        sid = self.owner(row)
        return self._group_by_id.get(sid) if sid else None

    def load_for(self, db, rows) -> "_Students":
        """Догрузить всех, о ком могут спросить по этим строкам."""
        return self.load(
            db,
            ids=[row_student_id(r.get("student_id"), r.get("id"))
                 for r in rows if isinstance(r, dict)],
            surnames=[r.get("student_f") or "" for r in rows if isinstance(r, dict)])


def _domain_refusal(db, name: str, item: dict, cfg: dict) -> str:
    """Причина, по которой доменные правила журнала НЕ пускают эту запись («» — пускают).

    🔥 ЗАЧЕМ (20.09.2026, находка ревью J06). Веб-ручка `/web/teacher/grade` проверяет
    ЧЕТЫРЕ вещи: значение по шкале, назначение на пару, архив прошлых семестров и замок
    зачётки (выставлена итоговая — текущие оценки по предмету закрыты). Через
    `/sync/push` не проверялось НИ ОДНО, кроме назначения: одна и та же операция
    получала разное решение в зависимости от ТРАНСПОРТА. Офлайн-копия обходила и замок
    зачётки, и запрет правки архива, и проверку значения — молча, с успешным ответом.

    ⚠️ Отказ НЕ выдаётся за сохранение: он попадает в `rejected`, клиент его читает
    (`sync_engine`: предупреждение в лог + `last_rejected` для индикатора), а сверка
    «сервер = истина» при непустом `rejected` не стирает локальный кэш — то есть работа
    остаётся у человека, а не исчезает вместе с отказом.

    ⚠️ Правила НЕ ПЕРЕПИСАНЫ здесь второй копией — зовутся те же функции, что у веба
    (`grading.is_allowed_value`, `_ensure_term_open`). Вторая копия разошлась бы с
    первой на первой же правке, и разошлась бы молча.

    ⚠️ Проверяется ТОЛЬКО то, что реально МЕНЯЕТСЯ (см. вызывающий): полный снимок
    десктопа раз в N циклов везёт и архивные оценки, совпадающие с серверными. Отвергать
    их значило бы держать `rejected` вечно ненулевым — а заодно навсегда отключить
    сверку, которая при отказах кэш не трогает.

    ⚠️ И только для ПРЕПОДАВАТЕЛЯ, ровно как проверка области рядом. У администратора в
    вебе другие двери и другие права (он и итоговую снимает, и архив правит), а его push
    несёт весь справочник колледжа — применить к нему учительские замки значило бы
    сломать синхронизацию хост-ПК ради симметрии, которой в продукте и нет.
    """
    from .web._common import _ensure_term_open        # то же правило, что у веб-ручки
    from ..webdata import grading, current_term

    if name == "term_grades":
        if not grading.is_allowed_value((item.get("grade") or "").strip()):
            return "недопустимое значение итоговой оценки"
        return ""
    if name != "grades":
        return ""
    if not grading.is_allowed_value((item.get("grade") or "").strip()):
        return "недопустимое значение оценки"

    #Пересдачи ключуются с суффиксом (<id>_retake[_N]) — период и замок смотрим по
    #БАЗОВОМУ занятию, ровно как это делает веб-ручка.
    lid = _re.sub(r"_retake(_\d+)?$", "", (item.get("lesson_id") or "").strip())
    if not lid:
        return ""
    lesson = db.get(Lesson, lid)
    if lesson is None or lesson.deleted:
        return ""        #занятия нет — не наш случай, LWW разберётся сам
    ly = (lesson.year or "").strip()
    if ly:
        cy, cs = current_term(cfg)
        if ly != cy or int(lesson.semester or 0) != cs:
            return f"семестр {ly}·{lesson.semester} в архиве (только чтение)"

    #Замок зачётки персональный, значит нужен ИМЕННО ЭТОТ студент. Старый ФИО-ключ
    #сюда доезжает без `student_id`; угадывать по фамилии нельзя — у тёзок это был бы
    #чужой замок (см. J08), а промах в эту сторону отнимает у человека его работу.
    #⚠️ Id — из той же двери, что и остальное (W-04): у строки старого клиента колонка
    #пуста, а ключ push уже перевёл на её владельца. Это не угадывание — ключ приведён
    #только при однозначном опознании, и замок обязан идти за ключом.
    student_id = row_student_id(item.get("student_id"), item.get("id"))
    if not student_id:
        return ""
    try:
        _ensure_term_open(db, student_id, lesson.subject, lesson.year, lesson.semester)
    except HTTPException:
        return "по предмету уже выставлена итоговая — семестр закрыт"
    return ""


def _row_scope(name: str, row) -> dict:
    """Область СУЩЕСТВУЮЩЕЙ строки в том же виде, в каком её ждёт `_teacher_may_write`.

    Нужна затем, чтобы право спрашивалось не только про то, КУДА кладут, но и про то,
    ГДЕ запись лежит сейчас (см. вызывающего)."""
    if name == "lessons":
        return {"group_name": getattr(row, "group_name", "") or "",
                "subject": getattr(row, "subject", "") or ""}
    if name == "grades":
        return {"lesson_id": getattr(row, "lesson_id", "") or ""}
    if name == "term_grades":
        return {"id": getattr(row, "id", "") or "",
                "student_id": getattr(row, "student_id", "") or "",
                "student_f": getattr(row, "student_f", "") or "",
                "student_n": getattr(row, "student_n", "") or "",
                "subject": getattr(row, "subject", "") or ""}
    return {}


def _learn_scope_of_existing(db: Session, name: str, row, lesson_pairs: dict,
                             students: "_Students") -> None:
    """Дочитать в карты то, что нужно для суждения о СУЩЕСТВУЮЩЕЙ строке.

    ⚠️ Без этого проверка существующей записи давала бы ЛОЖНЫЕ отказы, а не защиту:
    `lesson_pairs` и `students` строятся по ПРИСЛАННЫМ данным, и занятия, на
    которое ссылается лежащая в базе оценка, там может не быть вовсе. Отказ по
    незнанию неотличим для человека от «сервер съел мою оценку», поэтому недостающее
    добираем точечно — по одному ключу и только когда он действительно понадобился."""
    if name == "grades":
        lid = getattr(row, "lesson_id", "") or ""
        if lid and lid not in lesson_pairs:
            got = (db.query(Lesson.group_name, Lesson.subject)
                     .filter(Lesson.id == lid).first())
            lesson_pairs[lid] = (got[0] or "", got[1] or "") if got else None
    elif name == "term_grades":
        students.load_for(db, [_row_scope(name, row)])


def _teacher_may_write(name: str, item: dict, allowed_pairs, allowed_subjects: set,
                       lesson_pairs: dict, students: "_Students") -> bool:
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
    #Итоговая оценка за семестр несёт предмет, но НЕ группу — группу студента достаёт
    #`_Students` (W-04): по id, а по ФИО только без тёзок. Не опознан — None, и пара
    #(None, предмет) не совпадёт ни с одной разрешённой: отказ, а не догадка.
    if name == "term_grades":
        return (students.group_of(item), item.get("subject", "")) in allowed_pairs
    return False


def _now() -> str:
    #UTC + смещение (+00:00), с микросекундами. Сервер — ЕДИНЫЙ источник меток
    #времени для синка (см. push): так LWW не зависит от часов клиентов.
    return datetime.now(timezone.utc).isoformat()


#🔥 ВРЕМЯ КАК КУРСОР — ИЗВЕСТНАЯ ЛОВУШКА (исследование синка 25.09.2026, W-02).
#`updated_at` ставится ДО коммита, а читатель видит только закоммиченное (снимок WAL).
#Писатель поставил метку T1, pull начал читать в T2 > T1 и строки ещё не видит; писатель
#коммитит — а следующий pull с `since=T2` её уже НИКОГДА не попросит: T1 < T2. Строка
#терялась до полной сверки, молча. Окно — миллисекунды у одиночной оценки и секунды у
#массовых операций админа и старых push.
#Поэтому водяной знак отдаём с НАХЛЁСТОМ: «всё, что новее, чем две минуты до начала
#чтения». Пограничные строки придут повторно (применение идемпотентно — правило «лучше
#отдать повторно, чем потерять»), а не пропадут.
#⚠️ Это ОБЕЗБОЛИВАЮЩЕЕ, а не лечение. Транзакция длиннее нахлёста или скачок часов больше
#него по-прежнему теряют строку. Лечение — номер изменения от сервера (`change_seq`):
#он растёт внутри транзакции записи, писатель в SQLite один, и порядок номеров совпадает
#с порядком коммитов (план — внутреннее исследование синка 25.09.2026, П9; в репозиторий не входит). Время остаётся
#для людей («когда»), координатой потока оно быть не должно.
PULL_LOOKBACK_S = 120


def _pull_watermark() -> str:
    """Водяной знак для ответа pull: «сейчас» минус нахлёст (см. выше)."""
    return (datetime.now(timezone.utc) - timedelta(seconds=PULL_LOOKBACK_S)).isoformat()


def _row_to_dict(row, model) -> dict:
    return {c.name: getattr(row, c.name) for c in model.__table__.columns}


#Ключи config, которые НЕ должны покидать сервер к не-админам: секреты провайдеров ИИ
#(токен GigaChat и т.п.). Паттерн, а не точный список — чтобы новый секретный ключ не
#«протёк» по недосмотру. Методику оценок, тему, выбор провайдера НЕ трогаем (не секреты).
_SECRET_CFG_PATTERNS = ("credential", "token", "secret", "api_key", "apikey", "password")


def _is_secret_config_key(key: str) -> bool:
    k = (key or "").lower()
    return any(p in k for p in _SECRET_CFG_PATTERNS)


def _config_without_secrets(rows: list) -> list:
    """Строки `config` без секретов — и на уровне строки, И ВНУТРИ её значения.

    🔥 УТЕЧКА, КОТОРУЮ СТОРОЖ НЕ ВИДЕЛ (26.09.2026). Фильтр смотрел только на ИМЯ строки,
    а настройки ИИ сайт кладёт ВНУТРЬ строки `config` — словарём, где лежит и
    `gigachat_credentials` (`POST /web/admin/ai-config`). Строка называется `config`,
    секретом по имени не выглядит, и рабочий ключ к платному внешнему сервису уезжал в
    `/sync/pull` каждому преподавателю и студенту — на все ПК колледжа. Сторож
    `test_pull_teacher_row_scope` засевал ключ ОТДЕЛЬНОЙ строкой, то есть не так, как его
    сохраняет продукт, и потому был зелёным рядом с утечкой.
    ⚠️ Значение копируем, а не правим на месте: `_row_to_dict` отдаёт ТОТ ЖЕ словарь,
    что лежит в объекте сессии."""
    out = []
    for c in rows or []:
        if _is_secret_config_key(c.get("key", "")):
            continue
        v = c.get("value")
        if isinstance(v, dict):
            c = dict(c, value={k: x for k, x in v.items() if not _is_secret_config_key(k)})
        out.append(c)
    return out


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

#🔒 ПУСТОЕ ЗНАЧЕНИЕ ПОЛЯ, КОТОРОГО КЛИЕНТ НЕ ЗНАЕТ, НЕ ЗАТИРАЕТ НЕПУСТОЕ НА СЕРВЕРЕ
#(20.09.2026, находка ревью J03). Родня `_NEVER_BLANK`, но случай другой и мягче: там
#секрет нельзя ТРОГАТЬ вовсе, здесь непустое значение применяется как обычно — нельзя
#только СТЕРЕТЬ его пустотой.
#
#🔥 Дефект был настоящий и терял данные людей. Даты пересдач 2–5 живут в `Lesson.extra`
#(их пишет веб — `routers/web/write.py`, читает `teacher.py`), а десктопная таблица
#`lessons` такой колонки не имеет вовсе. Сборщик синхронизации честно подставлял
#`"extra": {}` — и полный снимок с любого ПК преподавателя затирал заполненные в вебе
#даты пустым словарём. Ни ошибки, ни отказа: обычная успешная синхронизация.
#
#⚠️ Почему это чинится И ЗДЕСЬ, хотя сам сборщик тоже исправлен (`sync_engine.py`
#больше не шлёт `extra`): правка клиента доедет до людей ТОЛЬКО новой сборкой .exe, а
#парк сидит на прежней и продолжит слать пустоту. Серверная половина закрывает уже
#установленные версии одним деплоем.
#
#⚠️ Список ЯВНЫЙ, по паре «таблица + поле», и это не перестраховка. Правило «пустой
#JSON не затирает» по ТИПУ колонки было бы шире дефекта и запретило бы законное:
#`users.subjects`, `groups.subjects`, `curated_groups` — тоже JSON, и их очистка
#(сняли предметы, сняли кураторство) — обычное действие администратора.
#⚠️ Соседний случай — `lessons.subgroup`: десктоп его не шлёт ВООБЩЕ, а отсутствующий
#ключ и так не применяется (см. `changed` ниже), поэтому защита ему сейчас не нужна.
#Начнёт слать — сюда его и добавлять: ноль там значит «Совместно», и от «я не знаю
#этого поля» он неотличим.
_KEEP_WHEN_BLANK = {("lessons", "extra")}


def _strip_other_hashes(users: list, own_login: str) -> None:
    """Хеш пароля оставляем ТОЛЬКО владельцу (нужен для офлайн-входа на его ПК);
    у остальных строк вырезаем — на клиентском ПК чужих хешей быть не должно."""
    for u in users:
        if u.get("login") != own_login:
            u["password_hash"] = ""


def _scope_for_student(changes: dict, user: User, db: Session) -> None:
    """Студент получает ТОЛЬКО своё: свою строку user, свои оценки/итоги, занятия своей
    группы и саму группу. Чужих студентов (ПДн) и чужих занятий он не видит вовсе.

    🔥 «Свои оценки» раньше значили «с моими фамилией и именем» (W-04, 26.09.2026) —
    полный тёзка из ДРУГОЙ группы выкачивал на свой компьютер оценки и итоговые
    чужого человека. Теперь «своё» — по неизменяемому id (`models.row_student_id`), а
    старая строка без id — по ФИО с условием:
      • оценка — только на занятии СВОЕЙ группы (ровно то же правило, что у сайта,
        `webdata.student_records`: копия программы не видит больше, чем сайт);
      • итоговая группы не несёт — только если полного тёзки у студента нет вовсе."""
    from .. import webdata as W
    login = user.login or ""
    me = user.id or ""
    f, n, grp = (user.surname or ""), (user.name or ""), (user.group_name or "")
    changes["users"] = [u for u in (changes.get("users") or []) if u.get("login") == login]
    changes["groups"] = [g for g in (changes.get("groups") or []) if g.get("name") == grp]
    changes["lessons"] = [l for l in (changes.get("lessons") or []) if l.get("group_name") == grp]

    def legacy_candidate(row) -> bool:
        return (not row_student_id(row.get("student_id"), row.get("id"))
                and row.get("student_f") == f and row.get("student_n") == n)

    def owned(row) -> bool:
        return row_student_id(row.get("student_id"), row.get("id")) == me != ""

    grades = changes.get("grades") or []
    own_lessons = None
    if any(legacy_candidate(gr) for gr in grades):
        #Занятия группы — из БАЗЫ, а не из ответа: в дельте их там может не быть. С
        #удалёнными — надгробие оценки обязано доехать туда же, куда доехала оценка.
        own_lessons = {r[0] for r in db.query(Lesson.id).filter(Lesson.group_name == grp).all()}
    changes["grades"] = [
        gr for gr in grades
        if owned(gr) or (legacy_candidate(gr)
                         and W.base_lesson_id(gr.get("lesson_id") or "") in own_lessons)]

    terms = changes.get("term_grades") or []
    no_namesake = None
    if any(legacy_candidate(t) for t in terms):
        no_namesake = db.query(User.id).filter(
            User.role == "student", User.surname == f, User.name == n,
            User.id != me).first() is None
    changes["term_grades"] = [t for t in terms
                              if owned(t) or (legacy_candidate(t) and no_namesake)]
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
    #🔥 ТОЧЕЧНО, А НЕ ВСЯ ТАБЛИЦА (аудит 22.09.2026, F-22; исследование синка W-03).
    #Раньше на КАЖДЫЙ pull (раз в 30 с с каждой программы) читались ВСЕ занятия и ВСЕ
    #студенты колледжа — даже при пустой дельте. Нужны только занятия, на которые
    #ссылаются оценки этой выдачи, и студенты её итоговых. Тот же приём, что у приёма
    #(`_incoming_lesson_ids`, `_Students.load_for`).
    #🔥 Пересдача хранится строкой `<id занятия>_retake[_N]` (`webdata.base_lesson_id`), а
    #карта искала её по ПОЛНОМУ id — и оценки пересдач не доезжали до копии программы
    #преподавателя ВОВСЕ: журнал в программе показывал пустые колонки пересдач.
    grades = changes.get("grades") or []
    wanted = {W.base_lesson_id(gr.get("lesson_id") or "") for gr in grades} - {""}
    lesson_gs = {}
    for chunk in _chunks(sorted(wanted), 500):
        lesson_gs.update({row[0]: (row[1], row[2]) for row in
                          db.query(Lesson.id, Lesson.group_name, Lesson.subject)
                            .filter(Lesson.id.in_(chunk)).all()})
    changes["grades"] = [gr for gr in grades
                         if lesson_gs.get(W.base_lesson_id(gr.get("lesson_id") or "")) in pairs]
    #TermGrade хранит только студента+предмет, без группы — группу студента достаёт
    #`_Students` (W-04): по id, по ФИО — только без тёзок. Прежняя карта «ФИО → группа»
    #у тёзок из разных групп оставляла одного, и итоговая уезжала чужому преподавателю.
    terms = changes.get("term_grades") or []
    students = _Students().load_for(db, terms)
    changes["term_grades"] = [
        t for t in terms if (students.group_of(t), t.get("subject")) in pairs]
    #student_subgroups: только по НАЗНАЧЕННЫМ парам (как lessons/grades выше). Без фильтра
    #препод получал роспись подгрупп всех групп колледжа — чужая ростер-структура.
    changes["student_subgroups"] = [s for s in (changes.get("student_subgroups") or [])
                                    if (s.get("group_name"), s.get("subject")) in pairs]


def _scope_pull_for_role(changes: dict, user: User, db: Session) -> None:
    """Минимизация выгрузки по роли (152-ФЗ, снижение радиуса поражения одного ПК).

    Всем, ВКЛЮЧАЯ админа:
      • секреты config (токен GigaChat и пр.) не отдаём вовсе — ни отдельной строкой, ни
        внутри строки `config` (`_config_without_secrets`). Озвучку ИИ программа получает
        через сервер (`/vector/voice`, см. `vector_llm.set_remote`), токен остаётся тут.
    Админ получает все строки, но хеш пароля — ТОЛЬКО свой (W-06, 26.09.2026). Раньше
    ему уходили хеши всех пользователей «для правки юзеров» — с 25.09 все записи админа
    из программы идут на бой (`route_policy`: PROXY), а страницы, читающие признак
    пароля (`/web/admin/moderators`) и настройки ИИ (`/web/admin/ai-config`), и так
    пересылаются. В копии эти поля не нужны никому, а украденный ноутбук админа отдавал
    их все разом для перебора. Сбить хеш на бою пустым значением старая сборка не может:
    `_NEVER_BLANK`.
    Не-админам — ещё и row-scope ПДн: студент видит только себя, преподаватель — только
    свои группы/предметы. Свой хеш пароля пользователь получает (нужен для офлайн-входа)."""
    changes["config"] = _config_without_secrets(changes.get("config") or [])
    if user.role == "admin":
        _strip_other_hashes(changes.get("users") or [], user.login or "")
        return
    if user.role == "teacher":
        _scope_for_teacher(changes, user, db)
    elif user.role == "student":
        _scope_for_student(changes, user, db)
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


#━━ PULL ПО НОМЕРУ ИЗМЕНЕНИЯ (26.09.2026, исследование синка П7/П9) ━━━━━━━━━━━━━━━━━━━
#Курсор — номер изменения (`app/sync_clock.py`), а не время: порядок номеров совпадает с
#порядком коммитов, поэтому ничего не теряется ни на длинной транзакции, ни на скачке
#часов (W-02). Выдача ПОСТРАНИЧНАЯ: не больше `limit` изменений за ответ (W-03/F-22) —
#полная сверка большого колледжа больше не материализует всю базу в памяти одноядерной
#машины и не упирается в 45 с ожидания клиента.
#Прежний `since` по времени остаётся для программ до 4.1: они в поле и будут ходить
#так ещё месяцами.
PAGE_DEFAULT = 2000
PAGE_MAX = 5000

#Версия ПРАВИЛ области видимости. Поменял правило «кому что отдавать» — подними: каждая
#копия пересоберётся целиком и уберёт строки, которые ей больше не положены (W-05).
SCOPE_RULES = 2

#Ограничитель частоты (F-22: «обычная учётная запись может повторять тяжёлые pull»).
#Потолки с большим запасом над живым поведением: программа 4.1 ходит за головой раз в
#~20 с и тянет страницы только при изменениях, программа 3.9 — раз в 30 с; полная
#сверка колледжа — десятки страниц. Отказ — 429, и программа повторит позже сама.
PULL_LIMIT = (240, 300.0)
HEAD_LIMIT = (120, 300.0)
DIGEST_LIMIT = (30, 3600.0)
HEAD_WAIT_MAX = 20


def _rate_limit(user: User, kind: str, limit: tuple) -> None:
    from .. import shared_state
    n = shared_state.window_add(f"sync_rate:{kind}:{user.id or user.login}", limit[1])
    if n > limit[0]:
        raise HTTPException(status_code=429, headers={"Retry-After": "30"},
                            detail="Слишком частые запросы синхронизации — повторите позже.")


def _scope_key(user: User, db: Session) -> str:
    """Отпечаток области видимости: сменился — копия пересобирается целиком (W-05).

    Дельта не умеет сказать «эта строка тебе больше не положена» — сама строка ведь не
    менялась. Поэтому сняли назначение с преподавателя, перевели студента в другую
    группу — копия получает `reset: scope` и при полной сверке убирает всё лишнее. Без
    этого программа, открытая неделю, продолжала хранить ПДн снятой группы."""
    parts = [f"rules{SCOPE_RULES}", user.role or "", user.id or "", user.login or ""]
    if user.role == "teacher":
        from .. import webdata as W
        ty, ts = W.current_term(W.load_config(db))
        pairs = sorted(W.teacher_assignments(db, user.id, ty, ts, allow_fallback=False))
        parts += [ty, str(ts)] + [f"{g}\x1f{s}" for g, s in pairs]
    elif user.role == "student":
        parts += [user.group_name or "", user.surname or "", user.name or ""]
    return hashlib.sha256("\x1e".join(parts).encode("utf-8")).hexdigest()[:24]


def _page_upper(db: Session, cursor: int, head: int, limit: int) -> int:
    """Верхняя граница страницы: `limit`-й по счёту номер после курсора (или голова).

    Номер у каждого изменения свой (счётчик один на все таблицы и журнал удалений),
    поэтому в окне (курсор, граница] ровно не больше `limit` изменений."""
    if head <= cursor:
        return cursor
    from ..db import _ddl_ident
    parts = [f"SELECT change_seq AS s FROM {_ddl_ident(m.__tablename__)} "
             "WHERE change_seq > :c AND change_seq <= :h" for m in SYNC_MODELS.values()]
    parts.append("SELECT seq AS s FROM sync_deletes WHERE seq > :c AND seq <= :h")
    sql = ("SELECT s FROM (" + " UNION ALL ".join(parts) + ") "
           "ORDER BY s LIMIT 1 OFFSET :off")
    row = db.execute(text(sql), {"c": cursor, "h": head, "off": limit - 1}).first()
    return int(row[0]) if row else head


def _removed_in_scope(rows, user: User, db: Session) -> dict:
    """{таблица: [ключи]} удалений, о которых этому человеку МОЖНО сообщить.

    Ключ оценки содержит id студента: рассылать ключи всем значило бы раздавать чужие
    идентификаторы. Поэтому удалённая строка проходит ТОТ ЖЕ фильтр области видимости,
    что и живые, — по полям, которые триггер сохранил при удалении."""
    pseudo: dict = {}
    for r in rows:
        if r.tbl in SYNC_MODELS:
            pseudo.setdefault(r.tbl, []).append(sync_clock.scope_row(r.tbl, r.scope))
    if not pseudo:
        return {}
    _scope_pull_for_role(pseudo, user, db)
    out = {}
    for name, items in pseudo.items():
        pk = list(SYNC_MODELS[name].__table__.primary_key.columns)[0].name
        keys = [it.get(pk) for it in items if it.get(pk)]
        if keys:
            out[name] = keys
    return out


def _pull_page(db: Session, user: User, cursor: int, limit: int, scope: str,
               epoch: str) -> dict:
    clock = sync_clock.read(db)
    head = clock["seq"]
    sc = _scope_key(user, db)
    base = {"head": head, "scope": sc, "epoch": clock["epoch"], "server_time": _now()}
    if cursor > 0:
        #Курсор больше не годится — копия обязана пересобраться с нуля. Причины разные и
        #названы отдельно: в журнале программы по ним видно, ЧТО случилось.
        why = ""
        if epoch and epoch != clock["epoch"]:
            why = "epoch"        #база восстановлена из резервной копии
        elif cursor > head:
            why = "ahead"        #то же без смены метки: номера на бою откатились назад
        elif cursor < clock["horizon"]:
            why = "horizon"      #журнал удалений вычищен дальше курсора (W-16)
        elif scope != sc:
            why = "scope"        #изменилась область видимости (W-05)
        if why:
            return dict(base, reset=why, cursor=0, more=True, changes={}, removed={})
    limit = min(max(int(limit or PAGE_DEFAULT), 1), PAGE_MAX)
    upper = _page_upper(db, cursor, head, limit)
    changes = {}
    for name, model in SYNC_MODELS.items():
        rows = [] if upper <= cursor else (
            db.query(model).filter(model.change_seq > cursor, model.change_seq <= upper).all())
        changes[name] = [_row_to_dict(r, model) for r in rows]
    removed_rows = [] if upper <= cursor else (
        db.query(SyncDelete).filter(SyncDelete.seq > cursor, SyncDelete.seq <= upper).all())
    _scope_pull_for_role(changes, user, db)
    removed = _removed_in_scope(removed_rows, user, db)
    return dict(base, cursor=upper, more=upper < head, changes=changes, removed=removed)


@router.get("/pull")
def pull(since: str = "", cursor: Optional[int] = None, limit: int = PAGE_DEFAULT,
         scope: str = "", epoch: str = "", request: Request = None,
         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Отдать изменения: по номеру (`cursor`, программа 4.1+) или по времени (`since`).

    По номеру — страница: {cursor, more, head, scope, epoch, changes, removed} или
    {reset: причина} — тогда копия начинает заново с `cursor=0` и в конце убирает всё,
    чего не увидела. По времени — прежний ответ {server_time, changes}."""
    _deny_web(request)   #браузеру полный дамп БД не отдаём (см. модульный docstring)
    _rate_limit(user, "pull", PULL_LIMIT)
    if cursor is not None:
        return _pull_page(db, user, max(0, int(cursor)), limit, scope or "", epoch or "")
    #Метку времени фиксируем ДО выборки, а не после. Клиент сохранит её как новую
    #границу дельты (следующий pull попросит since=server_time). Если взять метку
    #ПОСЛЕ выборки, запись, попавшая в БД между выборкой и взятием метки, не вошла
    #бы в этот ответ и была бы пропущена следующим pull. Беря метку раньше, мы в
    #худшем случае повторно отдадим пограничную запись (применение идемпотентно),
    #но НЕ потеряем её.
    server_time = _pull_watermark()
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


def _read_head() -> dict:
    db = SessionLocal()
    try:
        return sync_clock.read(db)
    finally:
        db.close()


@router.get("/head")
async def head(after: int = -1, wait: int = 0, request: Request = None,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Номер головы потока — дёшево; с `wait` — долгий опрос (W-20).

    Ответ приходит сразу, если голова уже больше `after`, иначе ждём коммита правки
    строки синка (будильник `sync_notify`), но не дольше `HEAD_WAIT_MAX` секунд. Области
    видимости здесь НЕТ намеренно: её смена всегда сопровождается правкой строки синка
    (назначение, группа, семестр), значит голова вырастет, и pull скажет `reset: scope`.

    ⚠️ Соединение с базой отпускаем ДО ожидания (см. `sync_notify`): иначе пятнадцать
    ждущих программ держали бы весь пул соединений."""
    _deny_web(request)
    await run_in_threadpool(_rate_limit, user, "head", HEAD_LIMIT)
    await run_in_threadpool(db.close)
    import asyncio
    loop = asyncio.get_running_loop()
    deadline = loop.time() + min(max(int(wait or 0), 0), HEAD_WAIT_MAX)
    state = await run_in_threadpool(_read_head)
    while state["seq"] <= after and loop.time() < deadline:
        await sync_notify.wait(min(sync_notify.RECHECK_S, deadline - loop.time()))
        state = await run_in_threadpool(_read_head)
    return {"head": state["seq"], "epoch": state["epoch"]}


#Поля, без которых фильтр области видимости не может решить про строку. Дайджест берёт
#только их, ключ и номер — а не строки целиком, как полная выдача.
def _digest_columns(name: str, model) -> list:
    pk = list(model.__table__.primary_key.columns)[0].name
    want = {pk, "change_seq", *sync_clock.SCOPE_FIELDS.get(name, ())}
    if name == "users":
        want |= {"login", "role", "group_name"}
    return [c for c in model.__table__.columns if c.name in want]


@router.get("/digest")
def digest(request: Request = None, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    """«Сверщик»: отпечаток того, что эта копия ОБЯЗАНА содержать (26.09.2026, П16).

    По каждой таблице — {count, hash, last}: число строк в области видимости, sha256 от
    отсортированных пар «ключ:номер» и последний номер, тронувший таблицу (включая
    удаления). Программа сверяет с тем же по своей копии и сравнивает только таблицы,
    которые не менялись после её курсора (`last` не больше курсора): иначе разница —
    это просто ещё не скачанная правка, а не расхождение. Совпало — значок «сверено»;
    не совпало — полная сверка копии и запись в журнал, ЧТО разошлось."""
    _deny_web(request)
    _rate_limit(user, "digest", DIGEST_LIMIT)
    clock = sync_clock.read(db)
    head_seq = clock["seq"]
    changes = {}
    for name, model in SYNC_MODELS.items():
        cols = _digest_columns(name, model)
        rows = db.query(*cols).filter(model.change_seq <= head_seq).all()
        changes[name] = [dict(zip([c.name for c in cols], r)) for r in rows]
    _scope_pull_for_role(changes, user, db)
    last_del = {r[0]: int(r[1] or 0) for r in db.execute(text(
        "SELECT tbl, MAX(seq) FROM sync_deletes WHERE seq <= :h GROUP BY tbl"),
        {"h": head_seq}).all()}
    tables = {}
    for name, items in changes.items():
        pk = list(SYNC_MODELS[name].__table__.primary_key.columns)[0].name
        tables[name] = table_digest(items, pk)
        tables[name]["last"] = max(tables[name]["last"], last_del.get(name, 0))
    return {"head": head_seq, "epoch": clock["epoch"], "scope": _scope_key(user, db),
            "tables": tables}


def table_digest(items, pk: str) -> dict:
    """{count, hash, last} по строкам таблицы. ОДНА функция для сервера и программы:
    две копии формулы разошлись бы молча, и Сверщик врал бы в обе стороны."""
    pairs = sorted(f"{it.get(pk)}:{int(it.get('change_seq') or 0)}" for it in items
                   if it.get(pk) is not None)
    last = max((int(it.get("change_seq") or 0) for it in items), default=0)
    return {"count": len(pairs),
            "hash": hashlib.sha256("\n".join(pairs).encode("utf-8")).hexdigest(),
            "last": last}



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
    #Строки устаревшего снимка (см. `_based_on_older_version`): не отказ по правам, а
    #«ты стоишь на старой версии». Отдельным ключом, НЕ в `rejected`: старые сборки
    #считают `rejected` отказом в правах и перестают стирать кэш при сверке — а именно
    #сверка «сервер = истина» и лечит у них устаревший снимок.
    stale = {}
    #🔥 ПРИЧИНЫ ОТКАЗА, А НЕ ТОЛЬКО ИХ ЧИСЛО. «Отклонено: 3» человеку не говорит ничего и
    #читается как сбой синхронизации; «семестр в архиве» и «уже выставлена итоговая» —
    #это два РАЗНЫХ действия с его стороны. Множество (а не список) — одна и та же
    #причина на сотне строк не должна превращаться в сотню строк в логе.
    refusals: dict = {}
    new_homework = []    #ДЗ, впервые приехавшие с клиента — разослать после commit

    #Построчная авторизация преподавателя — по его НАЗНАЧЕНИЯМ (группа, предмет), тем же
    #источником, что и на сайте. Для admin проверки нет (он вправе писать всё). Карты
    #строим по одному разу на запрос.
    is_teacher = user.role == "teacher"
    #Конфиг читаем ОДИН раз на запрос: доменные правила ниже спрашивают у него текущий
    #термин, а push бывает на тысячу строк.
    domain_cfg = None
    if is_teacher:
        from ..webdata import load_config as _load_config
        domain_cfg = _load_config(db)
    teacher_pairs = None          #None = назначений нет вовсе → прежнее правило по предмету
    teacher_subjects = set()
    lesson_pairs = {}
    students = _Students()
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
            #Тот же приём, что и с картами занятий: не весь справочник колледжа, а
            #студенты, о которых спросят строки пакета, — по их id и по их фамилиям
            #(см. `_Students`: там же урок краевого пробела). Id после приведения ключа
            #(`_normalize_grade_key`) тоже покрыт: он найден по фамилии из пакета.
            students.load_for(db, changes.get("term_grades") or [])

    #Карта занятие→группа: нужна, чтобы развести ПОЛНЫХ ТЁЗОК при нормализации ключа
    #оценки, пришедшей от старого клиента (без student_id). Двух Ивановых Иванов в одну
    #группу не заводят, поэтому занятие однозначно указывает на нужного. Строим один раз
    #на запрос и только если оценки в payload вообще есть.
    lesson_group = {}
    if changes.get("grades"):
        #Та же выборка по списку, что и у карты пар: полная таблица здесь не нужна была
        #никогда — карта читается только по `lesson_id` пришедших оценок.
        _want = _incoming_lesson_ids(changes)
        for _chunk in _chunks(sorted(_want), 500):
            lesson_group.update({r[0]: (r[1] or "") for r in
                                 db.query(Lesson.id, Lesson.group_name)
                                   .filter(Lesson.id.in_(_chunk)).all()})

    for name, items in changes.items():
        model = SYNC_MODELS.get(name)
        if model is None or name not in allowed or not isinstance(items, list):
            continue
        pk = list(model.__table__.primary_key.columns)[0].name
        cols = {c.name for c in model.__table__.columns}
        #Поля, по которым решаем «изменилось ли»: всё, кроме PK и служебных меток.
        #Номер изменения ставит база (`sync_clock`): присланный клиентом не сравниваем и
        #не пишем — иначе строка получила бы ЧУЖОЙ номер и выпала из курсоров копий.
        compare_cols = cols - {pk, "updated_at"} - SERVER_ONLY_COLUMNS
        count = 0
        rej = 0
        stale_n = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            item = {k: v for k, v in item.items() if k not in SERVER_ONLY_COLUMNS}
            key = item.get(pk)
            #Оценки ключуются по НЕИЗМЕНЯЕМОМУ student_id (этап 3). Клиенту на слово не
            #верим: старая версия шлёт ФИО-ключ, и без пересчёта строка легла бы РЯДОМ
            #с новой — дубль одной и той же оценки в журнале.
            if name in ("grades", "term_grades") and key:
                key = _normalize_grade_key(db, name, item, lesson_group)
                item = dict(item, id=key)
            if not key:
                continue
            existing = db.get(model, key)
            #Преподаватель не вправе трогать чужую пару (группа, предмет) — отбрасываем.
            #
            #🔥 ПРАВО СПРАШИВАЕТСЯ ПРО ДВЕ ОБЛАСТИ, А НЕ ПРО ОДНУ (20.09.2026, находка
            #ревью J05). Раньше проверялись ТОЛЬКО присланные поля, и этого хватало
            #ровно до тех пор, пока запись создаётся. Для СУЩЕСТВУЮЩЕЙ строки правило
            #читалось наоборот: преподаватель, знающий id чужого занятия, слал этот id
            #со СВОЕЙ разрешённой парой (группа, предмет) — проверка смотрела на
            #присланное, соглашалась, а дальше те же поля записывались в чужую строку.
            #То есть занятие «переезжало» к отправителю вместе с оценками, и никакой
            #отдельной защиты на этом пути не было.
            #
            #Теперь: можно менять запись, если она УЖЕ твоя, и класть её можно только
            #туда, где ты тоже вправе писать. Первая половина закрывает угон чужого,
            #вторая — вынос своего в чужую группу.
            if is_teacher:
                if not _teacher_may_write(name, item, teacher_pairs, teacher_subjects,
                                          lesson_pairs, students):
                    rej += 1
                    continue
                if existing is not None:
                    _learn_scope_of_existing(db, name, existing, lesson_pairs, students)
                    if not _teacher_may_write(name, _row_scope(name, existing),
                                              teacher_pairs, teacher_subjects,
                                              lesson_pairs, students):
                        rej += 1
                        continue
            if existing is None:
                #🔒 Доменные правила журнала — те же, что у веб-ручки (J06): значение по
                #шкале, архив прошлых семестров, замок зачётки. До 20.09.2026 через этот
                #путь не проверялось ничего из перечисленного.
                if is_teacher:
                    why = _domain_refusal(db, name, item, domain_cfg)
                    if why:
                        rej += 1
                        refusals.setdefault(name, set()).add(why)
                        continue
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
            #Поле, присланное пустым, при непустом серверном — это «клиент его не
            #знает», а не «человек его очистил» (см. _KEEP_WHEN_BLANK выше).
            for _blank in [k for k, v in item.items()
                           if (name, k) in _KEEP_WHEN_BLANK and not v
                           and getattr(existing, k, None)]:
                item.pop(_blank)
            changed = any(k in item and getattr(existing, k) != item[k]
                          for k in compare_cols)
            #🔥 УСТАРЕВШИЙ СНИМОК НЕ ОТКАТЫВАЕТ СЕРВЕР (аудит 22.09.2026, находка F-03).
            #Решение «применять или нет» принималось по одному содержимому: у кого оно
            #иное, тот и прав. А старый синк десктопа возвращает строки, полученные с
            #сервера РАНЬШЕ, с ТОЙ серверной меткой, что была у них при получении, и его
            #слияние свежую серверную оценку не принимает (пишет «конфликт»). Итог был
            #живым дефектом, а не теорией: оценку поменяли на сайте или в телефоне, а
            #через несколько минут полный снимок программы того же преподавателя
            #возвращал прежнее значение — молча, со свежей серверной меткой.
            #Правило: строка, основанная на версии СТАРШЕ или РАВНОЙ хранимой, ничего не
            #меняет. Настоящая правка клиента несёт более позднюю метку (локальную при
            #правке), эхо устаревшего снимка — метку той версии, с которой его сняли.
            #Метка клиента по-прежнему НЕ записывается (метку ставит сервер, §4.3) — она
            #лишь говорит, на какой версии клиент стоял. Нет метки — судить не о чем,
            #работает прежнее правило (старые клиенты без поля не ломаются).
            if changed and _based_on_older_version(item.get("updated_at"),
                                                   getattr(existing, "updated_at", "")):
                stale_n += 1
                continue
            #⚠️ Правила спрашиваем ТОЛЬКО у того, что реально меняется. Полный снимок
            #десктопа раз в N циклов везёт и архивные оценки, совпадающие с серверными:
            #отвергать их значило бы держать `rejected` вечно ненулевым — и заодно
            #навсегда выключить сверку «сервер = истина», которая при отказах кэш не
            #стирает (см. `sync_engine.reconcile`).
            if changed and is_teacher:
                why = _domain_refusal(db, name, item, domain_cfg)
                if why:
                    rej += 1
                    refusals.setdefault(name, set()).add(why)
                    continue
            if changed:
                for k, v in item.items():
                    if k in compare_cols:
                        setattr(existing, k, v)
                existing.updated_at = server_ts   #метку обновляет сервер
                count += 1
        applied[name] = count
        if rej:
            rejected[name] = rej
        if stale_n:
            stale[name] = stale_n

    db.commit()
    for hw in new_homework:
        _notify_homework_from_sync(db, hw)
    #Преподаватель попытался записать НЕ свой предмет — это нарушение прав, поэтому
    #видно в админской консоли (а не молча игнорируется).
    if rejected:
        _why = "; ".join(f"{t}: {', '.join(sorted(v))}" for t, v in sorted(refusals.items()))
        events.record("warn", "push_rejected",
                      f"отклонены записи: {rejected}" + (f" ({_why})" if _why else ""),
                      user.login)
    result = {"server_time": server_ts, "applied": applied}
    if stale:
        result["stale"] = stale
    #rejected включаем, только если что-то отвергли — клиенту видно, что часть
    #правок не его (не молчим, но и не шумим в обычном случае).
    if rejected:
        result["rejected"] = rejected
        if refusals:
            #Клиент показывает это человеку (`sync_runner.status`) — без причины он
            #увидел бы «часть правок не уехала» и пошёл бы искать поломку связи.
            result["rejected_reasons"] = {t: sorted(v) for t, v in refusals.items()}
    return result
