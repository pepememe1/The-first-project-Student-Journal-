"""
test_sync_never_blanks_secrets.py — синхронизация не имеет права ОБНУЛИТЬ секрет.

Регрессия стоила потери входа у 10 студентов на боевом сервере 30.07.2026, и механизм
надо помнить целиком, иначе он вернётся: на pull сервер САМ вырезает чужие хеши (верно —
на клиентском ПК их быть не должно), десктоп сохраняет строки уже с пустым полем и на
следующем push честно возвращает их обратно. Пустота ложилась поверх настоящего хеша.

Восстановить хеш нельзя — он невыводим; только из бэкапа, а четырёх аккаунтов в бэкапе
не оказалось вовсе. Поэтому правило простое: клиент может ЗАДАТЬ секрет, но не может
обнулить тот, которого не знает.
"""
from app.db import SessionLocal
from app.models import User
from conftest import make_admin


def _student(db, login="s1", pwd_hash="pbkdf2_sha512$hash$here"):
    db.merge(User(id=f"stud:{login}", login=login, role="student",
                  surname="Тестов", name="Тест", group_name="К74/1",
                  password_hash=pwd_hash, deleted=False,
                  updated_at="2026-07-01T00:00:00+00:00"))
    db.commit()


def test_push_with_empty_hash_does_not_wipe_password(client):
    """Ровно тот случай, что случился на бою: клиент вернул строку с пустым хешем."""
    admin = make_admin(client)
    db = SessionLocal()
    try:
        _student(db, "s1")
    finally:
        db.close()

    r = client.post("/sync/push", json={"changes": {"users": [
        {"id": "stud:s1", "login": "s1", "role": "student", "surname": "Тестов",
         "name": "Тест", "group_name": "К74/1", "password_hash": ""}]}}, headers=admin)
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        u = db.get(User, "stud:s1")
        assert u.password_hash, "пустой хеш НЕ должен затирать настоящий — вход бы пропал"
    finally:
        db.close()


def test_push_can_still_set_a_real_hash(client):
    """Запрет касается только ОБНУЛЕНИЯ: настоящий хеш по-прежнему принимается, иначе
    сломался бы законный перенос учётных данных между узлами."""
    admin = make_admin(client)
    db = SessionLocal()
    try:
        _student(db, "s2", pwd_hash="")
    finally:
        db.close()

    client.post("/sync/push", json={"changes": {"users": [
        {"id": "stud:s2", "login": "s2", "role": "student", "surname": "Тестов",
         "name": "Тест", "password_hash": "pbkdf2_sha512$new$hash"}]}}, headers=admin)

    db = SessionLocal()
    try:
        assert db.get(User, "stud:s2").password_hash == "pbkdf2_sha512$new$hash"
    finally:
        db.close()
