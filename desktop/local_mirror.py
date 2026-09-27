"""
local_mirror.py — наполнение ЛОКАЛЬНОЙ базы приложения копией боевой.

Зачем. Десктоп поднимает у себя настоящее серверное приложение (`desktop/local_api.py`), и
на нём же работает общий Vue-интерфейс. Но своя база у этого приложения пустая, поэтому
без зеркала интерфейс открылся бы, а данных в нём не было. Зеркало — то, что делает
переход на общий интерфейс совместимым с offline-first: один раз скачали, дальше журнал
открывается без сети.

━━ ПОЧЕМУ НЕ ЧЕРЕЗ HTTP `/sync/push` ━━
Казалось бы, проще всего: взять `/sync/pull` с боевого и отдать его в `/sync/push`
локального. Не работает, и не по мелочи:
  • `/sync/push` ограничен ролью (`PUSH_SCOPE`): студент не вправе писать пользователей
    и группы, и зеркало у него вышло бы дырявым — ровно те справочники, без которых
    журнал пуст, и не доехали бы;
  • push ШТАМПУЕТ свою метку `updated_at`. Для копии это яд: метка — часы механизма
    LWW, и переписав её локальным временем, мы бы навсегда рассинхронизировали копию
    с оригиналом (следующая дельта считала бы наши строки новее серверных);
  • push попутно шлёт уведомления о новых ДЗ — на бою они уже разосланы, второй раз
    не нужно.

Поэтому зеркало пишет в локальную базу НАПРЯМУЮ. Важно: это НЕ вторая реализация
бизнес-логики (её мы дублировать не имеем права — см. историю с классификатором
Вектора). Здесь нет ни расчёта оценок, ни прав, ни уведомлений: только построчное
копирование готовых записей, отданных сервером. Вся логика по-прежнему живёт в одном
месте — в серверном приложении, которое эту копию потом и обслуживает.

━━ ГРАНИЦЫ ━━
Копия ЧИТАЕТСЯ, но не является источником правды. ⚠️ Здесь было написано «правки уходят
на боевой сервер обычным синком десктопа» — это было неправдой с удаления Qt (аудит
22.09.2026, F-02): интерфейс пишет в ЭТУ копию, а старый синк собирал правки из другой
базы. Теперь правки журнала уходят очередью `desktop/desk_outbox.py`, остальные записи
пересылаются на бой сразу (`desktop/route_policy.py`).
Зеркало не спорит с оригиналом, с одним исключением: строку, по которой в очереди есть
правка, оно НЕ перезаписывает (`skip`) — иначе человек видел бы, как его оценка
«откатилась», пока правка ещё не дошла до боя.

━━ ГОНКИ (исследование синка 25.09.2026, W-07) ━━
Снимок качается ВНЕ замка (сеть — до 45 с), а решается и применяется ПОД замком
`desk_outbox.APPLY_LOCK`, под которым же правки встают в очередь. Три правила применения:
  • строка с правкой в очереди — не трогаем; правка «в полёте» без известного ключа —
    не применяем снимок вовсе (повторим следующим циклом);
  • снимок старше версии, которую бой уже принял от нас, эту строку не откатывает;
  • снимок старше уже применённого (два прохода разом) не применяется вовсе.

━━ КУРСОР — НОМЕР ИЗМЕНЕНИЯ (26.09.2026, исследование синка П7/П9/П16) ━━
С боем 4.1 зеркало идёт не «с метки времени», а «с номера изменения» (`/sync/pull?cursor=`,
серверная половина — `server/app/sync_clock.py`), страницами. Отсюда четыре правила:
  • строка копии НИКОГДА не откатывается к более старой боевой версии: номер в копии —
    последняя увиденная боевая версия, и страница с меньшим номером её не трогает;
  • удалённое на бою (журнал удалений) убирается и из копии — раньше только полной
    сверкой;
  • полная сверка — не на каждом запуске, а когда нужна: первый вход, сброс от боя
    (сменилась область видимости, вычищен журнал удалений, база восстановлена из копии),
    просьба очереди и раз в неделю (`FULL_EVERY_DAYS`). Прежнее поведение — переменной
    `GRADEBOOK_MIRROR_FULL_EACH_START=1` (решает `sync_runner`);
  • полная сверка идёт СТРАНИЦАМИ и в конце убирает всё, чего не увидела.
Бой до 4.1 параметр `cursor` не знает и отвечает по-старому — тогда зеркало идёт прежним
путём по времени (`_legacy_*`), ничего не ломая.
"""
import os
import threading
from datetime import datetime, timedelta, timezone

