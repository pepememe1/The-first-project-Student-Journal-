"""
desk_outbox.py — очередь правок журнала, сделанных В ПРОГРАММЕ, на боевой сервер.

━━ ЗАЧЕМ (аудит 22.09.2026, находка F-02, P1) ━━
Внутри программы интерфейс пишет в ЛОКАЛЬНУЮ копию базы (её обслуживает настоящий
`server/app`, см. `desktop/local_api.py`). Копия наполнялась зеркалом только в одну
сторону — с боя на ПК, — а старый синк собирал правки из другой базы, в которую
интерфейс не пишет с удаления Qt. Оценка получала «сохранено», жила в копии и на бой не
доезжала НИКОГДА. Эта очередь — недостающая половина: правка журнала ложится в копию
мгновенно (offline-first, §4.1) и тут же встаёт сюда, а отсюда уходит на бой.

━━ КАК УСТРОЕНО ━━
1. Запрос журнала (`route_policy.REPLAY`) встаёт в очередь ДО обработчика (`pending`):
   сбой процесса между «записали в копию» и «поставили в очередь» не теряет правку.
2. Обработчик пишет в копию. 2xx → запись `ready`, запоминаем ключ строки, версию ДО
   правки (`base_updated_at`) и ПОСЛЕ (`updated_at`). Не 2xx → запись убираем: копия
   отказала, бой откажет по той же причине.
3. Досылка (`flush`) идёт СТРОГО ПО ПОРЯДКУ — оценка к занятию не уедет раньше самого
   занятия:
     2xx                       → убрать, запомнить «локальная версия → боевая»;
     409 с кодом `conflict`    → на экран конфликтов (решает человек, не мы);
     отказ по существу         → «не принято сервером» с причиной (403/404/400/409…);
     сеть, 5xx, 408, 425, 429  → остановиться и повторить позже, НИЧЕГО не перескакивая;
     401                       → остановиться: истёк боевой токен, его обновит цикл.
4. Строку, у которой в очереди есть правка, зеркало НЕ перезаписывает
   (`mirror_guard`): иначе человек видел бы, как его оценка «откатилась» у него на глазах.
   Ключ строки известен уже при постановке (`route_policy.row_key_hint`), решение зеркала и
   постановка идут под одним замком (`APPLY_LOCK`), а правку, которую бой уже принял,
   снимок, снятый ДО досылки, не откатывает (исследование синка 25.09.2026, W-07).
5. Правка, на которой сервер раз за разом падает ОШИБКОЙ ПРИЛОЖЕНИЯ (500), не держит
   очередь вечно: после `MAX_SERVER_ERRORS` попыток с растущей паузой она уходит в «не
   принято сервером» с кнопкой «Повторить», а очередь идёт дальше (W-10). Ответы шлюза
   (502/503/504 — сервер лежит или перезапускается) против правки не считаются.

━━ ВЕРСИЯ, КОТОРУЮ ВИДЕЛ ЧЕЛОВЕК ━━
Бой отличает «правка на свежей версии» от «затирание чужой» по `base_updated_at`
(`server/app/routers/web/_common.py::_ensure_base_version`). Тонкость в цепочке: вторая
правка той же оценки офлайн снята уже с ЛОКАЛЬНОЙ версии первой, а не с боевой. Поэтому
после каждой успешной досылки запоминаем пару «локальная версия → боевая» (`desk_versions`)
и подставляем боевую; а пока более ранняя правка той же строки не решена (конфликт или
отказ), поздняя ждёт — отправь её раньше, и бой сверял бы её не с той версией.

━━ ВЕРСИЯ — НОМЕР ИЗМЕНЕНИЯ (26.09.2026, W-14) ━━
С боем 4.1 база правки — `base_seq`: номер изменения строки в копии, то есть последняя
увиденная ЗДЕСЬ боевая версия (в копии номера не ставит никто, их приносит зеркало).
Время ПК из протокола уходит: раньше, если пары «локальная версия → боевая» не было, бой
сверял свою метку с меткой, которую поставили часы этой машины. Номер берётся уже при
ПОСТАНОВКЕ в очередь — поэтому и «осиротевшая» правка (процесс упал до ответа
обработчика) досылается со своей базой, а не без неё. Цепочка правок одной строки
разворачивается так же, как по времени: «наша база → номер, который бой дал нашей
правке» (`desk_seq_versions`). `base_updated_at` досылается рядом — его читает бой до 4.1.

━━ ГДЕ ЖИВЁТ ━━
В той же зашифрованной копии базы, что и данные, к которым правки относятся (своя копия
у каждого пользователя, SQLCipher). Отдельный файл был бы вторым местом с ПДн, которое
надо не забыть зашифровать, перенести и стереть при смене владельца.
"""
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import log

