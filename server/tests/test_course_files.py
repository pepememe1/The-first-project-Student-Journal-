"""
test_course_files.py — файл-материал курса (аудит 22.09.2026, F-26).

Файл идёт через ту же инфраструктуру вложений, что у мессенджера, но ВЛАДЕЛЕЦ у него —
курс (`course:<id>`), а не беседа. Отсюда то, что здесь держится:
- грузить может только тот, кто правит курс; смотреть — только тот, кто курс видит;
- файл одного курса нельзя «перевесить» на другой курс по id вложения;
- через мессенджер файл курса не скачать и не вложить в сообщение — такой беседы нет;
- без хранилища — честный 503, а не молча принятая загрузка;
- удалили материал — файл уходит из хранилища (у материала, в отличие от сообщения,
  нет причины хранить оригинал для модерации).

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН: убрать `_require_edit` из подписи — краснеет «студент не
грузит»; убрать сверку владельца в `add_material` — краснеет «чужой курс»; убрать
`_can_view` из выдачи ссылки — краснеет «чужой студент»; не звать `_drop_course_file` —
краснеет «удаление убирает файл».
"""
import pytest

from conftest import make_admin, make_teacher, assign_teacher
from test_courses import _make_student, _new_course


@pytest.fixture
def s3(monkeypatch):
    """Хранилище «настроено» (S3-режим без сети): подписи считаются локально, HEAD и
    удаление подменены — проверяем наши правила, а не чужой сервис."""
    from app import storage
    monkeypatch.setattr(storage, "MODE", "s3")
    for k, v in (("ENDPOINT", "https://s3.example"), ("BUCKET", "gb"),
                 ("ACCESS_KEY", "key"), ("SECRET_KEY", "secret")):
        monkeypatch.setattr(storage, k, v)
    monkeypatch.setattr(storage, "head_object", lambda key: {})
    removed = []
    monkeypatch.setattr(storage, "delete_object", lambda key: removed.append(key) or True)
    return removed


def _world(client):
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    assign_teacher(client, admin, "teach:teacher1", "К74-1", "Математика")
    assign_teacher(client, admin, "teach:teacher1", "К75-1", "Математика")
    cid = _new_course(client, teacher, group="К74-1")
    return admin, teacher, cid


def _upload(client, headers, cid, name="лекция.pdf", mime="application/pdf"):
    r = client.post(f"/web/courses/{cid}/files/sign", headers=headers,
                    json={"name": name, "size": 1234, "mime": mime})
    assert r.status_code == 200, r.text
    att = r.json()["attachment_id"]
    assert client.post(f"/web/messenger/uploads/{att}/done", headers=headers).status_code == 200
    return att


def _add_file(client, headers, cid, att, title=""):
    return client.post(f"/web/courses/{cid}/materials", headers=headers,
                       json={"title": title, "kind": "file", "attachment_id": att})


def test_author_attaches_file_and_student_downloads_it(client, s3):
    admin, teacher, cid = _world(client)
    att = _upload(client, teacher, cid)
    r = _add_file(client, teacher, cid, att)
    assert r.status_code == 200, r.text
    mid = r.json()["id"]

    student = _make_student(client, admin, login="s_in", group="К74-1")
    course = client.get(f"/web/courses/{cid}", headers=student).json()
    m = next(x for x in course["materials"] if x["id"] == mid)
    assert m["kind"] == "file" and m["title"] == "лекция.pdf"
    assert m["file"] == {"name": "лекция.pdf", "size": 1234, "mime": "application/pdf"}
    assert m["url"] == "", "в материал утёк id вложения вместо пустой ссылки"

    r = client.get(f"/web/courses/{cid}/materials/{mid}/file", headers=student)
    assert r.status_code == 200, r.text
    assert r.json()["url"].startswith("https://s3.example/")


def test_student_cannot_upload_to_course(client, s3):
    admin, teacher, cid = _world(client)
    student = _make_student(client, admin, login="s_in", group="К74-1")
    r = client.post(f"/web/courses/{cid}/files/sign", headers=student,
                    json={"name": "x.pdf", "size": 10, "mime": "application/pdf"})
    assert r.status_code == 403


