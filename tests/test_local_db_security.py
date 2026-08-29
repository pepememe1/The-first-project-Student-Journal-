"""
test_local_db_security.py — база синхронизации зашифрована, а смена аккаунта не
оставляет на диске данных прежнего человека.

Жалоба Ярослава (28.08.2026): «почему я через обычный DB Browser спокойно захожу в
базу без пароля и вижу все данные пользователей». Разбор подтвердил три отдельные
дыры, и каждая закрывается своим средством (подробности — в шапке `data/local_db.py`):
  1. файл был обычным SQLite — ФИО и оценки читал любой просмотрщик;
  2. удалённые строки оставались лежать в свободных страницах;
  3. ИМЕНА ключей `kv_store` сами были персональными данными
     (`_local:my_theme:student:Фамилия|Имя|Группа` — четверых разных людей).

⚠️ ПОЧЕМУ ТЕСТЫ ИМЕННО ТАКИЕ. Проверять «в коде вызывается шифрование» бесполезно:
вызов может стоять и не срабатывать (наш самый частый класс дефекта). Поэтому ниже
всюду проверяется НАБЛЮДАЕМОЕ СВОЙСТВО ФАЙЛА на диске — читается ли он посторонним
инструментом, остались ли в нём чужие байты. Обратный ход к каждому случаю назван в
его докстринге.
"""
import glob
import os
import sqlite3

import pytest

from data import device_key, local_db

pytestmark = pytest.mark.skipif(
    not device_key.driver_available(),
    reason="без sqlcipher3 шифровать нечем — проверять нечего")

KEY = "a" * 64                              #64 hex — годный ключ, см. device_key.is_valid


