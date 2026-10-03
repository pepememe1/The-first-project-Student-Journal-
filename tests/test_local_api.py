"""
test_local_api.py — ЛОКАЛЬНОЕ серверное приложение внутри десктопа (desktop/local_api.py).

Это ядро объединения платформ: десктоп показывает ту же Vue-SPA и ходит в тот же
`/web/*`, что и сайт, но всё на своём компьютере — отсюда offline-first.

Закрепляем ровно те свойства, потеря которых означает не баг, а сломанное обещание
пользователю: «снаружи не подключиться», «никаких окон», «интерфейс и данные с одного
адреса». Тест поднимает НАСТОЯЩЕЕ приложение, а не заглушку: иначе он не заметил бы,
что серверный пакет перестал импортироваться в десктопном окружении.
"""
import os
import tempfile
import threading
import urllib.error
import urllib.request

import pytest

from desktop import local_api


@pytest.fixture(scope="module")
def api():
    """Поднимает локальный сервер на ВРЕМЕННОЙ базе (боевую и десктопную не трогаем)."""
    tmp_db = os.path.join(tempfile.mkdtemp(), "local_app_test.db").replace("\\", "/")
    os.environ["GRADEBOOK_DB_URL"] = f"sqlite:///{tmp_db}"
    srv = local_api.LocalAPI()
    if not srv.start():
        pytest.skip(f"серверный пакет недоступен в этом окружении: {srv.error}")
    yield srv
    srv.stop()


def _get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_ensure_server_path_falls_back_to_sys_executable_dir(monkeypatch, tmp_path):
    """Живой баг («программа не запускается» под собранным .exe): под Nuitka onefile
    __file__-путь (кандидат №1, от расположения local_api.py в репозитории) не
    находит server/app там, где Nuitka РЕАЛЬНО его распаковывает — это отдельный кэш
    (--onefile-tempdir-spec), доступный через dirname(sys.executable). Эмулируем это:
    кандидат №1 «не находится» (репозиторий отсутствует), а рядом с sys.executable
    лежит настоящий server/ — ensure_server_path обязана дойти до него."""
    real_isdir = os.path.isdir
    repo_candidate = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(local_api.__file__))), "server")
    fake_exe_dir = tmp_path / "onefile_cache"
    (fake_exe_dir / "server").mkdir(parents=True)

    def fake_isdir(path):
        if os.path.abspath(path) == os.path.abspath(repo_candidate):
            return False                                        # кандидат 1 «не найден»
        return real_isdir(path)

    monkeypatch.setattr(os.path, "isdir", fake_isdir)
    monkeypatch.setattr("sys.executable", str(fake_exe_dir / "python.exe"))
    expected = str(fake_exe_dir / "server")
    monkeypatch.setattr("sys.path", [p for p in __import__("sys").path if p != expected])

    local_api.ensure_server_path()
    import sys as _sys
    assert expected in _sys.path


def test_listens_only_on_loopback(api):
    """Самая важная проверка файла: сервер обязан слушать ТОЛЬКО себя.

    Ловит правку «поставим 0.0.0.0, чтобы зайти с телефона». Прежде здесь стояла отсылка
    к фоновому серверу хоста (`server_control.py`) — он удалён 15.08.2026, и законной
    альтернативы «пустить в сеть» у этой копии не осталось вовсе."""
    import inspect
    src = inspect.getsource(local_api.LocalAPI.start)
    assert '"127.0.0.1"' in src, "локальный сервер должен слушать только петлю"
    assert "0.0.0.0" not in src, "0.0.0.0 открывает сервер в сеть — так нельзя"


def test_port_is_ephemeral(api):
    assert api.port > 1024


def test_serves_the_same_spa(api):
    """Интерфейс приходит с локального адреса — значит откроется и без интернета."""
    code, body = _get(api.url("/"))
    assert code == 200
    assert b"<div id=\"app\">" in body or b"assets/" in body, body[:200]


def test_serves_api_from_the_same_origin(api):
    """SPA и `/web/*` — ОДИН адрес: не нужен ни CORS, ни настройка «адрес сервера».
    Именно это позволяет держать один интерфейсный код на обе платформы."""
    code, _ = _get(api.url("/health"))
    assert code == 200