import log

_LOG = log.get("local_mirror")

#Ключ, под которым в локальной базе лежит метка последней успешной синхронизации.
#Держим ВНУТРИ той же базы, а не в настройках приложения: метка и данные обязаны
#переезжать/удаляться вместе, иначе после ручного удаления файла базы дельта решит,
#что всё уже скачано, и копия останется пустой навсегда.
_WATERMARK_KEY = "local_mirror_since"
#Состояние курсора — там же, в копии (переезжает и стирается вместе с данными).
_CURSOR_KEY = "local_mirror_cursor"
_SCOPE_KEY = "local_mirror_scope"
_EPOCH_KEY = "local_mirror_epoch"
_FULL_AT_KEY = "local_mirror_full_at"
#Каким протоколом шли в последний раз: "seq" (бой 4.1+) или "time" (бой до 4.1).
_PROTOCOL_KEY = "local_mirror_protocol"
_STATE_KEYS = (_WATERMARK_KEY, _CURSOR_KEY, _SCOPE_KEY, _EPOCH_KEY, _FULL_AT_KEY,
               _PROTOCOL_KEY)

#Полная сверка раз в неделю — страховка на случай, которого протокол не предусмотрел.
FULL_EVERY_DAYS = 7
PAGE_LIMIT = 2000
#Потолок страниц за проход: сорок миллионов строк — заведомо больше любого колледжа, но
#ошибка протокола не превратит проход в бесконечный цикл.
MAX_PAGES = 20000

#🔒 Один проход зеркала за раз на процесс (исследование синка П3.4). Цикл синка, фоновый
#проход после записи и вход иначе тянули бы страницы параллельно, и более старая страница
#могла лечь поверх более новой.
_PASS_LOCK = threading.Lock()
PASS_WAIT_S = 60


def _local_session():
    """Сессия ЛОКАЛЬНОЙ базы (той, что обслуживает локальное приложение).

    `prepare_env` обязателен и здесь: без него `app.db` открыл бы базу разработчика, и
    зеркало наполняло бы НЕ ТОТ файл — незаметно, потому что ошибок при этом не будет."""
    from desktop import local_api
    local_api.prepare_env()
    from app.db import SessionLocal          # noqa: WPS433 — server-пакет уже в sys.path
    return SessionLocal()


def _get_watermark(db) -> str:
    from app.models import ConfigKV
    row = db.get(ConfigKV, _WATERMARK_KEY)
    return (row.value if row is not None else "") or ""


def _set_watermark(db, value: str) -> None:
    _set(db, _WATERMARK_KEY, value)


def _get(db, key: str) -> str:
    from app.models import ConfigKV
    row = db.get(ConfigKV, key)
    return str((row.value if row is not None else "") or "")


def _set(db, key: str, value) -> None:
    from app.models import ConfigKV
    row = db.get(ConfigKV, key)
    if row is None:
        db.add(ConfigKV(key=key, value=value))
    else:
        row.value = value


def state() -> dict:
    """{cursor, scope, epoch, full_at, protocol, since} — состояние зеркала копии."""
    db = _local_session()
    try:
        raw = {k: _get(db, k) for k in _STATE_KEYS}
    finally:
        db.close()
    try:
        cursor = int(raw[_CURSOR_KEY] or 0)
    except ValueError:
        cursor = 0
    return {"cursor": cursor, "scope": raw[_SCOPE_KEY], "epoch": raw[_EPOCH_KEY],
            "full_at": raw[_FULL_AT_KEY], "protocol": raw[_PROTOCOL_KEY],
            "since": raw[_WATERMARK_KEY]}