_LOG = log.get("desk_outbox")

#Запись «pending» старше этого — не «в полёте», а осиротевшая после сбоя процесса между
#постановкой в очередь и ответом обработчика. Досылаем её как обычную: правку человек
#сделал, а мог и не увидеть ответа — потерять её хуже, чем прислать.
ORPHAN_AFTER_S = 120
#Пары «локальная версия → боевая» нужны, только пока копия не подтянула боевую версию
#зеркалом. Две недели — с огромным запасом на любой офлайн.
VERSIONS_TTL_DAYS = 14
HTTP_TIMEOUT_S = 20.0
#Коды, при которых повтор ОСМЫСЛЕН: сеть, перегрузка, ограничитель, таймаут, 5xx.
_TRANSIENT = frozenset({0, 408, 425, 429})
#Ответ ШЛЮЗА (Caddy): само приложение недоступно — рестарт при выкладке, авария. Это
#«сервер лежит», а не «правка ядовитая»: засчитывай такие ответы против правки, и долгая
#авария отбраковала бы всю очередь по одной записи.
_GATEWAY = frozenset({502, 503, 504})
#Ошибка ПРИЛОЖЕНИЯ (500 и прочие 5xx, кроме шлюза) на одной и той же правке: столько
#попыток с растущей паузой, потом правка уходит в «не принято сервером», а очередь идёт
#дальше (исследование синка 25.09.2026, W-10). Раньше одна такая запись держала очередь
#НАВСЕГДА: досылка идёт строго по порядку и на ней останавливалась.
MAX_SERVER_ERRORS = 5
RETRY_BASE_S = 30
RETRY_MAX_S = 1800

_DDL = (
    """CREATE TABLE IF NOT EXISTS desk_outbox (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        login TEXT NOT NULL,
        method TEXT NOT NULL,
        path TEXT NOT NULL,
        query TEXT NOT NULL DEFAULT '',
        body BLOB,
        ctype TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL,
        tbl TEXT NOT NULL DEFAULT '',
        row_key TEXT NOT NULL DEFAULT '',
        base TEXT,
        local_after TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        created_epoch REAL NOT NULL DEFAULT 0,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_status INTEGER NOT NULL DEFAULT 0,
        next_at REAL NOT NULL DEFAULT 0,
        detail TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS desk_versions (
        row_key TEXT NOT NULL,
        local_ts TEXT NOT NULL,
        prod_ts TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (row_key, local_ts))""",
    """CREATE TABLE IF NOT EXISTS desk_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT '')""",
    #База правки по номеру → номер, который бой дал нашей правке (см. «ВЕРСИЯ»).
    """CREATE TABLE IF NOT EXISTS desk_seq_versions (
        row_key TEXT NOT NULL,
        base_seq INTEGER NOT NULL,
        prod_seq INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (row_key, base_seq))""",
)

#Одна досылка за раз: два потока (фоновый «пинок» и цикл синка) иначе отправили бы одну
#и ту же правку дважды, а порядок перемешался бы.
_FLUSH_LOCK = threading.Lock()
#🔒 ЗАМОК ПРИМЕНЕНИЯ (исследование синка 25.09.2026, W-07). Под ним зеркало решает, какие
#строки копии не трогать, и применяет снимок боя; под ним же правка встаёт в очередь.
#Без него решение и применение разделяло окно: правка вставала в очередь и ложилась в
#копию уже ПОСЛЕ того, как зеркало посчитало защищённые строки, — и зеркало тут же
#затирало её старым серверным значением.
#⚠️ Досылка этот замок НЕ берёт: она ходит в сеть до 20 с на запись, и человек, нажавший
#«Сохранить», ждал бы её. От досылки зеркало защищает другое правило — «не откатывать
#ниже версии, которую бой уже принял от нас» (`mirror_guard()['sent']`).
APPLY_LOCK = threading.Lock()
_KICK_LOCK = threading.Lock()
_kick_thread = None
_kick_again = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _engine():
    """Движок ТЕКУЩЕЙ копии. Берём в момент вызова, а не при импорте: при смене
    пользователя `app.db.rebind` заменяет движок, и сохранённая ссылка писала бы в
    копию прежнего человека."""
    from desktop import local_api
    local_api.prepare_env()
    from app import db as _db
    return _db.engine


