"""
versioning.py — сравнение ВЕРСИЙ строк журнала (метка `updated_at`, которую ставит сервер).

Зачем отдельный модуль (аудит 22.09.2026, находки F-03 и F-09). Вопрос «на какой версии
стоял клиент, когда правил» задаётся в двух местах — в синке десктопа (`/sync/push`) и в
записи журнала (`/web/teacher/*`, куда программа досылает офлайн-правки очередью). Две
копии сравнения разошлись бы молча и ровно там, где ошибка стоит дороже всего: одна
сторона считала бы правку свежей, другая — устаревшей.

Метка клиента по-прежнему НЕ записывается никуда (метку ставит сервер, §4.3 CLAUDE.md):
здесь она только отвечает на вопрос «с какой версии снята правка».
"""
from datetime import datetime, timezone


def version_key(ts):
    """Метка → число секунд (None — разобрать нечем).

    Разбираем, а не сравниваем строками: `isoformat()` выбрасывает нулевые микросекунды,
    а «Z» лексикографически больше «+00:00» — строковое сравнение молча ошибалось бы
    ровно на границе, где и решается «старше ли снимок»."""
    s = ts.strip() if isinstance(ts, str) else ""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if d.tzinfo is None:                   #наивную метку считаем UTC, как и весь синк
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def based_on_older_version(incoming_ts, stored_ts) -> bool:
    """Снята ли строка с версии НЕ НОВЕЕ хранимой (эхо устаревшего снимка).

    Равенство тоже «не новее»: настоящая правка клиента получает метку в момент правки,
    то есть строго позже версии, с которой он её начал. Одна из меток не разбирается —
    судить не о чем, возвращаем False, и вызывающий работает по прежнему правилу."""
    inc, cur = version_key(incoming_ts), version_key(stored_ts)
    return inc is not None and cur is not None and inc <= cur


def changed_since(stored_ts, base_ts) -> bool:
    """Изменилась ли строка ПОСЛЕ версии, на которой стоял автор правки.

    `base_ts` — версия, которую автор видел, когда правил ('' — строки у него не было).
    Разбор тот же, что у `based_on_older_version`; неразбираемая хранимая метка
    считается «изменилась» только при пустой базе: автор её не видел вовсе."""
    cur = version_key(stored_ts)
    if not (base_ts or "").strip():
        return cur is not None or bool((stored_ts or "").strip())
    base = version_key(base_ts)
    if cur is None or base is None:
        return False
    return cur > base
