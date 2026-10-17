"""
test_attachment_lifecycle.py — путь файла от подписи до чтения (аудит 17.10.2026).

━━ ЧТО БЫЛО ━━
• Подтверждение на пустой ответ хранилища ставило «готово»: подпись → без загрузки →
  `/done` давало карточку файла, которого нет, а настоящая загрузка в этот id уже
  запрещалась.
• Суточный потолок считался по ЗАЯВЛЕННОМУ размеру, а принималось до общего предела:
  девять подписей по байту и девять файлов по 25 МБ — 225 МБ при потолке 200.
• Локальная загрузка писала прямо в итоговый файл: запрос, задержавшийся до
  подтверждения, перезаписывал уже подтверждённый и отправленный документ.
• Чтение спрашивало ТЕКУЩИЙ режим хранилища: упало свободное место ниже порога —
  старые файлы переставали открываться; завели ключи S3 — их искали в бакете.
• Вкладки «Файлы» и «Медиа» не знали про «удалить у себя» и очистку истории.

⚠️ ОБРАТНЫЙ ХОД ПРОВЕРЕН на прежних `attachments.py` и `storage.py`: краснеют все
девять, каждый — на своём утверждении (законная загрузка в них — контрольная половина).
"""
import os

import pytest
from fastapi import HTTPException

from conftest import make_admin, make_teacher
from app.security import hash_password


def _student(client, admin, login="bob", name="Боб Бобов"):
    surname, given = name.split(" ", 1)
    r = client.post("/sync/push", json={"changes": {"users": [{
        "id": f"stud:{login}", "role": "student", "login": login,
        "password_hash": hash_password("studpass1"), "full_name": name,
        "surname": surname, "name": given, "group_name": "К-24",
    }]}}, headers=admin)
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"login": login, "password": "studpass1"})
    return f"stud:{login}", {"Authorization": f"Bearer {r.json()['access_token']}"}


def _world(client):
    admin = make_admin(client)
    a = make_teacher(client, admin)
    b_id, b = _student(client, admin)
    conv = client.post("/web/messenger/chats/group",
                       json={"title": "Файлы", "member_ids": [b_id]},
                       headers=a).json()["conversation_id"]
    return a, (b_id, b), conv