def test_api_still_requires_auth(api):
    """«Локально» не значит «без пароля»: тот же JWT-барьер, что и на бою."""
    code, _ = _get(api.url("/web/vector/ask"), data=b"{}",
                   headers={"Content-Type": "application/json"})
    assert code == 401


def test_runs_in_thread_not_process(api):
    """«Никаких окон» держится на том, что сервер — поток: процесс мог бы мигнуть
    консолью, поток не может показать окно в принципе."""
    assert isinstance(api._thread, threading.Thread)
    assert api._thread.daemon, "поток обязан быть демоном — иначе программа не закроется"


def test_start_is_idempotent(api):
    port = api.port
    assert api.start() is True
    assert api.port == port, "повторный старт не должен поднимать второй сервер"


def test_local_db_is_separate_file():
    """Локальная база приложения — ОТДЕЛЬНЫЙ файл, а не десктопный vsgutu_grades.db:
    у них разные схемы, и смешивать их нельзя."""
    url = local_api.local_db_url("ivanov")
    assert url.startswith("sqlite:///")
    assert "local_app_" in url
    assert "vsgutu_grades" not in url


def test_copy_is_separate_per_user():
    """Файл СВОЙ на каждого вошедшего. Раньше он был один на машину, и после сеанса
    преподавателя в нём оставались оценки всей группы — следующий вошедший студент их
    читал (найдено на живой машине: 44 оценки шести студентов)."""
    a = local_api.local_db_file("ivanov")
    b = local_api.local_db_file("petrov")
    assert a != b, "общий файл = чужие данные следующему вошедшему"
    assert "ivanov" not in a, "логин — тоже ПДн, в имени файла ему не место"


def test_copy_is_encrypted_when_driver_present():
    """Копия ШИФРУЕТСЯ (SQLCipher), ключ — под DPAPI. Без этого ФИО, группы и оценки
    читались из файла любым просмотрщиком, в т.ч. с украденного диска."""
    try:
        import sqlcipher3  # noqa: F401
    except Exception:
        pytest.skip("драйвер sqlcipher3 не установлен в этом окружении")
    assert local_api._local_db_key(), "ключ обязан заводиться, если драйвер есть"
    local_api.prepare_env()
    assert os.environ.get("GRADEBOOK_DB_KEY"), "сервер обязан получить ключ"


# ── Локальная сессия ────────────────────────────────────────────────────────────────
def test_local_session_opens_protected_endpoint(api):
    """Токен боевого сервера подписан ЧУЖИМ секретом — локальный обязан его отвергнуть.
    Поэтому для общего интерфейса выпускается СВОЙ токен; без него внутри программы
    показывалась форма входа, хотя человек уже вошёл."""
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    db.merge(User(id="stud:t", login="t", role="student", surname="Тестов", name="Тест",
                  group_name="К74/1", deleted=False,
                  updated_at="2026-07-01T00:00:00+00:00"))
    db.commit()
    db.close()

    access, refresh = local_api.issue_local_session("t", "student")
    assert access and refresh

    url = api.url("/web/student/overview")
    assert _get(url, headers={"X-Client": "web"})[0] == 401, "без токена — 401"
    code, _ = _get(url, headers={"X-Client": "web",
                                 "Authorization": f"Bearer {access}"})
    assert code == 200, "со своим токеном локальный сервер обязан пустить"


def test_user_exists_tells_whether_mirror_caught_up(api):
    """Сразу после первого входа зеркало могло не докачать самого человека. Токен тогда
    безупречен, а `/web/*` всё равно отвечает «требуется авторизация» — и внутри
    программы появляется форма входа. Поэтому наличие человека проверяем ЗАРАНЕЕ и в
    этом случае показываем вкладку с боевого сервера."""
    assert local_api.user_exists("t") is True
    assert local_api.user_exists("ghost-no-such-login") is False
    assert local_api.user_exists("") is False


def test_local_session_registers_auth_session(api):
    """Токен с jti сервер считает отозванным, пока нет записи сессии — поэтому её
    заводим. Побочная польза: локальный выход и отзыв работают как на бою."""
    from app.db import SessionLocal
    from app.models import AuthSession
    access, _ = local_api.issue_local_session("t", "student")
    from app.security import decode_token
    jti = decode_token(access).get("jti")
    db = SessionLocal()
    try:
        row = db.query(AuthSession).filter(AuthSession.jti == jti).first()
        assert row is not None and not row.revoked
        assert row.login == "t" and row.kind == "access"
    finally:
        db.close()


