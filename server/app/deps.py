"""
deps.py — Зависимости FastAPI: текущий пользователь из JWT и проверка ролей.
"""
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .security import decode_token
from .models import User, AuthSession
from . import events, throttle, connect


def ensure_device_allowed(request: Request, db: Session):
    """Барьер подтверждения устройства: пускаем только одобренные ПК и сам хост.

    Применяется ко ВСЕМ защищённым эндпоинтам (через get_current_user) и ко входу
    (см. routers/auth.py). Неодобренное устройство получает 403 — оно сначала должно
    пройти подтверждение через /connect/* (вкладка «Запросы на подключение» у админа).
    Сам барьер реализован в connect.device_allowed (хост опознаётся по device_id)."""
    if not connect.device_allowed(request, db):
        raise HTTPException(
            status_code=403,
            detail="Устройство не подтверждено администратором. Запросите подключение "
                   "и введите код, который выдаст администратор.")


def is_web_client(request: Request) -> bool:
    """Пришёл ли запрос из БРАУЗЕРА (веб-версия), а не из десктоп-проги.

    Веб-клиент помечает себя заголовком `X-Client: web` (см. фронтенд api/client.js).

    ⚠️ ЧТО ДАЁТ ПОДМЕНА ЭТОГО ЗАГОЛОВКА — читать внимательно, здесь раньше стояла
    НЕПРАВДА («максимум доступ уровня студента, для персонала барьер остаётся»).
    Барьер устройства НЕ применяется ни к одной роли веб-клиента, включая admin
    (см. device_barrier_applies ниже и server/tests/test_device_policy.py). Значит
    подмена заголовка снимает барьер и с персонала — но НЕ даёт войти: нужны верные
    логин и пароль, а под ними уже работают анти-брутфорс, HTTPS и role-scoped
    `/web/*`. Синк (`/sync/*`) остаётся закрытым — там этот же заголовок наоборот
    ЗАПРЕЩАЕТ доступ (routers/sync.py::_deny_web).

    ⚠️ Отдельно про срок сессии, чтобы не пересказывать неточно: длину сессии выбирает
    НЕ эта функция, а `config.issue_ttl_min`, и смотрит она ровно на значение
    `android` — `web` получает те же 5 часов, что и десктоп. То есть недельный срок
    открывает подмена заголовка ИМЕННО на `android`, а не «веб-клиентом вообще».

    ⚠️ `android` — ТА ЖЕ САМАЯ веб-редакция, просто в обёртке Capacitor (§11): тот же
    Vue, те же role-scoped `/web/*`, синк ей не нужен. Значение появилось отдельно
    только затем, чтобы у телефона был свой (недельный) потолок сессии — см.
    config.session_ttl_min. Если бы мы забыли учесть его ЗДЕСЬ, приложение внезапно
    попало бы под барьер устройства и перестало пускать преподавателей с телефона."""
    if request is None:
        return False
    return (request.headers.get("x-client", "") or "").strip().lower() in ("web", "android")