def needs_full(st: dict = None) -> bool:
    """Нужна ли полная сверка по курсору: курсора нет или прошлой сверке больше недели."""
    st = st if st is not None else state()
    if not st.get("cursor"):
        return True
    try:
        at = datetime.fromisoformat(st.get("full_at") or "")
    except ValueError:
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - at > timedelta(days=FULL_EVERY_DAYS)


def full_at_start() -> bool:
    """Делать ли полную сверку на старте сессии программы.

    С боем 4.1 — нет: курсор, область видимости, горизонт и журнал удалений держат копию
    честной и без неё (первый вход и недельная страховка — в `needs_full`). С боем до 4.1
    — да, как раньше (§4.5): там дельта по времени не видит удалений."""
    if os.environ.get("GRADEBOOK_MIRROR_FULL_EACH_START", "") == "1":
        return True
    try:
        return state().get("protocol") == "time"
    except Exception:           # noqa: BLE001 — копии ещё нет: первый проход и так полный
        return False


def apply_changes(db, changes: dict, skip=frozenset(), sent=None, sent_seq=None) -> int:
    """Построчно вписать полученные записи в локальную базу. Возвращает число строк.

    Метки `updated_at` берём КАК ЕСТЬ — см. шапку модуля. Неизвестные модели молча
    пропускаем: сервер может уметь больше, чем знает эта сборка десктопа, и падать
    из-за этого нельзя. `skip` — {(таблица, ключ)} строк с неотправленной правкой;
    `sent` / `sent_seq` — {ключ: боевая версия / номер} наших уже принятых боем правок.

    🔑 Номер изменения в копии — последняя увиденная БОЕВАЯ версия строки. Страница с
    меньшим номером строку не трогает: иначе проход, начатый раньше, откатил бы то, что
    уже привёз более поздний (и следующая правка этой клетки ушла бы со старой базой)."""
    from app.models import SYNC_MODELS
    sent = sent or {}
    sent_seq = sent_seq or {}
    journal = _journal_tables() if (sent or sent_seq) else frozenset()
    total = 0
    for name, items in (changes or {}).items():
        model = SYNC_MODELS.get(name)
        if model is None or not isinstance(items, list):
            continue
        pk = list(model.__table__.primary_key.columns)[0].name
        cols = {c.name for c in model.__table__.columns}
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item.get(pk)
            if not key or (name, key) in skip:
                continue
            #Бой уже принял нашу правку этой строки с версией НОВЕЕ присланной: снимок
            #снят до досылки и откатил бы её (W-07). Сравниваем две метки ОДНОГО сервера.
            inc_seq = _as_int(item.get("change_seq"))
            if name in journal:
                if inc_seq and inc_seq < sent_seq.get(key, 0):
                    continue
                if not inc_seq and (item.get("updated_at") or "") < (sent.get(key) or ""):
                    continue
            if inc_seq and "change_seq" in cols:
                cur = db.get(model, key)
                if cur is not None and _as_int(getattr(cur, "change_seq", 0)) > inc_seq:
                    continue
            data = {k: v for k, v in item.items() if k in cols}
            #merge, а не «db.get + add/update»: он сам решает «вставить или обновить».
            #flush СРАЗУ и намеренно: до сброса новая строка не попадает в карту
            #объектов сессии, и следующий merge того же id завёл бы ВТОРУЮ вставку —
            #падение по уникальности ключа. Стоимость нулевая: INSERT всё равно один,
            #меняется только момент его отправки.
            db.merge(model(**data))
            db.flush()
            total += 1
    return total