@pytest.fixture
def local(monkeypatch, tmp_path):
    """Локальное хранение в своём каталоге: ключей S3 нет, режим задан явно."""
    from app import storage
    monkeypatch.setattr(storage, "MODE", "local")
    monkeypatch.setattr(storage, "LOCAL_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "ENDPOINT", "")
    return tmp_path


def _s3(monkeypatch, head):
    from app import storage
    for k, v in (("MODE", "s3"), ("ENDPOINT", "https://s3.example"), ("BUCKET", "gb"),
                 ("ACCESS_KEY", "key"), ("SECRET_KEY", "secret")):
        monkeypatch.setattr(storage, k, v)
    monkeypatch.setattr(storage, "head_object", head)


def _sign(client, headers, conv, size, name="к.txt", mime="text/plain"):
    r = client.post("/web/messenger/uploads/sign", headers=headers,
                    json={"conversation_id": conv, "name": name, "size": size, "mime": mime})
    assert r.status_code == 200, r.text
    return r.json()


def _put_local(client, sign, data: bytes):
    return client.post(sign["url"], files={sign["form_field"]: ("к.txt", data, "text/plain")})


def _done(client, headers, att):
    return client.post(f"/web/messenger/uploads/{att}/done", headers=headers)


def test_confirm_without_upload_does_not_make_a_ready_file(client, local):
    a, _b, conv = _world(client)
    sign = _sign(client, a, conv, 10)
    att = sign["attachment_id"]

    r = _done(client, a, att)
    assert r.status_code == 409, f"подтвердили файл, которого нет: {r.text}"
    #Неготовое вложение к сообщению не приложить — карточки без файла не будет.
    assert client.post(f"/web/messenger/chats/{conv}/messages", headers=a,
                       json={"body": "", "attachment_id": att}).status_code == 400
    #И настоящая загрузка после неудачного подтверждения по-прежнему возможна.
    assert _put_local(client, sign, b"x" * 10).status_code == 200
    assert _done(client, a, att).status_code == 200


def test_storage_outage_is_a_retry_not_a_ready_file(client, monkeypatch):
    from app import storage

    def down(key):
        raise storage.StorageUnavailable("сеть")

    _s3(monkeypatch, down)
    a, _b, conv = _world(client)
    att = _sign(client, a, conv, 100, "к.pdf", "application/pdf")["attachment_id"]
    r = _done(client, a, att)
    assert r.status_code == 502, f"сбой хранилища принят за готовность: {r.text}"
    assert client.post(f"/web/messenger/chats/{conv}/messages", headers=a,
                       json={"body": "", "attachment_id": att}).status_code == 400
    #Хранилище ожило — тот же id подтверждается.
    monkeypatch.setattr(storage, "head_object", lambda key: {"size": 100, "mime": "application/pdf"})
    assert _done(client, a, att).status_code == 200


def test_missing_object_in_bucket_is_not_ready(client, monkeypatch):
    _s3(monkeypatch, lambda key: {})
    a, _b, conv = _world(client)
    att = _sign(client, a, conv, 100, "к.pdf", "application/pdf")["attachment_id"]
    assert _done(client, a, att).status_code == 409


def test_local_upload_cannot_exceed_the_declared_size(client, local):
    """Заявленный размер — резерв суточного потолка; больше него не принимаем."""
    a, _b, conv = _world(client)
    sign = _sign(client, a, conv, 10)
    r = _put_local(client, sign, b"x" * 11)
    assert r.status_code == 413, f"приняли файл больше заявленного: {r.text}"
    from app import storage
    assert not os.path.exists(storage.local_path(sign["attachment_id"]))
    assert not [p for p in os.listdir(local) if ".part-" in p], "остался временный файл"
    #Ровно заявленное — законно.
    assert _put_local(client, sign, b"x" * 10).status_code == 200
    assert _done(client, a, sign["attachment_id"]).status_code == 200


def test_bucket_object_bigger_than_declared_is_refused(client, monkeypatch):
    from app import storage
    deleted = []
    _s3(monkeypatch, lambda key: {"size": 101, "mime": "application/pdf"})
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key) or True)
    a, _b, conv = _world(client)
    att = _sign(client, a, conv, 100, "к.pdf", "application/pdf")["attachment_id"]
    assert _done(client, a, att).status_code == 413
    assert deleted, "объект больше заявленного остался в хранилище"


def test_daily_quota_cannot_be_bypassed_by_tiny_declarations(client, local, monkeypatch):
    """Дословная форма обхода: подписи «по байту», файлы — по полному пределу."""
    from app import storage
    monkeypatch.setattr(storage, "MAX_USER_DAY_BYTES", 30)
    a, _b, conv = _world(client)
    accepted = 0
    for _ in range(3):
        sign = _sign(client, a, conv, 1)
        if _put_local(client, sign, b"x" * 25).status_code == 200:
            accepted += 25
    assert accepted <= storage.MAX_USER_DAY_BYTES, \
        f"сутки при потолке 30 байт приняли {accepted} байт"