# ── Самолечение локальной копии ─────────────────────────────────────────────────────
def test_unreadable_copy_is_moved_aside_not_deleted(tmp_path, monkeypatch):
    """Нечитаемая копия НЕ имеет права ронять программу.

    Копия базы — производные данные (истина на сервере, сюда она зеркалится), поэтому
    единственно верное поведение — начать её заново. Поймано на живой машине: копию
    однажды зашифровали SQLCipher, а следующий запуск шёл из окружения БЕЗ драйвера —
    обычный sqlite видел мусор, сервер падал на старте («file is not a database»), и
    вместе с ним не открывалась ВСЯ программа.

    ⚠️ Файл именно ПЕРЕИМЕНОВЫВАЕТСЯ: в нём могли остаться офлайн-правки, не уехавшие
    на сервер. Вернуть их из «.unreadable» можно, из небытия — нет."""
    fake = tmp_path / "local_app_test.db"
    #Байты «не SQLite» — ровно то, что видит обычный sqlite в зашифрованном файле.
    fake.write_bytes(b"\x96\xb1\x00\x06not-a-database")
    for suffix in ("-wal", "-shm"):
        (tmp_path / f"local_app_test.db{suffix}").write_bytes(b"garbage")
    monkeypatch.setattr(local_api, "local_db_file", lambda login="": str(fake))

    local_api._ensure_copy_openable("", encrypted=False)

    assert not fake.exists(), "нечитаемая копия должна уйти с дороги"
    saved = list(tmp_path.glob("local_app_test.db.unreadable-*"))
    assert saved, "старый файл обязан СОХРАНИТЬСЯ, а не удалиться"
    #Спутники -wal/-shm тоже уносим: оставшись рядом, они испортят новый файл.
    assert not (tmp_path / "local_app_test.db-wal").exists()
    assert not (tmp_path / "local_app_test.db-shm").exists()


def test_healthy_copy_is_left_alone(tmp_path, monkeypatch):
    """Исправную копию не трогаем: иначе каждый запуск терял бы офлайн-данные."""
    import sqlite3
    good = tmp_path / "local_app_ok.db"
    con = sqlite3.connect(str(good))
    con.execute("CREATE TABLE t (x INTEGER)")
    con.commit()
    con.close()
    monkeypatch.setattr(local_api, "local_db_file", lambda login="": str(good))

    local_api._ensure_copy_openable("", encrypted=False)

    assert good.exists(), "рабочую копию убирать нельзя"
    assert not list(tmp_path.glob("*.unreadable-*"))


def test_env_file_key_cannot_leak_into_the_local_copy(monkeypatch, tmp_path):
    """Ключ из `server/.env` НЕ должен шифровать личную копию пользователя.

    Серверный пакет читает `.env` через `os.environ.setdefault` — то есть занимает любую
    переменную, которой нет. Пока `prepare_env` УДАЛЯЛА `GRADEBOOK_DB_KEY`, место
    освобождалось, и копию начинал шифровать чужой ключ из `.env` вместо DPAPI-ключа
    этого устройства.

    Последствие было хуже утечки: копия, зашифрованная запуском С драйвером sqlcipher3,
    не открывалась запуском БЕЗ него — локальный сервер падал на старте («file is not a
    database»), а с ним не открывалась ВСЯ программа. Поймано на живой машине.

    Поэтому переменная задаётся ЯВНО (пустой строкой), и `setdefault` её не перебьёт."""
    monkeypatch.setattr(local_api, "_local_db_key", lambda: "")
    monkeypatch.setenv("GRADEBOOK_DB_KEY", "ключ-из-чужого-env")
    monkeypatch.setenv("GRADEBOOK_DB_URL", f"sqlite:///{tmp_path / 'x.db'}")

    local_api.prepare_env()

    assert os.environ.get("GRADEBOOK_DB_KEY") == "", "ключ обязан быть ПУСТЫМ, а не отсутствовать"
    assert "GRADEBOOK_DB_KEY" in os.environ, "переменная должна СУЩЕСТВОВАТЬ, иначе .env её займёт"


