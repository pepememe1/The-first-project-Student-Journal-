"""
local_db.py — шифрование и ПРИНАДЛЕЖНОСТЬ базы синхронизации (`vsgutu_grades.db`).

━━ ЗАЧЕМ ЭТО ПОЯВИЛОСЬ (жалоба Ярослава, 28.08.2026) ━━
«Почему я обычным DB Browser спокойно захожу в базу без пароля и вижу все данные
пользователей.» Так и было: файл был ОБЫЧНЫМ SQLite. Шифровалось только содержимое
таблицы `users` (Fernet под DPAPI, префикс `enc:`), а `students`, `grades`,
`term_grades`, `lessons`, `groups` лежали открытым текстом — ФИО, группы, предметы и
оценки читались любым просмотрщиком, в том числе с украденного или сданного в ремонт
диска. В §6 CLAUDE.md при этом стояло «ПДн на диске (десктоп) — Fernet»; верно это
было ровно для одной таблицы из семи.

Три отдельные дыры, и закрывать их надо разными средствами:

  1️⃣ **Открытые таблицы.** Лечится шифрованием ФАЙЛА ЦЕЛИКОМ (SQLCipher, тем же
     механизмом и тем же ключом устройства, что уже защищают `local_app_*.enc.db`).

  2️⃣ **Удалённая строка остаётся на диске.** SQLite не затирает освобождённые
     страницы. Реконсиляция на входе (`reset_synced_local_data`) честно делает
     `DELETE FROM grades`, но байты остаются лежать в файле до тех пор, пока страницу
     не переиспользуют. У живого файла на 3 МБ полезных данных было меньше чем на
     100 КБ — всё остальное свободные страницы с ФИО прежних аккаунтов. Логическая
     очистка от такого не спасает НИКОГДА, поэтому:
       • шифрование закрывает и свободные страницы тоже;
       • `PRAGMA secure_delete` затирает освобождаемое — он нужен именно для запуска
         БЕЗ драйвера SQLCipher, где шифрования не будет вовсе;
       • перевод на шифр идёт через `sqlcipher_export`, то есть файл ПЕРЕСОБИРАЕТСЯ
         с нуля, и свободных страниц в нём не остаётся ни одной.

  3️⃣ **Ключи `kv_store` — сами по себе персональные данные.** Значения зашифрованы,
     а ИМЕНА ключей нет, и в живом файле лежало
     `_local:my_theme:student:Загдаева|Арина|К64/2` и ещё три человека. То есть даже
     при зашифрованных значениях файл выдавал, кто работал на этой машине, из какой
     группы и в какой роли. Это тоже закрывается шифрованием файла — но ТОЛЬКО оно и
     закрывает, потому что шифровать имена ключей нельзя (по ним идёт поиск).

━━ ПРИНАДЛЕЖНОСТЬ («вошёл другой человек — базы прежнего быть не должно») ━━
Раньше файл был ОДИН на машину и накапливал следы всех, кто когда-либо входил.
Теперь в нём лежит метка владельца, и при входе другого человека файл СТИРАЕТСЯ и
заводится заново.

⚠️ **Стереть всё нельзя — часть ключей принадлежит МАШИНЕ, а не человеку.** В том же
`kv_store` живут `device_id` (по нему работает барьер устройства: потеряем — ПК
станет «новым» и потребует одобрения администратором заново), адрес сервера, состояние
анти-брутфорса и журнал аудита. Стереть журнал аудита при смене аккаунта — это вообще
подарок нарушителю: сменил пользователя и стёр след. Поэтому переносим ЯВНЫЙ БЕЛЫЙ
СПИСОК (`MACHINE_KEYS`), а не «всё, что начинается на `_local:`».

⚠️ И обратное: список именно БЕЛЫЙ, а не чёрный. Чёрный неполон всегда, а первым
забытым в нём окажется ключ вида `_local:my_theme:student:Фамилия|Имя|Группа` — то
есть ровно то, ради чего всё затевалось.
"""
import os
import sqlite3

