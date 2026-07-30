"""
test_data_transfer.py — выгрузка/загрузка данных админкой (ZIP) = она же резервная копия.
`/web/admin/data/{datasets,export,inspect,import}`.

Это операция над БОЕВЫМИ данными, поэтому тесты закрепляют в первую очередь границы
безопасности, а не «сохранилось/загрузилось»:
  • пароли НЕ покидают сервер и НЕ обнуляются при импорте (ровно эта авария случилась на
    бою: пустое поле вернулось поверх настоящего хеша и обнулило вход 10 студентам);
  • импорт СЛИВАЕТ, а не «очищает и заливает» — иначе восстановление из старого архива
    удаляло бы всё, что появилось после его снятия;
  • метку времени ставит сервер (иначе LWW на десктопах счёл бы восстановленное устаревшим);
  • ничего не пишется без явного выбора наборов;
  • доступ — только администратору.
"""
import io
import json
import zipfile

import pytest

from conftest import make_admin, make_teacher


def _add_student(client, admin, login="ivanov", group="ИС-21", surname="Иванов"):
    from app.security import hash_password
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password("secret123"), "surname": surname, "name": "Пётр",
        "full_name": f"{surname} Пётр", "group_name": group,
    }]}}, headers=admin)
    assert r.status_code == 200, r.text


def _export(client, admin, sets=""):
    r = client.get("/web/admin/data/export", params={"sets": sets} if sets else {},
                   headers=admin)
    assert r.status_code == 200, r.text
    return r.content


def _zip_json(blob, fname):
    return json.loads(zipfile.ZipFile(io.BytesIO(blob)).read(fname).decode("utf-8"))


# ── Выгрузка ────────────────────────────────────────────────────────────────────────
def test_export_is_a_zip_with_separate_files_and_manifest(client):
    """«При экспорте — зип-архив, где все данные по отдельности»: по файлу на набор."""
    admin = make_admin(client)
    _add_student(client, admin)
    blob = _export(client, admin)
    names = set(zipfile.ZipFile(io.BytesIO(blob)).namelist())
    assert "manifest.json" in names
    assert "students.json" in names and "groups.json" in names
    manifest = _zip_json(blob, "manifest.json")
    assert manifest["datasets"]["students"] == 1
    assert manifest["labels"]["students"] == "Студенты"


def test_export_never_contains_password_hashes(client):
    """Архив уходит на рабочий стол, в почту и в облако. Хеш — предмет офлайн-перебора,
    поэтому в выгрузке его нет НИКОГДА."""
    admin = make_admin(client)
    _add_student(client, admin)
    blob = _export(client, admin)
    rows = _zip_json(blob, "students.json")
    assert rows and "password_hash" not in rows[0], rows[0]
    #И на всякий случай — по всему архиву: поле не должно просочиться ни в один файл.
    z = zipfile.ZipFile(io.BytesIO(blob))
    for n in z.namelist():
        assert b"password_hash" not in z.read(n), n


def test_export_can_be_limited_to_picked_sets(client):
    admin = make_admin(client)
    _add_student(client, admin)
    blob = _export(client, admin, sets="students")
    names = set(zipfile.ZipFile(io.BytesIO(blob)).namelist())
    assert names == {"students.json", "manifest.json"}, names


def test_export_skips_deleted_rows(client):
    """Надгробия синка в архив не идут: иначе импорт «восстановил» бы удалённых как удалённых."""
    admin = make_admin(client)
    _add_student(client, admin)
    client.post("/sync/push", json={"changes": {"users": [
        {"id": "stud:ivanov", "role": "student", "login": "ivanov", "deleted": True}]}},
        headers=admin)
    assert _zip_json(_export(client, admin), "students.json") == []