def test_own_key_is_used_when_driver_present(monkeypatch, tmp_path):
    """Свой DPAPI-ключ устройства побеждает: копия шифруется им, а не значением из `.env`."""
    monkeypatch.setattr(local_api, "_local_db_key", lambda: "deadbeef")
    monkeypatch.setattr(local_api, "_drop_plaintext_copy", lambda login: None)
    monkeypatch.setenv("GRADEBOOK_DB_KEY", "ключ-из-чужого-env")
    monkeypatch.setenv("GRADEBOOK_DB_URL", f"sqlite:///{tmp_path / 'y.db'}")

    local_api.prepare_env()

    assert os.environ.get("GRADEBOOK_DB_KEY") == "deadbeef"


def test_encrypted_and_plain_copies_have_different_names(monkeypatch):
    """Зашифрованная и открытая копии — РАЗНЫЕ файлы.

    Одна машина может запускать программу двумя способами: собранным .exe (в нём вшит
    `sqlcipher3`, копия шифруется) и из исходников (драйвера может не быть, копия
    открытая). При общем имени они дрались за один файл: копию от .exe запуск из
    исходников открыть не мог и падал со «file is not a database» — и наоборот.
    Поймано на живой машине; разные имена разводят их навсегда."""
    plain = local_api.local_db_file("ivanov", encrypted=False)
    enc = local_api.local_db_file("ivanov", encrypted=True)
    assert plain != enc
    assert enc.endswith(".enc.db") and not plain.endswith(".enc.db")


def test_plaintext_cleanup_targets_the_plain_file(monkeypatch, tmp_path):
    """Уборка открытой копии обязана целиться в ОТКРЫТОЕ имя.

    После разделения имён «удалить незашифрованную» без явного указания снесло бы
    зашифрованный файл — тот самый, которым программа сейчас работает."""
    monkeypatch.setattr(local_api, "_local_db_key", lambda: "deadbeef")
    monkeypatch.setattr(local_api, "local_db_file",
                        lambda login="", encrypted=None: str(tmp_path / "plain.db")
                        if encrypted is False else str(tmp_path / "enc.enc.db"))
    (tmp_path / "plain.db").write_bytes(b"SQLite format 3\x00" + b"0" * 64)
    (tmp_path / "enc.enc.db").write_bytes(b"\x01\x02random-encrypted")

    #БЕЗ подмены `wipe_local_db`: проверяем НАСТОЯЩЕЕ удаление. Подменённая заглушка
    #скрыла бы ровно ту ошибку, ради которой тест и написан — уборка звала стирание без
    #указания файла и сносила бы зашифрованную копию, а открытая с ПДн оставалась лежать.
    local_api._drop_plaintext_copy("ivanov")

    assert not (tmp_path / "plain.db").exists(), "открытая копия с ПДн обязана исчезнуть"
    assert (tmp_path / "enc.enc.db").exists(), "зашифрованную копию трогать нельзя"


def test_sync_status_route_requires_the_local_caller(api):
    """`/desk/sync/status` рассказывает, сколько у человека неотправленных и конфликтных
    правок. Это не то, что стоит отдавать любому процессу на машине, поэтому охранник тот
    же, что у прокси (`_local_caller_ok`), а не «мы же на петле»."""
    code, _ = _get(api.url("/desk/sync/status"))
    assert code == 403, "без локального токена состояние синка отдавать нельзя"


def test_sync_status_passes_the_counters_through(api, monkeypatch):
    """🔥 Тест на САМУ ПРОВОДКУ, ради которой маршрут и заведён.

    До него `sync_runner.status()` не звал никто, кроме теста: индикатор жил в Qt и был
    удалён вместе с ней. Значит конфликт оценки и отвергнутая сервером правка «звучали»
    только строкой в `gradebook.log`, которую никто не открывает. Здесь проверяется, что
    цифры доезжают до HTTP — то есть до интерфейса."""
    from sync import sync_runner

    monkeypatch.setattr(local_api, "_session_login", lambda: "t")
    monkeypatch.setattr(sync_runner, "status",
                        lambda: {"online": True, "fails": 0, "error": "", "auth_error": "",
                                 "rejected": {"grades": 2}, "conflicts": 3})

    access, _ = local_api.issue_local_session("t", "teacher")
    code, body = _get(api.url("/desk/sync/status"),
                      headers={"Authorization": f"Bearer {access}"})
    assert code == 200
    import json as _json
    data = _json.loads(body)
    assert data["available"] is True
    assert data["conflicts"] == 3, "счётчик конфликтов не доехал до интерфейса"
    assert data["rejected"] == {"grades": 2}, "отвергнутые правки не доехали"