@contextmanager
def _tx():
    """Транзакция на текущей копии; таблицы очереди заводятся при каждом входе.

    `CREATE TABLE IF NOT EXISTS` стоит микросекунды, а кэш «уже заведено» ошибся бы
    ровно после стирания файла копии (смена владельца), когда таблиц снова нет."""
    from sqlalchemy import text
    with _engine().begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
        #Колонка, добавленная после первых копий с очередью: CREATE TABLE IF NOT EXISTS
        #существующую таблицу не меняет (тот же урок, что `create_all` на сервере).
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(desk_outbox)"))}
        if "next_at" not in cols:
            conn.execute(text("ALTER TABLE desk_outbox ADD COLUMN next_at REAL NOT NULL "
                              "DEFAULT 0"))
        if "base_seq" not in cols:
            #NULL — номер неизвестен (строка из копии до 4.1 или ключ не виден): тогда
            #досылается только прежняя база по времени.
            conn.execute(text("ALTER TABLE desk_outbox ADD COLUMN base_seq INTEGER"))
        yield conn


def _rows(conn, sql: str, **params) -> list:
    from sqlalchemy import text
    return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def _exec(conn, sql: str, **params):
    from sqlalchemy import text
    return conn.execute(text(sql), params)


# ── постановка в очередь ─────────────────────────────────────────────────────────────
def _local_seq(conn, table: str, key: str):
    """Номер изменения строки в копии: 0 — строки нет, None — номер неизвестен.

    Строка есть, а номер 0 — это копия до 4.1 (строку привезло зеркало по времени).
    Выдать такой 0 за «строки не было» нельзя: бой счёл бы любую правку конфликтом."""
    if not table or not key:
        return None
    try:
        from app.models import SYNC_MODELS
        from app.db import _ddl_ident
        model = SYNC_MODELS.get(table)
        if model is None:
            return None
        pk = list(model.__table__.primary_key.columns)[0].name
        rows = _rows(conn, f"SELECT change_seq FROM {_ddl_ident(model.__tablename__)} "
                           f"WHERE {_ddl_ident(pk)} = :k", k=key)
    except Exception as e:      # noqa: BLE001 — без номера правка уйдёт с базой по времени
        _LOG.info(f"[outbox] номер строки не прочитался: {e}")
        return None
    if not rows:
        return 0
    return int(rows[0]["change_seq"] or 0) or None


def enqueue(login: str, method: str, path: str, query: str, body: bytes,
            ctype: str) -> int:
    """Поставить правку в очередь ДО обработчика. Возвращает номер записи."""
    from desktop import route_policy
    spec = route_policy.replay_spec(method, path)
    #Под замком применения: пока зеркало решает и применяет, новая правка ждёт (обычно
    #миллисекунды) — иначе оно затёрло бы её, не зная о ней (W-07).
    with APPLY_LOCK:
        with _tx() as c:
            key = route_policy.row_key_hint(method, path, body)
            #База — ДО обработчика (он поменяет строку): так и «осиротевшая» правка
            #уйдёт со своей базой (W-14).
            base_seq = _local_seq(c, spec.get("table", ""), key) if spec.get("base") else None
            res = _exec(c, """INSERT INTO desk_outbox (login, method, path, query, body,
                              ctype, state, tbl, row_key, base, base_seq, created_at,
                              created_epoch)
                              VALUES (:l, :m, :p, :q, :b, :ct, 'pending', :t, :k, NULL,
                                      :bs, :ca, :ce)""",
                        l=login, m=(method or "").upper(), p=path, q=query or "",
                        b=bytes(body or b""), ct=ctype or "", t=spec.get("table", ""),
                        k=key, bs=base_seq, ca=_now(), ce=time.time())
            return int(res.lastrowid)


