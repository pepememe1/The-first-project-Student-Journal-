"""
throttle.py — Защита серверного входа от перебора паролей (анти-брутфорс).

Зачем (152-ФЗ, приказ ФСТЭК России №21):
  Клиентский анти-брутфорс (audit.py в десктопе) защищает только локальный вход
  в программу. Как только сервер виден по сети (ЛВС колледжа или белый IP), его
  эндпоинт /auth/login становится мишенью для перебора пароля. Поэтому ограничение
  попыток нужно и здесь, на стороне сервера, иначе пароль подбирается извне.

Ключ блокировки — пара (IP, логин), а НЕ один логин. Причина: на публичном сервере
блокировка только по логину позволила бы любому злоумышленнику заблокировать вход
настоящему пользователю, просто долбя его логин неверным паролем (lockout-DoS).
Пара (IP, логин) бьёт ровно по атакующему: один источник, пытающийся подобрать один
аккаунт. Дополнительно держим грубый лимит по одному IP — чтобы перебор множества
логинов с одной машины («распыление») тоже упирался в стену.

Хранение — в памяти процесса. Этого достаточно: в типовом развёртывании колледжа
сервер крутится одним процессом (uvicorn, один воркер), а рестарт сервера атакующему
недоступен. ⚠️ Если когда-нибудь запустите несколько воркеров (gunicorn -w N) или
несколько машин за балансировщиком — счётчики перестанут быть общими; тогда выносите
состояние в общий слой (Redis/БД). Для текущей модели «один ПК-сервер» память верна.

Модуль потокобезопасен: FastAPI выполняет синхронные эндпоинты в пуле потоков, и
к одним и тем же счётчикам могут обращаться параллельно — поэтому доступ под Lock.
"""
import threading
import time

#Те же пороги, что и у клиента (audit.py) — единое поведение «7 попыток / 5 минут».
MAX_FAILS = 7            #неверных попыток на пару (IP, логин) до блокировки
LOCK_SECONDS = 300       #длительность блокировки (5 минут)

#Грубый предохранитель от «распыления»: сколько всего неудач с ОДНОГО IP по разным
#логинам терпим, прежде чем заблокировать этот IP целиком.
IP_MAX_FAILS = 30
IP_LOCK_SECONDS = 300

#Регистрация (самостоятельная): по требованию — 5 неверных попыток подряд → ждать 3 мин.
#Отдельный счётчик по IP, чтобы заявками не задудосили сайт.
REG_MAX_FAILS = 5
REG_LOCK_SECONDS = 180

#Окно подсчёта неудач: серия «протухает», если давно не было попыток. Без него счётчик
#копился ВЕЧНО (обнулялся только после сработавшей блокировки), и человек, ошибшийся
#7 раз за полгода, получал бы бан — при обещанных «7 попыток / 5 минут».
FAIL_WINDOW = 300

#Уборка мусора: сервер торчит в интернете, и боты долбятся с ТЫСЯЧ разных IP. Каждая
#новая пара (IP, логин) оставляла запись НАВСЕГДА → словари росли безгранично и съедали
#память VPS. Держим только «живые» записи: заблокированные + недавно активные.
IDLE_TTL = 900           #сколько храним запись без активности (не заблокированную)
GC_EVERY = 200           #как часто (по числу регистраций неудач) запускать уборку
MAX_ENTRIES = 20000      #жёсткий предохранитель на случай взрывного всплеска

_lock = threading.Lock()
#login-ключ "ip|login" -> {"fails": int, "locked_until": float, "last": float}
_pairs: dict = {}
#ip-ключ "ip" -> {"fails": int, "locked_until": float, "last": float}
_ips: dict = {}
#ip-ключ регистрации "ip" -> {...}
_reg: dict = {}
_since_gc = 0            #счётчик обращений до следующей уборки


def _pair_key(ip: str, login: str) -> str:
    return f"{(ip or '').strip()}|{(login or '').strip().lower()}"


def _check(store: dict, key: str) -> int:
    """Возвращает остаток блокировки в секундах (0 — не заблокирован)."""
    rec = store.get(key)
    if not rec:
        return 0
    left = int(rec.get("locked_until", 0) - time.time())
    return left if left > 0 else 0


def seconds_until_unlocked(ip: str, login: str) -> int:
    """Сколько секунд осталось до разблокировки (0 — вход разрешён).
    Берём максимум из блокировки по паре (IP, логин) и по самому IP."""
    with _lock:
        return max(_check(_pairs, _pair_key(ip, login)), _check(_ips, (ip or "").strip()))