def test_sync_status_says_unknown_instead_of_inventing_zero(api, monkeypatch):
    """Синк мог не запуститься вовсе (вход по сохранённой сессии, пароля нет). Тогда
    честный ответ — «состояние неизвестно», а НЕ ноль конфликтов: ноль на экране значит
    «всё сошлось», чего мы в этот момент не знаем. Обратная проверка к тесту выше — без
    неё «починка» вида «всегда возвращать нули» осталась бы незамеченной."""
    from sync import sync_runner

    def _boom():
        raise RuntimeError("синк не запущен")

    monkeypatch.setattr(local_api, "_session_login", lambda: "t")
    monkeypatch.setattr(sync_runner, "status", _boom)

    access, _ = local_api.issue_local_session("t", "teacher")
    code, body = _get(api.url("/desk/sync/status"),
                      headers={"Authorization": f"Bearer {access}"})
    assert code == 200, "недоступность синка — не ошибка HTTP, интерфейс не должен падать"
    import json as _json
    data = _json.loads(body)
    assert data["available"] is False
    assert "conflicts" not in data, "нельзя выдавать ноль за известное значение"


# ── Раздел «Сервер» пускает только администратора (аудит 22.09.2026, F-01, P0) ──────
def _seed_role(login: str, role: str) -> None:
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        db.merge(User(id=f"u:{login}", login=login, role=role, surname="Тестов",
                      name="Тест", deleted=False,
                      updated_at="2026-09-25T00:00:00+00:00"))
        db.commit()
    finally:
        db.close()


def test_local_caller_reports_the_role_from_the_local_copy(api, monkeypatch):
    """Роль берётся из ЛОКАЛЬНОЙ копии базы, а не из утверждения токена: иначе
    разжалованный на бою администратор сохранял бы права до конца жизни токена."""
    _seed_role("f01_teacher", "teacher")
    monkeypatch.setattr(local_api, "_session_login", lambda: "f01_teacher")
    #Токен нарочно выписан с ролью admin: локальная копия говорит «teacher» — верим ей.
    access, _ = local_api.issue_local_session("f01_teacher", "admin")
    assert access, "тесту нужен настоящий подписанный токен"
    who = local_api._local_caller(f"Bearer {access}")
    assert who == {"login": "f01_teacher", "role": "teacher"}, who


def test_refresh_token_is_not_a_pass(api, monkeypatch):
    """Пропуском служит только access: refresh живёт дольше, и пускать по нему значило
    бы продлить права мимо срока (на бою это закрыто проверкой типа в get_current_user)."""
    _seed_role("f01_refresh", "admin")
    monkeypatch.setattr(local_api, "_session_login", lambda: "f01_refresh")
    access, refresh = local_api.issue_local_session("f01_refresh", "admin")
    assert local_api._local_caller(f"Bearer {access}")
    assert local_api._local_caller(f"Bearer {refresh}") == {}


def test_server_section_refuses_a_teacher_over_http(api, monkeypatch):
    """Сквозная проверка на НАСТОЯЩЕМ локальном сервере: преподаватель, вошедший в
    программу, получает 403 на строку команд к боевой машине, администратор — проходит."""
    from desktop import server_admin
    monkeypatch.setattr(server_admin, "_load", lambda: [])
    monkeypatch.setattr(server_admin, "_save", lambda items: True)
    monkeypatch.setattr(server_admin, "suggested_host", lambda: "")
    monkeypatch.setattr(server_admin, "_audit", lambda *a, **k: None)

    _seed_role("f01_t", "teacher")
    _seed_role("f01_a", "admin")
    body = b'{"command": "id"}'
    json_h = {"Content-Type": "application/json"}

    monkeypatch.setattr(local_api, "_session_login", lambda: "f01_t")
    teacher, _ = local_api.issue_local_session("f01_t", "teacher")
    code, _ = _get(api.url("/desk/servers/any/exec"), data=body,
                   headers={**json_h, "Authorization": f"Bearer {teacher}"})
    assert code == 403, f"преподаватель получил доступ к строке команд: {code}"

    monkeypatch.setattr(local_api, "_session_login", lambda: "f01_a")
    admin, _ = local_api.issue_local_session("f01_a", "admin")
    code, _ = _get(api.url("/desk/servers"), headers={"Authorization": f"Bearer {admin}"})
    assert code == 200, f"администратора охранник не пустил: {code}"