def mark_ready(seq: int, response: dict) -> None:
    """Обработчик копии ответил 2xx — правка готова к досылке.

    Из ответа берём ключ строки и версии до/после. У создания занятия в тело досылки
    дописываем id, выданный копией: иначе бой завёл бы занятие под ДРУГИМ id, и оценки,
    выставленные к нему офлайн, досылались бы к несуществующему на бою занятию. Там, где
    обработчик штампует запись текущим периодом (`term`), дописываем и период, названный
    копией: бой сверит его со своим и откажет, если семестр успел смениться (W-08)."""
    from desktop import route_policy
    response = response if isinstance(response, dict) else {}
    with _tx() as c:
        rows = _rows(c, "SELECT * FROM desk_outbox WHERE seq = :s", s=seq)
        if not rows:
            return
        it = rows[0]
        spec = route_policy.replay_spec(it["method"], it["path"])
        row_key = str(response.get("id") or "")
        base = None
        base_seq = it.get("base_seq")
        if spec.get("base"):
            #'' — строки у человека не было; бой различает это от «ключа нет вовсе».
            base = str(response.get("base_updated_at") or "")
            if "base_seq" in response:
                #Обработчик копии знает строку точно (ключ мог быть не виден в запросе).
                bs = response.get("base_seq")
                base_seq = None if bs is None else int(bs)
        body = it["body"]
        extra = {}
        if spec.get("create") and row_key:
            extra["id"] = row_key
        if spec.get("term") and response.get("year") and response.get("semester"):
            extra["year"] = str(response["year"])
            extra["semester"] = int(response["semester"])
        if extra:
            try:
                data = json.loads(bytes(body or b"") or b"{}")
            except ValueError:
                data = None
            if isinstance(data, dict):
                for k, v in extra.items():
                    if not data.get(k):
                        data[k] = v
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        _exec(c, """UPDATE desk_outbox SET state = 'ready', row_key = :k, base = :b,
                    base_seq = :bs, local_after = :la, body = :body WHERE seq = :s""",
              k=row_key or it["row_key"], b=base, bs=base_seq,
              la=str(response.get("updated_at") or ""), body=body, s=seq)


def drop(seq: int) -> None:
    """Обработчик копии отказал — правки не было, досылать нечего."""
    with _tx() as c:
        _exec(c, "DELETE FROM desk_outbox WHERE seq = :s AND state = 'pending'", s=seq)


# ── состояние для интерфейса и зеркала ───────────────────────────────────────────────
def counts(login: str) -> dict:
    """Сколько правок ждут отправки, в конфликте и отвергнуты — для значка синка."""
    try:
        with _tx() as c:
            rows = _rows(c, """SELECT state, COUNT(*) AS n FROM desk_outbox
                               WHERE login = :l GROUP BY state""", l=login or "")
    except Exception as e:      # noqa: BLE001 — значок не должен ронять страницу
        _LOG.warning(f"[outbox] состояние очереди не прочиталось: {e}")
        return {"available": False, "pending": 0, "conflicts": 0, "rejected": 0}
    by = {r["state"]: int(r["n"]) for r in rows}
    return {"available": True,
            "pending": by.get("pending", 0) + by.get("ready", 0),
            "conflicts": by.get("conflict", 0),
            "rejected": by.get("rejected", 0)}


def pending_keys(login: str = "") -> set:
    """{(таблица, ключ строки)} — строки, которые зеркалу трогать нельзя: по ним в очереди
    есть правка (ещё не дошла, в конфликте или отвергнута и не разобрана)."""
    try:
        with _tx() as c:
            sql = "SELECT tbl, row_key FROM desk_outbox WHERE row_key != ''"
            if login:
                sql += " AND login = :l"
            rows = _rows(c, sql, l=login)
    except Exception as e:      # noqa: BLE001
        _LOG.warning(f"[outbox] ключи ожидающих правок не прочитались: {e}")
        return set()
    return {(r["tbl"], r["row_key"]) for r in rows}