def _as_int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def apply_removed(db, removed: dict, skip=frozenset()) -> int:
    """Убрать из копии строки, удалённые на бою (журнал удалений, `sync_deletes`).

    Строку с неотправленной правкой не трогаем — как и при применении: правку решает
    очередь, а не зеркало. Возвращает число убранных строк."""
    from app.models import SYNC_MODELS
    total = 0
    for name, keys in (removed or {}).items():
        model = SYNC_MODELS.get(name)
        if model is None or not isinstance(keys, list):
            continue
        pk_col = list(model.__table__.primary_key.columns)[0]
        gone = [k for k in keys if k and (name, k) not in skip]
        for i in range(0, len(gone), 500):
            total += db.query(model).filter(pk_col.in_(gone[i:i + 500])).delete(
                synchronize_session=False) or 0
    if total:
        db.flush()
    return total


def _supports_cursor(client) -> bool:
    return callable(getattr(client, "pull_page", None))


def mirror_once(client=None) -> dict:
    """Один проход зеркала: дельта по курсору (или полная сверка, если курсора нет).

    Возвращает {ok, rows, removed, cursor|since, error} и признаки `deferred` (правка в
    полёте — повторим), `busy` (другой проход уже идёт), `full` (это была полная сверка)."""
    if client is None:
        client = _default_client()
    if client is None:
        return {"ok": False, "rows": 0, "since": "", "error": "нет активной сессии с сервером"}
    if not _supports_cursor(client):
        return _legacy_mirror_once(client)
    return _with_pass_lock(lambda: _seq_pass(client, full=False))


def rebuild(client=None) -> dict:
    """Сверка «сервер = истина» для копии: полный проход, лишнее — долой (см. `_seq_pass`)."""
    if client is None:
        client = _default_client()
    if client is None:
        return {"ok": False, "rows": 0, "removed": 0, "error": "нет активной сессии с сервером"}
    if not _supports_cursor(client):
        return _legacy_rebuild(client)
    return _with_pass_lock(lambda: _seq_pass(client, full=True))


def _with_pass_lock(fn) -> dict:
    if not _PASS_LOCK.acquire(timeout=PASS_WAIT_S):
        return {"ok": True, "busy": True, "rows": 0}
    try:
        return fn()
    except Exception as e:      # noqa: BLE001 — копия цела, повторим следующим циклом
        _LOG.warning(f"[mirror] проход не удался: {e}")
        return {"ok": False, "rows": 0, "error": str(e)}
    finally:
        _PASS_LOCK.release()


def _seq_pass(client, full: bool) -> dict:
    st = state()
    if full or needs_full(st):
        return _seq_full(client, why="просьба" if full else "по расписанию")
    return _seq_delta(client, st)


def _page(client, cursor: int, scope: str, epoch: str) -> dict:
    page = client.pull_page(cursor, PAGE_LIMIT, scope, epoch) or {}
    if "cursor" not in page and not page.get("reset"):
        raise _LegacyServer()
    return page


class _LegacyServer(Exception):
    """Бой до 4.1: курсора не знает — идём прежним путём по времени."""


def _apply_page(page: dict, expect_cursor, sent_filter=None) -> dict:
    """Применить страницу под замком. {ok, rows, removed} | {deferred} | {superseded}."""
    from desktop import desk_outbox
    with desk_outbox.APPLY_LOCK:
        guard = desk_outbox.mirror_guard()
        if guard["in_flight"]:
            return {"deferred": True}
        db = _local_session()
        try:
            if expect_cursor is not None and _as_int(_get(db, _CURSOR_KEY)) != expect_cursor:
                #Курсор сдвинул кто-то другой (сторонний вызов мимо замка прохода) —
                #эта страница ему уже не нужна, а поверх новой ложиться не имеет права.
                return {"superseded": True}
            removed = apply_removed(db, page.get("removed") or {}, skip=guard["keys"])
            rows = apply_changes(db, page.get("changes") or {}, skip=guard["keys"],
                                 sent=guard["sent"], sent_seq=guard.get("sent_seq") or {})
            if expect_cursor is not None:
                _set(db, _CURSOR_KEY, str(_as_int(page.get("cursor"))))
                _set(db, _PROTOCOL_KEY, "seq")
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    return {"ok": True, "rows": rows, "removed": removed}