def _gc(force: bool = False):
    """Выбрасывает протухшие записи. Вызывается изредка (см. GC_EVERY) — без фонового
    потока. Держим: заблокированные (наказание не должно теряться) и недавно активные.

    ВАЖНО: чистим и записи с fails>0 — именно они составляют основную массу мусора
    (бот сделал 2-3 попытки с одного IP и ушёл). Условие «удалять только при fails==0»
    оставило бы утечку почти нетронутой."""
    global _since_gc
    _since_gc += 0 if force else 1
    if not force and _since_gc < GC_EVERY:
        return
    _since_gc = 0
    now = time.time()
    for store in (_pairs, _ips, _reg):
        stale = [k for k, v in store.items()
                 if v.get("locked_until", 0) <= now and now - v.get("last", 0) > IDLE_TTL]
        for k in stale:
            store.pop(k, None)
        #предохранитель: при взрывном всплеске (быстрее уборки) режем самые старые
        if len(store) > MAX_ENTRIES:
            for k, _v in sorted(store.items(), key=lambda kv: kv[1].get("last", 0))[
                    :len(store) - MAX_ENTRIES]:
                if store.get(k, {}).get("locked_until", 0) <= now:
                    store.pop(k, None)


def _register_failure(store: dict, key: str, threshold: int, lock_seconds: int):
    now = time.time()
    rec = store.get(key, {"fails": 0, "locked_until": 0, "last": now})
    #истёкшая блокировка обнуляет счётчик — новая серия считается с нуля
    if rec.get("locked_until", 0) and rec["locked_until"] < now:
        rec = {"fails": 0, "locked_until": 0, "last": now}
    #СКОЛЬЗЯЩЕЕ ОКНО: давние неудачи не копятся (иначе редкие опечатки за месяцы
    #складывались бы в блокировку живого пользователя).
    elif now - rec.get("last", now) > FAIL_WINDOW:
        rec = {"fails": 0, "locked_until": rec.get("locked_until", 0), "last": now}
    rec["fails"] = rec.get("fails", 0) + 1
    rec["last"] = now
    if rec["fails"] >= threshold:
        rec["locked_until"] = now + lock_seconds
        rec["fails"] = 0
    store[key] = rec
    _gc()


def register_failure(ip: str, login: str):
    """Фиксирует неудачную попытку входа: и по паре (IP, логин), и по IP."""
    with _lock:
        _register_failure(_pairs, _pair_key(ip, login), MAX_FAILS, LOCK_SECONDS)
        _register_failure(_ips, (ip or "").strip(), IP_MAX_FAILS, IP_LOCK_SECONDS)


def register_success(ip: str, login: str):
    """Удачный вход сбрасывает счётчик по паре (IP, логин). Счётчик IP не трогаем —
    иначе один верный вход обнулял бы наказание за «распыление» по чужим логинам."""
    with _lock:
        _pairs.pop(_pair_key(ip, login), None)


def seconds_until_reg_unlocked(ip: str) -> int:
    """Сколько секунд до разблокировки регистрации с этого IP (0 — можно)."""
    with _lock:
        return _check(_reg, (ip or "").strip())


def register_reg_failure(ip: str):
    """Фиксирует неудачную (невалидную) попытку регистрации с IP."""
    with _lock:
        _register_failure(_reg, (ip or "").strip(), REG_MAX_FAILS, REG_LOCK_SECONDS)


def register_reg_success(ip: str):
    """Успешная заявка сбрасывает счётчик регистраций этого IP."""
    with _lock:
        _reg.pop((ip or "").strip(), None)


def reset():
    """Полный сброс состояния — нужен тестам, чтобы прогоны не влияли друг на друга."""
    global _since_gc
    with _lock:
        _pairs.clear()
        _ips.clear()
        _reg.clear()
        _since_gc = 0


def gc_now() -> tuple:
    """Принудительная уборка (тесты/диагностика). Возвращает размеры словарей после неё."""
    with _lock:
        _gc(force=True)
        return len(_pairs), len(_ips), len(_reg)


def sizes() -> tuple:
    """Текущие размеры счётчиков — для мониторинга роста памяти."""
    with _lock:
        return len(_pairs), len(_ips), len(_reg)


def client_ip(request) -> str:
    """IP клиента для блокировки перебора.

    ⚠️ БЕЗОПАСНОСТЬ: X-Forwarded-For задаёт КЛИЕНТ, и его первый элемент подделывается.
    Caddy (reverse_proxy) не вырезает входящий XFF, а дописывает реальный адрес в КОНЕЦ.
    Раньше брали первый элемент — атакующий слал случайный XFF на каждой попытке, и
    счётчик (IP, логин) никогда не срабатывал → серверный анти-брутфорс обходился.

    Правильный источник — заголовок, который ставит САМ прокси из проверенного TCP-пира:
      • X-Real-IP  — задаётся в Caddyfile (`header_up X-Real-IP {remote_host}`), клиент
        его перебить не может (Caddy перезаписывает);
      • если его нет — берём ПОСЛЕДНИЙ хоп X-Forwarded-For (его дописал Caddy = реальный
        клиент; подделанные клиентом значения остаются левее);
      • совсем без прокси (dev) — прямой адрес соединения.
    """
    rip = request.headers.get("x-real-ip", "").strip()
    if rip:
        return rip
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[-1].strip()
    client = getattr(request, "client", None)
    return (client.host if client else "") or ""
