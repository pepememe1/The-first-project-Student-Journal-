"""
local_mirror.py — наполнение ЛОКАЛЬНОЙ базы приложения копией боевой.

Зачем. Десктоп поднимает у себя настоящее серверное приложение (`ui/local_api.py`), и
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
Копия ЧИТАЕТСЯ, но не является источником правды: правки по-прежнему уходят на боевой
сервер обычным синком десктопа. Поэтому конфликтов у зеркала не бывает — оно всегда
догоняет оригинал, а не спорит с ним.
"""
import log

_LOG = log.get("local_mirror")

#Ключ, под которым в локальной базе лежит метка последней успешной синхронизации.
#Держим ВНУТРИ той же базы, а не в настройках приложения: метка и данные обязаны
#переезжать/удаляться вместе, иначе после ручного удаления файла базы дельта решит,
#что всё уже скачано, и копия останется пустой навсегда.
_WATERMARK_KEY = "local_mirror_since"


def _local_session():
    """Сессия ЛОКАЛЬНОЙ базы (той, что обслуживает локальное приложение).

    `prepare_env` обязателен и здесь: без него `app.db` открыл бы базу разработчика, и
    зеркало наполняло бы НЕ ТОТ файл — незаметно, потому что ошибок при этом не будет."""
    import local_api
    local_api.prepare_env()
    from app.db import SessionLocal          # noqa: WPS433 — server-пакет уже в sys.path
    return SessionLocal()


def _get_watermark(db) -> str:
    from app.models import ConfigKV
    row = db.get(ConfigKV, _WATERMARK_KEY)
    return (row.value if row is not None else "") or ""


def _set_watermark(db, value: str) -> None:
    from app.models import ConfigKV
    row = db.get(ConfigKV, _WATERMARK_KEY)
    if row is None:
        db.add(ConfigKV(key=_WATERMARK_KEY, value=value))
    else:
        row.value = value


def apply_changes(db, changes: dict) -> int:
    """Построчно вписать полученные записи в локальную базу. Возвращает число строк.

    Метки `updated_at` берём КАК ЕСТЬ — см. шапку модуля. Неизвестные модели молча
    пропускаем: сервер может уметь больше, чем знает эта сборка десктопа, и падать
    из-за этого нельзя."""
    from app.models import SYNC_MODELS
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
            if not key:
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


def mirror_once(client=None) -> dict:
    """Один цикл зеркалирования. Возвращает {ok, rows, since, error}.

    `client` — готовый SyncClient (по умолчанию собирается из текущей сессии). Дельта:
    просим только то, что новее сохранённой метки, поэтому повторные вызовы дёшевы."""
    result = {"ok": False, "rows": 0, "since": "", "error": ""}
    try:
        if client is None:
            client = _default_client()
        if client is None:
            result["error"] = "нет активной сессии с сервером"
            return result
        db = _local_session()
        try:
            since = _get_watermark(db)
            payload = client.pull(since)
            changes = (payload or {}).get("changes", {}) or {}
            rows = apply_changes(db, changes)
            #Метку двигаем ТОЛЬКО после успешного применения: оборвались на середине —
            #следующий заход просто скачает тот же кусок заново (запись идемпотентна),
            #а вот сдвинутая заранее метка потеряла бы данные безвозвратно.
            server_time = (payload or {}).get("server_time") or since
            _set_watermark(db, server_time)
            db.commit()
            result.update(ok=True, rows=rows, since=server_time)
            _LOG.info(f"[mirror] в локальную базу перенесено записей: {rows}")
        finally:
            db.close()
    except Exception as e:
        result["error"] = str(e)
        _LOG.warning(f"[mirror] не удалось обновить локальную копию: {e}")
    return result


def _default_client():
    """SyncClient текущей сессии (или None, если пользователь ещё не вошёл/нет сети)."""
    try:
        from sync_runner import fresh_auth
        from sync_client import SyncClient
        base, token = fresh_auth()
        if not base or not token:
            return None
        return SyncClient(base, token=token)
    except Exception:
        return None