# ── Очередь правок в состоянии синка; передача сессии (аудит 22.09.2026, F-02/F-04/N-05)
def test_sync_status_reports_the_outbox(api, monkeypatch):
    """Проводка «очередь → /desk/sync/status → значок»: без неё человек не узнал бы, что
    его оценки ещё не дошли до сервера (сам цикл синка про очередь не рассказывает)."""
    import json as _json
    from desktop import desk_outbox
    _seed_role("f02_st", "teacher")
    monkeypatch.setattr(local_api, "_session_login", lambda: "f02_st")
    seq = desk_outbox.enqueue("f02_st", "POST", "/web/teacher/grade", "", b"{}",
                              "application/json")
    desk_outbox.mark_ready(seq, {"id": "G-status", "base_updated_at": "", "updated_at": "L"})
    token, _ = local_api.issue_local_session("f02_st", "teacher")
    code, body = _get(api.url("/desk/sync/status"),
                      headers={"Authorization": f"Bearer {token}"})
    assert code == 200
    data = _json.loads(body)
    assert data["outbox"]["pending"] >= 1, "очередь не доехала до статуса"
    #W-11: выход спрашивает именно этот признак. Без него `has_unsent` снова осталась
    #бы функцией без вызывающего, а человек — без вопроса «точно уходите?».
    assert data.get("unsent") is True, "признак неотправленного не доехал до статуса"


def test_bootstrap_gives_no_session_when_the_personal_copy_did_not_open(api, monkeypatch):
    """🔒 F-04: копия не открылась — сессии нет. Раньше она выдавалась на ПРЕЖНЕЙ базе:
    человек работал в чужом файле, и его правки ложились туда же."""
    issued = []
    monkeypatch.setattr(local_api, "_session_login", lambda: "f04_boot")
    monkeypatch.setattr(local_api, "_saved_session_alive", lambda: True)
    monkeypatch.setattr(local_api, "switch_user_db", lambda login, authenticated=False: False)
    monkeypatch.setattr(local_api, "issue_local_session",
                        lambda login, role: issued.append(login) or ("tok-x", "ref-x"))
    code, body = _get(api.url("/desktop/bootstrap?route=/"))
    assert code == 200
    assert not issued and b"tok-x" not in body, "сессия выдана на чужой базе"


def test_bootstrap_resumes_sync_for_a_restored_session(api, monkeypatch):
    """🔥 N-05: по сохранённой сессии синк не запускался вовсе — копия не обновлялась до
    повторного входа, а очередь правок не уходила. Уже работающий синк этого же человека
    не перезапускается: `start(login, "")` затёр бы пароль, которым он продлевает вход."""
    from sync import sync_runner
    started = []
    monkeypatch.setattr(local_api, "_session_login", lambda: "f05_boot")
    monkeypatch.setattr(local_api, "_saved_session_alive", lambda: True)
    monkeypatch.setattr(local_api, "switch_user_db", lambda login, authenticated=False: True)
    monkeypatch.setattr(local_api, "issue_local_session", lambda login, role: ("tok", "ref"))
    monkeypatch.setattr(sync_runner, "start",
                        lambda login, password, role: started.append((login, password)))
    monkeypatch.setattr(sync_runner, "current_login", lambda: "")
    assert _get(api.url("/desktop/bootstrap?route=/"))[0] == 200
    assert started == [("f05_boot", "")], started

    started.clear()
    monkeypatch.setattr(sync_runner, "current_login", lambda: "f05_boot")
    assert _get(api.url("/desktop/bootstrap?route=/"))[0] == 200
    assert started == [], "живой синк того же человека перезапущен без пароля"



def test_local_user_names_come_from_the_local_copy(api):
    """ФИО и обращение — из копии, тем же правилом, что вход на бою."""
    _seed_role("f06_names", "teacher")
    full, greet = local_api.local_user_names("f06_names")
    assert full == "Тестов Тест", full
    assert greet, "обращение пустое — Вектор поздоровается без имени"
    assert local_api.local_user_names("nobody_here") == ("", "")


