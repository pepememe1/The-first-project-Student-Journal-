# -*- coding: utf-8 -*-
"""
test_asvs_hardening.py — сторожа требований OWASP ASVS 5.0, закрытых или впервые
поставленных под тест 07.10.2026 (таблица вердиктов — docs/security/asvs-baseline.json).

Здесь лежит то, у чего нет своего тематического файла. Каждый тест назван требованием,
которое он держит, и проверяет ПОВЕДЕНИЕ, а не наличие строки в коде: строку в коде
сверяет сам сторож таблицы (`tests/test_asvs_baseline.py`), а «done» без теста поведения
таблица не принимает.
"""
import io
import json
import pathlib
import re
import zipfile

import pytest

from conftest import make_admin

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
WEB = {"X-Client": "web"}


def _student(client, admin, login="s1", password="studpass1"):
    r = client.post("/web/admin/students", json={
        "login": login, "surname": "Иванова", "name": "Мария", "group": "К-1",
        "password": password}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": password}, headers=WEB)
    assert r.status_code == 200, r.text
    return r.json()


# ── V14.3.2: личные ответы не оседают в кэше браузера ─────────────────────────────────

PRIVATE = ["/me/prefs", "/me/sessions", "/web/terms", "/web/messenger/chats", "/sync/head",
           "/admin/online", "/connect/status", "/vector/voice", "/web/net-takoy-ruchki"]


@pytest.mark.parametrize("path", PRIVATE)
def test_private_api_answers_are_never_cached(client, path):
    """Отказ без входа — тоже ответ личного раздела: правило стоит на адресе, а не на
    успехе. Иначе первая же ручка, отдавшая 200, осталась бы без запрета."""
    r = client.get(path)
    assert r.headers.get("Cache-Control") == "no-store", (path, r.status_code, dict(r.headers))


def test_private_answers_with_data_are_not_cached_either(client):
    admin = make_admin(client)
    tok = _student(client, admin)
    me = {"Authorization": f"Bearer {tok['access_token']}", **WEB}
    for path in ("/me/prefs", "/me/sessions", "/web/student/overview"):
        r = client.get(path, headers=me)
        assert r.status_code == 200 and r.headers.get("Cache-Control") == "no-store", (path, r.text[:80])
    #И сам ответ со свежим токеном — тоже: он и есть самое ценное в кэше.
    r = client.post("/auth/login", json={"login": "s1", "password": "studpass1"}, headers=WEB)
    assert r.status_code == 200 and r.headers.get("Cache-Control") == "no-store"


#`/app/updates` сюда не входит намеренно: при бандле в каталоге разработчика ручка кладёт
#рядом с ним кэш манифеста — тест не должен оставлять файлы в рабочем дереве.
@pytest.mark.parametrize("path", ["/health", "/desktop/updates", "/"])
def test_public_answers_keep_their_own_caching(client, path):
    """Обратная сторона: публичное и страницы сайта запрет не получают — иначе обновления
    и ассеты перестали бы кэшироваться вовсе, а запрет «на всё» перестают замечать."""
    r = client.get(path)
    assert r.headers.get("Cache-Control") != "no-store", (path, dict(r.headers))


def test_the_private_rule_is_everything_except_the_named_public():
    """Правило — «всё под API, кроме названного публичного». Новый личный раздел получает
    запрет сам; проверяем это на КАЖДОМ существующем маршруте приложения."""
    from app import main
    assert main._is_private_api_path("/web/admin/overview")
    assert main._is_private_api_path("/me") and main._is_private_api_path("/auth/login")
    assert not main._is_private_api_path("/downloads/GradeBookAI.exe")
    assert not main._is_private_api_path("/teacher/journal"), "страница сайта — не API"
    assert not main._is_private_api_path("/application-form"), "«app» сравнивается сегментом"
    #Полный обход, а не плоский `app.routes`: подключённые роутеры лежат вложенными, и
    #плоский перебор видит семь маршрутов из четырёхсот (так этот тест и ослеп в первый раз).
    from test_spa_fallback import _all_paths
    private = public = 0
    for path in _all_paths(main.app.router):
        if not path.startswith("/") or not main._is_api_path(path):
            continue
        if main._is_private_api_path(path):
            private += 1
        else:
            public += 1
            assert path.strip("/").split("/")[0] in main._PUBLIC_API_PREFIXES, path
    assert private > 100 and public >= 5, (private, public)


def _all_routes(router) -> list:
    """Сами маршруты, а не только адреса — тем же полным обходом, что `_all_paths`."""
    out = []
    for r in getattr(router, "routes", []):
        if getattr(r, "path", "") and getattr(r, "dependant", None) is not None:
            out.append(r)
        nested = getattr(r, "original_router", None) or (r if hasattr(r, "routes") else None)
        if nested is not None and nested is not router:
            out.extend(_all_routes(nested))
    return out


def _reads_the_token(dependant) -> bool:
    """Читает ли ручка (сама или любой её зависимостью) заголовок Authorization."""
    for p in dependant.header_params:
        if (getattr(p, "alias", "") or getattr(p, "name", "")).lower() == "authorization":
            return True
    return any(_reads_the_token(d) for d in dependant.dependencies)


def test_nothing_behind_a_login_lives_under_a_public_prefix():
    """Обратная сторона правила (ручная проверка 07.10.2026): публичный префикс назван
    целиком («app», «desktop», «public»…), и ручка со входом, однажды заведённая под ним,
    молча осталась бы без запрета кэша — личный ответ в кэше общего компьютера. Смотрим не
    на адрес, а на то, читает ли ручка токен."""
    from app import main
    behind_login = [r for r in _all_routes(main.app.router)
                    if main._is_api_path(r.path) and _reads_the_token(r.dependant)]
    assert len(behind_login) > 100, f"обход ослеп: ручек со входом найдено {len(behind_login)}"
    wrong = sorted({r.path for r in behind_login if not main._is_private_api_path(r.path)})
    assert not wrong, f"ручки со входом под публичным префиксом (ответ кэшируется): {wrong}"


def test_the_login_detector_can_tell_a_guarded_route_from_an_open_one():
    from fastapi import APIRouter, Depends
    from app.deps import get_current_user, require_admin
    probe = APIRouter()

    @probe.get("/app/open")
    def _open():
        return {}

    @probe.get("/app/mine")
    def _mine(user=Depends(get_current_user)):
        return {}

    @probe.get("/app/admin-only")
    def _admin_only(user=Depends(require_admin)):
        return {}

    seen = {r.path: _reads_the_token(r.dependant) for r in _all_routes(probe)}
    assert seen == {"/app/open": False, "/app/mine": True, "/app/admin-only": True}, seen


# ── V13.4.4: TRACE не поддерживается ──────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/", "/health", "/web/terms", "/auth/login", "/teacher"])
def test_trace_is_not_supported(client, path):
    r = client.request("TRACE", path, headers={"X-Secret-Probe": "should-not-echo"})
    assert r.status_code in (404, 405), (path, r.status_code)
    assert "should-not-echo" not in r.text and "x-secret-probe" not in r.text.lower()


# ── V16.4.1: в журнал ложится одна строка ─────────────────────────────────────────────

FORGED = "ivanov\r\n2026-10-07 INFO login.ok admin вторая\x00строка\tконец"


def test_a_log_entry_is_always_one_line():
    from app import events
    clean = events.one_line(FORGED)
    assert not re.search(r"[\x00-\x1f\x7f-\x9f  ]", clean), repr(clean)
    #Перевод строки не выброшен молча, а ПОКАЗАН — попытка сама по себе сигнал.
    assert clean == "ivanov\\r\\n2026-10-07 INFO login.ok admin\\nвтораястрока конец"
    assert events.one_line(None) == "" and events.one_line(42) == "42"
    assert events.one_line("Обычная запись — без изменений, ё и 中文 тоже") == \
        "Обычная запись — без изменений, ё и 中文 тоже"


def test_forged_lines_do_not_reach_either_journal(client):
    """Логин неудачного входа присылает человек — и он ложится в оба журнала: в живой
    монитор администратора и в постоянный журнал безопасности."""
    from app import audit, events
    from app.db import SessionLocal
    from app.models import AuditEvent
    make_admin(client)
    client.post("/auth/login", json={"login": FORGED, "password": "x" * 9}, headers=WEB)
    events.record("warn", "проба\nподделка", FORGED, login=FORGED)
    db = SessionLocal()
    try:
        audit.log(db, actor=FORGED, action="probe", target=FORGED, detail=FORGED, device=FORGED)
        rows = db.query(AuditEvent).all()
        assert any(r.action == "probe" for r in rows)
        for r in rows:
            for field in (r.actor, r.target, r.detail, r.device, r.action, r.role, r.level):
                assert not re.search(r"[\r\n  \x00]", field or ""), (r.action, repr(field))
        #Цепочка целостности считается по тому, что ЛЕЖИТ в базе: после чистки она сходится.
        report = audit.verify_chain(db)
        assert report.get("ok", report.get("status") == "ok"), report
    finally:
        db.close()
    for e in events.recent(0)["events"]:
        for field in (e["kind"], e["message"], e["login"]):
            assert not re.search(r"[\r\n  \x00]", field), repr(field)


# ── V5.2.3: архив импорта проверяется ДО распаковки ───────────────────────────────────

def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_an_archive_bomb_is_refused_before_unpacking(client, monkeypatch):
    from app import data_transfer as DT
    admin = make_admin(client)
    monkeypatch.setattr(DT, "MAX_ARCHIVE_UNPACKED", 1024 * 1024)
    #Пять мегабайт нулей сжимаются в пять килобайт — настоящая «бомба» в миниатюре.
    bomb = _zip({"groups.json": b"[" + b" " * (5 * 1024 * 1024) + b"]"})
    assert len(bomb) < 20_000

    def boom(*a, **k):
        raise AssertionError("архив начали распаковывать, не проверив объявленный размер")
    #Обе двери чтения: файлы архива продукт читает через `open`, а `read` закрыт на случай,
    #если кто-то вернёт прежний вызов.
    monkeypatch.setattr(zipfile.ZipFile, "read", boom)
    monkeypatch.setattr(zipfile.ZipFile, "open", boom)
    for url, extra in (("/web/admin/data/inspect", {}), ("/web/admin/data/import", {"sets": "groups"})):
        r = client.post(url, files={"file": ("x.zip", bomb, "application/zip")}, data=extra,
                        headers=admin)
        assert r.status_code == 400 and "МБ" in r.json()["detail"], (url, r.text)


def _lying_archive(real: int, declared: int) -> bytes:
    """Архив, чьё оглавление объявляет `declared` байт, а поток разворачивается в `real`.
    Оглавление пишет приславший: проверка по нему одному верит на слово."""
    import struct
    blob = bytearray(_zip({"groups.json": b"[" + b" " * real + b"]"}))
    for sig, off in ((b"PK\x01\x02", 24), (b"PK\x03\x04", 22)):
        at = blob.find(sig)
        assert at >= 0, sig
        struct.pack_into("<I", blob, at + off, declared)
    return bytes(blob)


def test_an_archive_that_lies_about_its_size_is_not_unpacked_in_full():
    """Объявлено десять байт, внутри двадцать четыре мегабайта: предел по оглавлению такой
    архив проходит, и защищает уже само чтение — в память не должно лечь больше объявленного."""
    import tracemalloc
    from app import data_transfer as DT
    real = 24 * 1024 * 1024
    blob = _lying_archive(real, 10)
    assert len(blob) < 100_000
    assert zipfile.ZipFile(io.BytesIO(blob)).infolist()[0].file_size == 10

    class _NothingToWrite:          #до записи дело дойти не должно — только итоговый commit
        def commit(self):
            pass

    for call in (lambda: DT.inspect_zip(blob),
                 lambda: DT.import_zip(_NothingToWrite(), blob, ["groups"],
                                       "2026-10-07T00:00:00")):
        tracemalloc.start()
        try:
            out = call()
            _cur, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        #Настоящая распаковка дала бы десятки мегабайт; честное чтение — килобайты.
        assert peak < real // 8, f"в память легло {peak // 1024} КБ при объявленных 10 байтах"
        assert "groups" not in (out.get("written") or {}), out


def test_the_bounded_reader_returns_an_honest_file_whole():
    from app import data_transfer as DT
    body = b"[" + b"1," * 300_000 + b"1]"
    z = zipfile.ZipFile(io.BytesIO(_zip({"a.json": body, "empty.json": b""})))
    assert DT._read_member(z, "a.json") == body
    assert DT._read_member(z, "empty.json") == b""


def test_an_archive_with_too_many_files_is_refused(client):
    from app import data_transfer as DT
    admin = make_admin(client)
    many = _zip({f"f{i}.json": "[]" for i in range(DT.MAX_ARCHIVE_FILES + 1)})
    r = client.post("/web/admin/data/inspect", files={"file": ("x.zip", many, "application/zip")},
                    headers=admin)
    assert r.status_code == 400 and "файлов" in r.json()["detail"], r.text


def test_an_honest_export_still_imports(client):
    """Пределы не задевают настоящую выгрузку: снять и тут же посмотреть состав."""
    admin = make_admin(client)
    _student(client, admin)
    blob = client.get("/web/admin/data/export", headers=admin).content
    r = client.post("/web/admin/data/inspect", files={"file": ("x.zip", blob, "application/zip")},
                    headers=admin)
    assert r.status_code == 200 and r.json()["datasets"], r.text


# ── V7.4.2, V7.2.4: удалённый человек и новый вход ────────────────────────────────────

def test_a_deleted_account_is_out_on_the_next_request(client):
    admin = make_admin(client)
    tok = _student(client, admin)
    me = {"Authorization": f"Bearer {tok['access_token']}", **WEB}
    assert client.get("/me/prefs", headers=me).status_code == 200
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        db.query(User).filter(User.login == "s1").update({"deleted": True})
        db.commit()
    finally:
        db.close()
    assert client.get("/me/prefs", headers=me).status_code == 401
    r = client.post("/auth/refresh", json={"refresh_token": tok["refresh_token"]}, headers=WEB)
    assert r.status_code == 401, r.text


def test_every_login_gets_its_own_session_token(client):
    from jose import jwt
    admin = make_admin(client)
    a = _student(client, admin)
    b = client.post("/auth/login", json={"login": "s1", "password": "studpass1"}, headers=WEB).json()
    ids = [jwt.get_unverified_claims(t["access_token"]).get("jti") for t in (a, b)]
    assert all(ids) and ids[0] != ids[1], ids
    assert a["access_token"] != b["access_token"] and a["refresh_token"] != b["refresh_token"]


def test_a_token_signed_with_another_algorithm_is_refused(client):
    """V9.1.3: алгоритм подписи задан сервером; «none» и подмена алгоритма не проходят."""
    import base64
    admin = make_admin(client)
    tok = _student(client, admin)["access_token"]
    head, payload, _sig = tok.split(".")
    none_head = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    for forged in (f"{none_head}.{payload}.", f"{none_head}.{payload}.{_sig}", f"{head}.{payload}.AAAA"):
        r = client.get("/me/prefs", headers={"Authorization": f"Bearer {forged}", **WEB})
        assert r.status_code == 401, forged[:40]


# ── V1.2.4, V1.2.5, V5.3.2: имена и команды собираются не из строк человека ───────────

def test_ddl_identifiers_are_checked_not_trusted():
    from app import db
    assert db._ddl_ident("messages") == "messages"
    for bad in ('users; DROP TABLE users', 'a"b', "x' OR '1'='1", "name with space", "", None):
        with pytest.raises(ValueError, match="недопустимое имя"):
            db._ddl_ident(bad)


def test_the_server_never_runs_a_shell_string():
    """Ни одного запуска через оболочку и ни одного исполнения строки как кода во всём
    `server/app`. Команды, где они есть, собираются СПИСКОМ аргументов."""
    import ast
    bad = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = ast.unparse(node.func)
            if name in ("os.system", "os.popen", "eval", "exec", "subprocess.getoutput",
                        "subprocess.getstatusoutput"):
                bad.append(f"{path.relative_to(APP)}:{node.lineno} {name}()")
            if any(k.arg == "shell" and getattr(k.value, "value", None) is True
                   for k in node.keywords):
                bad.append(f"{path.relative_to(APP)}:{node.lineno} shell=True")
    assert not bad, "\n".join(bad)
    #Обратный ход: разбор видит обе формы, когда они есть.
    probe = ast.parse("import subprocess, os\nsubprocess.run(cmd, shell=True)\nos.system(cmd)")
    calls = [ast.unparse(n.func) for n in ast.walk(probe) if isinstance(n, ast.Call)]
    assert calls == ["subprocess.run", "os.system"]


def test_an_attachment_id_cannot_leave_its_folder():
    """V5.3.2: имя файла вложения на диске собирается из id, и «../» в нём не выживает."""
    from app import storage
    root = pathlib.Path(storage.local_path("probe")).resolve().parent
    for evil in ("../../etc/passwd", "..\\..\\windows\\win.ini", "a/b/c", "x\x00y", "/abs/olute"):
        got = pathlib.Path(storage.local_path(evil)).resolve()
        assert got.parent == root, (evil, str(got))
    #Обратный ход: без чистки тот же id уводит из папки — проверка это видит.
    import os
    raw = pathlib.Path(os.path.join(storage.LOCAL_DIR, "../../etc/passwd")).resolve()
    assert raw.parent != root