def _make_plain(path, rows=40):
    """Обычная незашифрованная база с узнаваемыми персональными данными внутри."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE kv_store (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE grades (id TEXT PRIMARY KEY, student TEXT, value TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO grades VALUES (?,?,?)",
                     (f"g{i}", f"Загдаева|Арина|К64/2", "5"))
    conn.commit()
    conn.close()
    return path


# ── 1. Шифрование ──────────────────────────────────────────────────────────────────

def test_encrypted_file_is_not_readable_by_a_plain_sqlite_viewer(tmp_path):
    """Главное свойство: после перевода файл перестаёт открываться посторонним.

    Обратный ход: уберите вызов `encrypt_in_place` — тест краснеет, потому что
    обычный sqlite3 снова спокойно читает ФИО."""
    p = _make_plain(str(tmp_path / "db.db"))
    assert local_db.is_plaintext(p), "исходный файл обязан быть открытым — иначе тест пуст"

    assert local_db.encrypt_in_place(p, KEY) is True
    assert not local_db.is_plaintext(p)

    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(p).execute("SELECT COUNT(*) FROM grades").fetchone()


def test_personal_data_is_no_longer_findable_in_the_raw_bytes(tmp_path):
    """ФИО не должно находиться в файле поиском по байтам.

    ⚠️ Проверяем именно СЫРЫЕ БАЙТЫ, а не «база не открывается»: свободные страницы
    не открываются вместе с базой, но прекрасно читаются `grep`-ом по файлу — ровно
    так ФИО прежних аккаунтов и лежали на рабочей машине."""
    p = _make_plain(str(tmp_path / "db.db"))
    assert "Загдаева".encode("utf-8") in open(p, "rb").read(), "тест выродился"

    local_db.encrypt_in_place(p, KEY)
    assert "Загдаева".encode("utf-8") not in open(p, "rb").read()


def test_encryption_keeps_every_row(tmp_path):
    """Перевод не имеет права потерять ни одной оценки."""
    p = _make_plain(str(tmp_path / "db.db"), rows=57)
    local_db.encrypt_in_place(p, KEY)
    conn = local_db.connect(p, KEY)
    try:
        assert conn.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 57
    finally:
        conn.close()


def test_without_a_key_nothing_is_touched(tmp_path):
    """Нет ключа — файл остаётся как был. Это ветка запуска из исходников без драйвера:
    молча «сделать вид, что зашифровали» было бы хуже отсутствия шифрования."""
    p = _make_plain(str(tmp_path / "db.db"))
    assert local_db.encrypt_in_place(p, "") is False
    assert local_db.is_plaintext(p)


def test_a_bad_key_is_refused_rather_than_used(tmp_path):
    """Ключ не 64 hex — отказ, а не подстановка в SQL.

    Значение уходит в текст запроса (`KEY "x'…'"` параметризовать нельзя), и
    проверка формата здесь единственное, что стоит между нами и инъекцией."""
    p = _make_plain(str(tmp_path / "db.db"))
    assert local_db.encrypt_in_place(p, "x'; DROP TABLE grades; --") is False
    assert local_db.is_plaintext(p)


def test_encryption_is_idempotent(tmp_path):
    """Второй вызов на уже зашифрованной базе не делает ничего.

    Важно, потому что зовётся он при КАЖДОМ запуске программы."""
    p = _make_plain(str(tmp_path / "db.db"))
    assert local_db.encrypt_in_place(p, KEY) is True
    assert local_db.encrypt_in_place(p, KEY) is False


# ── 2. Размер ──────────────────────────────────────────────────────────────────────

def test_conversion_reclaims_free_pages(tmp_path):
    """Перевод пересобирает файл, и раздутый файл резко худеет.

    На рабочей машине 3 МБ файла приходились на данные объёмом меньше 100 КБ — всё
    остальное было свободными страницами с ФИО прежних аккаунтов."""
    p = str(tmp_path / "db.db")
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE kv_store (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE junk (id INTEGER PRIMARY KEY, payload TEXT)")
    conn.executemany("INSERT INTO junk(payload) VALUES (?)", [("x" * 900,)] * 3000)
    conn.commit()
    conn.execute("DELETE FROM junk")             #строк нет, а страницы остались
    conn.commit()
    conn.close()
    was = os.path.getsize(p)

    local_db.encrypt_in_place(p, KEY)
    assert os.path.getsize(p) < was / 2, (
        f"файл не ужался: было {was}, стало {os.path.getsize(p)} — значит свободные "
        f"страницы (а с ними и удалённые ФИО) остались лежать в файле")


def test_compact_shrinks_a_bloated_database(tmp_path):
    """VACUUM работает и на уже зашифрованной базе — это единственный честный способ
    сделать файл меньше. Сжимать шифротекст архиватором бессмысленно по построению."""
    p = _make_plain(str(tmp_path / "db.db"))
    local_db.encrypt_in_place(p, KEY)
    conn = local_db.connect(p, KEY)
    conn.executemany("INSERT INTO grades VALUES (?,?,?)",
                     [(f"j{i}", "x" * 900, "5") for i in range(3000)])
    conn.commit()
    conn.execute("DELETE FROM grades")
    conn.commit()
    conn.close()
    assert local_db.compact(p, KEY) > 0


def test_secure_delete_is_on(tmp_path):
    """Затирание освобождаемых страниц включено.

    Это страховка для запуска БЕЗ драйвера SQLCipher: там шифрования не будет вовсе,
    и `secure_delete` остаётся единственным, что не даёт удалённому ФИО лежать в
    файле. Обратный ход: уберите PRAGMA из `local_db.connect` — краснеет."""
    p = _make_plain(str(tmp_path / "db.db"))
    conn = local_db.connect(p, "")
    try:
        assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
    finally:
        conn.close()


# ── 3. Владелец базы ───────────────────────────────────────────────────────────────

def _owned_db(tmp_path, login, extra=()):
    p = _make_plain(str(tmp_path / "db.db"))
    local_db.encrypt_in_place(p, KEY)
    local_db.write_owner(p, KEY, login)
    if extra:
        conn = local_db.connect(p, KEY)
        conn.executemany("INSERT OR REPLACE INTO kv_store(key, value) VALUES (?,?)", extra)
        conn.commit()
        conn.close()
    return p


def test_same_user_keeps_the_database(tmp_path):
    """Тот же человек — база остаётся на месте вместе с офлайн-правками."""
    p = _owned_db(tmp_path, "ivanov")
    assert local_db.adopt(p, KEY, "ivanov") is False
    conn = local_db.connect(p, KEY)
    try:
        assert conn.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 40
    finally:
        conn.close()


def test_another_user_wipes_the_database(tmp_path):
    """🔒 Ядро требования: вошёл другой — данных прежнего не осталось.

    Обратный ход: верните `adopt` к «просто переставить метку» — краснеет, потому что
    сорок оценок прежнего человека остаются в файле."""
    p = _owned_db(tmp_path, "ivanov")
    assert local_db.adopt(p, KEY, "petrov") is True
    conn = local_db.connect(p, KEY)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM sqlite_master "
                            "WHERE type='table' AND name='grades'").fetchone()[0]
        assert rows == 0 or conn.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 0
    finally:
        conn.close()
    assert "Загдаева".encode("utf-8") not in open(p, "rb").read()


def test_machine_scoped_keys_survive_the_switch(tmp_path):
    """device_id, анти-брутфорс и журнал аудита принадлежат МАШИНЕ и обязаны выжить.

    ⚠️ Не косметика. Потеря `device_id` делает компьютер «новым» — барьер устройства
    потребует одобрения администратором заново, то есть смена аккаунта выбивала бы
    преподавателя из программы. А сброс `login_throttle` и `audit_log` означал бы,
    что защиту от перебора и след безопасности можно обнулить сменой пользователя."""
    p = _owned_db(tmp_path, "ivanov", extra=[
        ("_local:device_id", "enc:MACHINE"),
        ("_local:login_throttle", "enc:THROTTLE"),
        ("_local:audit_log", "enc:AUDIT"),
    ])
    local_db.adopt(p, KEY, "petrov")
    conn = local_db.connect(p, KEY)
    try:
        got = dict(conn.execute("SELECT key, value FROM kv_store").fetchall())
    finally:
        conn.close()
    assert got.get("_local:device_id") == "enc:MACHINE"
    assert got.get("_local:login_throttle") == "enc:THROTTLE"
    assert got.get("_local:audit_log") == "enc:AUDIT"


def test_user_scoped_keys_do_not_survive_the_switch(tmp_path):
    """А токен, сохранённый вход и тема с ФИО в ИМЕНИ ключа — обязаны уйти.

    ⚠️ Именно эти ключи и накопились на рабочей машине: `_local:my_theme:student:
    Загдаева|Арина|К64/2` и ещё три человека. Имя ключа не шифруется (по нему идёт
    поиск), поэтому оставить его значило бы оставить ПДн."""
    p = _owned_db(tmp_path, "ivanov", extra=[
        ("_local:api_token", "enc:ТОКЕН"),
        ("_local:session", "enc:ВХОД"),
        ("_local:my_theme:student:Загдаева|Арина|К64/2", "enc:ТЕМА"),
        ("_local:remote_servers", "enc:СЕРВЕРЫ"),
    ])
    local_db.adopt(p, KEY, "petrov")
    conn = local_db.connect(p, KEY)
    try:
        keys = [r[0] for r in conn.execute("SELECT key FROM kv_store")]
    finally:
        conn.close()
    for gone in ("_local:api_token", "_local:session", "_local:remote_servers",
                 "_local:my_theme:student:Загдаева|Арина|К64/2"):
        assert gone not in keys, f"ключ прежнего пользователя уцелел: {gone}"


def test_whitelist_is_white_not_black():
    """Список машинных ключей — БЕЛЫЙ. Чёрный неполон всегда, а первым забытым в нём
    оказался бы ключ вида `my_theme:student:Фамилия|Имя|Группа`."""
    for k in local_db.MACHINE_KEYS:
        assert not k.startswith("_local:my_theme"), "в белый список попал ключ человека"
        assert "|" not in k, "в белый список попал ключ с ФИО"


def test_missing_marker_does_not_wipe_anything(tmp_path):
    """Первый запуск после обновления: метки ещё нет — стирать НЕЛЬЗЯ.

    Иначе обновление уничтожало бы офлайн-правки, ещё не уехавшие на сервер, у
    каждого без исключения."""
    p = _make_plain(str(tmp_path / "db.db"))
    local_db.encrypt_in_place(p, KEY)
    assert local_db.adopt(p, KEY, "ivanov") is False
    conn = local_db.connect(p, KEY)
    try:
        assert conn.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 40
    finally:
        conn.close()
    assert local_db.read_owner(p, KEY) == local_db.owner_hash("ivanov")


def test_owner_marker_is_not_the_login_itself(tmp_path):
    """Логин — тоже персональные данные, в базе он лежит отпечатком."""
    p = _owned_db(tmp_path, "ivanov@esstu.ru")
    assert "ivanov" not in local_db.read_owner(p, KEY)


# ── 4. Копии и резервные копии ─────────────────────────────────────────────────────

def test_plaintext_backups_are_removed_and_encrypted_ones_are_kept(tmp_path):
    """Зашифровать базу и оставить её открытые копии — это театр.

    Копии снимаются автоматически (до 48 штук) обычным копированием файла, то есть
    ВСЕ, снятые до перехода, — полные снимки журнала открытым текстом."""
    d = tmp_path / "backups"
    d.mkdir()
    plain = _make_plain(str(d / "vsgutu_grades_20260101_000000.db"))
    enc = _make_plain(str(d / "vsgutu_grades_20260102_000000.db"))
    local_db.encrypt_in_place(enc, KEY)

    assert local_db.purge_plaintext_backups(str(d)) == 1
    assert not os.path.exists(plain)
    assert os.path.exists(enc), "зашифрованную копию трогать нельзя — она и есть бэкап"


def test_other_users_copies_are_purged_and_mine_is_kept(tmp_path, monkeypatch):
    """Копии прочих аккаунтов машины уходят, моя остаётся.

    Сюда же попадает `local_app.db` БЕЗ хеша — копия времён, когда файл был один на
    машину. Прежняя уборка целилась только в имя С хешем, и файл на 659 КБ с семью
    пользователями и сорока четырьмя оценками пролежал на рабочей машине месяц."""
    import hashlib
    import app_paths
    from desktop import local_api

    monkeypatch.setattr(app_paths, "data_dir", lambda: str(tmp_path))
    mine = hashlib.sha256(b"ivanov").hexdigest()[:16]
    names = [f"local_app_{mine}.enc.db",                      #моя рабочая
             f"local_app_{mine}.db",                          #моя открытая
             "local_app_0123456789abcdef.enc.db",             #чужая
             "local_app_fedcba9876543210.enc.db",             #чужая
             "local_app.db"]                                  #наследие до разделения
    for n in names:
        (tmp_path / n).write_bytes(b"SQLite format 3\x00")
    (tmp_path / "local_app.key").write_bytes("ключ трогать нельзя".encode("utf-8"))

    assert local_api.purge_other_user_copies("ivanov") == 3
    assert (tmp_path / f"local_app_{mine}.enc.db").exists()
    assert (tmp_path / f"local_app_{mine}.db").exists(), \
        "открытую копию ТЕКУЩЕГО человека убирает _drop_plaintext_copy, и только при " \
        "живом ключе: при временном сбое DPAPI слепая уборка снесла бы рабочий файл"
    assert (tmp_path / "local_app.key").exists(), "ключ устройства — не копия базы"
    assert not (tmp_path / "local_app.db").exists()
    assert len(glob.glob(str(tmp_path / "local_app_0*"))) == 0


# ── 5. Свойство кода: обойти шифрование нечем ──────────────────────────────────────

def test_no_direct_sqlite_connect_to_the_sync_database():
    """В `data/core.py` не осталось прямых `sqlite3.connect(LOCAL_DB…)`.

    🔥 Зачем сторож. Раньше таких мест было ПЯТЬ (соединение, резервная копия,
    восстановление, стирание, создание таблиц), и добавить шифрование «в основном
    пути», забыв про резервное копирование, очень легко — а забытое место как раз и
    оставляет файл с ФИО открытым. Проверяем ОТСУТСТВИЕ обхода, а не наличие вызова.
    Обратный ход: верните `sqlite3.connect(LOCAL_DB)` в любую из функций — краснеет."""
    import io
    src = io.open("data/core.py", encoding="utf-8").read()
    assert "sqlite3.connect(LOCAL_DB" not in src, (
        "кто-то снова открывает базу мимо data/local_db.connect — это обход шифрования")


# ── 6. Размер: сжатие крупных значений ─────────────────────────────────────────────

def _big_json(n=9000):
    """Похожее на кэш расписания: много однотипных записей, отлично сжимается."""
    return '{"pairs":[' + '{"g":"K74/1","s":"Matematika","t":"Ivanov"},' * n + ']}'


def test_a_large_value_is_stored_compressed():
    """Крупное значение уходит в базу сжатым.

    Замер, из-за которого это появилось: 92 % локальной базы (2 565 284 из 2 785 280
    байт) занимал ОДИН ключ `_local:schedule_cache`, и его JSON сжимается в 19.6 раза.
    Обратный ход: поднимите `_COMPRESS_MIN` выше размера значения — краснеет."""
    from data import security
    big = _big_json()
    packed = security.encrypt_value(big)
    assert packed.startswith("encz:"), "крупное значение снова легло несжатым"
    assert len(packed) < len(big) / 10
    assert security.decrypt_value(packed) == big, "сжатое значение обязано читаться обратно"


def test_small_values_keep_the_old_format_byte_for_byte():
    """🔒 Мелкие значения формат НЕ меняют, и это не мелочь.

    Старая сборка про `encz:` не знает и вернула бы такое значение строкой
    «encz:gAAAA…» как будто это открытый текст. Для кэша это неприятно (скачается
    заново), для токена, сохранённого входа и журнала аудита — потеря. Поэтому сжатие
    включается только на заведомо крупных и восстановимых блобах."""
    from data import security
    for text in ("", "korotko", "x" * 1000, "y" * 60000):
        assert security.encrypt_value(text).startswith("enc:")


def test_old_uncompressed_values_are_still_readable():
    """Значения, записанные ДО этой правки, читаются как раньше.

    Иначе обновление программы обнулило бы всем настройки и сохранённый вход."""
    import base64
    from data import security
    old = security._ENC_PREFIX + base64.urlsafe_b64encode(
        security._encrypt_bytes("privet".encode("utf-8"), security.get_data_key())).decode()
    assert security.decrypt_value(old) == "privet"


def test_is_encrypted_recognises_both_forms():
    """Забыв `encz:` здесь, мы получили бы худший исход: шифротекст поехал бы дальше
    по программе под видом «обычного текста старых данных»."""
    from data import security
    assert security.is_encrypted(security.encrypt_value(_big_json()))
    assert security.is_encrypted(security.encrypt_value("korotko"))
    assert not security.is_encrypted("prosto tekst")


def test_repack_shrinks_an_existing_database(tmp_path):
    """Уже лежащее крупное значение перекладывается и файл РЕАЛЬНО худеет.

    ⚠️ Без этого шага сжатие включилось бы только на следующей записи значения, то
    есть у кэша расписания — через сутки. Человек, попросивший файл поменьше, увидел
    бы прежние мегабайты."""
    from data import security
    import base64
    p = str(tmp_path / "db.db")
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE kv_store (key TEXT PRIMARY KEY, value TEXT)")
    #Кладём в СТАРОЙ форме — ровно так, как оно лежит у людей после обновления.
    legacy = security._ENC_PREFIX + base64.urlsafe_b64encode(
        security._encrypt_bytes(_big_json().encode("utf-8"), security.get_data_key())).decode()
    conn.execute("INSERT INTO kv_store VALUES ('_local:schedule_cache', ?)", (legacy,))
    conn.commit()
    conn.close()
    local_db.encrypt_in_place(p, KEY)
    was = os.path.getsize(p)

    assert local_db.repack_large_values(p, KEY) > 0
    assert os.path.getsize(p) < was / 3, "файл не ужался — перекладка не сработала"

    conn = local_db.connect(p, KEY)
    try:
        v = conn.execute("SELECT value FROM kv_store WHERE key='_local:schedule_cache'").fetchone()[0]
    finally:
        conn.close()
    assert security.decrypt_value(v) == _big_json(), "значение испорчено перекладкой"


def test_repack_never_destroys_a_value_it_cannot_read(tmp_path):
    """🔥 Значение, которое не расшифровалось, ОСТАЁТСЯ КАК БЫЛО.

    `decrypt_value` при неудаче возвращает пустую строку — разумно для чтения, но
    здесь такой ответ означал бы «запиши на место данных пустоту». Под тем же ключом
    лежат журнал аудита и настройки. Обратный ход: уберите проверку `if not plain` в
    `repack_large_values` — краснеет."""
    p = str(tmp_path / "db.db")
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE kv_store (key TEXT PRIMARY KEY, value TEXT)")
    #Чужим ключом — расшифровать нечем: имитируем повреждение или чужой профиль.
    broken = "enc:" + "A" * 200000
    conn.execute("INSERT INTO kv_store VALUES ('_local:audit_log', ?)", (broken,))
    conn.commit()
    conn.close()
    local_db.encrypt_in_place(p, KEY)

    local_db.repack_large_values(p, KEY)
    conn = local_db.connect(p, KEY)
    try:
        v = conn.execute("SELECT value FROM kv_store WHERE key='_local:audit_log'").fetchone()[0]
    finally:
        conn.close()
    assert v == broken, "нечитаемое значение затёрли — так теряют журнал аудита"


# ── 7. Уборка необратима, поэтому за паролем ───────────────────────────────────────

def test_purge_never_runs_before_the_password_is_checked(monkeypatch):
    """🔥 Уборка чужих баз — ТОЛЬКО после подтверждённого входа.

    `switch_user_db` зовётся в том числе ДО проверки пароля: в `_login_flow` есть
    спекулятивная попытка «вдруг человек уже входил на этой машине — тогда пустим его
    офлайн», и логин там ещё ничем не подтверждён. Повесив уборку на сам факт
    переключения (а именно так я и сделал сначала), мы отдали бы любому, кто НАБРАЛ
    чужой логин с любым паролем, право стереть локальные копии всех остальных
    пользователей машины: вход честно отклоняется, а данные уже не вернуть.

    Обратный ход: уберите проверку `if authenticated` в `switch_user_db` — краснеет."""
    from desktop import local_api
    local_api.ensure_server_path()
    import app.db as _db

    calls = []
    monkeypatch.setattr(local_api, "_purge_previous_user", lambda login: calls.append(login))
    monkeypatch.setattr(local_api, "prepare_env", lambda: None)
    monkeypatch.setattr(local_api, "local_db_url", lambda login="": "sqlite:///" + login)
    monkeypatch.setattr(local_api, "_ensure_copy_openable", lambda login, enc: None)
    monkeypatch.setattr(local_api, "_local_db_key", lambda: "")
    monkeypatch.setattr(_db, "DATABASE_URL", "sqlite:///kto-to-drugoy", raising=False)
    monkeypatch.setattr(_db, "rebind", lambda url, key="": None, raising=False)

    local_api.switch_user_db("ivanov")
    assert calls == [], "чужие базы стёрты по одному лишь НАБРАННОМУ логину, без пароля"

    local_api.switch_user_db("ivanov", authenticated=True)
    assert calls == ["ivanov"], "после подтверждённого входа уборка обязана сработать"


def test_purge_also_runs_when_the_database_is_already_the_right_one(monkeypatch):
    """Ранний выход «переключать нечего» не должен пропускать уборку.

    Иначе она не срабатывала бы ровно у того, кто входит на этой машине постоянно, —
    то есть у обычного пользователя, а не у редкого."""
    from desktop import local_api
    local_api.ensure_server_path()
    import app.db as _db

    calls = []
    monkeypatch.setattr(local_api, "_purge_previous_user", lambda login: calls.append(login))
    monkeypatch.setattr(local_api, "prepare_env", lambda: None)
    monkeypatch.setattr(local_api, "local_db_url", lambda login="": "sqlite:///" + login)
    monkeypatch.setattr(_db, "DATABASE_URL", "sqlite:///ivanov", raising=False)

    assert local_api.switch_user_db("ivanov", authenticated=True) is True
    assert calls == ["ivanov"]


def test_schema_is_rebuilt_after_the_owner_changes(monkeypatch, tmp_path):
    """🔥 После смены владельца база обязана снова иметь ВСЕ таблицы.

    `adopt` уносит файл целиком, из одиннадцати таблиц остаётся одна (`kv_store`), а
    `_init_sqlite_tables` зовётся только на СТАРТЕ программы — смена же аккаунта идёт
    без перезапуска. Без пересоздания схемы синхронизация до конца сеанса работала бы
    по базе без таблиц: сбор дельты молча отдавал бы пустоту (там `except` вокруг
    каждого запроса), а слияние падало бы на «no such table: grades».
    Проверено вживую до починки: 11 таблиц превращались в 1.

    Обратный ход: уберите `core.DBManager.init()` из `_purge_previous_user` — краснеет."""
    from desktop import local_api
    from data import core

    monkeypatch.setattr(local_api, "purge_other_user_copies", lambda login: 0)
    monkeypatch.setattr(local_api, "_local_db_key", lambda: device_key.db_key())

    core.DBManager.init()
    key = device_key.db_key()
    local_db.write_owner(core.LOCAL_DB, key, "ivanov")

    conn = local_db.connect(core.LOCAL_DB, key)
    try:
        before = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "grades" in before, "тест выродился — таблиц не было и до смены владельца"

    local_api._purge_previous_user("petrov")

    conn = local_db.connect(core.LOCAL_DB, key)
    try:
        after = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        #Главное: журнал снова работоспособен, а не «файл существует».
        assert conn.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 0
    finally:
        conn.close()
    missing = before - after
    assert not missing, f"после смены владельца пропали таблицы: {sorted(missing)}"


def test_plaintext_file_opens_without_noise_before_migration(tmp_path, caplog):
    """Открытый ещё файл открывается БЕЗ ключа и без ошибок в журнале.

    🔥 Между запуском программы и миграцией есть окно, в котором ключ уже есть, а база
    ещё открытая: в него успевает попасть чтение адреса сервера. Попытка открыть такой
    файл С ключом даёт «file is not a database», и в логе ПЕРВОГО старта после
    обновления появлялись две строки ошибок на ровном месте (поймано живым прогоном
    автообновления 29.08.2026). Само лечится через секунду, но такой шум прячет
    настоящие сбои — по ним же потом и ищут причину.

    Обратный ход: уберите ветку `if key and is_plaintext(path): key = ""` — краснеет."""
    import logging
    p = _make_plain(str(tmp_path / "db.db"))
    with caplog.at_level(logging.WARNING, logger="gradebook.local_db"):
        conn = local_db.connect(p, KEY)
        try:
            assert conn.execute("SELECT COUNT(*) FROM grades").fetchone()[0] == 40
        finally:
            conn.close()
    noisy = [r.getMessage() for r in caplog.records
             if "not a database" in r.getMessage() or "PRAGMA" in r.getMessage()]
    assert not noisy, f"в журнале шум на ровном месте: {noisy}"


def test_migration_still_happens_after_a_plaintext_open(tmp_path):
    """И главное: поблажка выше НЕ отменяет шифрование — миграция отрабатывает следом.

    Иначе получилось бы худшее из возможного: база молча осталась бы открытой, а в
    журнале не было бы даже предупреждения, потому что мы его сами и убрали."""
    p = _make_plain(str(tmp_path / "db.db"))
    conn = local_db.connect(p, KEY)
    conn.close()
    assert local_db.is_plaintext(p), "до миграции файл обязан оставаться открытым"
    assert local_db.encrypt_in_place(p, KEY) is True
    assert not local_db.is_plaintext(p), "после миграции файл обязан быть зашифрован"
