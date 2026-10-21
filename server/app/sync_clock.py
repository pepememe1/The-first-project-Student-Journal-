"""
sync_clock.py — номер изменения строки (`change_seq`): курсор синка вместо времени.

━━ ЗАЧЕМ (26.09.2026, исследование синка W-02/W-03/W-14/W-16, инвариант §4.16) ━━
Дельта синка шла по времени: «отдай всё, что новее `since`». Но метку `updated_at`
ставят ДО коммита, а читатель (WAL) видит только закоммиченное. Писатель поставил метку
T1, pull начал читать в T2 > T1 и строки ещё не видит; писатель коммитит — и следующий
pull с `since=T2` её уже НИКОГДА не попросит. Нахлёст в 120 с (`PULL_LOOKBACK_S`) это
обезболивающее: транзакция длиннее нахлёста или скачок часов по-прежнему теряли строку.

Лечение — номер, который выдаёт САМА БАЗА внутри транзакции записи. Писатель в SQLite
один, поэтому порядок номеров совпадает с порядком коммитов: если клиент увидел номер N,
он увидел и всё, что меньше N. Время остаётся для людей («когда»), координатой потока
оно больше не служит.

Кто (исследование 20.10.2026): Лесли Лэмпорт, «Time, Clocks, and the Ordering of Events
in a Distributed System», 1978. Его вывод: в распределённой системе порядок событий
задаёт не физическое время, а счётчик, который растёт с каждым событием («логические
часы»). У нас случай проще лэмпортовского — писатель один (SQLite), поэтому хватает
одного общего счётчика, и он даёт не частичный, а полный порядок. Тот же приём —
`log sequence number` в WAL баз данных и offset в Kafka.

━━ КАК УСТРОЕНО ━━
• `sync_clock` — одна строка: последний номер (`seq`), горизонт журнала удалений
  (`horizon`) и метка базы (`epoch`).
• У каждой таблицы `SYNC_MODELS` колонка `change_seq` с индексом и ТРИ триггера:
  вставка и изменение берут следующий номер; удаление берёт номер и пишет строку в
  журнал удалений `sync_deletes` (без него копия не узнала бы о жёстком удалении).
• Уже лежащие строки нумеруются ОДИН раз по порядку `updated_at` (старые — меньшими).

━━ ГДЕ ТРИГГЕРОВ БЫТЬ НЕ ДОЛЖНО ━━
В ЛОКАЛЬНОЙ КОПИИ ПРОГРАММЫ (`GRADEBOOK_LOCAL_COPY=1`, ставит `desktop/local_api.py`).
Там номер значит «последняя увиденная боевая версия строки»: его приносит зеркало, а
правка в копии его не трогает — и потому он годится базой правки при досылке на бой
(W-14: часы ПК уходят из протокола). Триггер в копии переписал бы боевой номер своим
и сломал бы обе вещи сразу, причём молча.

⚠️ Триггер изменения срабатывает, когда номер НЕ поменяли (обычная правка) ИЛИ поменяли
на чужое значение (клиент прислал свой номер — на приёме он вырезается, но защита не
должна держаться на одной двери). Своя же внутренняя правка номера на текущее значение
счётчика его не зовёт — отсюда нет ни двойного счёта при вставке, ни рекурсии.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone

#Версия ТЕКСТА триггеров. Поменял тело — подними: `ensure` снимет триггеры прежних
#версий и поставит новые (`CREATE TRIGGER IF NOT EXISTS` старое тело не заменил бы).
TRIGGER_VERSION = 1

#Поля области видимости удалённой строки — по ним `/sync/pull` решает, кому можно
#сообщить её ключ (в ключе оценки лежит id студента: рассылать его всем — утечка).
#Порядок значим: так поля склеиваются в `sync_deletes.scope` и так же разбираются.
SCOPE_FIELDS = {
    "users": ("id", "login", "role", "group_name"),
    "groups": ("id", "name"),
    "subjects": ("id",),
    "lessons": ("id", "group_name", "subject"),
    "grades": ("id", "lesson_id", "student_id", "student_f", "student_n"),
    "term_grades": ("id", "student_id", "student_f", "student_n", "subject"),
    "schedule_overrides": ("id",),
    "subject_hours": ("id",),
    "student_subgroups": ("id", "student_id", "group_name", "subject"),
    "zet_thresholds": ("id",),
    "config": ("key",),
}
_SEP = "\x1f"

#Сколько живёт журнал удалений. Как у надгробий (`retention.TOMBSTONE_DAYS`): копия,
#молчавшая дольше, всё равно пересобирается целиком по горизонту.
DELETES_KEEP_DAYS = int(os.environ.get("GRADEBOOK_SYNC_DELETES_KEEP_DAYS", "180"))


def is_local_copy() -> bool:
    """Это локальная копия программы, а не бой (см. шапку)."""
    return os.environ.get("GRADEBOOK_LOCAL_COPY", "") == "1"


def _trigger_names(table: str, version: int = TRIGGER_VERSION) -> tuple:
    return tuple(f"trg_cseq_v{version}_{kind}_{table}" for kind in ("ins", "upd", "del"))


def _scope_expr(fields) -> str:
    return " || char(31) || ".join(f"ifnull(CAST(OLD.{f} AS TEXT), '')" for f in fields)


def _trigger_ddl(name: str, table: str, pk: str) -> list:
    from .db import _ddl_ident
    t, p = _ddl_ident(table), _ddl_ident(pk)
    fields = [_ddl_ident(f) for f in SCOPE_FIELDS.get(name, (pk,))]
    ins, upd, dele = _trigger_names(t)
    bump = "UPDATE sync_clock SET seq = seq + 1 WHERE id = 1;"
    cur = "(SELECT seq FROM sync_clock WHERE id = 1)"
    #SAST B608 (здесь и ниже в этой функции): это DDL триггеров. `t`, `p`, `fields` и
    #имена триггеров прошли `_ddl_ident`, `cur` и `bump` — константы этого файла.
    #Связанных параметров у CREATE TRIGGER нет вовсе, поэтому текст собирается строкой.
    stamp = f"UPDATE {t} SET change_seq = {cur} WHERE rowid = NEW.rowid;"  # nosec B608
    return [
        f"CREATE TRIGGER IF NOT EXISTS {ins} AFTER INSERT ON {t} BEGIN {bump} {stamp} END",
        (f"CREATE TRIGGER IF NOT EXISTS {upd} AFTER UPDATE ON {t} "
         f"WHEN NEW.change_seq IS OLD.change_seq OR NEW.change_seq IS NOT {cur} "
         f"BEGIN {bump} {stamp} END"),
        (f"CREATE TRIGGER IF NOT EXISTS {dele} AFTER DELETE ON {t} BEGIN {bump} "  # nosec B608
         f"INSERT INTO sync_deletes (seq, tbl, pk, scope, at) VALUES ({cur}, "
         f"'{_ddl_ident(name)}', CAST(OLD.{p} AS TEXT), {_scope_expr(fields)}, "
         f"strftime('%Y-%m-%dT%H:%M:%fZ', 'now')); END"),
    ]


def _our_triggers(conn) -> list:
    return [r[0] for r in conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'trg_cseq_%'")]


def ensure(engine) -> dict:
    """Идемпотентная миграция номера изменения. Вызывается из `db.init_db` на старте.

    Возвращает {numbered, triggers} — сколько строк пронумеровано этим запуском и стоят
    ли триггеры (для журнала старта: «пронумеровано 0» на втором запуске и есть норма)."""
    from sqlalchemy import inspect
    from .db import _ddl_ident
    from .models import SYNC_MODELS, SyncClock, SyncDelete
    SyncClock.__table__.create(bind=engine, checkfirst=True)
    SyncDelete.__table__.create(bind=engine, checkfirst=True)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    local = is_local_copy()
    numbered = 0
    with engine.begin() as conn:
        if conn.exec_driver_sql("SELECT COUNT(*) FROM sync_clock WHERE id = 1").scalar() == 0:
            conn.exec_driver_sql(
                "INSERT INTO sync_clock (id, seq, horizon, epoch) VALUES (1, 0, 0, ?)",
                (secrets.token_hex(8),))
        present = {}
        for name, model in SYNC_MODELS.items():
            table = model.__tablename__
            if table not in tables:
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if "change_seq" not in cols:
                conn.exec_driver_sql(
                    f"ALTER TABLE {_ddl_ident(table)} "
                    "ADD COLUMN change_seq INTEGER NOT NULL DEFAULT 0")
            conn.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS {_ddl_ident('ix_' + table + '_change_seq')} "
                f"ON {_ddl_ident(table)} (change_seq)")
            present[name] = model
        #Снимаем ВСЕ свои триггеры до нумерации: иначе нумерация сама бы их дёргала. В
        #копии программы они не нужны вовсе (см. шапку) — там на этом и заканчиваем.
        for trg in _our_triggers(conn):
            conn.exec_driver_sql(f"DROP TRIGGER IF EXISTS {_ddl_ident(trg)}")
        if local:
            return {"numbered": 0, "triggers": False}
        #Строки без номера (всё, что лежало до миграции) нумеруем ОДНИМ ходом по времени
        #правки: старое получает меньшие номера, поэтому курсор ведёт себя как дельта.
        todo = []
        for order, (_name, model) in enumerate(present.items()):
            t = _ddl_ident(model.__tablename__)
            #SAST B608: `t` — имя таблицы модели через `_ddl_ident` (строкой выше).
            for rowid, ts in conn.exec_driver_sql(
                    f"SELECT rowid, updated_at FROM {t} "  # nosec B608
                    "WHERE change_seq = 0 OR change_seq IS NULL"):
                todo.append((ts or "", order, rowid, t))
        if todo:
            todo.sort()
            start = conn.exec_driver_sql("SELECT seq FROM sync_clock WHERE id = 1").scalar() or 0
            by_table: dict = {}
            for i, (_ts, _o, rowid, t) in enumerate(todo, start=1):
                by_table.setdefault(t, []).append((start + i, rowid))
            for t, pairs in by_table.items():
                conn.exec_driver_sql(
                    #SAST B608: `t` — то же проверенное имя таблицы; номера — параметрами.
                    f"UPDATE {t} SET change_seq = ? WHERE rowid = ?", pairs)  # nosec B608
            conn.exec_driver_sql("UPDATE sync_clock SET seq = ? WHERE id = 1",
                                 (start + len(todo),))
            numbered = len(todo)
        for name, model in present.items():
            pk = list(model.__table__.primary_key.columns)[0].name
            for ddl in _trigger_ddl(name, model.__tablename__, pk):
                conn.exec_driver_sql(ddl)
    if numbered:
        print(f"[db] номер изменения: пронумеровано строк {numbered}")
    return {"numbered": numbered, "triggers": True}


def read(db) -> dict:
    """{seq, horizon, epoch} — закоммиченное состояние счётчика."""
    from sqlalchemy import text
    row = db.execute(text("SELECT seq, horizon, epoch FROM sync_clock WHERE id = 1")).first()
    if row is None:
        return {"seq": 0, "horizon": 0, "epoch": ""}
    return {"seq": int(row[0] or 0), "horizon": int(row[1] or 0), "epoch": row[2] or ""}


def scope_row(name: str, packed: str) -> dict:
    """Разобрать `sync_deletes.scope` обратно в словарь полей строки."""
    fields = SCOPE_FIELDS.get(name, ())
    parts = (packed or "").split(_SEP)
    return {f: (parts[i] if i < len(parts) else "") for i, f in enumerate(fields)}


def purge_deletes(db, days: int = DELETES_KEEP_DAYS) -> int:
    """Вычистить журнал удалений старше `days` и сдвинуть горизонт (W-16).

    Горизонт — наибольший вычищенный номер: копия с курсором ниже могла пропустить
    удаление и получит от `/sync/pull` просьбу пересобраться целиком. Без этого правила
    уборка журнала молча оставляла бы у давно молчавшей копии удалённые на бою строки."""
    from sqlalchemy import text
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S")
    top = db.execute(text("SELECT MAX(seq) FROM sync_deletes WHERE at != '' AND at < :c"),
                     {"c": cutoff}).scalar()
    if not top:
        return 0
    n = db.execute(text("DELETE FROM sync_deletes WHERE seq <= :s"), {"s": top}).rowcount or 0
    db.execute(text("UPDATE sync_clock SET horizon = MAX(horizon, :s) WHERE id = 1"),
               {"s": top})
    return n


#Перескок счётчика при новой метке базы. Миллиард — заведомо больше числа правок,
#которое база успеет набрать между снимком и восстановлением, и далеко до предела
#точных целых в JavaScript (2⁵³), где номер живёт у сайта и телефона.
EPOCH_GAP = 1_000_000_000


def new_epoch(db) -> str:
    """Новая метка базы — после восстановления из резервной копии (см. `SyncClock`).

    Все копии программ, сохранившие курсор со старой меткой, пересоберутся целиком:
    номера после отката выдаются заново, и прежний курсор указывал бы на чужие правки.

    🔥 И СЧЁТЧИК ПЕРЕСКАКИВАЕТ ВПЕРЁД (21.10.2026, нашла модель синхронизации). Без
    перескока номера после восстановления выдаются ПОВТОРНО: у правки, ждавшей в очереди
    программы, база — номер из прежней нумерации, и он мог совпасть с номером новой
    чужой правки той же строки. Бой сверяет «номер не менялся» — и принимал её без
    конфликта, молча затирая чужое (`_ensure_base_version`). С перескоком новые номера
    больше любого прежнего: база из прежней нумерации совпадает только с версией,
    которая и правда пережила восстановление, а в остальных случаях честный конфликт."""
    from sqlalchemy import text
    epoch = secrets.token_hex(8)
    db.execute(text("UPDATE sync_clock SET epoch = :e, seq = seq + :g WHERE id = 1"),
               {"e": epoch, "g": EPOCH_GAP})
    db.commit()
    return epoch


# ── Якорь вне базы: восстановление из копии замечается само (21.10.2026) ───────────────
# 🔥 Метка базы (`epoch`) живёт ВНУТРИ базы — и резервная копия возвращает её вместе с
# данными. Если после восстановления забыть `--new-epoch` (а забудут: восстанавливают в
# аварии, ночью, по памяти), бой выдаёт номера заново под ПРЕЖНЕЙ меткой. Программа с
# курсором 120 после отката к 100 и новых правок 101…130 пропустит 101–120 молча:
# «я их уже видела» — а это другие правки (разбор Ярослава 21.10.2026).
# Поэтому рядом с файлом базы лежит якорь — то, что клиенты УЖЕ видели: метка, наибольший
# выданный номер и длина журнала аудита. Снимок базы (`VACUUM INTO`) его не включает, и
# восстановление его не откатывает. На старте бой сверяется: база «помолодела» под той
# же меткой — значит её подменили копией, и бой сам меняет поколение (с перескоком
# номеров), громко сообщая об этом. Журнал аудита стал короче, чем был, — тоже громко:
# цепочка хешей остаётся «целой» и после отката, а исчезнувшие записи видны только так.
# Якорь поднимается при КАЖДОЙ выдаче головы, которая выше записанной. Ограничение «не
# чаще раза в 30 с» здесь было и оказалось дефектом (живая проверка 21.10.2026): старт
# службы сам пишет якорь, и всё, что клиенты получили в следующие полминуты, в него не
# попадало — восстановление «свежей» копии проходило незамеченным. Цена без ограничения —
# одна маленькая запись файла (без fsync) на рост головы; чтение файла и так на каждой.
# ⚠️ Граница остаётся одна: номера, выданные НЕ через `/sync/pull` (ответ записи оценки),
# в якорь попадают со следующим опросом любой программы. Копия программы ловит и это
# сама — по голове боя ниже своего курсора (`local_mirror`).
#Имя — СКРЫТЫЙ файл, а не «<база>.что-то»: регламент восстановления уносит битую базу
#маской `gradebook_server.db*`, и якорь с таким именем уехал бы вместе с ней.
ANCHOR_SUFFIX = ".sync-anchor.json"
#Метка «базу восстановил установщик» (`deploy/install.sh --restore-db`): на новой машине
#якоря нет вовсе, и узнать о подмене больше не из чего.
RESTORED_SUFFIX = ".restored"


def _beside_db(suffix: str) -> str:
    from . import db as _db
    url = _db.DATABASE_URL or ""
    if is_local_copy() or not url.startswith("sqlite:///") or ":memory:" in url:
        return ""
    path = url.split("sqlite:///", 1)[-1]
    folder, name = os.path.split(path)
    return os.path.join(folder, f".{name}{suffix}")


def anchor_path() -> str:
    """Путь якоря рядом с файлом базы ('' — база не файл или это копия программы)."""
    return _beside_db(ANCHOR_SUFFIX)


def restored_mark_path() -> str:
    return _beside_db(RESTORED_SUFFIX)


def _read_anchor(path: str) -> dict:
    import json
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_anchor(path: str, data: dict) -> None:
    """Атомарно: временный файл и замена. Сбой записи не роняет бой — только журнал."""
    import json
    import logging
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        logging.getLogger("gradebook.sync_clock").warning("якорь синка не записан: %s", e)


def _audit_top(conn) -> int:
    """Номер последней записи журнала аудита — по первичному ключу, без прохода таблицы.
    Удаление из середины этим не видно, но его и так ловит цепочка хешей; откат хвоста
    цепочка не ловит, а этот номер — да."""
    from sqlalchemy import text
    try:
        return int(conn.execute(text("SELECT MAX(id) FROM audit_events")).scalar() or 0)
    except Exception:      # noqa: BLE001 — таблицы ещё нет на совсем новой базе
        return 0


def touch_anchor(conn, seq: int, epoch: str) -> None:
    """Клиентам выдана голова `seq` — поднять якорь, если он отстал. Пишем только при
    росте головы (или смене поколения): опрос без новых правок файл не трогает."""
    path = anchor_path()
    if not path:
        return
    old = _read_anchor(path)
    if old.get("epoch") == epoch and int(old.get("seq") or 0) >= int(seq or 0):
        return
    _write_anchor(path, dict(old, epoch=epoch, seq=int(seq or 0), audit_top=_audit_top(conn),
                             at=datetime.now(timezone.utc).isoformat()))


def check_restore(engine) -> dict:
    """На старте: не подменили ли базу копией. {restored, audit_shrunk, epoch}.

    Признак — номер базы МЕНЬШЕ якоря, при ЛЮБОЙ метке (Полковник, 21.10.2026): после
    первого восстановления метка уже другая, и снимок, снятый ДО него, вернулся бы со своей
    прежней меткой — сравнение «метка та же» его пропускало. Ручной `--new-epoch` номер
    поднимает (перескок), поэтому за восстановление не считается. Совсем новая база на месте
    прежней (номер с нуля) тоже получит перескок — это безвредно: поколение новое и так."""
    import logging
    from sqlalchemy import text
    log = logging.getLogger("gradebook.sync_clock")
    out = {"restored": False, "audit_shrunk": False, "epoch": ""}
    path = anchor_path()
    if not path:
        return out
    with engine.begin() as conn:
        row = conn.execute(text("SELECT seq, epoch FROM sync_clock WHERE id = 1")).first()
        if row is None:
            return out
        seq, epoch = int(row[0] or 0), row[1] or ""
        audit_top = _audit_top(conn)
        anchor = _read_anchor(path)
        mark = restored_mark_path()
        by_installer = bool(mark) and os.path.exists(mark)
        if by_installer or (anchor and seq < int(anchor.get("seq") or 0)):
            epoch = secrets.token_hex(8)
            conn.execute(text("UPDATE sync_clock SET epoch = :e, seq = seq + :g WHERE id = 1"),
                         {"e": epoch, "g": EPOCH_GAP})
            seq += EPOCH_GAP
            out["restored"] = True
            log.warning("🔁 БАЗА ВОССТАНОВЛЕНА ИЗ КОПИИ (%s). Поколение сменено "
                        "автоматически (%s) — копии программ пересоберутся целиком, правки "
                        "из их очередей придут с конфликтом, а не затрут новое.",
                        "по метке установщика" if by_installer else
                        f"номер {row[0]} ниже уже выданного {anchor.get('seq')}", epoch)
            if by_installer:
                try:
                    os.remove(mark)
                except OSError as e:
                    log.warning("метка восстановления не снята: %s", e)
        if anchor and audit_top < int(anchor.get("audit_top") or 0):
            out["audit_shrunk"] = True
            log.warning("⚠️ ЖУРНАЛ БЕЗОПАСНОСТИ КОРОЧЕ, ЧЕМ БЫЛ: последняя запись №%s, а в "
                        "якоре №%s. Так бывает после восстановления из копии — записи после "
                        "снимка утрачены; цепочка хешей при этом сходится, поэтому "
                        "заметно это только здесь.", audit_top, anchor.get("audit_top"))
    _write_anchor(path, {"epoch": epoch, "seq": seq, "audit_top": audit_top,
                         "at": datetime.now(timezone.utc).isoformat()})
    out["epoch"] = epoch
    return out


if __name__ == "__main__":                  # pragma: no cover — ручной инструмент на бою
    import sys
    if "--new-epoch" not in sys.argv:
        print("Использование: python -m app.sync_clock --new-epoch  "
              "(после восстановления базы из резервной копии)")
        raise SystemExit(2)
    from .db import SessionLocal, init_db
    init_db()
    _db = SessionLocal()
    try:
        print(f"Новая метка базы: {new_epoch(_db)} — копии программ пересоберутся целиком.")
    finally:
        _db.close()