def _seq_delta(client, st: dict) -> dict:
    """Дельта от курсора: страницы до `more=false`, курсор двигается после каждой."""
    cursor, scope, epoch = st["cursor"], st["scope"], st["epoch"]
    rows = removed = 0
    try:
        for _ in range(MAX_PAGES):
            page = _page(client, cursor, scope, epoch)
            if page.get("reset"):
                _LOG.info(f"[mirror] бой просит полную сверку: {page['reset']}")
                return _seq_full(client, why=str(page["reset"]))
            res = _apply_page(page, expect_cursor=cursor)
            if res.get("deferred"):
                _LOG.info("[mirror] правка в полёте — страницу применим следующим циклом")
                return {"ok": True, "deferred": True, "rows": rows, "cursor": cursor}
            if res.get("superseded"):
                return {"ok": True, "superseded": True, "rows": rows, "cursor": cursor}
            rows += res["rows"]
            removed += res["removed"]
            cursor = _as_int(page.get("cursor"))
            if not page.get("more"):
                break
    except _LegacyServer:
        return _legacy_mirror_once(client)
    if rows or removed:
        _LOG.info(f"[mirror] дельта: строк {rows}, удалено {removed}, курсор {cursor}")
    return {"ok": True, "rows": rows, "removed": removed, "cursor": cursor}


def _seq_full(client, why: str = "") -> dict:
    """Полная сверка по курсору: с нуля страницами, в конце — убрать неувиденное.

    ⚠️ Страницы ложатся в копию сразу (человек видит данные, не дожидаясь конца), а
    лишнее убирается ОДНИМ шагом в конце — только когда увидено всё. Оборвалась сеть
    посередине — ничего не удалено, курсор прежний, следующий проход начнёт заново.
    ⚠️ Не удаляется: строка с правкой в очереди, строка, которую бой принял от нас уже
    ПОСЛЕ последней страницы (её номер больше итогового курсора), таблица `config`
    (там рядом с боевыми ключами лежат служебные метки копии)."""
    from app.models import SYNC_MODELS
    from desktop import desk_outbox
    for _attempt in range(3):
        cursor, scope, epoch = 0, "", ""
        seen = {name: set() for name in SYNC_MODELS}
        rows = 0
        restart = False
        try:
            for _ in range(MAX_PAGES):
                page = _page(client, cursor, scope, epoch)
                if page.get("reset"):
                    restart = True       #область видимости сменилась прямо посреди прохода
                    break
                if cursor == 0:
                    scope, epoch = str(page.get("scope") or ""), str(page.get("epoch") or "")
                #🔥 Сначала удаления страницы, потом её строки — тот же порядок, что при
                #применении. В одной странице бывают и старое удаление строки, и её новая
                #вставка (оценку стёрли, потом поставили заново): строка в таблице всегда
                #новее своего удаления. В обратном порядке живая строка считалась бы
                #«неувиденной» и стиралась бы в конце сверки (нашёл симулятор W-19).
                for name, keys in (page.get("removed") or {}).items():
                    if name in seen and isinstance(keys, list):
                        seen[name].difference_update(keys)
                for name, items in (page.get("changes") or {}).items():
                    model = SYNC_MODELS.get(name)
                    if model is None or not isinstance(items, list):
                        continue
                    pk = list(model.__table__.primary_key.columns)[0].name
                    seen[name].update(it.get(pk) for it in items if isinstance(it, dict))
                res = _apply_page(page, expect_cursor=None)
                if res.get("deferred"):
                    return {"ok": True, "deferred": True, "rows": rows, "full": True}
                rows += res["rows"]
                cursor = _as_int(page.get("cursor"))
                if not page.get("more"):
                    break
        except _LegacyServer:
            return _legacy_rebuild(client)
        if restart:
            continue
        with desk_outbox.APPLY_LOCK:
            guard = desk_outbox.mirror_guard()
            if guard["in_flight"]:
                return {"ok": True, "deferred": True, "rows": rows, "full": True}
            keep, sent_seq = guard["keys"], guard.get("sent_seq") or {}
            journal = _journal_tables()
            db = _local_session()
            try:
                removed = 0
                for name, model in SYNC_MODELS.items():
                    if name in _REBUILD_KEEP_TABLES:
                        continue
                    pk_col = list(model.__table__.primary_key.columns)[0]
                    gone = [k for (k,) in db.query(pk_col).all()
                            if k not in seen[name] and (name, k) not in keep
                            and not (name in journal and sent_seq.get(k, 0) > cursor)]
                    for i in range(0, len(gone), 500):
                        db.query(model).filter(pk_col.in_(gone[i:i + 500])).delete(
                            synchronize_session=False)
                    removed += len(gone)
                _set(db, _CURSOR_KEY, str(cursor))
                _set(db, _SCOPE_KEY, scope)
                _set(db, _EPOCH_KEY, epoch)
                _set(db, _FULL_AT_KEY, datetime.now(timezone.utc).isoformat())
                _set(db, _PROTOCOL_KEY, "seq")
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        _LOG.info(f"[mirror] полная сверка ({why}): строк {rows}, убрано лишних {removed}, "
                  f"курсор {cursor}")
        return {"ok": True, "rows": rows, "removed": removed, "cursor": cursor, "full": True}
    return {"ok": False, "rows": 0, "full": True,
            "error": "область видимости менялась трижды подряд — сверка отложена"}