def device_barrier_applies(request: Request, role: str) -> bool:
    """Нужно ли для этого запроса проверять одобрение устройства.

    Политика веба (согласована с заказчиком, §11 CLAUDE.md): в браузере и в мобильном
    приложении барьер НЕ применяется НИ К ОДНОЙ РОЛИ — ни студенту, ни преподавателю,
    ни администратору. Защита веба: верные креды + анти-брутфорс + HTTPS + role-scoped
    `/web/*`, а полный дамп базы через `/sync/*` веб-клиенту закрыт отдельно
    (routers/sync.py::_deny_web). ДЕСКТОП и любой не-веб клиент — жёсткий барьер как
    прежде (инвариант §6 не ослаблен для них).

    ⚠️ ЗДЕСЬ РАНЬШЕ БЫЛО НАПИСАНО ОБРАТНОЕ — что персонал в вебе проходит подтверждение
    устройства «как в десктопе». Неправдой это было с самого начала: код первой же
    строкой отвечает False любому веб-клиенту, роль не смотрится вовсе. Цена такой
    ошибки в докстринге выше обычной: по нему делается вывод о том, чем защищён
    администратор, — и вывод получался в сторону «безопаснее, чем на самом деле».
    В `routers/auth.py` из-за этого же жила ветка, которая не исполнялась НИКОГДА
    (`if web and ... and device_barrier_applies(...)` тождественно `web and not web`).
    Фактическую политику держат server/tests/test_device_policy.py — в том числе
    `test_web_staff_open_without_approval` и мобильный `test_android_admin_*`.

    ⚠️ `role` СЕЙЧАС НЕ ВЛИЯЕТ на результат. Параметр оставлен намеренно: если политику
    вернут к ролевой (а разговор об этом возможен — недельная мобильная сессия у admin
    без подтверждения устройства это осознанный размен, а не данность), правка будет
    ЗДЕСЬ, в одном месте, а не в трёх вызывающих. Не удалять «как неиспользуемый»."""
    # Веб-клиент (браузер) барьер устройства НЕ проходит — ни для одной роли. Защита
    # веба: валидные креды + анти-брутфорс + HTTPS + role-scoped /web/* (не /sync).
    # Барьер устройства — десктоп-специфичная защита (чужой ПК не должен тянуть всю
    # БД через /sync); для десктопа и любого не-веб клиента он остаётся строгим.
    if is_web_client(request):
        return False
    return True


def get_current_user(authorization: str = Header(None),
                     request: Request = None,
                     db: Session = Depends(get_db)) -> User:
    """Достаёт пользователя по токену из заголовка Authorization: Bearer <token>."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Недействительный или просроченный токен")
    #ЧЁРНЫЙ СПИСОК / отзыв: токен с jti валиден, только пока его сессия не revoked.
    #Так logout и админская блокировка мгновенно аннулируют украденный/устаревший токен,
    #даже если по подписи и exp он ещё «живой». Токены БЕЗ jti (старого формата) пускаем
    #по подписи+exp до их естественного истечения — обратная совместимость.
    jti = payload.get("jti")
    if jti:
        sess = db.query(AuthSession).filter(AuthSession.jti == jti).first()
        if sess is None or sess.revoked:
            raise HTTPException(status_code=401, detail="Сессия завершена или отозвана")
    user = db.query(User).filter(
        User.login == payload.get("sub"), User.deleted == False  #noqa: E712
    ).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    #Даже с валидным токеном доступ закрыт, если устройство не подтверждено: токен мог
    #быть выдан до отзыва доступа или скопирован на чужой ПК. Для веб-студента барьер
    #не применяется (открытый веб-доступ), для персонала и десктопа — применяется.
    if device_barrier_applies(request, user.role):
        ensure_device_allowed(request, db)
    #Отмечаем активность для админского «кто онлайн». Это единая точка — через
    #get_current_user проходит КАЖДЫЙ авторизованный запрос (pull/push/admin).
    #Не критично для запроса, поэтому под try: мониторинг не должен ронять API.
    try:
        ip = throttle.client_ip(request) if request is not None else ""
        name = user.full_name or f"{user.surname} {user.name}".strip()
        events.touch(user.login, user.role, name, ip)
    except Exception:
        pass
    return user


def current_jti(authorization: str = Header(None)) -> str:
    """`jti` выданного токена — устойчивая метка ОДНОГО входа.

    Зачем: есть величины, которые обязаны быть одинаковыми во всех вкладках и после
    любой перезагрузки, но разными после нового входа. День для этого не годится
    (перезаход даёт то же самое до полуночи), а запрос — тем более (метка менялась бы
    между вкладками). `jti` уникален на каждый выданный токен и живёт ровно столько же,
    сколько сессия.

    ⚠️ Это НЕ проверка доступа. Рядом всегда стоит `get_current_user`, который в том же
    запросе уже отверг бы недействительный или отозванный токен. Здесь нужна только
    стабильная строка, поэтому подпись не перепроверяется и ошибок не выбрасывается:
    нет заголовка или токен старого формата без `jti` — возвращаем пустую строку, и
    вызывающий сам решает, чем её заменить.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return ""
    payload = decode_token(authorization.split(" ", 1)[1].strip())
    return str((payload or {}).get("jti") or "")


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Требуются права администратора")
    return user
