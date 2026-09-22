"""
shared_state.py — ОДНА ДВЕРЬ к состоянию, которое обязано быть общим для всех процессов.

━━ ЗАЧЕМ ЭТОТ МОДУЛЬ СУЩЕСТВУЕТ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Потолок масштаба у нас не SQLite и не язык, а инвариант «один uvicorn»: реестр сокетов,
анти-брутфорс, ход активностей и ещё полтора десятка величин живут в памяти ПРОЦЕССА.
На боевом VPS это было незаметно (там одно ядро). На машине, которую мы ставим сами
(8–12 ядер), это значит, что используется одно ядро из восьми.

Мест, которые ломает второй воркер, ДВАДЦАТЬ ТРИ, и они перечислены поимённо в
`server/tests/test_process_local_state.py`. Восемнадцать из них — «перенести»: при N
процессах ломается СМЫСЛ, а не скорость.

🔥 ГЛАВНАЯ ОПАСНОСТЬ ЭТОЙ РАБОТЫ НАЗВАНА ЗАРАНЕЕ: перенести часть и не заметить.
Перенесёшь три места из восемнадцати — получишь МОЛЧА ослабленный анти-брутфорс при
полностью зелёных тестах: пять попыток превратятся в 5×N, и увидеть это можно только
подбором пароля. Поэтому здесь не только примитивы, но и ВОРОТА: число воркеров
выводится из полноты переноса (`workers_allowed()`), а не задаётся отдельной настройкой,
которая однажды разойдётся с действительностью.

━━ ЧТО ВКЛЮЧАЕТ ОБЩЕЕ СОСТОЯНИЕ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ НЕ НАЛИЧИЕ ПАКЕТА, А НАСТРОЙКА `GRADEBOOK_REDIS_URL`. Это принципиально: пакет
`redis` крошечный и может приехать транзитивно, а «поставил библиотеку — молча
переключился режим работы продукта» — ровно тот класс отказа, из-за которого в проекте
запрещено объявлять зависимость комментарием. Настройки нет → поведение БУКВАЛЬНО
сегодняшнее, память процесса, один воркер.

━━ ЧЕСТНАЯ ГРАНИЦА: ЧТО ДЕЛАЕМ ПРИ ОТКАЗЕ REDIS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Выбор здесь неприятный в обе стороны, и молчать о нём нельзя.
  • отказать (fail closed) — значит, что падение Redis запирает ВХОД всему колледжу:
    ограничитель не смог посчитать попытки, следовательно никто не входит;
  • продолжить на памяти (fail open) — значит, что ограничители тихо становятся
    поворкерными, то есть в N раз слабее, и никто об этом не узнает.
Принято второе, НО с громким сигналом: `degraded()` поднимается, в обычный лог уходит
предупреждение (один раз, а не на каждый запрос), и признак виден в `/health` и в
разделе «Сервер». Тихая деградация запрещена; шумная — допустимый размен, потому что
запертый вход это отказ продукта, а ослабленный ограничитель — ухудшение защиты, от
которого страхует ещё и сам пароль.
⚠️ Отсюда требование к эксплуатации: Redis обязан жить на ТОЙ ЖЕ машине, что и сервер
(unix-сокет или 127.0.0.1). Redis по сети добавил бы сетевой отказ на путь КАЖДОГО
входа — и это была бы наша собственная новая точка отказа.

━━ ПРИМИТИВОВ ТРИ, И ЭТОГО ХВАТАЕТ НА ВСЕ ВОСЕМНАДЦАТЬ МЕСТ ━━━━━━━━━━━━━━━━━━━━━━━━━
  1. значение со сроком      — записи анти-брутфорса, баны, кулдауны, «уже видели»,
                               присутствие, задачи-вызовы passkey, заявки на ПК;
  2. скользящее окно         — все ограничители частоты (их девять);
  3. поток с номерами        — живая консоль администратора и рассылка по сокетам.
Четвёртого не заводить без нужды: каждый примитив — это ещё одна форма, которую придётся
одинаково реализовать в обоих движках, а расхождение движков даст дефект, видимый
только на бою.
"""
import itertools
import json
import logging
import os
import threading
import time