def _legacy_mirror_once(client) -> dict:
    """Один цикл зеркалирования ПО ВРЕМЕНИ (бой до 4.1). Возвращает {ok, rows, since, error}.

    `client` — готовый SyncClient (по умолчанию собирается из текущей сессии). Дельта:
    просим только то, что новее сохранённой метки, поэтому повторные вызовы дёшевы."""
    result = {"ok": False, "rows": 0, "since": "", "error": ""}
    try:
        db = _local_session()
        try:
            since = _get_watermark(db)
        finally:
            db.close()
        payload = client.pull(since)          #сеть — вне замка
        changes = (payload or {}).get("changes", {}) or {}
        server_time = (payload or {}).get("server_time") or since
        from desktop import desk_outbox
        with desk_outbox.APPLY_LOCK:
            guard = desk_outbox.mirror_guard()
            if guard["in_flight"]:
                result.update(ok=True, deferred=True, since=since)
                _LOG.info("[mirror] правка в полёте — снимок применим следующим циклом")
                return result
            db = _local_session()
            try:
                current = _get_watermark(db)
                if current and server_time and current > server_time:
                    #Другой проход уже применил снимок НОВЕЕ этого (W-07): наш старше и
                    #откатил бы свежие строки. Терять нечего — всё, что в нём есть, уже
                    #лежит в копии в более новом виде.
                    result.update(ok=True, superseded=True, since=current)
                    return result
                rows = apply_changes(db, changes, skip=guard["keys"], sent=guard["sent"])
                #Метку двигаем ТОЛЬКО после успешного применения: оборвались на середине —
                #следующий заход просто скачает тот же кусок заново (запись идемпотентна),
                #а вот сдвинутая заранее метка потеряла бы данные безвозвратно.
                _set_watermark(db, server_time)
                _set(db, _PROTOCOL_KEY, "time")
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        result.update(ok=True, rows=rows, since=server_time)
        _LOG.info(f"[mirror] в локальную базу перенесено записей: {rows}")
    except Exception as e:
        result["error"] = str(e)
        _LOG.warning(f"[mirror] не удалось обновить локальную копию: {e}")
    return result


def _journal_tables() -> frozenset:
    """Таблицы, которые правит журнал программы (их версии помнит очередь досылки)."""
    from desktop import route_policy
    return route_policy.replay_tables()


#Таблицы, которые полная сверка НЕ чистит. `config` хранит рядом с серверными ключами
#СОБСТВЕННЫЕ служебные метки копии (метку дельты зеркала `local_mirror_since`), а
#удалённые на бою ключи приходят надгробиями и так.
_REBUILD_KEEP_TABLES = frozenset({"config"})