def test_late_upload_cannot_replace_a_confirmed_file(client, local):
    """Две загрузки по одной ссылке: вторая начала ДО подтверждения первой, а дописала
    ПОСЛЕ. Раньше она перезаписывала подтверждённый и уже отправленный документ."""
    from app import storage
    from app.db import SessionLocal
    from app.routers.messenger.attachments import upload_local
    a, _b, conv = _world(client)
    sign = _sign(client, a, conv, 10)
    att, token = sign["attachment_id"], sign["url"].split("t=", 1)[1]

    class LateStream:
        """Пока задержавшаяся загрузка «в пути», первая доходит и подтверждается."""
        def __init__(self):
            self.calls = 0

        def read(self, _n):
            self.calls += 1
            if self.calls == 1:
                assert _put_local(client, sign, b"A" * 10).status_code == 200
                assert _done(client, a, att).status_code == 200
                return b"B" * 10
            return b""

    class Upload:
        file = LateStream()

    db = SessionLocal()
    try:
        with pytest.raises(HTTPException) as err:
            upload_local(att, t=token, file=Upload(), db=db)
        assert err.value.status_code == 404
    finally:
        db.close()
    with open(storage.local_path(att), "rb") as f:
        assert f.read() == b"A" * 10, "поздняя загрузка заменила подтверждённый файл"
    assert not [p for p in os.listdir(local) if ".part-" in p], "остался временный файл"


def test_existing_local_file_opens_whatever_the_current_mode(client, local, monkeypatch):
    from app import storage
    a, (b_id, b), conv = _world(client)
    sign = _sign(client, a, conv, 10)
    att = sign["attachment_id"]
    assert _put_local(client, sign, b"z" * 10).status_code == 200
    assert _done(client, a, att).status_code == 200

    #Завели ключи S3 — старый локальный файл ищут не в бакете.
    for k, v in (("MODE", "auto"), ("ENDPOINT", "https://s3.example"), ("BUCKET", "gb"),
                 ("ACCESS_KEY", "key"), ("SECRET_KEY", "secret")):
        monkeypatch.setattr(storage, k, v)
    r = client.get(f"/web/messenger/attachments/{att}/url", headers=b)
    assert r.status_code == 200 and r.json()["url"].startswith("/web/messenger/uploads/local/"), r.text

    #Место кончилось, приём новых файлов выключен — существующий всё равно открывается.
    monkeypatch.setattr(storage, "MODE", "off")
    r = client.get(f"/web/messenger/attachments/{att}/url", headers=b)
    assert r.status_code == 200, f"старый файл перестал открываться: {r.text}"
    got = client.get(r.json()["url"])
    assert got.status_code == 200 and got.content == b"z" * 10


def test_files_and_media_tabs_respect_personal_clearing(client, monkeypatch):
    _s3(monkeypatch, lambda key: {"size": 100, "mime": "application/pdf"})
    a, (b_id, b), conv = _world(client)
    att = _sign(client, a, conv, 100, "к.pdf", "application/pdf")["attachment_id"]
    assert _done(client, a, att).status_code == 200
    file_mid = client.post(f"/web/messenger/chats/{conv}/messages", headers=a,
                           json={"body": "", "attachment_id": att}).json()["id"]
    gif = client.post(f"/web/messenger/chats/{conv}/messages", headers=a,
                      json={"body": "https://static.klipy.com/ii/abc/1.gif", "kind": "gif"})
    assert gif.status_code == 200, gif.text

    def files(h):
        return [f["message_id"] for f in
                client.get(f"/web/messenger/chats/{conv}/files", headers=h).json()["files"]]

    def media(h):
        return client.get(f"/web/messenger/chats/{conv}/media", headers=h).json()["media"]

    #«Удалить у себя» — файл уходит из вкладки у Боба, у автора остаётся.
    assert client.delete(f"/web/messenger/messages/{file_mid}?scope=self",
                         headers=b).status_code == 200
    assert files(b) == [], "скрытое у себя сообщение осталось во вкладке «Файлы»"
    assert files(a) == [file_mid]

    #Очистка истории — гифка уходит из «Медиа» у Боба, у автора остаётся.
    assert media(b), "до очистки гифка должна быть видна"
    assert client.delete(f"/web/messenger/chats/{conv}?clear_only=1", headers=b).status_code == 200
    assert media(b) == [], "очищенная история вернулась вкладкой «Медиа»"
    assert media(a), "чужая очистка не должна трогать автора"