import log

_LOG = log.get("local_db")

#Ключ, под которым в самой базе лежит отпечаток её владельца.
OWNER_KEY = "_local:db_owner"

#🔒 БЕЛЫЙ СПИСОК: что принадлежит МАШИНЕ и переживает смену пользователя.
#У каждого пункта своя причина, и ни один не «на всякий случай»:
MACHINE_KEYS = (
    "_local:device_id",         #барьер устройства; потеря = ПК снова ждёт одобрения
    "_local:device_connected",  #состояние того же барьера
    "_local:api_url",           #адрес сервера — свойство установки, а не человека
    "_local:is_host",           #роль машины в сети колледжа
    "_local:host_autostart",    #то же самое
    "_local:login_throttle",    #анти-брутфорс: сброс = обход защиты сменой аккаунта
    "_local:audit_log",         #след безопасности; стереть его сменой аккаунта нельзя
    "_local:offline_ack",       #разовое согласие на офлайн-режим, свойство установки
)

#Всё остальное — принадлежит ЧЕЛОВЕКУ и обязано уйти вместе с ним: токены
#(`api_token`, `api_refresh_token`), сохранённый вход (`session`), тема
#(`my_theme:*`), показанные подсказки (`mascot_seen:*`), несохранённые настройки
#(`pending_prefs`), список серверов администратора (`remote_servers` — там ещё и
#пароли SSH под DPAPI), кэш расписания его группы (`schedule_cache`).