def mirror_guard(login: str = "") -> dict:
    """Что зеркалу нельзя трогать. Зовётся ПОД `APPLY_LOCK` (исследование синка
    25.09.2026, W-07):

      keys      {(таблица, ключ)} — по строке есть правка в очереди (ещё не дошла, в
                конфликте или отвергнута и не разобрана);
      in_flight есть правка «в полёте», ключ которой ещё неизвестен (обработчик копии не
                ответил) — применять снимок сейчас нельзя вовсе, повторим следующим циклом;
      sent      {ключ: боевая версия} — наши правки, уже принятые боем. Снимок, снятый ДО
                их досылки, старше и не имеет права их откатить.

    ⚠️ Порядок чтения значим: сначала очередь, потом версии. Досылка удаляет запись из
    очереди и заносит версию ОДНОЙ транзакцией, поэтому правка, прочитанная «ещё в
    очереди», защищена ключом, а «уже досланная» — версией; проскочить между ними нельзя."""
    edge = time.time() - ORPHAN_AFTER_S
    with _tx() as c:
        sql = "SELECT tbl, row_key, state, created_epoch FROM desk_outbox"
        if login:
            sql += " WHERE login = :l"
        queue = _rows(c, sql, l=login)
        sent_rows = _rows(c, """SELECT row_key, MAX(prod_ts) AS prod_ts FROM desk_versions
                                GROUP BY row_key""")
        seq_rows = _rows(c, """SELECT row_key, MAX(prod_seq) AS prod_seq
                               FROM desk_seq_versions GROUP BY row_key""")
    keys = {(r["tbl"], r["row_key"]) for r in queue if r["row_key"]}
    in_flight = any(r["state"] == "pending" and not r["row_key"]
                    and float(r["created_epoch"] or 0) >= edge for r in queue)
    sent = {r["row_key"]: r["prod_ts"] for r in sent_rows if r["row_key"] and r["prod_ts"]}
    #Тот же смысл по номеру: снимок строки с номером НИЖЕ этого снят до нашей досылки.
    sent_seq = {r["row_key"]: int(r["prod_seq"] or 0) for r in seq_rows
                if r["row_key"] and r["prod_seq"]}
    return {"keys": keys, "in_flight": in_flight, "sent": sent, "sent_seq": sent_seq}


def has_unsent(login: str = "") -> bool:
    """Есть ли у человека правки, которых бой ещё не видел (включая неразобранные)."""
    n = counts(login)
    return bool(n["pending"] or n["conflicts"] or n["rejected"])


def problems(login: str) -> list:
    """Конфликты и отказы — для экрана «Что не ушло на сервер»."""
    with _tx() as c:
        rows = _rows(c, """SELECT seq, method, path, body, state, tbl, row_key, created_at,
                                  last_status, detail FROM desk_outbox
                           WHERE login = :l AND state IN ('conflict', 'rejected')
                           ORDER BY seq""", l=login or "")
    out = []
    for r in rows:
        try:
            sent = json.loads(bytes(r.pop("body") or b"") or b"{}")
        except ValueError:
            sent = {}
        try:
            detail = json.loads(r.get("detail") or "{}")
        except ValueError:
            detail = {"message": r.get("detail") or ""}
        r["sent"] = sent if isinstance(sent, dict) else {}
        r["detail"] = detail
        out.append(r)
    return out


def resolve(seq: int, login: str, action: str) -> dict:
    """Решение человека по конфликту или отказу.

      keep_mine   — дослать ещё раз БЕЗ сверки версии (сознательно затереть серверное);
      keep_server — отказаться от своей правки: запись убирается, копия вернётся к
                    серверному состоянию полной сверкой зеркала;
      dismiss     — для отказа: «понял, убрать» (то же, что keep_server);
      retry       — только для правки, отложенной из-за ОШИБКИ СЕРВЕРА (W-10): она могла
                    быть временной. Отказ по существу (нет прав, семестр закрыт) повтором
                    не лечится, и кнопки для него нет намеренно.
    """
    with _tx() as c:
        rows = _rows(c, "SELECT * FROM desk_outbox WHERE seq = :s AND login = :l",
                     s=seq, l=login or "")
        if not rows:
            return {"ok": False, "detail": "Запись очереди не найдена"}
        it = rows[0]
        if action == "keep_mine":
            if it["state"] != "conflict":
                return {"ok": False, "detail": "Повторить можно только конфликт"}
            _exec(c, """UPDATE desk_outbox SET state = 'ready', base = NULL, base_seq = NULL,
                        detail = '' WHERE seq = :s""", s=seq)
            return {"ok": True, "flush": True}
        if action == "retry":
            if it["state"] != "rejected" or int(it["last_status"] or 0) < 500:
                return {"ok": False, "detail": "Повторить можно только правку, отложенную "
                                               "из-за ошибки сервера"}
            _exec(c, """UPDATE desk_outbox SET state = 'ready', attempts = 0, next_at = 0,
                        detail = '' WHERE seq = :s""", s=seq)
            return {"ok": True, "flush": True}
        if action in ("keep_server", "dismiss"):
            _exec(c, "DELETE FROM desk_outbox WHERE seq = :s", s=seq)
            _set_state(c, "rebuild_mirror", "1")
            return {"ok": True, "rebuild": True}
    return {"ok": False, "detail": f"Неизвестное действие: {action}"}


