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
from ..models import User, AuthSession, set_user_password
from ..schemas import LoginIn, TokenOut, BootstrapIn, RefreshIn
from ..security import verify_password, create_token_full, decode_token
from ..config import issue_ttl_min, session_ttl_min
from .. import throttle, events, audit

router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> str:
    #UTC + смещение (+00:00) — единый формат меток с клиентом, чтобы LWW-сравнение
    #строк было корректным независимо от часового пояса.
    return datetime.now(timezone.utc).isoformat()


def client_kind(request: Request) -> str:
    """Каким клиентом пришёл запрос: 'android' | 'web' | '' (десктоп).

    Заголовок ставит сам клиент (`api/client.js`), подделать его тривиально — поэтому
    он НЕ даёт никаких прав, а только выбирает длину сессии при ВЫДАЧЕ токена. Дальше
    выбор фиксируется в auth_sessions.client и уже не зависит от заголовков."""
    if request is None:
        return ""
    v = (request.headers.get("x-client", "") or "").strip().lower()
    return v if v in ("android", "web") else ""


def _record_session(db: Session, jti: str, login: str, role: str, kind: str,
                    exp: int, request: Request, pair_jti: str = "", client: str = ""):
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
                       pair_jti=pair_jti, client=client))


def _issue_token_pair(db: Session, user: User, request: Request) -> TokenOut:
    """Выдаёт пару (access + refresh), записывает обе сессии и коммитит.

    access — короткий (для запросов), refresh — длинный (тихое обновление). Связаны
    через pair_jti, чтобы logout/отзыв гасил оба разом.

    ⚠️ Длину сессии задаёт КЛИЕНТ (мобильное приложение — до ближайшего понедельника,
    сайт и десктоп — прежние 5 часов, см. config.issue_ttl_min и комментарий там же о
    том, почему это не одинаково для всех устройств). Записываем её в саму сессию,
    чтобы потолок на /auth/refresh считался от того же значения, а не от заголовка
    очередного запроса."""
    client = client_kind(request)
    ttl = issue_ttl_min(client)
    access, a_jti, a_exp = create_token_full(user.login, user.role, "access", ttl_min=ttl)
    refresh, r_jti, r_exp = create_token_full(user.login, user.role, "refresh", ttl_min=ttl)
    _record_session(db, a_jti, user.login, user.role, "access", a_exp, request, r_jti, client)
    _record_session(db, r_jti, user.login, user.role, "refresh", r_exp, request, a_jti, client)
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
        full_name=body.full_name, updated_at=_now(),
    )
    set_user_password(u, body.password)   #хеш и дата выдачи — одной функцией
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
        audit.log(db, request, actor=login_str, action="login.fail", level="warn")
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")

    throttle.register_success(ip, login_str)
    events.record("info", "login", f"вход выполнен (роль {u.role})", login_str, ip)
    audit.log(db, request, actor=login_str, role=u.role, action="login.ok")

    #Преподаватель вошёл — СРАЗУ запускаем сборку снимка расписания в фоне. Полный
    #снимок это ~68 запросов к порталу (десятки секунд), и раньше эта сборка стартовала
    #только когда препод уже открыл вкладку расписания — он смотрел на «строится…».
    #Теперь сборка идёт, пока он на дашборде, и к моменту открытия расписание готово.
    #warm() ничего не блокирует: лишь стартует фоновый поток, если снимок несвежий.
    if u.role == "teacher":
        try:
            from .. import schedule_web
            schedule_web.warm()
        except Exception:
            pass        #прогрев — удобство, а не условие входа; сбой не мешает логину
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
    #⚠️ АБСОЛЮТНЫЙ потолок сессии — от РЕАЛЬНОГО момента входа (sess.issued_at, дата в
    #БД, а не exp из JWT). Без этой проверки «жёсткие 5 часов» держались ТОЛЬКО тем,
    #что refresh не ротируется и его exp считался как iat+JWT_REFRESH_TTL_MIN — то есть
    #предположением, что JWT_REFRESH_TTL_MIN всегда равен JWT_TTL_MIN. Токен, выданный
    #ДО того, как это значение однажды сузили с 30 дней до 5 часов, продолжал бы
    #обновляться ещё месяц — ровно так и было поймано вживую (простое повторное
    #открытие сайта держало сессию намного дольше 5 часов). Теперь потолок не зависит
    #от текущего конфига и не может быть обойдён повторным изменением настройки.
    try:
        issued = datetime.fromisoformat(sess.issued_at)
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
        session_age_min = (datetime.now(timezone.utc) - issued).total_seconds() / 60
    except (TypeError, ValueError):
        session_age_min = 0      #метка повреждена/отсутствует — не блокируем по этой причине
    #Потолок берём ПО КЛИЕНТУ, записанному в самой сессии при входе (см. models.AuthSession
    #и config.session_ttl_min): у мобильного приложения он недельный, у сайта и десктопа —
    #прежние 5 часов. Читать «мобильный ли клиент» из ЗАГОЛОВКА прямо здесь нельзя: тогда
    #браузер, приславший X-Client: android, растянул бы уже выданную веб-сессию до недели,
    #то есть заголовок стал бы способом обойти потолок.
    if session_age_min > session_ttl_min(sess.client or ""):
        sess.revoked = True
        db.commit()
        raise HTTPException(status_code=401, detail="Сессия истекла, нужен повторный вход")
    #ВТОРАЯ, независимая граница — КОНКРЕТНЫЙ срок, назначенный этой сессии при входе
    #(auth_sessions.expires_at). Проверка выше сравнивает возраст с потолком ПОЛИТИКИ и
    #поэтому не видит рубежа, который зависит от даты входа: мобильная сессия кончается
    #в ближайший понедельник, и в воскресенье её возраст (шесть дней) честно меньше
    #недельного потолка — то есть одной верхней проверки мало, понедельник наступил бы,
    #а сессия жила дальше. Ноль/пусто = запись старого формата, такие судим только по
    #возрасту (не выкидывать людей из-за нашей же миграции).
    now_ts = int(datetime.now(timezone.utc).timestamp())
    if sess.expires_at and now_ts >= int(sess.expires_at):
        sess.revoked = True
        db.commit()
        raise HTTPException(status_code=401, detail="Сессия истекла, нужен повторный вход")
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
    #Длину нового access берём из САМОЙ СЕССИИ, а не из заголовка этого запроса, и не
    #из глобального дефолта: иначе у мобильной сессии access жил бы 5 часов при недельном
    #потолке и приложение всё равно ходило бы за refresh каждые пять часов — то есть
    #ровно то, от чего мы уходим. Клиент наследуется, а не перечитывается.
    #⚠️ И ОБРЕЗАЕМ его сроком самой сессии. Без обрезки выданный в воскресенье access жил
    #бы неделю — то есть пережил бы понедельничный рубеж: проверки выше срабатывают
    #только когда клиент придёт ЗА ОБНОВЛЕНИЕМ, а с ещё действующим access он не придёт
    #вовсе. Рубеж, который держится лишь при добровольном визите клиента, — не рубеж.
    ttl = session_ttl_min(sess.client or "")
    if sess.expires_at:
        ttl = max(1, min(ttl, int((int(sess.expires_at) - now_ts) // 60)))
    access, a_jti, a_exp = create_token_full(u.login, u.role, "access", ttl_min=ttl)
    _record_session(db, a_jti, u.login, u.role, "access", a_exp, request, jti,
                    sess.client or "")
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
        audit.log(db, request, actor=user.login, role=user.role, action="logout")
    return {"revoked": revoked}


# ── Самостоятельная регистрация студентов и восстановление пароля ────────────────
import uuid as _uuid                                                   # noqa: E402
from fastapi import Body                                              # noqa: E402
from ..models import RegistrationRequest, Group                       # noqa: E402
from .. import reg_utils, mailer, gost                                # noqa: E402


@router.post("/register")
def register(body: dict = Body(...), request: Request = None, db: Session = Depends(get_db)):
    """Заявка студента на регистрацию (публичная, без токена). Проверяем ФИО, ГРУППУ
    (с учётом «сдвоенных» — К104/2 → К104/2,105.0), телефон и e-mail (только разрешённые
    домены). Аккаунт НЕ создаётся сразу — заявка ждёт одобрения администратора."""
    #Анти-DDoS заявками: 5 неверных попыток с одного IP → блок на 3 минуты.
    ip = throttle.client_ip(request) if request is not None else ""
    left = throttle.seconds_until_reg_unlocked(ip)
    if left:
        raise HTTPException(status_code=429,
                            detail=f"Слишком много попыток регистрации. Подождите {left // 60 + 1} мин.")

    def _fail(msg: str, code: int = 400):
        throttle.register_reg_failure(ip)          #каждая невалидная попытка приближает блок
        raise HTTPException(status_code=code, detail=msg)

    full_name = " ".join((body.get("full_name") or "").split())
    phone_in = body.get("phone") or ""
    email = (body.get("email") or "").strip().lower()
    group_in = (body.get("group") or "").strip()

    if not reg_utils.valid_full_name(full_name):
        _fail("Укажите ФИО полностью (минимум фамилия и имя)")
    phone = reg_utils.normalize_phone(phone_in)
    if not phone:
        _fail("Некорректный номер телефона")
    if not reg_utils.valid_email(email):
        _fail("Разрешены только почты @yandex.ru, @mail.ru, @esstu.ru")
    names = [g.name for g in db.query(Group).filter(Group.deleted == False).all()]  # noqa: E712
    group = reg_utils.resolve_group(group_in, names)
    if not group:
        _fail(f"Группа «{group_in}» не найдена. Формат: К‹число›/‹подгруппа›, например К104/2.")

    #не плодим дубликаты: уже есть студент с таким логином или заявка на рассмотрении
    if db.query(User).filter(User.login == email, User.deleted == False).first():  # noqa: E712
        _fail("Аккаунт с такой почтой уже существует", 409)
    if db.query(RegistrationRequest).filter(
            RegistrationRequest.email == email,
            RegistrationRequest.status == "pending").first():
        _fail("Заявка с такой почтой уже на рассмотрении", 409)

    db.add(RegistrationRequest(id=str(_uuid.uuid4()), full_name=full_name, group_name=group,
                               phone=gost.encrypt(phone),  # ПДн-телефон шифруем при хранении (ГОСТ)
                               email=email, status="pending", created_at=_now()))
    db.commit()
    throttle.register_reg_success(ip)              #удачная заявка сбрасывает счётчик
    try:
        events.record("info", "registration_request", f"{full_name} · {group} · {email}")
    except Exception:
        pass
    audit.log(db, request, actor=email, action="reg.request", target=group)
    return {"ok": True, "group": group}


@router.post("/recover")
def recover(body: dict = Body(...), request: Request = None, db: Session = Depends(get_db)):
    """Восстановление пароля студента по e-mail (= логин). Если аккаунт есть — генерируем
    НОВЫЙ пароль, сохраняем ХЕШ (старый пароль перестаёт работать), отзываем активные
    сессии и высылаем новый пароль на почту. Ответ ВСЕГДА одинаковый и НЕ содержит sent
    (не раскрываем существование почты — анти-энумерация). Лимит по IP — анти-спам сбросов."""
    ip = throttle.client_ip(request) if request is not None else ""
    left = throttle.seconds_until_reg_unlocked(ip)
    if left:
        raise HTTPException(status_code=429,
                            detail=f"Слишком много запросов. Подождите {left // 60 + 1} мин.")
    throttle.register_reg_failure(ip)   #каждый запрос на сброс приближает временный лимит
    email = (body.get("email") or "").strip().lower()
    u = db.query(User).filter(User.login == email, User.role == "student",
                              User.deleted == False).first()  # noqa: E712
    sent = False
    if u:
        pw = reg_utils.gen_password()
        set_user_password(u, pw)                #храним только хеш; старый недействителен
        u.updated_at = _now()
        db.query(AuthSession).filter(AuthSession.login == email).update({"revoked": True})
        db.commit()
        sent = mailer.send_email(
            email, "GradeBookAI — новый пароль",
            f"Здравствуйте!\n\nВаш новый пароль для входа в электронный журнал: {pw}\n"
            f"Логин: {email}\n\nВойдите на https://esstu-gradebook.ru и при желании смените пароль.",
            html=mailer._brand_html("Новый пароль", [
                "Вы запросили восстановление доступа. Ваш новый пароль:",
                f"<b style='font-size:18px'>{pw}</b>",
                f"Логин: <b>{email}</b>",
                "Войдите на <a href='https://esstu-gradebook.ru'>esstu-gradebook.ru</a>."]))
    _ = sent  # ответ намеренно НЕ зависит от sent — не раскрываем существование аккаунта
    #В ЖУРНАЛ (внутренний, админ-only) писать факт можно: анти-энумерация касается только
    #ответа клиенту. Пишем, был ли сброс реально выполнен — для разбора инцидентов.
    audit.log(db, request, actor=email, action="password.recover",
              detail="сброшен" if u else "аккаунт не найден")
    return {"ok": True}