def owner_hash(login: str) -> str:
    """Отпечаток владельца базы. Хеш, а не логин: имя учётной записи — тоже
    персональные данные, и класть его в базу открытым текстом незачем (ровно по этой
    же причине хешируется имя файла у `local_app_*.enc.db`)."""
    import hashlib
    return hashlib.sha256((login or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def is_plaintext(path: str) -> bool:
    """Файл — ОБЫЧНЫЙ SQLite (то есть читается кем угодно)."""
    try:
        with open(path, "rb") as f:
            return f.read(16).startswith(b"SQLite format 3")
    except OSError:
        return False


def connect(path: str, key: str = "", timeout: int = 10):
    """Соединение с базой: зашифрованное, если есть чем, обычное — если нечем.

    ⚠️ `PRAGMA key` обязан быть ПЕРВОЙ операцией соединения, до любого запроса, —
    иначе SQLCipher уже решит, что база открывается без ключа, и упадёт.
    ⚠️ `secure_delete` ставим ВСЕГДА, а не только в незашифрованном случае: он ничего
    не стоит на нашем объёме, а в запуске из исходников без драйвера остаётся
    единственным, что затирает удалённые ФИО в свободных страницах.
    """
    conn = None
    if key:
        try:
            from data import device_key
            if not device_key.is_valid(key):
                raise ValueError("ключ не 64 hex-символа")
            import sqlcipher3
            conn = sqlcipher3.connect(path, timeout=timeout)
            #Кавычки именно такие: x'…' — это СЫРЫЕ 32 байта. Без них SQLCipher
            #посчитал бы строку паролем и прогнал бы через KDF, то есть получился бы
            #ДРУГОЙ ключ, и база, зашифрованная одним способом, не открылась бы другим.
            conn.execute("PRAGMA key = \"x'%s'\"" % key)
        except Exception as e:                      # noqa: BLE001
            #Тихо откатываться на открытую базу нельзя: человек будет уверен, что его
            #данные зашифрованы. Но и не пустить его в программу тоже нельзя.
            #Компромисс — громкая запись и работа как раньше.
            _LOG.error("[local-db] зашифрованное соединение не открылось (%s) — база "
                       "работает БЕЗ шифрования", e)
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            conn = None
    if conn is None:
        conn = sqlite3.connect(path, timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA secure_delete=ON")
    except Exception as e:                          # noqa: BLE001
        _LOG.warning("[local-db] PRAGMA не применились: %s", e)
    return conn


def use_named_rows(conn) -> None:
    """Обращаться к колонкам по ИМЕНИ, а не по номеру, — на любом драйвере.

    ⚠️ `sqlite3.Row` соединению SQLCipher НЕ подходит: драйвер другой, и попытка
    отдаёт «Row() argument 1 must be sqlite3.Cursor, not sqlcipher3.dbapi2.Cursor».
    Ошибка вылезает не в момент присваивания, а на первом же чтении строки — то есть
    далеко от места, где сделано неверное предположение. Берём фабрику у ТОГО ЖЕ
    модуля, что и соединение."""
    import sys
    mod = sys.modules.get(type(conn).__module__)
    row = getattr(mod, "Row", None)
    if row is not None:
        conn.row_factory = row


def encrypt_in_place(path: str, key: str) -> bool:
    """Перевести существующую ОТКРЫТУЮ базу на шифрование. True — перевели.

    Механизм — штатный `sqlcipher_export`: открываем обычный файл драйвером SQLCipher
    (без ключа он ведёт себя как обычный SQLite), подцепляем к нему ПУСТУЮ
    зашифрованную базу и просим переложить туда всё содержимое.

    ⚠️ Побочный и главный эффект: новый файл СОБИРАЕТСЯ С НУЛЯ. Это не оптимизация —
    именно так из него исчезают свободные страницы со старыми ФИО, которые обычным
    `DELETE` не убираются никогда (см. дыру №2 в шапке модуля). Заодно файл резко
    худеет: у живого экземпляра 3 МБ занимали в основном они.

    ⚠️ Порядок «сначала проверить, потом подменить» обязателен. Подменить и потом
    обнаружить, что новый файл не открывается, значило бы потерять журнал вместе с
    офлайн-правками, которые ещё не уехали на сервер.
    """
    from data import device_key
    if not key or not device_key.is_valid(key):
        return False
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    if not is_plaintext(path):
        return False                                #уже зашифрована — работы нет

    tmp = path + ".enc.tmp"
    for leftover in (tmp, tmp + "-wal", tmp + "-shm"):
        try:
            if os.path.exists(leftover):
                os.remove(leftover)
        except OSError as e:
            _LOG.error("[local-db] не убрать остаток прошлой попытки %s: %s", leftover, e)
            return False

    before = _row_census(path, "")
    try:
        import sqlcipher3
        src = sqlcipher3.connect(path, timeout=30)
        try:
            #Журнал в основной файл: иначе часть свежих правок осталась бы в -wal и в
            #выгрузку не попала — то самое «после обновления пропали последние оценки».
            src.execute("PRAGMA journal_mode=DELETE")
            src.execute("ATTACH DATABASE ? AS gbenc KEY \"x'%s'\"" % key, (tmp,))
            src.execute("SELECT sqlcipher_export('gbenc')")
            src.execute("DETACH DATABASE gbenc")
        finally:
            src.close()
    except Exception as e:                          # noqa: BLE001
        _LOG.error("[local-db] перевод базы на шифрование не удался (%s) — файл оставлен "
                   "как есть, данные целы", e)
        _quiet_remove(tmp)
        return False

    after = _row_census(tmp, key)
    if after is None or before is None or after != before:
        _LOG.error("[local-db] зашифрованная копия не совпала с исходной (%s против %s) — "
                   "подмену НЕ делаем", after, before)
        _quiet_remove(tmp)
        return False

    try:
        os.replace(tmp, path)
    except OSError as e:
        _LOG.error("[local-db] подменить файл базы не удалось: %s", e)
        _quiet_remove(tmp)
        return False
    #Хвосты от НЕЗАШИФРОВАННОЙ базы: остались бы рядом — испортили бы новый файл, да и
    #сами содержат те же самые ФИО открытым текстом.
    for suffix in ("-wal", "-shm"):
        _quiet_remove(path + suffix)
    _LOG.info("[local-db] база переведена на шифрование (SQLCipher), %d строк перенесено",
              sum(before.values()))
    return True


def _row_census(path: str, key: str):
    """{таблица: число строк} — для сверки «ничего не потеряли». None при ошибке.

    Сверяем СОСТАВ, а не факт «файл открылся»: `sqlcipher_export` может отработать
    частично, и открывающийся файл с половиной оценок выглядел бы совершенно
    нормальным ровно до того дня, когда кто-то хватится своих оценок."""
    conn = None
    try:
        conn = connect(path, key)
        out = {}
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for n in names:
            out[n] = conn.execute('SELECT COUNT(*) FROM "%s"' % n).fetchone()[0]
        return out
    except Exception as e:                          # noqa: BLE001
        _LOG.warning("[local-db] не удалось пересчитать строки в %s: %s", path, e)
        return None
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _quiet_remove(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
        except OSError:
            pass


def read_owner(path: str, key: str) -> str:
    """Отпечаток владельца базы ('' — базы нет, метки нет или прочитать нечем)."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return ""
    conn = None
    try:
        conn = connect(path, key)
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (OWNER_KEY,)).fetchone()
        return (row[0] if row else "") or ""
    except Exception:                               # noqa: BLE001
        #Нет таблицы kv_store (совсем свежая база) или файл не открылся — это не ошибка
        #и не повод шуметь: вызывающий сам решит, что делать с пустым ответом.
        return ""
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def write_owner(path: str, key: str, login: str) -> None:
    """Проставить владельца. Значение — отпечаток (см. `owner_hash`), не логин."""
    conn = None
    try:
        conn = connect(path, key)
        conn.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO kv_store(key, value) VALUES(?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                     (OWNER_KEY, owner_hash(login)))
        conn.commit()
    except Exception as e:                          # noqa: BLE001
        _LOG.warning("[local-db] метка владельца не записана: %s", e)
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _machine_keys(path: str, key: str) -> list:
    """Значения ключей МАШИНЫ из уходящей базы — чтобы перенести их в новую."""
    conn = None
    try:
        conn = connect(path, key)
        marks = ",".join("?" for _ in MACHINE_KEYS)
        rows = conn.execute(
            "SELECT key, value FROM kv_store WHERE key IN (%s)" % marks,
            tuple(MACHINE_KEYS)).fetchall()
        return [(k, v) for k, v in rows]
    except Exception:                               # noqa: BLE001
        return []
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def adopt(path: str, key: str, login: str) -> bool:
    """Сделать базу принадлежащей `login`. True — базу пришлось стереть и завести заново.

    Три случая, и все три разные:
      • метки нет (первый запуск после обновления) — просто ставим свою и НИЧЕГО не
        трогаем. Стирать здесь было бы вредительством: в базе лежат офлайн-правки
        того, кто обновился, а причин считать их чужими нет;
      • метка совпала — работаем дальше как обычно;
      • метка ЧУЖАЯ — файл уходит целиком, вместе со свободными страницами. Данные не
        теряются: истина живёт на сервере, и следующий полный pull наполнит копию
        заново (тот же принцип, что у `local_mirror`).
    """
    if not login:
        return False
    want = owner_hash(login)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        write_owner(path, key, login)
        return False
    have = read_owner(path, key)
    if not have:
        write_owner(path, key, login)
        return False
    if have == want:
        return False

    carried = _machine_keys(path, key)
    _quiet_remove(path)

    #🔥 ФАЙЛ МОГ НЕ УДАЛИТЬСЯ, И ЭТО НЕ ТЕОРИЯ. На Windows открытый где-то ещё файл
    #не стирается вовсе (фоновая синхронизация вполне может держать соединение), а
    #`_quiet_remove` про это молчит. Без проверки дальше пошла бы самая опасная из
    #возможных развязок: мы бы записали в УЦЕЛЕВШУЮ базу прежнего человека новую
    #метку владельца — и его оценки поехали бы дальше под чужим именем, причём с
    #бумажкой «владелец сменён» в логе. Поэтому здесь проверяем результат, а не
    #намерение, и при неудаче честно вычищаем содержимое запросами.
    wiped_by_file = not os.path.exists(path)
    if not wiped_by_file:
        _LOG.warning("[local-db] файл базы удалить не удалось (занят другим процессом) — "
                     "вычищаем содержимое запросами")
        if not _wipe_contents(path, key):
            _LOG.error("[local-db] базу прежнего пользователя стереть НЕ УДАЛОСЬ — "
                       "метку владельца не меняем, чтобы его данные не оказались "
                       "подписаны чужим именем")
            return False

    conn = None
    try:
        conn = connect(path, key)
        conn.execute("CREATE TABLE IF NOT EXISTS kv_store (key TEXT PRIMARY KEY, value TEXT)")
        for k, v in carried:
            conn.execute("INSERT OR REPLACE INTO kv_store(key, value) VALUES(?, ?)", (k, v))
        conn.execute("INSERT OR REPLACE INTO kv_store(key, value) VALUES(?, ?)",
                     (OWNER_KEY, want))
        conn.commit()
    except Exception as e:                          # noqa: BLE001
        _LOG.warning("[local-db] новую базу завести не удалось: %s", e)
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    if not wiped_by_file:
        #Запросы освобождают страницы, но не укорачивают файл — а на незашифрованной
        #базе освобождённая страница это и есть читаемое ФИО. VACUUM обязателен именно
        #здесь, в отличие от ветки с удалением файла, где стирать уже нечего.
        compact(path, key)
    _LOG.info("[local-db] вошёл другой пользователь — база прежнего удалена (%s), "
              "перенесено ключей машины: %d",
              "файл целиком" if wiped_by_file else "содержимое запросами", len(carried))
    return True


def _wipe_contents(path: str, key: str) -> bool:
    """Запасной путь: вычистить базу запросами, когда файл удалить не дали.

    Сносим ТАБЛИЦЫ, а не строки: `DROP TABLE` убирает заодно индексы, а `DELETE`
    оставил бы схему с пустыми, но по-прежнему занятыми страницами. Таблицы заведёт
    заново `DBManager._init_sqlite_tables()` при следующем обращении."""
    conn = None
    try:
        conn = connect(path, key)
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for n in names:
            conn.execute('DROP TABLE IF EXISTS "%s"' % n)
        conn.commit()
        return True
    except Exception as e:                          # noqa: BLE001
        _LOG.error("[local-db] очистка запросами не удалась: %s", e)
        return False
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def compact(path: str, key: str) -> int:
    """VACUUM: пересобрать файл без свободных страниц. Возвращает, сколько байт ушло.

    ⚠️ Это НЕ косметика и не «чтобы красиво». Свободная страница — это страница с
    прежним содержимым, и пока она лежит в файле, удалённые ФИО из него никуда не
    делись. У зашифрованной базы они хотя бы зашифрованы, у незашифрованной (запуск
    из исходников без драйвера) — нет.

    ⚠️ Сжимать файл архиватором СВЕРХ этого бессмысленно: шифротекст не сжимается по
    построению (иначе он был бы предсказуем). Весь выигрыш в размере даёт именно
    VACUUM, и он же — единственный честный ответ на «сделай файл поменьше».
    """
    if not os.path.exists(path):
        return 0
    was = os.path.getsize(path)
    conn = None
    try:
        conn = connect(path, key)
        #VACUUM не работает внутри транзакции, а python-драйвер открывает её сам под
        #любой DML. Пустой уровень изоляции = «не начинай транзакцию за меня».
        conn.isolation_level = None
        conn.execute("VACUUM")
    except Exception as e:                          # noqa: BLE001
        _LOG.warning("[local-db] VACUUM не выполнен: %s", e)
        return 0
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    try:
        return max(0, was - os.path.getsize(path))
    except OSError:
        return 0


def repack_large_values(path: str, key: str) -> int:
    """Переложить УЖЕ лежащие крупные значения в сжатую форму. Сколько байт освободили.

    Зачем отдельным шагом, а не «само со временем». Сжатие включается в
    `security.encrypt_value`, то есть действует только на СЛЕДУЮЩУЮ запись значения.
    У кэша расписания следующая запись случится, когда истечёт его срок, — то есть
    файл на 2.8 МБ ещё сутки оставался бы прежним, и человек, попросивший сделать его
    меньше, никакой разницы бы не увидел. Здесь мы просто перечитываем и пишем обратно.

    ⚠️ ЗНАЧЕНИЕ, КОТОРОЕ НЕ РАСШИФРОВАЛОСЬ, ПРОПУСКАЕМ. `decrypt_value` при неудаче
    возвращает ПУСТУЮ СТРОКУ (это её давнее поведение, и оно разумно для чтения), а
    здесь такой ответ означал бы «запиши на место данных пустоту». Испортить кэш —
    полбеды, но под тем же ключом лежат журнал аудита и настройки.
    ⚠️ Пишем обратно, ТОЛЬКО если стало короче: у уже сжатого содержимого перекладка
    даёт минус, и гонять её по кругу каждый запуск незачем.
    """
    from data import security
    if not os.path.exists(path):
        return 0
    saved = 0
    conn = None
    try:
        conn = connect(path, key)
        rows = conn.execute(
            "SELECT key, value FROM kv_store WHERE length(value) >= ?",
            (security._COMPRESS_MIN,)).fetchall()
        for k, v in rows:
            if not isinstance(v, str) or v.startswith(security._ENCZ_PREFIX):
                continue
            plain = security.decrypt_value(v)
            if not plain:
                _LOG.warning("[local-db] значение «%s» не расшифровалось — оставляем как есть", k)
                continue
            packed = security.encrypt_value(plain)
            if len(packed) >= len(v):
                continue
            conn.execute("UPDATE kv_store SET value = ? WHERE key = ?", (packed, k))
            saved += len(v) - len(packed)
        conn.commit()
    except Exception as e:                          # noqa: BLE001
        _LOG.warning("[local-db] перекладка крупных значений не удалась: %s", e)
        return 0
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    if saved:
        #Без VACUUM освободившиеся страницы останутся в файле, и «файл стал меньше»
        #окажется неправдой ровно там, где её проще всего проверить — в проводнике.
        freed = compact(path, key)
        _LOG.info("[local-db] крупные значения переложены: в базе минус %d байт, "
                  "файл ужался на %d байт", saved, freed)
    return saved


def purge_plaintext_backups(backup_dir: str) -> int:
    """Убрать копии базы, снятые ДО перехода на шифрование. Возвращает их число.

    🔥 Без этого вся работа была бы театром. Копии снимаются автоматически (до 48
    штук) обычным копированием файла — значит все копии, сделанные до сегодня,
    представляют собой полные незашифрованные снимки журнала с ФИО и оценками. На
    живой машине их было две общим весом 5.9 МБ, и открывались они тем же
    просмотрщиком, что и сама база.

    ⚠️ Удаляем только ОТКРЫТЫЕ и только после того, как рабочая база уже успешно
    зашифрована (порядок вызова — на стороне `DBManager.init`). Зашифрованные копии
    остаются: они и есть смысл резервного копирования.
    """
    import glob
    if not os.path.isdir(backup_dir):
        return 0
    n = 0
    for f in glob.glob(os.path.join(backup_dir, "vsgutu_grades_*.db")):
        try:
            if not is_plaintext(f):
                continue
            os.remove(f)
            n += 1
        except OSError as e:
            _LOG.warning("[local-db] незашифрованная копия %s не удалена: %s", f, e)
    if n:
        _LOG.info("[local-db] удалено незашифрованных резервных копий: %d "
                  "(это были полные снимки журнала открытым текстом)", n)
    return n