def test_other_group_student_cannot_get_file_link(client, s3):
    admin, teacher, cid = _world(client)
    mid = _add_file(client, teacher, cid, _upload(client, teacher, cid)).json()["id"]
    other = _make_student(client, admin, login="s_out", group="К99-9")
    assert client.get(f"/web/courses/{cid}/materials/{mid}/file", headers=other).status_code == 403


def test_file_of_one_course_cannot_be_attached_to_another(client, s3):
    admin, teacher, cid = _world(client)
    other_cid = _new_course(client, teacher, title="Второй", group="К75-1")
    att = _upload(client, teacher, other_cid)
    r = _add_file(client, teacher, cid, att)
    assert r.status_code == 400, "файл чужого курса прицепился по id вложения"


def test_unconfirmed_upload_is_not_a_material(client, s3):
    admin, teacher, cid = _world(client)
    r = client.post(f"/web/courses/{cid}/files/sign", headers=teacher,
                    json={"name": "x.pdf", "size": 10, "mime": "application/pdf"})
    att = r.json()["attachment_id"]
    assert _add_file(client, teacher, cid, att).status_code == 400


def test_messenger_attachment_cannot_become_course_file(client, s3):
    """Вложение беседы — не файл курса: иначе личный файл из переписки публиковался бы
    всей группе одним запросом."""
    admin, teacher, cid = _world(client)
    conv = client.post("/web/messenger/chats/saved", headers=teacher).json()["conversation_id"]
    r = client.post("/web/messenger/uploads/sign", headers=teacher,
                    json={"conversation_id": conv, "name": "личное.pdf", "size": 10,
                          "mime": "application/pdf"})
    assert r.status_code == 200, r.text
    att = r.json()["attachment_id"]
    client.post(f"/web/messenger/uploads/{att}/done", headers=teacher)
    assert _add_file(client, teacher, cid, att).status_code == 400


def test_course_file_is_not_reachable_through_messenger(client, s3):
    """Ссылку выдаёт только курс: у мессенджера доступ — участие в беседе, а беседы
    `course:<id>` не существует. И вложить файл курса в сообщение нельзя."""
    admin, teacher, cid = _world(client)
    att = _upload(client, teacher, cid)
    _add_file(client, teacher, cid, att)
    student = _make_student(client, admin, login="s_in", group="К74-1")
    r = client.get(f"/web/messenger/attachments/{att}/url", headers=student)
    assert r.status_code in (403, 404), r.text
    conv = client.post("/web/messenger/chats/saved", headers=teacher).json()["conversation_id"]
    r = client.post(f"/web/messenger/chats/{conv}/messages", headers=teacher,
                    json={"body": "", "attachment_id": att})
    assert r.status_code == 400, "файл курса ушёл вложением в беседу"


def test_no_storage_is_an_honest_503(client, monkeypatch):
    from app import storage
    monkeypatch.setattr(storage, "MODE", "off")
    monkeypatch.setattr(storage, "ENDPOINT", "")
    admin, teacher, cid = _world(client)
    r = client.post(f"/web/courses/{cid}/files/sign", headers=teacher,
                    json={"name": "x.pdf", "size": 10, "mime": "application/pdf"})
    assert r.status_code == 503


def test_executable_is_refused_by_the_shared_whitelist(client, s3):
    admin, teacher, cid = _world(client)
    r = client.post(f"/web/courses/{cid}/files/sign", headers=teacher,
                    json={"name": "setup.exe", "size": 10,
                          "mime": "application/x-msdownload"})
    assert r.status_code == 415


def test_deleting_material_removes_the_file(client, s3):
    from app.db import SessionLocal
    from app.models import Attachment
    admin, teacher, cid = _world(client)
    att = _upload(client, teacher, cid)
    mid = _add_file(client, teacher, cid, att).json()["id"]
    assert client.delete(f"/web/courses/{cid}/materials/{mid}", headers=teacher).status_code == 200
    assert s3 and s3[0].endswith(att), "объект в хранилище остался сиротой"
    with SessionLocal() as db:
        assert db.query(Attachment).filter(Attachment.id == att).first() is None