def _legacy_rebuild(client) -> dict:
    """Сверка «сервер = истина» ПО ВРЕМЕНИ (бой до 4.1): полный снимок, лишнее — долой.

    Зачем. Дельта приносит изменённые строки, но НЕ убирает строки, которых на бою нет:
    занятие, созданное офлайн и отвергнутое боем (нет прав, семестр закрыт), так и
    осталось бы в журнале этой машины призраком. Прежняя сверка (`sync_engine.reconcile`)
    делала это для ДРУГОЙ базы, которую интерфейс не читает.

    ⚠️ Строки с неотправленной правкой не трогаем (`desk_outbox.mirror_guard`): полная
    сверка не имеет права стереть то, что ещё не дошло до боя, — и то, что дошло уже
    ПОСЛЕ того, как снимок был снят (W-07).
    ⚠️ Сначала снимок по сети, потом одна транзакция замены: оборвалась сеть — копия
    осталась прежней, а не пустой."""
    result = {"ok": False, "rows": 0, "removed": 0, "error": ""}
    try:
        payload = client.pull("")             #сеть — вне замка
        changes = (payload or {}).get("changes", {}) or {}
        server_time = (payload or {}).get("server_time") or ""
        from app.models import SYNC_MODELS
        from desktop import desk_outbox
        with desk_outbox.APPLY_LOCK:
            guard = desk_outbox.mirror_guard()
            if guard["in_flight"]:
                #Не ошибка: правка в полёте, сверку повторим следующим циклом.
                result.update(deferred=True)
                return result
            keep, sent = guard["keys"], guard["sent"]
            journal = _journal_tables()
            db = _local_session()
            try:
                current = _get_watermark(db)
                if current and server_time and current > server_time:
                    #Снимок старше уже применённого — сверять по нему нельзя (W-07).
                    result.update(deferred=True)
                    return result
                removed = 0
                for name, model in SYNC_MODELS.items():
                    if name in _REBUILD_KEEP_TABLES or not isinstance(changes.get(name), list):
                        continue
                    pk_col = list(model.__table__.primary_key.columns)[0]
                    on_server = {it.get(pk_col.name) for it in changes[name]
                                 if isinstance(it, dict)}
                    local_ids = [r[0] for r in db.query(pk_col).all()]
                    #Строку, которую бой принял от нас ПОСЛЕ снятия снимка, в снимке и не
                    #могло быть — это не «лишнее», а «ещё не видно» (W-07).
                    gone = [k for k in local_ids
                            if k not in on_server and (name, k) not in keep
                            and not (name in journal and server_time
                                     and (sent.get(k) or "") >= server_time)]
                    for i in range(0, len(gone), 500):
                        part = gone[i:i + 500]
                        db.query(model).filter(pk_col.in_(part)).delete(
                            synchronize_session=False)
                    removed += len(gone)
                rows = apply_changes(db, changes, skip=keep, sent=sent)
                if server_time:
                    _set_watermark(db, server_time)
                _set(db, _PROTOCOL_KEY, "time")
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
        result.update(ok=True, rows=rows, removed=removed)
        _LOG.info(f"[mirror] полная сверка: строк {rows}, убрано лишних {removed}")
    except Exception as e:      # noqa: BLE001 — копия цела, повторим следующим циклом
        result["error"] = str(e)
        _LOG.warning(f"[mirror] полная сверка не удалась: {e}")
    return result


def _default_client():
    """SyncClient текущей сессии (или None, если пользователь ещё не вошёл/нет сети).

    Цикл синка знает живой токен; если цикла нет (запись переслали на бой, а синк ещё
    не поднялся), берём ту же цепочку, что у прокси: сохранённый токен → refresh."""
    try:
        from sync.sync_runner import fresh_auth
        from sync.sync_client import SyncClient
        base, token = fresh_auth()
        if not base or not token:
            from desktop import local_api
            base, token, _why = local_api._remote_auth()
        if not base or not token:
            return None
        return SyncClient(base, token=token)
    except Exception:
        return None
