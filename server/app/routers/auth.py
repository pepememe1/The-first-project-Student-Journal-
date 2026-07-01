"""
auth.py — Авторизация: создание первого администратора и вход (JWT).

Offline-first: пользователей заводит админ в десктоп-проге, они синхронизируются
на сервер уже хешами паролей. Логин через API/сайт работает с теми же паролями.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import (ensure_device_allowed, get_current_user, is_web_client,
                    device_barrier_applies)
from ..models import User, AuthSession
from ..schemas import LoginIn, TokenOut, BootstrapIn, RefreshIn
from ..security import (hash_password, verify_password, create_token_full,
                        decode_token)
from .. import throttle, events

router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> str:
    #UTC + смещение (+00:00) — единый формат меток с клиентом, чтобы LWW-сравнение
    #строк было корректным независимо от часового пояса.
    return datetime.now(timezone.utc).isoformat()


def _record_session(db: Session, jti: str, login: str, role: str, kind: str,
                    exp: int, request: Request, pair_jti: str = ""):
    """Сохраняет выданный токен в AuthSession (для отзыва/refresh/видимости сессий)."""
    dev = ip = ""
    try:
        if request is not None:
            dev = request.headers.get("X-Device-Id", "") or ""
            ip = throttle.client_ip(request)
    except Exception:
        pass
    db.add(AuthSession(jti=jti, login=login, role=role, kind=kind, device_id=dev,
                       ip=ip, issued_at=_now(), expires_at=int(exp), revoked=False,
                       pair_jti=pair_jti))


def _issue_token_pair(db: Session, user: User, request: Request) -> TokenOut:
    """Выдаёт пару (access + refresh), записывает обе сессии и коммитит.

    access — короткий (для запросов), refresh — длинный (тихое обновление). Связаны
    через pair_jti, чтобы logout/отзыв гасил оба разом."""
    access, a_jti, a_exp = create_token_full(user.login, user.role, "access")
    refresh, r_jti, r_exp = create_token_full(user.login, user.role, "refresh")
    _record_session(db, a_jti, user.login, user.role, "access", a_exp, request, r_jti)
    _record_session(db, r_jti, user.login, user.role, "refresh", r_exp, request, a_jti)
    db.commit()
    name = user.full_name or f"{user.surname} {user.name}".strip()
    return TokenOut(access_token=access, refresh_token=refresh, role=user.role, name=name)


@router.post("/bootstrap-admin", response_model=TokenOut)
def bootstrap_admin(body: BootstrapIn, request: Request, db: Session = Depends(get_db)):
    """Создаёт ПЕРВОГО администратора. Работает только если админа ещё нет —
    безопасно вызывать при первичной настройке сервера.

    Барьер устройства применяется и здесь: первичную настройку делает хост (его
    device_id пропускается), а случайный ПК из сети не сможет создать админа."""
    ensure_device_allowed(request, db)
    exists = db.query(User).filter(
        User.role == "admin", User.deleted == False  # noqa: E712
    ).first()
    if exists:
        raise HTTPException(status_code=409, detail="Администратор уже создан")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Пароль не короче 8 символов")
    login = body.login.strip()
    #Детерминированный id (admin:<login>): когда десктоп позже пришлёт админа
    #через /sync, он обновит ЭТУ же строку, а не создаст дубликат.
    u = User(
        id=f"admin:{login}", role="admin", login=login,
        password_hash=hash_password(body.password), full_name=body.full_name,
        updated_at=_now(),
    )
    db.add(u)
    db.commit()
    return _issue_token_pair(db, u, request)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    """Вход по логину и паролю. Роль — внутри токена.

    Анти-брутфорс: до сверки пароля проверяем, не заблокирован ли этот источник за
    серию неверных попыток (см. throttle). Блокировка по паре (IP, логин) — чтобы
    атакующий не мог запереть вход настоящему пользователю. Неудача увеличивает
    счётчик, удачный вход его сбрасывает."""
    login_str = body.login.strip()
    ip = throttle.client_ip(request)
    web = is_web_client(request)

    #Барьер устройства ДО сверки пароля: неодобренный ПК не должен входить (даже зная
    #верные креды), и не нужно дёргать дорогой PBKDF2 ради него. ДЕСКТОП (и любой не-веб
    #клиент) — жёсткий барьер, как прежде. Для ВЕБА барьер откладываем: студенту он не
    #нужен, а роль мы узнаем после поиска пользователя (ниже).
    if not web:
        ensure_device_allowed(request, db)

    left = throttle.seconds_until_unlocked(ip, login_str)
    if left > 0:
        #429 + Retry-After — стандартный сигнал «слишком много попыток, подожди».
        events.record("warn", "login_throttled",
                      f"вход заблокирован за перебор (ещё {left} с)", login_str, ip)
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много неудачных попыток. Повторите через {left} с.",
            headers={"Retry-After": str(left)},
        )

    u = db.query(User).filter(
        User.login == login_str, User.deleted == False  # noqa: E712
    ).first()
    #Веб: персонал (teacher/admin) обязан пройти подтверждение устройства ещё ДО сверки
    #пароля (тот же барьер, что в десктопе), а студент входит открыто. Неизвестного
    #пользователя барьером не выделяем — он уйдёт в обычный 401 (не палим, есть ли логин).
    if web and u is not None and device_barrier_applies(request, u.role):
        ensure_device_allowed(request, db)

    if not u or not verify_password(body.password, u.password_hash):
        throttle.register_failure(ip, login_str)
        events.record("warn", "login_failed", "неверный логин или пароль", login_str, ip)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    throttle.register_success(ip, login_str)
    events.record("info", "login", f"вход выполнен (роль {u.role})", login_str, ip)
    return _issue_token_pair(db, u, request)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    """Тихое обновление сессии: меняем валидный refresh-токен на НОВЫЙ access.

    Сценарий 152-ФЗ/удобства: короткий access протух (например, за время офлайна), но
    refresh ещё жив — клиент в фоне дёргает этот эндпоинт и продолжает работу, НЕ
    выкидывая пользователя на экран логина. Барьер устройства проверяем и здесь."""
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("typ") != "refresh":
        raise HTTPException(status_code=401, detail="Недействительный refresh-токен")
    jti = payload.get("jti", "")
    sess = db.query(AuthSession).filter(AuthSession.jti == jti).first()
    if sess is None or sess.revoked:
        #refresh отозван (logout/блокировка админом) или неизвестен — обновлять нечего
        raise HTTPException(status_code=401, detail="Сессия завершена или отозвана")
    login_str = payload.get("sub", "")
    u = db.query(User).filter(
        User.login == login_str, User.deleted == False  # noqa: E712
    ).first()
    if not u:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    #Барьер устройства применяем по той же политике, что и на входе: персонал и
    #десктоп — обязательно; веб-студенту не нужен (роль знаем из его же токена).
    if device_barrier_applies(request, u.role):
        ensure_device_allowed(request, db)
    #Новый access, привязанный к ТОМУ ЖЕ refresh (refresh не ротируем — он живёт до
    #своего exp или явного отзыва). Прежний access этой пары гасим.
    if sess.pair_jti:
        old = db.query(AuthSession).filter(AuthSession.jti == sess.pair_jti).first()
        if old is not None:
            old.revoked = True
    access, a_jti, a_exp = create_token_full(u.login, u.role, "access")
    _record_session(db, a_jti, u.login, u.role, "access", a_exp, request, jti)
    sess.pair_jti = a_jti
    db.commit()
    name = u.full_name or f"{u.surname} {u.name}".strip()
    #refresh возвращаем тот же — клиент продолжает им пользоваться.
    return TokenOut(access_token=access, refresh_token=body.refresh_token,
                    role=u.role, name=name)


@router.post("/logout")
def logout(request: Request, authorization: str = Header(None),
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Безопасный выход: сервер ОТЗЫВАЕТ текущий access и связанный refresh.

    Зачем серверу «забывать» токен: если злоумышленник успел скопировать токен из
    памяти ПК ДО нажатия «Выйти», без отзыва он пользовался бы им до конца срока. После
    logout сервер мгновенно перестаёт его принимать (чёрный список AuthSession)."""
    revoked = 0
    payload = decode_token((authorization or "").split(" ", 1)[-1].strip())
    jti = (payload or {}).get("jti", "")
    if jti:
        sess = db.query(AuthSession).filter(AuthSession.jti == jti).first()
        if sess is not None:
            sess.revoked = True
            revoked += 1
            if sess.pair_jti:
                pair = db.query(AuthSession).filter(AuthSession.jti == sess.pair_jti).first()
                if pair is not None and not pair.revoked:
                    pair.revoked = True
                    revoked += 1
        db.commit()
        events.record("info", "logout", "выход (токен отозван)", user.login,
                      throttle.client_ip(request))
    return {"revoked": revoked}