#Логгер берём как соседи (`audit.py`): корневой `log.py` — десктопный, и тянуть его в
#серверный модуль значило бы завести зависимость сервера от клиентской половины.
_LOG = logging.getLogger("gradebook.shared_state")

#Префикс всех наших ключей. Redis на машине может быть общим с чем-то ещё, и ключ вида
#"bans:1.2.3.4" рано или поздно с чем-нибудь столкнётся.
_PREFIX = "gb:"

#Потолок числа ключей на движке ПАМЯТЬ. Наследник `throttle.MAX_ENTRIES`, который при
#переносе перестал использоваться: срок закрывает медленное накопление, а всплеск нет.
MAX_KEYS = 20000
#Через сколько простоя выбрасывать пустое окно (у окон своего срока нет).
_WINDOW_IDLE_S = 3600

#Внутрипроцессный счётчик: делает член отсортированного множества уникальным даже
#когда часы не успели тикнуть. itertools.count атомарен относительно GIL.
_seq = itertools.count()

_warned = False
_degraded = False


def redis_url() -> str:
    """Настройка, включающая общее состояние. Пусто — работаем как раньше."""
    return (os.environ.get("GRADEBOOK_REDIS_URL") or "").strip()


# ─────────────────────────────────────────────────────────────────────────────────────
# ДВИЖОК «ПАМЯТЬ» — это НЕ заглушка, а сегодняшнее поведение продукта.
# Он обязан оставаться рабочим навсегда: на нём живут десктопный локальный сервер (там
# Redis не будет никогда) и любая установка в один процесс.
# ─────────────────────────────────────────────────────────────────────────────────────
class _MemoryBackend:
    """Состояние в памяти процесса. Ровно то, что было до переноса."""

    name = "memory"
    shared = False          #НЕ общее между процессами — отсюда и запрет на воркеров

    def __init__(self):
        self._lock = threading.RLock()
        self._values: dict = {}          #ключ -> (значение, до какого времени)
        self._windows: dict = {}         #ключ -> список меток времени
        self._streams: dict = {}         #канал -> (список (номер, запись), счётчик)

    #── значение со сроком ──────────────────────────────────────────────────────────
    #🔥 ХРАНИМ JSON-СТРОКУ, А НЕ ОБЪЕКТ, И ЭТО НЕ ПЕДАНТИЗМ (найдено разбором 10.09.2026).
    #Пока память клала объект как есть, она принимала то, чего Redis принять не может:
    #`bytes`, `set`, кортеж, нестроковый ключ словаря. На машине разработчика такой вызов
    #работал и тест был зелёным, а на бою тот же код ронял сериализацию — и `_call` уводил
    #ВСЕ процессы на память, то есть анти-брутфорс становился поворкерным МОЛЧА. Ровно тот
    #отказ, против которого затеян перенос.
    #⚠️ Побочно закрыто и второе расхождение: память отдавала ССЫЛКУ на своё значение, и
    #вызывающий, поправив полученный словарь, менял хранилище у себя за спиной. У Redis
    #так не бывает по построению.
    def get(self, key: str):
        with self._lock:
            rec = self._values.get(key)
            if not rec:
                return None
            raw, until = rec
            if until and until <= time.time():
                self._values.pop(key, None)
                return None
            return json.loads(raw)

    def set(self, key: str, value, ttl: float = 0) -> None:
        raw = json.dumps(value, ensure_ascii=False)      #упадёт ЗДЕСЬ, как и у Redis
        with self._lock:
            self._values[key] = (raw, time.time() + ttl if ttl else 0)

    def purge(self) -> int:
        """Выбросить протухшее и удержать потолок. Возвращает, сколько убрано.

        🔥 БЕЗ ЭТОГО БЫЛА НАСТОЯЩАЯ УТЕЧКА, и именно на бою (там движок — память).
        Срок у значения проверяется только ПРИ ЧТЕНИИ, а `keys()` протухшее прячет —
        значит запись, которую больше никто не спросит (выдуманный логин из перебора),
        не удалял НИКТО до перезапуска процесса. Прежний `throttle._gc` шёл по своему
        словарю и такие записи выбрасывал, а `MAX_ENTRIES` резал взрывной рост; при
        переносе обе страховки исчезли, а замены не появилось.
        ⚠️ Потолок оставлен намеренно: срок закрывает медленное накопление, а всплеск
        (бот перебирает сотни тысяч логинов быстрее, чем истекает час) — нет.
        """
        with self._lock:
            now = time.time()
            dead = [k for k, (_r, until) in self._values.items() if until and until <= now]
            for k in dead:
                self._values.pop(k, None)
            empty = [k for k, marks in self._windows.items()
                     if not marks or now - marks[-1] > _WINDOW_IDLE_S]
            for k in empty:
                self._windows.pop(k, None)
            over = len(self._values) - MAX_KEYS
            if over > 0:
                #Режем самые близкие к истечению: у бессрочных ключей срок 0, и они
                #уходили бы первыми — а это как раз то, что терять нельзя.
                victims = sorted((v[1] or float("inf"), k)
                                 for k, v in self._values.items())[:over]
                for _until, k in victims:
                    self._values.pop(k, None)
                dead.extend(k for _u, k in victims)
            return len(dead) + len(empty)

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)

    def update(self, key: str, fn, ttl: float = 0):
        """Атомарное «прочитать-изменить-записать».

        ⚠️ Атомарность здесь не педантизм: две одновременные неудачные попытки входа
        прочитали бы fails=4 обе и записали 5 обе — одна попытка потерялась бы, и порог
        блокировки сдвинулся бы вверх. Именно так ограничитель и обходят.
        """
        with self._lock:
            cur = self.get(key)
            new = fn(cur)
            if new is None:
                self._values.pop(key, None)
            else:
                self.set(key, new, ttl)
            return new

    def keys(self, prefix: str) -> list:
        with self._lock:
            now = time.time()
            return [k for k, (_v, until) in list(self._values.items())
                    if k.startswith(prefix) and (not until or until > now)]

    #── скользящее окно ─────────────────────────────────────────────────────────────
    def window_add(self, key: str, window: float) -> int:
        with self._lock:
            now = time.time()
            marks = [t for t in self._windows.get(key, []) if now - t < window]
            marks.append(now)
            self._windows[key] = marks
            return len(marks)

    def window_count(self, key: str, window: float) -> int:
        with self._lock:
            now = time.time()
            marks = [t for t in self._windows.get(key, []) if now - t < window]
            if marks:
                self._windows[key] = marks
            else:
                self._windows.pop(key, None)
            return len(marks)

    def window_clear(self, key: str) -> None:
        with self._lock:
            self._windows.pop(key, None)

    #── поток с номерами ────────────────────────────────────────────────────────────
    def stream_append(self, channel: str, payload: dict, maxlen: int = 500) -> int:
        with self._lock:
            items, seq = self._streams.get(channel, ([], 0))
            seq += 1
            items.append((seq, payload))
            if len(items) > maxlen:
                del items[:len(items) - maxlen]
            self._streams[channel] = (items, seq)
            return seq

    def stream_read(self, channel: str, after: int = 0, limit: int = 500) -> list:
        with self._lock:
            items, _seq = self._streams.get(channel, ([], 0))
            return [dict(p, _seq=n) for n, p in items if n > after][-limit:]

    def ping(self) -> bool:
        return True