def test_bootstrap_hands_the_full_name_not_the_login(api, monkeypatch):
    """🔥 Живой прогон 01.10.2026: после перезапуска программы в меню стоял ЛОГИН вместо
    ФИО, а Вектор здоровался без имени — оболочка клала логин в поле имени `gb.user`."""
    monkeypatch.setattr(local_api, "_session_login", lambda: "f06_boot")
    monkeypatch.setattr(local_api, "_saved_session_alive", lambda: True)
    monkeypatch.setattr(local_api, "switch_user_db", lambda login, authenticated=False: True)
    monkeypatch.setattr(local_api, "issue_local_session", lambda login, role: ("tok", "ref"))
    monkeypatch.setattr(local_api, "_resume_sync", lambda login, role: None)
    monkeypatch.setattr(local_api, "local_user_names",
                        lambda login: ("Ivanov Ivan Petrovich", "Ivan Petrovich"))
    code, body = _get(api.url("/desktop/bootstrap?route=/"))
    assert code == 200
    assert b"Ivanov Ivan Petrovich" in body, "в gb.user снова логин вместо ФИО"
    assert b"Ivan Petrovich" in body.replace(b"Ivanov Ivan Petrovich", b"")

# ── Озвучка Вектора через бой (26.09.2026: ключ ИИ в копию больше не приезжает) ──────
def test_local_server_voices_the_vector_through_prod(api):
    """Проводка: локальный сервер ставит в `vector_llm` боевую озвучку. Без неё, после
    того как ключ GigaChat перестал утекать в копию, Вектор в программе молча перестал бы
    переформулировать ответы — ни ошибки, ни предупреждения."""
    from app import vector_llm
    assert vector_llm._remote is local_api._remote_vector, \
        "локальный сервер не подключил озвучку Вектора через сервер"


def test_remote_vector_asks_prod_as_the_signed_in_person(monkeypatch):
    import httpx
    sent = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"text": "переформулировано"}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, json=json, headers=headers)
        return _Resp()
    monkeypatch.setattr(local_api, "_remote_auth", lambda: ("https://prod.example", "TOK", ""))
    monkeypatch.setattr(httpx, "post", fake_post)
    out = local_api._remote_vector("voice", {"facts": "ф", "locale": "en"})
    assert out == "переформулировано"
    assert sent["url"] == "https://prod.example/vector/voice"
    assert sent["json"] == {"facts": "ф", "locale": "en", "mode": "voice"}
    assert sent["headers"]["Authorization"] == "Bearer TOK"


def test_local_server_asks_prod_about_the_server_state(api):
    """Проводка: без хука Вектор в программе снова описывал бы ноутбук админа."""
    from app.routers.web import vector as web_vector
    assert web_vector._remote_server_state is local_api._remote_server_state, \
        "локальный сервер не подключил ответ о состоянии сервера с боя"


def test_remote_server_state_asks_prod_vector_as_the_signed_in_person(monkeypatch):
    import httpx
    import vector_nlu
    sent = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"text": "Сервер: …", "intent": "server_state"}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, json=json, headers=headers)
        return _Resp()
    monkeypatch.setattr(local_api, "_remote_auth", lambda: ("https://prod.example", "TOK", ""))
    monkeypatch.setattr(httpx, "post", fake_post)
    assert local_api._remote_server_state()["intent"] == "server_state"
    assert sent["url"] == "https://prod.example/web/vector/ask"
    assert sent["headers"]["Authorization"] == "Bearer TOK"
    #Вопрос обязан разбираться боем как server_state — иначе бой ответит про другое.
    assert vector_nlu.classify(sent["json"]["message"])["intent"] == "server_state"


def test_remote_server_state_without_a_session_is_none(monkeypatch):
    monkeypatch.setattr(local_api, "_remote_auth", lambda: ("https://prod.example", "", "expired"))
    assert local_api._remote_server_state() is None


def test_remote_vector_without_a_session_answers_nothing(monkeypatch):
    """Нет входа или сети — пустой ответ: Вектор отдаст факты без переформулировки."""
    monkeypatch.setattr(local_api, "_remote_auth", lambda: ("https://prod.example", "", "expired"))
    assert local_api._remote_vector("voice", {"facts": "ф"}) == ""
