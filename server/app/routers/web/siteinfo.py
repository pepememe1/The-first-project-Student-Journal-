"""
siteinfo.py — Инфо-панель сервера и сайта (только чтение).

Часть пакета `routers/web` (разрезан в 3.6: один файл на 4288 строк правили
62 коммита за полгода — он и был главным источником конфликтов при
одновременной работе). Общий роутер и хелперы — в `_common.py`; порядок
регистрации маршрутов задаёт `__init__.py`.
"""
from ._common import *      # noqa: F401,F403 — общий router, модели, хелперы


# СЕРВЕР И САЙТ (инфо-панель, только чтение) ──────────────────────────────────────
import time as _time                                                    # noqa: E402
#Общая строка версии продукта (корень в sys.path через webdata — тем же приёмом, что
#`vector_nlu` в _common.py). Литерала здесь больше нет: он дважды отставал от релиза.
import desktop_update                                                   # noqa: E402
_SERVER_START_TS = _time.time()   #≈ старт процесса (web.py грузится при старте)


@router.get("/admin/server-info")
def admin_server_info(request: Request = None,
                      _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Статус сервера/сайта для веб-вкладки «Сервер»: адрес, версия, тип БД, шифрование
    ПДн (152-ФЗ), ГОСТ-бэкенд, кто онлайн, учебный период, аптайм. Только чтение —
    хостингом управляют на самой машине сервера (раздел «Сервер», §16 — по SSH), из
    браузера это не трогаем."""
    import os
    from ...config import DATABASE_URL, ALLOWED_ORIGINS
    from ... import gost, security, events as _events
    is_sqlite = DATABASE_URL.startswith("sqlite")
    #⚠️ НЕ os.environ: ключ может приходить из учётных данных службы или из
    #файла (см. app/secrets_source.py). Читая окружение напрямую, эта страница
    #показала бы админу «шифрование выключено» на сервере, где оно включено, —
    #то есть правдоподобную ложь ровно на экране безопасности.
    from ... import secrets_source
    db_key = secrets_source.get("GRADEBOOK_DB_KEY")
    sqlcipher = False
    if is_sqlite and db_key:
        try:
            import sqlcipher3  # noqa: F401
            sqlcipher = True
        except ImportError:
            sqlcipher = False
    bi = gost.backend_info()
    domain = (os.environ.get("GRADEBOOK_DOMAIN", "").strip()
              or (ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS and ALLOWED_ORIGINS != ["*"] else ""))
    if domain and not domain.startswith("http"):
        domain = "https://" + domain
    cfg = W.load_config(db)
    cy, cs = W.current_term(cfg)
    gost_hash = security._openssl_gost_name()
    return {
        "address": domain or (str(request.base_url).rstrip("/") if request else ""),
        #Версия берётся из ОБЩЕЙ константы (корневой desktop_update.py), а не из литерала.
        #Прежний литерал сопровождался комментарием «правь руками при каждом релизе» — и
        #дважды отставал: сначала на шесть версий («Release 3.0»), потом снова («3.6.1»
        #при 3.7). Просьба к человеку помнить о синхронизации — не механизм.
        "version": desktop_update.APP_VERSION,
        "status": "работает",
        "uptime_sec": int(_time.time() - _SERVER_START_TS),
        "db_kind": "PostgreSQL" if not is_sqlite else "SQLite",
        "db_file_encrypted": sqlcipher,          # файл БД шифруется целиком (SQLCipher AES-256)
        "pdn_field_encrypted": gost.enabled(),   # поля ПДн (телефон) шифруются «Кузнечик»
        "crypto_backend": bi.get("backend", ""),
        "crypto_algorithm": bi.get("algorithm", ""),
        "crypto_certified": bi.get("certified", False),
        "gost_hash_backend": gost_hash or "gostcrypto (pure-python)",
        #ОТКУДА взяты секреты, а не сами секреты. Нужно на приёмке и при
        #переходе на учётные данные службы: вопрос «точно ли сервер читает
        #ключ из хранилища, а не из старой переменной окружения» иначе
        #проверяется только чтением кода, то есть верой. Значения не
        #возвращаются никогда — `source_of` их не выдаёт по построению.
        "secret_sources": {name: secrets_source.source_of(name)
                           for name in secrets_source.SECRET_NAMES},
        "online_count": len(_events.online()),
        "term": {"year": cy, "semester": cs},
        "counts": {
            "students": db.query(User).filter(User.role == "student", User.deleted == False).count(),  # noqa: E712
            "teachers": db.query(User).filter(User.role == "teacher", User.deleted == False).count(),  # noqa: E712
            "groups": db.query(Group).filter(Group.deleted == False).count(),  # noqa: E712
        },
    }
