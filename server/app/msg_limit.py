"""
msg_limit.py — Анти-флуд отправки сообщений в мессенджере (per-user rate limit).

Зачем (152-ФЗ, приказ ФСТЭК России №21, устойчивость к злоупотреблению):
  Контроль доступа мессенджера прочный (в чужую беседу не написать), но частота записи
  ничем не ограничена: залогиненный аккаунт мог слать тысячи сообщений в секунду —
  раздувание БД, спам собеседнику, отказ в обслуживании. throttle.py защищает только вход;
  здесь — тормоз на саму отправку. При превышении сервер отвечает 429, а клиент показывает
  «не отправляйте сообщения так часто».

Модель — СКОЛЬЗЯЩЕЕ ОКНО по user_id, два предела сразу:
  • короткий  — гасит взрывной спам-скрипт (много сообщений за пару секунд);
  • длинный   — гасит равномерный, но избыточный поток.
Человек в живой переписке в эти пороги НЕ упирается; упирается автомат.

Хранение — в памяти процесса (как throttle.py): типовое развёртывание колледжа — один
воркер uvicorn. ⚠️ При нескольких воркерах/машинах счётчики перестанут быть общими —
тогда выносите состояние в общий слой (Redis). Для «один ПК-сервер» память верна.

Потокобезопасно: синхронные эндпоинты FastAPI исполняются в пуле потоков → доступ под Lock.
"""
import threading
import time
from collections import deque, defaultdict

#(окно в секундах, максимум сообщений в этом окне). Первый предел — антивзрыв, второй —
#антипоток. Пороги подобраны с запасом для живого набора и тесны для автомата.
_LIMITS = ((5.0, 10), (60.0, 60))
_MAX_WINDOW = max(w for w, _ in _LIMITS)

#Уборка простаивающих очередей: без неё словарь рос бы по одному ключу на каждого
#когда-либо писавшего. Держим только «живые» (в пределах последнего окна).
_GC_EVERY = 500          #как часто (по числу обращений) чистить
_MAX_ENTRIES = 50000     #жёсткий предохранитель на всплеск

_lock = threading.Lock()
_events: dict = defaultdict(deque)   #user_id -> deque[float] меток отправки
_since_gc = 0


def _prune(dq: deque, now: float) -> None:
    """Выбрасывает метки старше самого длинного окна — очередь не растёт бесконечно."""
    horizon = now - _MAX_WINDOW
    while dq and dq[0] <= horizon:
        dq.popleft()


def _gc(now: float) -> None:
    global _since_gc
    _since_gc += 1
    if _since_gc < _GC_EVERY and len(_events) < _MAX_ENTRIES:
        return
    _since_gc = 0
    for uid in [k for k, dq in _events.items() if not dq or dq[-1] <= now - _MAX_WINDOW]:
        _events.pop(uid, None)


def check(user_id: str) -> int:
    """Проверяет и РЕГИСТРИРУЕТ попытку отправки. Возвращает 0, если можно (метка записана),
    иначе — сколько СЕКУНД подождать до разблокировки (метку при отказе НЕ пишем, чтобы окно
    само истекало, а не продлевалось спамом). Пустой user_id не лимитируем (не должно быть)."""
    if not user_id:
        return 0
    now = time.time()
    with _lock:
        dq = _events[user_id]
        _prune(dq, now)
        for window, limit in _LIMITS:
            edge = now - window
            in_window = [t for t in dq if t > edge]
            if len(in_window) >= limit:
                #ждать, пока из окна выпадет самая старая метка этого предела
                return max(1, int(min(in_window) + window - now) + 1)
        dq.append(now)
        _gc(now)
        return 0


# §D2: «маскот-замедление» — вместо холодного 429 показываем Вектора с фразой (композер
# блокируется на cooldown_seconds). Порог МЯГЧЕ и УЖЕ базового (5 сообщений за 8 c) — на
# практике срабатывает раньше жёсткого лимита выше, который остаётся глубокой защитой от
# скрипта, игнорирующего клиентский UI. Эскалация — по истории «поймали на всплеске»:
#   1-е нарушение              → 8 c
#   повтор за 5 мин            → 20 c
#   3-е и далее нарушение за 10 мин → 60 c (+ тикет модерации — решает вызывающий код)
_MASCOT_BURST_WINDOW = 8.0
_MASCOT_BURST_LIMIT = 5
_VIOLATION_WINDOW = 600.0      # 10 минут — окно «систематичности»
_REPEAT_WINDOW = 300.0         # 5 минут — окно «повтора»

_violations: dict = defaultdict(deque)   # user_id -> deque[float] меток нарушения


def mascot_check(user_id: str):
    """Возвращает (wait_seconds, violations_in_10min). wait=0 — можно писать.

    Читает ТЕ ЖЕ метки успешной отправки, что и check() (общий _events), сама их не
    пишет — вызывать ДО check(), иначе последняя попытка уже попала бы в свой же расчёт.
    Одна затянувшаяся перегрузка не плодит нарушения на каждый повторный клик «Отправить»:
    новое нарушение засчитывается, только если с прошлого прошло больше окна всплеска."""
    if not user_id:
        return 0, 0
    now = time.time()
    with _lock:
        dq = _events[user_id]
        _prune(dq, now)
        in_burst = sum(1 for t in dq if t > now - _MASCOT_BURST_WINDOW)
        if in_burst < _MASCOT_BURST_LIMIT:
            return 0, 0
        vq = _violations[user_id]
        while vq and vq[0] <= now - _VIOLATION_WINDOW:
            vq.popleft()
        if not vq or now - vq[-1] > _MASCOT_BURST_WINDOW:
            vq.append(now)
        recent_10m = len(vq)
        recent_5m = sum(1 for t in vq if t > now - _REPEAT_WINDOW)
        if recent_10m >= 3:
            return 60, recent_10m
        if recent_5m >= 2:
            return 20, recent_10m
        return 8, recent_10m


def reset() -> None:
    """Полный сброс — нужен тестам, чтобы прогоны не влияли друг на друга."""
    global _since_gc
    with _lock:
        _events.clear()
        _violations.clear()
        _since_gc = 0


def size() -> int:
    """Число отслеживаемых пользователей — для мониторинга роста памяти."""
    with _lock:
        return len(_events)