# ─────────────────────────────────────────────────────────────────────────────────────
# ДВИЖОК «REDIS» — тот же контракт, но состояние переживает процесс и видно всем.
# ─────────────────────────────────────────────────────────────────────────────────────
class _RedisBackend:
    """Общее состояние в Redis.

    ⚠️ Значения кладём JSON-ом, а не pickle: pickle из общего хранилища — это
    исполнение чужих данных при десериализации, и если Redis когда-нибудь окажется
    доступен не только нам, это готовая дыра. JSON заведомо безопасен и читается глазами
    при разборе инцидента.
    """

    name = "redis"
    shared = True

    def __init__(self, url: str):
        import redis                                  # локальный импорт: пакет нужен
        self._r = redis.Redis.from_url(               # только этому движку
            url, decode_responses=True,
            socket_timeout=2, socket_connect_timeout=2,
            health_check_interval=30)
        self._r.ping()                                #проверяем СРАЗУ, а не на первом
        self._redis = redis                           #запросе человека

    #── значение со сроком ──────────────────────────────────────────────────────────
    def get(self, key: str):
        raw = self._r.get(key)
        return json.loads(raw) if raw is not None else None

    def set(self, key: str, value, ttl: float = 0) -> None:
        raw = json.dumps(value, ensure_ascii=False)
        if ttl:
            self._r.set(key, raw, px=int(ttl * 1000))
        else:
            self._r.set(key, raw)

    def delete(self, key: str) -> None:
        self._r.delete(key)

    def update(self, key: str, fn, ttl: float = 0):
        """Атомарно, через WATCH: между чтением и записью никто не вклинится.

        ⚠️ Повтор при конфликте обязателен и ограничен. Без ограничения два процесса,
        одновременно долбящие один ключ, могли бы крутиться здесь неограниченно — на
        пути ВХОДА это означало бы зависший запрос.
        """
        for _ in range(8):
            with self._r.pipeline() as pipe:
                try:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    cur = json.loads(raw) if raw is not None else None
                    new = fn(cur)
                    pipe.multi()
                    if new is None:
                        pipe.delete(key)
                    elif ttl:
                        pipe.set(key, json.dumps(new, ensure_ascii=False),
                                 px=int(ttl * 1000))
                    else:
                        pipe.set(key, json.dumps(new, ensure_ascii=False))
                    pipe.execute()
                    return new
                except self._redis.WatchError:
                    continue
        raise RuntimeError("не удалось атомарно обновить %s за 8 попыток" % key)

    def keys(self, prefix: str) -> list:
        #SCAN, а не KEYS: KEYS блокирует сервер на всё время обхода, и на боевой базе
        #это заметно. Здесь ключей немного, но привычка стоит дёшево.
        return list(self._r.scan_iter(match=prefix + "*", count=200))

    #── скользящее окно ─────────────────────────────────────────────────────────────
    #Реализовано отсортированным множеством: метка времени и как оценка, и как член.
    #Так «выбросить старое» — одна команда, а не чтение всего списка в питон.
    def window_add(self, key: str, window: float) -> int:
        now = time.time()
        with self._r.pipeline() as pipe:
            pipe.zremrangebyscore(key, 0, now - window)
            #🔥 ЧЛЕН ОБЯЗАН БЫТЬ УНИКАЛЕН, И ОДНОЙ МЕТКИ ВРЕМЕНИ ДЛЯ ЭТОГО МАЛО.
            #Первая версия ключевала парой «время+pid» — и контрактный тест сразу
            #показал `[1, 1, 1, 2]` вместо `[1, 2, 3, 4]`: `time.time()` на Windows
            #дискретен до ~16 мс (наша давняя грабля, та же, из-за которой дельта-pull
            #фильтрует по `>=`, а не `>`). Одинаковый член — это ОДНА запись в
            #множестве, то есть ограничитель молча недосчитывает всплеск, а всплеск
            #ровно и есть то, ради чего он заведён.
            pipe.zadd(key, {"%.6f:%d:%d" % (now, os.getpid(), next(_seq)): now})
            pipe.zcard(key)
            pipe.expire(key, int(window) + 1)
            return pipe.execute()[2]

    def window_count(self, key: str, window: float) -> int:
        now = time.time()
        with self._r.pipeline() as pipe:
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zcard(key)
            return pipe.execute()[1]

    def window_clear(self, key: str) -> None:
        self._r.delete(key)

    #── поток с номерами ────────────────────────────────────────────────────────────
    def stream_append(self, channel: str, payload: dict, maxlen: int = 500) -> int:
        seq = self._r.incr(channel + ":seq")
        with self._r.pipeline() as pipe:
            pipe.zadd(channel, {json.dumps(dict(payload, _seq=seq),
                                           ensure_ascii=False): seq})
            pipe.zremrangebyrank(channel, 0, -(maxlen + 1))
            pipe.execute()
        return seq

    def stream_read(self, channel: str, after: int = 0, limit: int = 500) -> list:
        raw = self._r.zrangebyscore(channel, "(%d" % after, "+inf", start=0, num=limit)
        return [json.loads(x) for x in raw]

    def purge(self) -> int:
        """У Redis срок хранения — его собственная забота, чистить нечего.

        ⚠️ Метод существует, чтобы вызывающему не приходилось спрашивать «а какой у нас
        движок». Первый же такой вопрос расползается по коду и превращает одну дверь в
        две ветки, которые потом расходятся.
        """
        return 0

    def ping(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False


# ─────────────────────────────────────────────────────────────────────────────────────
# ВЫБОР ДВИЖКА
# ─────────────────────────────────────────────────────────────────────────────────────
_backend = None
_backend_lock = threading.Lock()
#Память живёт всегда: она же — запасной путь при отказе Redis (см. «честная граница»).
_fallback = _MemoryBackend()


def backend():
    """Текущий движок. Заводится один раз и переживает запросы."""
    global _backend, _warned
    if _backend is not None:
        return _backend
    with _backend_lock:
        if _backend is not None:
            return _backend
        url = redis_url()
        if not url:
            _backend = _fallback
            return _backend
        try:
            _backend = _RedisBackend(url)
            _LOG.info("[shared] общее состояние: Redis (%s)", _safe_url(url))
        except Exception as e:
            #Настройка задана, а Redis не отвечает — это НЕ повод молча работать как
            #раньше: администратор считает, что состояние общее, и мог включить воркеров.
            _mark_degraded("не удалось подключиться к Redis: %s" % e)
            _backend = _fallback
        return _backend


def _safe_url(url: str) -> str:
    """Адрес без пароля: строка подключения уезжает в лог."""
    if "@" in url:
        head, _sep, tail = url.rpartition("@")
        scheme = head.split("//", 1)[0] if "//" in head else ""
        return "%s//***@%s" % (scheme, tail)
    return url


def _mark_degraded(why: str) -> None:
    """Поднять признак деградации. Громко, но ОДИН раз за запуск.

    Строка на каждый запрос превратила бы журнал в шум, а шумный журнал перестают
    читать — тот же довод, по которому приманка пишет в аудит только первое срабатывание.
    """
    global _degraded, _warned
    _degraded = True
    if not _warned:
        _warned = True
        _LOG.warning("[shared] ОБЩЕЕ СОСТОЯНИЕ НЕДОСТУПНО, работаем на памяти процесса: "
                     "%s. Ограничители стали поворкерными — при нескольких воркерах они "
                     "в N раз слабее.", why)


def available() -> bool:
    """Настоящее ли общее состояние (переживает процесс и видно соседям)."""
    return bool(getattr(backend(), "shared", False)) and not _degraded


def degraded() -> bool:
    """Была ли деградация. Показывается в /health и в разделе «Сервер»."""
    return _degraded


def describe() -> dict:
    """Что показать человеку. Без значений — только режим."""
    b = backend()
    return {
        "backend": getattr(b, "name", "?"),
        "shared": bool(getattr(b, "shared", False)),
        "degraded": _degraded,
        "url": _safe_url(redis_url()) if redis_url() else "",
    }


def reset_for_tests() -> None:
    """Забыть выбранный движок. Только для тестов — иначе выбор кэшируется на процесс."""
    global _backend, _degraded, _warned
    with _backend_lock:
        _backend = None
        _degraded = False
        _warned = False
        _fallback.__init__()


# ─────────────────────────────────────────────────────────────────────────────────────
# ПУБЛИЧНЫЕ ПРИМИТИВЫ
# Каждый переживает отказ Redis: падение хранилища не имеет права ронять запрос
# человека, но обязано поднять признак деградации.
# ─────────────────────────────────────────────────────────────────────────────────────
def _call(method: str, *args, **kw):
    b = backend()
    try:
        return getattr(b, method)(*args, **kw)
    except (TypeError, ValueError):
        #🔥 НАША ОШИБКА, А НЕ ОТКАЗ ХРАНИЛИЩА, и путать их нельзя. Значение, которое не
        #ложится в JSON, — это дефект вызывающего кода. Уйти на память значило бы
        #«починить» его тем, что ВСЕ процессы тихо теряют общее состояние: ограничители
        #становятся поворкерными, и никто не связывает это с одной неудачной строкой.
        #Пусть падает громко и в том месте, где написано.
        raise
    except Exception as e:
        if b is _fallback:
            raise                                 #память падать не умеет — это наш баг
        _mark_degraded("%s: %s" % (method, e))
        return getattr(_fallback, method)(*args, **kw)


def get(key: str):
    return _call("get", _PREFIX + key)


def set(key: str, value, ttl: float = 0) -> None:      # noqa: A001 — имя примитива
    _call("set", _PREFIX + key, value, ttl)


def delete(key: str) -> None:
    _call("delete", _PREFIX + key)


def update(key: str, fn, ttl: float = 0):
    return _call("update", _PREFIX + key, fn, ttl)


def keys(prefix: str) -> list:
    return [k[len(_PREFIX):] for k in _call("keys", _PREFIX + prefix)]


def take(key: str):
    """Прочитать И удалить за одно неделимое действие. Возвращает прежнее значение.

    🔑 Нужно там, где значение ОДНОРАЗОВОЕ: задача-вызов passkey, заявка на одобрение
    ПК. Пара «прочитать, потом удалить» даёт окно, в которое второй запрос успевает
    прочитать то же самое — то есть готовый повтор одноразового значения, причём тем
    вероятнее, чем больше процессов, а больше процессов и есть цель всей работы.

    ⚠️ Нового ПРИМИТИВА У ДВИЖКОВ это не заводит — построено на уже существующем
    атомарном `update`. Каждая новая форма пришлось бы одинаково реализовать в обоих
    движках, а расхождение движков даёт дефект, видимый только на бою.
    """
    box = {}

    def _grab(cur):
        box["v"] = cur
        return None                      #None у `update` означает «удалить»

    _call("update", _PREFIX + key, _grab, 0)
    return box.get("v")


def window_add(key: str, window: float) -> int:
    """Отметить событие и вернуть, сколько их в окне (включая это)."""
    return _call("window_add", _PREFIX + key, window)


def window_count(key: str, window: float) -> int:
    return _call("window_count", _PREFIX + key, window)


def window_clear(key: str) -> None:
    _call("window_clear", _PREFIX + key)


def purge() -> int:
    """Выбросить протухшее. На Redis пусто, на памяти — единственная защита от роста."""
    return _call("purge")


def stream_append(channel: str, payload: dict, maxlen: int = 500) -> int:
    return _call("stream_append", _PREFIX + channel, payload, maxlen)


def stream_read(channel: str, after: int = 0, limit: int = 500) -> list:
    return _call("stream_read", _PREFIX + channel, after, limit)


# ─────────────────────────────────────────────────────────────────────────────────────
# ВОРОТА: СКОЛЬКО ВОРКЕРОВ МОЖНО
# ─────────────────────────────────────────────────────────────────────────────────────
#🔥 ЧТО ЕЩЁ НЕ ПЕРЕНЕСЕНО. Список — не памятка, а ВОРОТА: пока он непуст, число воркеров
#принудительно равно одному, сколько бы ни просили.
#
#⚠️ Список не пишется от руки и не может соврать: `test_process_local_state.py` СЧИТАЕТ
#его разбором `ast` по живому коду и требует совпадения. Забыл вычеркнуть перенесённое —
#прогон покраснеет; вычеркнул не перенеся — покраснеет тоже.
#
#⚠️ Почему ворота вообще нужны. Опасность этой работы не в сложности, а в незаметности:
#перенеси три места из восемнадцати и запусти четыре воркера — анти-брутфорс станет
#вчетверо слабее МОЛЧА, при зелёных тестах, и узнаешь об этом от того, кто подберёт
#пароль. Отдельная настройка «сколько воркеров» такую ошибку не ловит: она описывает
#намерение, а не готовность.
PENDING_MIGRATION: tuple = (
    ("canary.py", "_seen"),
    ("canary.py", "_mine_hits"),
    ("connect.py", "_pending"),
    ("events.py", "_presence"),
    ("events.py", "_events"),
    ("msg_limit.py", "_events"),
    ("msg_limit.py", "_violations"),
    ("msg_limit.py", "_bucket_events"),
    #✅ throttle.py перенесён 10.09.2026 целиком — все шесть величин (пары, адреса,
    #регистрации, баны, остуда восстановления, признак подозрения). Он шёл первым
    #осознанно: это единственная группа, где поворкерное состояние не «неудобно», а
    #прямо ослабляет защиту, причём ровно в N раз и совершенно молча.
    #✅ publicschedule.py перенесён 10.09.2026 — предел публичной ручки больше не
    #умножается на число процессов.
    #✅ webauthn_router.py перенесён 10.09.2026 — он шёл вторым после throttle,
    #потому что ломал не удобство, а сам ВХОД по ключу.
)


#🔥 ОТДЕЛЬНЫЙ ФЛАГ, ПОТОМУ ЧТО СПИСОК ВЫШЕ ЕГО НЕ ЗАКРЫВАЕТ (найдено разбором
#10.09.2026). Здесь стояло, что реестр сокетов «входит в условие через PENDING_MIGRATION
#тем же порядком». Это было НЕПРАВДОЙ и неправдой опасной: список собирается разбором
#`ast` по изменяемому состоянию УРОВНЯ МОДУЛЯ, а реестр — поле объекта `ws_manager`,
#то есть разбор его не видит и увидеть не может. Дописать руками тоже нельзя: сторож
#требует ТОЧНОГО совпадения списка с разбором.
#Итог был бы такой: закрываем оставшиеся места, `migration_complete()` отвечает «да»,
#запускаются четыре процесса — и сообщение в группе доходит живым каналом только тем,
#кто попал в тот же воркер. Остальные ждут опроса, разреженного до 30 с ИМЕННО потому,
#что сокет считается живым. Ворота при этом молчат.
#Снимается флаг только вместе с рассылкой между процессами (§3.2 docs/plans/PLAN-MULTIWORKER.md).
BROADCAST_READY = False


def migration_complete() -> bool:
    """Всё ли готово ко второму воркеру.

    Условия ДВА, и второе не выводится из первого: перенесённое состояние уровня модуля
    (список выше, сверяется с кодом) И рассылка между процессами (флаг рядом, сверить с
    кодом её нельзя — соединение принадлежит процессу по построению).
    """
    return not PENDING_MIGRATION and BROADCAST_READY


def workers_allowed() -> int:
    """Сколько процессов uvicorn запускать. ЕДИНСТВЕННОЕ место, где это решается.

    Три условия, и все обязательны:
      • перенос ЗАВЕРШЁН (иначе ограничители молча слабеют в N раз);
      • общее состояние действительно работает (настройка задана и Redis отвечает);
      • администратор попросил явно — `GRADEBOOK_WORKERS`.

    ⚠️ Умолчание — ОДИН, даже когда всё готово. Молча занять восемь ядер на машине,
    которая никуда не переезжала, значит переделать прод без спроса: у нескольких
    процессов другой профиль памяти и другое поведение при перезапуске.
    ⚠️ Реестр сокетов остаётся ПРОЦЕССНЫМ по построению — соединение принадлежит
    процессу. Его закрывает не перенос состояния, а РАССЫЛКА между процессами, и она
    учитывается отдельным флагом `BROADCAST_READY`: разбором `ast` реестр не находится
    (это поле объекта, а не контейнер уровня модуля), поэтому в список он попасть не
    может, и полагаться на список здесь значило бы полагаться на пустоту.
    """
    want = (os.environ.get("GRADEBOOK_WORKERS") or "").strip()
    if not want.isdigit() or int(want) <= 1:
        return 1
    if not migration_complete():
        _LOG.warning("[shared] запрошено воркеров: %s, но перенос состояния не завершён "
                     "(осталось мест: %d) — работаем в ОДИН процесс",
                     want, len(PENDING_MIGRATION))
        return 1
    if not available():
        _LOG.warning("[shared] запрошено воркеров: %s, но общее состояние недоступно "
                     "(GRADEBOOK_REDIS_URL) — работаем в ОДИН процесс", want)
        return 1
    return min(int(want), 16)