def _set_state(conn, key: str, value: str) -> None:
    _exec(conn, """INSERT INTO desk_state (key, value) VALUES (:k, :v)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""", k=key, v=value)


def take_rebuild_request() -> bool:
    """Просил ли кто-то полной сверки зеркала (после отказа от своей правки). Сбрасывает."""
    try:
        with _tx() as c:
            rows = _rows(c, "SELECT value FROM desk_state WHERE key = 'rebuild_mirror'")
            if rows and rows[0]["value"] == "1":
                _set_state(c, "rebuild_mirror", "")
                return True
    except Exception as e:      # noqa: BLE001
        _LOG.warning(f"[outbox] признак сверки не прочитался: {e}")
    return False


def request_rebuild() -> None:
    """Попросить полной сверки зеркала (не удалась сейчас — повторится)."""
    try:
        with _tx() as c:
            _set_state(c, "rebuild_mirror", "1")
    except Exception as e:      # noqa: BLE001
        _LOG.warning(f"[outbox] признак сверки не записался: {e}")


# ── досылка ─────────────────────────────────────────────────────────────────────────
def _http_send(method: str, url: str, body: bytes, headers: dict) -> tuple:
    """(код, json). Код 0 — до сервера не дошли (сеть, TLS, таймаут)."""
    try:
        import httpx
        r = httpx.request(method, url, content=body or None, headers=headers,
                          timeout=HTTP_TIMEOUT_S)
    except Exception as e:      # noqa: BLE001 — сеть: повторим позже
        return 0, {"detail": f"{type(e).__name__}: {e}"}
    try:
        data = r.json()
    except ValueError:
        data = {"detail": (r.text or "")[:300]}
    return r.status_code, data if isinstance(data, dict) else {"detail": str(data)[:300]}


def _is_conflict(status: int, data: dict) -> bool:
    detail = (data or {}).get("detail")
    return status == 409 and isinstance(detail, dict) and detail.get("code") == "conflict"


def _mapped_base(conn, row_key: str, base):
    """Версия для сверки на бою: локальная версия прошлой НАШЕЙ правки → её боевая."""
    if base is None or not row_key or not base:
        return base
    rows = _rows(conn, """SELECT prod_ts FROM desk_versions
                          WHERE row_key = :k AND local_ts = :b""", k=row_key, b=base)
    return rows[0]["prod_ts"] if rows else base


def _mapped_base_seq(conn, row_key: str, base_seq):
    """Номер для сверки на бою: наша база → номер, который бой дал нашей же правке."""
    if base_seq is None or not row_key:
        return base_seq
    rows = _rows(conn, """SELECT prod_seq FROM desk_seq_versions
                          WHERE row_key = :k AND base_seq = :b""", k=row_key, b=int(base_seq))
    return int(rows[0]["prod_seq"]) if rows else int(base_seq)


def _promote_orphans(conn) -> None:
    """Осиротевшие `pending` (процесс упал между очередью и ответом) — в досылку."""
    _exec(conn, """UPDATE desk_outbox SET state = 'ready'
                   WHERE state = 'pending' AND created_epoch < :edge""",
          edge=time.time() - ORPHAN_AFTER_S)


def token_subject(token: str) -> str:
    """Логин из поля `sub` токена ('' — разобрать не удалось). Подпись НЕ проверяется и не
    должна: это сверка «чей токен у нас в руках», а не решение о доверии — его принимает
    сервер. Непонятный токен не повод остановить досылку, поэтому '' пропускает проверку."""
    try:
        import base64
        part = (token or "").split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return str(data.get("sub") or "")
    except Exception:      # noqa: BLE001
        return ""


def flush(login: str = "", auth=None, send=None, wait: float = 0.0) -> dict:
    """Дослать очередь на бой. Возвращает {sent, conflicts, rejected, stopped}.

    `auth()` → (адрес, токен, причина) — по умолчанию `local_api._remote_auth`;
    `send(method, url, body, headers)` → (код, json) — по умолчанию httpx. Оба подменяются
    в тестах: проверяется правило досылки, а не работает ли сегодня интернет.
    `wait` — сколько ждать, если досылка уже идёт в другом потоке (0 — не ждать)."""
    out = {"sent": 0, "conflicts": 0, "rejected": 0, "stopped": ""}
    got = _FLUSH_LOCK.acquire(timeout=wait) if wait > 0 else _FLUSH_LOCK.acquire(blocking=False)
    if not got:
        out["stopped"] = "busy"
        return out
    try:
        return _flush_locked(login, auth, send, out)
    finally:
        _FLUSH_LOCK.release()


