"""
publicschedule.py — расписание БЕЗ входа в аккаунт (`/public/schedule/*`).

━━ ЗАЧЕМ ━━
Виджет на рабочем столе Android обязан обновляться сам, а токена у него быть не может:
JWT в проекте живёт жёстко 5 часов (§6), и виджет, работающий первые пять часов после
входа, а дальше показывающий ошибку, хуже отсутствующего. Раньше это лечилось тем, что
снимок клало приложение, — но тогда расписание обновляется, только пока человек заходит
в приложение, а он может не заходить неделями.

━━ ПОЧЕМУ ЭТО НЕ ДЫРА ━━
Расписание берётся с ПУБЛИЧНОГО портала portal.esstu.ru, который отдаёт те же страницы
кому угодно без всякого входа (§5.1). Персональных данных в нём нет: группа, предмет,
аудитория и фамилия преподавателя — всё это и так открыто опубликовано вузом. Мы не
открываем новых данных, а лишь перестаём требовать токен там, где он ничего не защищал.

⚠️ **ЧЕГО ЗДЕСЬ БЫТЬ НЕ ДОЛЖНО НИКОГДА** — ни одной строки из журнала: ни оценок, ни
посещаемости, ни списков студентов, ни ЗЕТ, ни риска отчисления. Всё это ПДн, и роль
проверяется в `routers/web/*`. Этот файл существует ровно потому, что расписание —
единственная часть продукта, которая уже публична у первоисточника. Появится соблазн
«тут же рядом отдать средний балл» — соблазну не поддаваться, это будет утечка.

⚠️ Правки администратора (`ScheduleOverride`) НАКЛАДЫВАЮТСЯ, как и в кабинете. Иначе
виджет показывал бы расписание, отличное от того, что человек видит в приложении, —
а расхождение хуже, чем отсутствие правок: доверять нельзя ни одному из двух.

⚠️ Ответ УМЫШЛЕННО совпадает по форме с `/web/schedule` и `/web/schedule/teacher` —
клиент (и нативный виджет, и веб-слой) разбирает их одним и тем же кодом, второй
формат разошёлся бы с первым при первой же правке.
"""
import threading
import time
from collections import deque
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import schedule_web, throttle
from ..db import get_db
from ..models import Group

router = APIRouter(prefix="/public", tags=["public"])

#Мягкий предел частоты. Эндпоинт открытый, и без него один скрипт гоняет парсер
#портала в цикле. Числа щедрые: виджет обновляется раз в несколько часов, человек с
#телефона жмёт «обновить» единицы раз — а вот перебор всех групп подряд упрётся сразу.
#
#⚠️ Своя реализация, а не `throttle`: тот считает НЕУДАЧНЫЕ попытки входа и блокирует
#пару (IP, логин) — здесь нет ни логина, ни понятия «неудача». `msg_limit` ближе по
#приёму (скользящее окно на deque), но его пределы зашиты под сообщения. Пятнадцать
#строк своего окна честнее, чем натягивание чужой семантики.
_RATE_MAX = 60
_RATE_WINDOW_S = 60
_hits: dict = {}
_hits_lock = threading.Lock()


def _too_many(request: Request) -> bool:
    """True — превышен предел для этого IP. Вынесено отдельной функцией, чтобы тест
    подменял её, а не гонял шестьдесят реальных запросов."""
    try:
        ip = throttle.client_ip(request)
    except Exception:
        return False
    now = time.time()
    with _hits_lock:
        dq = _hits.get(ip)
        if dq is None:
            dq = _hits[ip] = deque()
        while dq and now - dq[0] > _RATE_WINDOW_S:
            dq.popleft()
        #Уборка: без неё словарь растёт на каждый новый IP и не уменьшается никогда.
        #На одноядерном VPS это единственный способ не отрастить утечку памяти.
        if len(_hits) > 5000:
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > _RATE_WINDOW_S]:
                _hits.pop(k, None)
        if len(dq) >= _RATE_MAX:
            return True
        dq.append(now)
        return False


def _limited() -> JSONResponse:
    #429, а не 403: клиенту надо понять, что дело во ЧАСТОТЕ, и повторить позже.
    return JSONResponse(status_code=429,
                        content={"detail": "Слишком часто. Повторите через минуту."})


@router.get("/schedule")
def public_schedule(request: Request, group: str = Query(""), category: str = Query(""),
                    db: Session = Depends(get_db)):
    """Расписание ГРУППЫ без входа в аккаунт.

    В отличие от `/web/schedule`, группу подставить «свою» неоткуда — токена нет,
    поэтому без параметра `group` честно отвечаем «недоступно», а не пустотой.
    Категорию, как и в кабинете, берём из базы, если клиент её не передал: у групп
    вне колледжа пустая категория резолвилась бы в колледж и не находила группу.
    """
    if _too_many(request):
        return _limited()
    g = (group or "").strip()
    if not g:
        return {"group": "", "category": schedule_web.default_category(),
                "week": schedule_web.current_week_parity(), "schedule": None,
                "available": False}
    cat = (category or "").strip()
    if not cat:
        grp = db.query(Group).filter(Group.name == g, Group.deleted == False).first()  # noqa: E712
        cat = (grp.category if grp else "") or ""
    #Тот же слитый источник (портал + правки админа), что и в кабинете. Импорт локальный:
    #`routers.web` тянет за собой пол-приложения, а нам нужна одна функция.
    from .web.schedule import _group_schedule
    data = _group_schedule(db, g, cat)
    return {
        "group": g,
        "category": cat or schedule_web.default_category(),
        "week": schedule_web.current_week_parity(),
        "schedule": data,
        "available": bool(data and data.get("weeks")),
    }


@router.get("/schedule/teacher")
def public_schedule_teacher(request: Request, name: str = Query(""),
                            category: str = Query("")):
    """Расписание ПРЕПОДАВАТЕЛЯ по ФИО, без входа в аккаунт.

    Авто-совпадения «сам себе» здесь нет и быть не может — некому совпадать, токена
    нет. Имя приходит от клиента: виджет запомнил его в момент входа, когда сервер
    уже сматчил преподавателя по ФИО (`matched_self`).

    ⚠️ Фамилия преподавателя — не ПДн в нашем смысле: она напечатана в открытом
    расписании вуза. Списка преподавателей отсюда НЕ отдаём (в отличие от
    `/web/schedule/teacher`, где он нужен для выпадающего списка) — открытый
    справочник сотрудников это уже другая история, и виджету он не нужен.
    """
    if _too_many(request):
        return _limited()
    who = (name or "").strip()
    if not who:
        return {"available": False, "building": False, "teacher": "",
                "week": schedule_web.current_week_parity(), "schedule": None}
    snap, building = schedule_web.full_state(category)
    if snap is None:
        return {"available": False, "building": building, "teacher": "",
                "week": schedule_web.current_week_parity(), "schedule": None}
    weeks = schedule_web.teacher_weeks(snap, who)
    return {
        "available": weeks is not None,
        "building": building,
        "teacher": who if weeks is not None else "",
        "week": schedule_web.current_week_parity(),
        "schedule": {"weeks": weeks} if weeks is not None else None,
    }


@router.get("/week")
def public_week():
    """Чётность текущей недели одним числом.

    Нужна тем клиентам, которые расписание уже держат у себя и хотят сверить только
    неделю (например, чтобы не считать её третьей копией формулы). Возвращаем и дату,
    на которую посчитано, — иначе при расхождении часовых поясов не разобраться, чья
    «сегодня» имелась в виду.
    """
    today = date.today()
    return {"date": today.isoformat(), "week": schedule_web.current_week_parity(today)}