# ── Осмотр архива ───────────────────────────────────────────────────────────────────
def test_inspect_reports_contents_without_writing(client):
    """«При импорте вылезет окно с данными, которые есть в файле» — этот шаг ничего не пишет."""
    admin = make_admin(client)
    _add_student(client, admin)
    blob = _export(client, admin)
    r = client.post("/web/admin/data/inspect",
                    files={"file": ("d.zip", blob, "application/zip")}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    got = {d["name"]: d["count"] for d in body["datasets"]}
    assert got["students"] == 1
    assert body["note"], "предупреждение про пароли обязано доехать до интерфейса"


def test_inspect_rejects_garbage(client):
    admin = make_admin(client)
    r = client.post("/web/admin/data/inspect",
                    files={"file": ("x.zip", b"not a zip at all", "application/zip")},
                    headers=admin)
    assert r.status_code == 400


# ── Импорт ──────────────────────────────────────────────────────────────────────────
def test_import_writes_only_picked_sets(client):
    """Отмечены студенты — предметы из того же архива не трогаем."""
    admin = make_admin(client)
    _add_student(client, admin)
    assert client.post("/web/admin/subjects", json={"name": "Математика"},
                       headers=admin).status_code in (200, 409)
    blob = _export(client, admin)

    #Чистим предметы, затем импортируем ТОЛЬКО студентов — предмет вернуться не должен.
    client.request("DELETE", "/web/admin/subjects", json={"name": "Математика"},
                   headers=admin)
    r = client.post("/web/admin/data/import",
                    files={"file": ("d.zip", blob, "application/zip")},
                    data={"sets": "students"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["written"] == {"students": 1}


def test_import_requires_explicit_choice(client):
    """Без выбора наборов — отказ: «залить всё, что было в файле» не может быть умолчанием
    у операции, меняющей боевые данные."""
    admin = make_admin(client)
    _add_student(client, admin)
    blob = _export(client, admin)
    r = client.post("/web/admin/data/import",
                    files={"file": ("d.zip", blob, "application/zip")},
                    data={"sets": ""}, headers=admin)
    assert r.status_code == 400


def test_import_does_not_blank_existing_password(client):
    """САМОЕ ВАЖНОЕ. В архиве пароля нет — импорт обязан сохранить уже имеющийся хеш.

    Иначе восстановление справочника выбивало бы вход всем существующим людям. Ровно эта
    авария (пустое поле поверх настоящего хеша) уже случилась на бою через синк."""
    admin = make_admin(client)
    _add_student(client, admin)
    blob = _export(client, admin)
    r = client.post("/web/admin/data/import",
                    files={"file": ("d.zip", blob, "application/zip")},
                    data={"sets": "students"}, headers=admin)
    assert r.status_code == 200, r.text
    #Вход обязан продолжать работать ТЕМ ЖЕ паролем.
    r = client.post("/auth/login", json={"login": "ivanov", "password": "secret123"})
    assert r.status_code == 200, r.text


def test_import_ignores_password_hash_from_file(client):
    """Хеш, подложенный в архив руками, этим путём в базу не попадает."""
    admin = make_admin(client)
    _add_student(client, admin)
    from app.security import hash_password
    evil = hash_password("подменённый")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("students.json", json.dumps([{
            "id": "stud:ivanov", "login": "ivanov", "role": "student",
            "surname": "Иванов", "name": "Пётр", "group_name": "ИС-21",
            "password_hash": evil}], ensure_ascii=False))
    r = client.post("/web/admin/data/import",
                    files={"file": ("d.zip", buf.getvalue(), "application/zip")},
                    data={"sets": "students"}, headers=admin)
    assert r.status_code == 200, r.text
    #Подменённый пароль НЕ работает, старый — работает.
    assert client.post("/auth/login",
                       json={"login": "ivanov", "password": "подменённый"}).status_code == 401
    assert client.post("/auth/login",
                       json={"login": "ivanov", "password": "secret123"}).status_code == 200


def test_import_merges_and_keeps_newer_records(client):
    """Слияние, а не «очистить и залить»: то, что появилось ПОСЛЕ снятия архива, остаётся."""
    admin = make_admin(client)
    _add_student(client, admin, login="ivanov", surname="Иванов")
    blob = _export(client, admin)                 #архив знает только Иванова
    _add_student(client, admin, login="petrov", surname="Петров")

    r = client.post("/web/admin/data/import",
                    files={"file": ("d.zip", blob, "application/zip")},
                    data={"sets": "students"}, headers=admin)
    assert r.status_code == 200, r.text
    logins = {s["login"] for s in client.get("/web/admin/students", headers=admin).json()["students"]}
    assert {"ivanov", "petrov"} <= logins, logins


def test_import_role_comes_from_dataset_not_from_file(client):
    """Подменённый файл «студентов» не должен заводить администратора."""
    admin = make_admin(client)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("students.json", json.dumps([{
            "id": "stud:hack", "login": "hack", "role": "admin",
            "surname": "Взлом", "name": "Тест", "group_name": "ИС-21"}],
            ensure_ascii=False))
    r = client.post("/web/admin/data/import",
                    files={"file": ("d.zip", buf.getvalue(), "application/zip")},
                    data={"sets": "students"}, headers=admin)
    assert r.status_code == 200, r.text
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        assert db.get(User, "stud:hack").role == "student"
    finally:
        db.close()


def test_import_stamps_server_time(client):
    """Метку ставит сервер: со старой меткой LWW на десктопах счёл бы восстановленное
    устаревшим, и данные тут же проиграли бы локальным копиям (§4.3)."""
    admin = make_admin(client)
    _add_student(client, admin)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("students.json", json.dumps([{
            "id": "stud:ivanov", "login": "ivanov", "role": "student",
            "surname": "Иванов", "name": "Пётр", "group_name": "ИС-21",
            "updated_at": "2000-01-01T00:00:00+00:00"}], ensure_ascii=False))
    client.post("/web/admin/data/import",
                files={"file": ("d.zip", buf.getvalue(), "application/zip")},
                data={"sets": "students"}, headers=admin)
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        assert not db.get(User, "stud:ivanov").updated_at.startswith("2000")
    finally:
        db.close()


def test_broken_archive_gives_400_not_500(client):
    admin = make_admin(client)
    r = client.post("/web/admin/data/import",
                    files={"file": ("d.zip", b"\\x00\\x01broken", "application/zip")},
                    data={"sets": "students"}, headers=admin)
    assert r.status_code == 400


# ── Права ───────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,method", [
    ("/web/admin/data/datasets", "get"),
    ("/web/admin/data/export", "get"),
])
def test_read_endpoints_are_admin_only(client, path, method):
    admin = make_admin(client)
    teach = make_teacher(client, admin, subjects=["Математика"])
    assert getattr(client, method)(path, headers=teach).status_code == 403


def test_import_is_admin_only(client):
    admin = make_admin(client)
    teach = make_teacher(client, admin, subjects=["Математика"])
    blob = _export(client, admin)
    r = client.post("/web/admin/data/import",
                    files={"file": ("d.zip", blob, "application/zip")},
                    data={"sets": "students"}, headers=teach)
    assert r.status_code == 403