def _flush_locked(login, auth, send, out) -> dict:
    from desktop import local_api
    login = login or local_api._session_login()
    if not login:
        out["stopped"] = "no-session"
        return out
    with _tx() as c:
        _promote_orphans(c)
        items = _rows(c, """SELECT * FROM desk_outbox WHERE login = :l
                            ORDER BY seq""", l=login)
        #Пары версий стареют: копия давно подтянула боевые версии зеркалом.
        _edge = (datetime.now(timezone.utc) - timedelta(days=VERSIONS_TTL_DAYS)).isoformat()
        _exec(c, "DELETE FROM desk_versions WHERE created_at < :edge", edge=_edge)
        _exec(c, "DELETE FROM desk_seq_versions WHERE created_at < :edge", edge=_edge)
    if not any(it["state"] == "ready" for it in items):
        return out
    base_url, token, why = (auth or local_api._remote_auth)()
    if not base_url or not token:
        out["stopped"] = why or "offline"
        return out
    #🔥 ТОКЕН ОБЯЗАН БЫТЬ ТОГО, ЧЬЯ ОЧЕРЕДЬ (28.09.2026, находка живого прогона граней).
    #После смены учётки в программе фоновый синк ещё держал клиента ПРЕЖНЕГО человека, и
    #правки преподавателя уезжали с токеном администратора: сервер отвечал «доступно
    #только для роли teacher», правка ложилась в «отвергнутые», а человек видел
    #бессмысленную причину. Чужим токеном не шлём НИЧЕГО — ждём следующего круга, когда
    #синк переключится (чинит его и `sync_runner.start`, это вторая страховка).
    owner = token_subject(token)
    if owner and owner.lower() != login.lower():
        out["stopped"] = "account-switch"
        return out
    send = send or _http_send
    held = set()          #строки, по которым более ранняя правка ждёт решения человека
    for it in items:
        key = (it["tbl"], it["row_key"])
        if it["state"] in ("conflict", "rejected"):
            if it["row_key"]:
                held.add(key)
            continue
        if it["state"] == "pending":
            #Запрос ещё обрабатывается копией. Перескочить нельзя: следующая правка
            #может от него зависеть (оценка к только что созданному занятию).
            out["stopped"] = "in-flight"
            break
        if it["row_key"] and key in held:
            continue
        if float(it.get("next_at") or 0) > time.time():
            #Повтор этой правки после ошибки сервера ещё не наступил. Перескочить её нельзя
            #— порядок держим, — поэтому ждём здесь же (W-10).
            out["stopped"] = "waiting"
            break
        body = bytes(it["body"] or b"")
        with _tx() as c:
            base = _mapped_base(c, it["row_key"], it["base"])
            #Номер — независимо от базы по времени: у «сироты» обработчик не ответил, и
            #базы по времени нет, а номер взят ещё при постановке в очередь (W-14).
            base_seq = _mapped_base_seq(c, it["row_key"], it.get("base_seq"))
        if ((base is not None or base_seq is not None)
                and (it["ctype"] or "").startswith("application/json")):
            try:
                data = json.loads(body or b"{}")
            except ValueError:
                data = None
            if isinstance(data, dict):
                if base is not None:
                    data["base_updated_at"] = base
                if base_seq is not None:
                    data["base_seq"] = base_seq
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        url = base_url.rstrip("/") + it["path"] + (f"?{it['query']}" if it["query"] else "")
        headers = {"Authorization": f"Bearer {token}", "X-Client": "web"}
        if it["ctype"]:
            headers["Content-Type"] = it["ctype"]
        status, data = send(it["method"], url, body, headers)
        with _tx() as c:
            if 200 <= status < 300:
                _exec(c, "DELETE FROM desk_outbox WHERE seq = :s", s=it["seq"])
                prod_ts = str((data or {}).get("updated_at") or "")
                if it["row_key"] and it["local_after"] and prod_ts:
                    _exec(c, """INSERT OR REPLACE INTO desk_versions
                                (row_key, local_ts, prod_ts, created_at)
                                VALUES (:k, :lt, :pt, :ca)""",
                          k=it["row_key"], lt=it["local_after"], pt=prod_ts, ca=_now())
                try:
                    prod_seq = int((data or {}).get("change_seq") or 0)
                except (TypeError, ValueError):
                    prod_seq = 0
                if it["row_key"] and prod_seq:
                    #Ключ — наша ИСХОДНАЯ база: следующая правка той же строки, сделанная
                    #до того, как зеркало привезло этот номер, стоит на той же базе.
                    #Создание (базы нет) — под 0: копия зовёт так «строки не было».
                    _exec(c, """INSERT INTO desk_seq_versions
                                (row_key, base_seq, prod_seq, created_at)
                                VALUES (:k, :b, :p, :ca)
                                ON CONFLICT(row_key, base_seq) DO UPDATE SET
                                  prod_seq = MAX(prod_seq, excluded.prod_seq),
                                  created_at = excluded.created_at""",
                          k=it["row_key"], b=int(it.get("base_seq") or 0), p=prod_seq,
                          ca=_now())
                out["sent"] += 1
                continue
            if status == 401:
                out["stopped"] = "expired"
                break
            if status in _TRANSIENT or status in _GATEWAY:
                #Сеть или сервер недоступен целиком: правка ни при чём, попыток не считаем.
                _exec(c, "UPDATE desk_outbox SET last_status = :st WHERE seq = :s",
                      st=status, s=it["seq"])
                out["stopped"] = "offline" if status == 0 else f"server {status}"
                break
            if status >= 500:
                n = int(it["attempts"] or 0) + 1
                if n < MAX_SERVER_ERRORS:
                    _exec(c, """UPDATE desk_outbox SET attempts = :n, last_status = :st,
                                next_at = :na WHERE seq = :s""",
                          n=n, st=status, s=it["seq"],
                          na=time.time() + min(RETRY_BASE_S * 2 ** (n - 1), RETRY_MAX_S))
                    out["stopped"] = f"server {status}"
                    break
                #🔥 Ядовитая правка: сервер падает именно на ней. Откладываем её на экран
                #«Что не ушло», а очередь идёт дальше (W-10).
                _exec(c, """UPDATE desk_outbox SET state = 'rejected', attempts = :n,
                            last_status = :st, detail = :d WHERE seq = :s""",
                      n=n, st=status, s=it["seq"],
                      d=json.dumps({"message": (
                          f"Сервер {n} раз подряд ответил ошибкой {status} на эту правку. "
                          "Она отложена, чтобы не держать остальные; её можно повторить.")},
                          ensure_ascii=False))
                out["rejected"] += 1
                if it["row_key"]:
                    held.add(key)
                continue
            state = "conflict" if _is_conflict(status, data) else "rejected"
            _exec(c, """UPDATE desk_outbox SET state = :state, attempts = attempts + 1,
                        last_status = :st, detail = :d WHERE seq = :s""",
                  state=state, st=status, s=it["seq"],
                  d=json.dumps((data or {}).get("detail", data), ensure_ascii=False)[:4000])
            out["conflicts" if state == "conflict" else "rejected"] += 1
            if it["row_key"]:
                held.add(key)
    if out["sent"] or out["conflicts"] or out["rejected"]:
        _LOG.info(f"[outbox] досылка: ушло {out['sent']}, конфликтов {out['conflicts']}, "
                  f"отвергнуто {out['rejected']}"
                  + (f", остановка: {out['stopped']}" if out["stopped"] else ""))
    return out


def kick() -> None:
    """Дослать очередь в фоне прямо сейчас (после новой правки). Не ждёт и не падает.

    Один фоновый поток на процесс: пинок во время досылки не заводит второй поток, а
    просит текущий пройти очередь ещё раз — новая правка могла встать уже после того,
    как он прочитал очередь."""
    global _kick_thread, _kick_again
    with _KICK_LOCK:
        if _kick_thread is not None and _kick_thread.is_alive():
            _kick_again = True
            return
        _kick_thread = threading.Thread(target=_kick_run, name="desk-outbox", daemon=True)
        _kick_thread.start()


def _kick_run() -> None:
    global _kick_again
    while True:
        try:
            flush(wait=30.0)
        except Exception as e:      # noqa: BLE001 — фоновая досылка не роняет программу
            _LOG.warning(f"[outbox] фоновая досылка сорвалась: {e}")
        with _KICK_LOCK:
            if not _kick_again:
                return
            _kick_again = False
