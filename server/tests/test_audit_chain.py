# -*- coding: utf-8 -*-
"""
test_audit_chain.py — 🔒 ЖУРНАЛ БЕЗОПАСНОСТИ ОБЯЗАН ЗАМЕЧАТЬ, ЧТО ЕГО ПРАВИЛИ.

━━ ЗАЧЕМ ━━
`audit_events` — единственный след того, кто и что делал: по нему разбирают инцидент,
им подтверждают аварийный сброс второго фактора, на него ссылается приказ ФСТЭК № 21.
До 01.09.2026 журнал был только-на-добавление лишь НА УРОВНЕ ПРИЛОЖЕНИЯ: продукт записи
не правил, но тот, кто получил доступ к базе, менял и удалял строки без единого следа.
То есть след не переживал ровно того события, ради которого его читают.

Теперь каждая запись несёт хеш предыдущей. Здесь проверяется, что цепочка:
  • строится при обычной записи;
  • ЛОВИТ правку содержимого, удаление из середины, вставку и перестановку;
  • не поднимает ложную тревогу на записях, сделанных ДО появления цепочки;
  • не мешает записи, если что-то пошло не так (инвариант «аудит не роняет операцию»).

⚠️ Половина тестов здесь — ОБРАТНЫЙ ХОД: они портят журнал и требуют, чтобы проверка
это заметила. Без них зелёный тест не отличить от неработающей проверки, а этот класс
ошибки у нас уже стоил четырёх зелёных версий подряд при сломанном продукте
(`pollingRespectsVisibility`).
"""
import pytest

from app import audit
from app.db import Base, SessionLocal, engine
from app.models import AuditEvent


def _write(db, n=3, actor="teacher1", action="grade.set"):
    for i in range(n):
        audit.log(db, actor=actor, role="teacher", action=action,
                  target="stud%d" % i, detail="урок %d" % i)


@pytest.fixture()
def clean_db():
    """Прямая сессия к пустой базе.

    Не через `client`: здесь проверяется САМА цепочка, а не ручка API, и лишний слой
    HTTP добавил бы записей о входе администратора, сбив пересчёт. Таблицы пересоздаём
    целиком — записи соседнего теста в общей тестовой базе выглядели бы как разрыв.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ────────────────────────────── прямой ход ──────────────────────────────

def test_chain_is_built_on_ordinary_writes(clean_db):
    """Обычная запись в журнал сама встраивается в цепочку."""
    _write(clean_db, 3)
    rows = clean_db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()
    assert len(rows) == 3
    assert all(r.entry_hash for r in rows), "запись без хеша — цепочка не строится"
    #Первая ни с чем не связана, каждая следующая — с предыдущей.
    assert rows[0].prev_hash == ""
    assert rows[1].prev_hash == rows[0].entry_hash
    assert rows[2].prev_hash == rows[1].entry_hash


def test_intact_chain_verifies(clean_db):
    """Нетронутый журнал сходится."""
    _write(clean_db, 5)
    report = audit.verify_chain(clean_db)
    assert report["status"] == "ok", report
    assert report["checked"] == 5
    assert report["problem_count"] == 0


def test_hash_depends_on_every_field(clean_db):
    """Слепок зависит от КАЖДОГО поля, а не от части.

    Поле, выпавшее из расчёта, — это поле, которое можно править безнаказанно. Проверяем
    свойством, а не перечислением: меняем по одному и требуем, чтобы хеш поехал.
    """
    base = {name: "x" for name in audit._HASHED_FIELDS}
    origin = audit.entry_digest("", base)
    for name in audit._HASHED_FIELDS:
        changed = dict(base)
        changed[name] = "y"
        assert audit.entry_digest("", changed) != origin, (
            "поле %s не влияет на хеш — его можно менять незаметно" % name)


def test_separator_prevents_field_smearing(clean_db):
    """Границы полей нельзя размыть переносом символов из одного в соседнее.

    Без разделителя (или с разделителем, встречающимся в данных) записи
    actor='a', action='b' и actor='ab', action='' дали бы ОДИН слепок — то есть
    подмена того, КТО совершил действие, прошла бы незаметно.
    """
    a = {name: "" for name in audit._HASHED_FIELDS}
    b = dict(a)
    a["actor"], a["role"] = "a", "b"
    b["actor"], b["role"] = "ab", ""
    assert audit.entry_digest("", a) != audit.entry_digest("", b)


def test_checkpoint_moves_with_the_journal(clean_db):
    """Контрольная точка отражает состояние журнала, а не выдумывает его."""
    _write(clean_db, 2)
    first = audit.checkpoint(clean_db)
    assert first["entries"] == 2 and first["head"]
    _write(clean_db, 1)
    second = audit.checkpoint(clean_db)
    assert second["entries"] == 3
    assert second["head"] != first["head"], (
        "голова цепочки не сдвинулась после новой записи — сверять такую контрольную "
        "точку бессмысленно")
    assert "AUDIT" in first["short"] and first["head"][:16] in first["short"]


def test_legacy_rows_are_not_called_tampering(clean_db):
    """Записи БЕЗ хешей — «унаследованные», а не «подделанные».

    На боевой базе их тысячи: они сделаны до появления цепочки. Назвать их порчей
    значило бы выдать постоянную ложную тревогу, а сигнал, который всегда красный,
    перестают читать — и настоящая тревога утонет вместе с ним.
    """
    clean_db.add(AuditEvent(created_ts=1, ts="2026-01-01T00:00:00+00:00",
                            actor="old", action="login.ok", entry_hash="", prev_hash=""))
    clean_db.commit()
    report = audit.verify_chain(clean_db)
    assert report["legacy"] == 1
    assert report["status"] != "broken", "унаследованная запись объявлена подделкой"


def test_chain_survives_the_boundary_between_legacy_and_signed(clean_db):
    """Переход «старые записи → новые» не должен выглядеть разрывом.

    Это и есть живой случай выкладки: в базе лежит история без хешей, дальше идут
    подписанные. Ложная тревога ровно в момент обновления обесценила бы механизм в
    первый же день.
    """
    clean_db.add(AuditEvent(created_ts=1, ts="2026-01-01T00:00:00+00:00",
                            actor="old", action="login.ok", entry_hash="", prev_hash=""))
    clean_db.commit()
    _write(clean_db, 3)
    report = audit.verify_chain(clean_db)
    assert report["status"] == "ok", report
    assert report["legacy"] == 1 and report["checked"] == 3


def test_audit_still_writes_when_the_head_is_unreadable(clean_db, monkeypatch):
    """Сбой чтения головы не имеет права СЪЕСТЬ событие.

    Потерянное событие не видно никогда, а разрыв цепочки виден при первой же проверке.
    Из двух зол выбираем то, которое заметно.
    """
    monkeypatch.setattr(audit, "_head_hash",
                        lambda db: (_ for _ in ()).throw(RuntimeError("база недоступна")))
    audit.log(clean_db, actor="teacher1", role="teacher", action="grade.set")
    assert clean_db.query(AuditEvent).count() == 1, "событие потеряно из-за сбоя цепочки"


# ────────────────────────────── обратный ход ──────────────────────────────

def test_edit_in_place_is_detected(clean_db):
    """Правка содержимого записи ломает пересчёт.

    Самый вероятный сценарий: администратор, сделавший что-то лишнее, меняет actor или
    detail в своей строке.
    """
    _write(clean_db, 5)
    victim = clean_db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()[2]
    victim.actor = "кто-то-другой"
    clean_db.commit()

    report = audit.verify_chain(clean_db)
    assert report["status"] == "broken", "правка записи прошла незамеченной"
    assert report["problems"][0]["id"] == victim.id


def test_deletion_from_the_middle_is_detected(clean_db):
    """Удаление записи из середины ломает связь у соседа.

    Именно так и «чистят» журнал: убирают одну неудобную строку, оставляя остальные.
    """
    _write(clean_db, 5)
    rows = clean_db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()
    clean_db.delete(rows[2])
    clean_db.commit()

    report = audit.verify_chain(clean_db)
    assert report["status"] == "broken", "удаление из середины прошло незамеченным"


def test_insertion_is_detected(clean_db):
    """Дописанная задним числом запись не встраивается в цепочку."""
    _write(clean_db, 3)
    rows = clean_db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()
    forged = AuditEvent(created_ts=rows[0].created_ts, ts=rows[0].ts,
                        actor="admin", role="admin", action="mfa.reset",
                        target="teacher1", detail="", level="info",
                        prev_hash=rows[0].entry_hash, entry_hash="подделка")
    clean_db.add(forged)
    clean_db.commit()

    report = audit.verify_chain(clean_db)
    assert report["status"] == "broken", "вставленная запись прошла незамеченной"


def test_reordering_is_detected(clean_db):
    """Перестановка записей местами ломает цепочку.

    Порядок событий бывает важнее их состава: «сброс второго фактора ДО входа» и «после»
    — это два разных инцидента.
    """
    _write(clean_db, 4)
    rows = clean_db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()
    rows[1].prev_hash, rows[2].prev_hash = rows[2].prev_hash, rows[1].prev_hash
    clean_db.commit()

    report = audit.verify_chain(clean_db)
    assert report["status"] == "broken", "перестановка прошла незамеченной"


def test_verifier_would_notice_a_broken_digest_function(clean_db):
    """Обратный ход на саму проверку: сломанный расчёт обязан её обрушить.

    Проверка, которая зелена и при неверной формуле, не проверяет ничего. Здесь мы
    ломаем ИМЕННО расчёт — так же, как его сломала бы неосторожная правка порядка
    полей в `_HASHED_FIELDS`.
    """
    _write(clean_db, 3)
    assert audit.verify_chain(clean_db)["status"] == "ok"

    original = audit._HASHED_FIELDS
    try:
        audit._HASHED_FIELDS = tuple(reversed(original))
        report = audit.verify_chain(clean_db)
        assert report["status"] == "broken", (
            "перестановка полей в расчёте не заметна — значит проверка не считает хеш, "
            "а сверяет что-то другое")
    finally:
        audit._HASHED_FIELDS = original
    #И убеждаемся, что вернули как было: иначе тест испортит соседей.
    assert audit.verify_chain(clean_db)["status"] == "ok"


def test_a_fully_rewritten_tail_still_verifies(clean_db):
    """⚠️ ЧЕСТНАЯ ГРАНИЦА, закреплённая тестом, а не обещанием.

    Тот, кто владеет базой, может пересчитать ВЕСЬ хвост и получить сходящуюся цепочку
    из подделанных записей — здесь мы это ровно и делаем. Тест зафиксирован НЕ для того,
    чтобы объявить механизм негодным, а чтобы утверждение «журнал нельзя подделать»
    никогда не появилось в документах: цепочка даёт заметность, а доказательство даёт
    только контрольная точка, сохранённая вне этой машины (ASVS V16.4.3, не сделано).
    """
    _write(clean_db, 4)
    rows = clean_db.query(AuditEvent).order_by(AuditEvent.id.asc()).all()
    for r in rows:
        r.actor = "переписано"
    prev = ""
    for r in rows:
        values = {name: getattr(r, name, "") for name in audit._HASHED_FIELDS}
        r.prev_hash = prev
        r.entry_hash = audit.entry_digest(prev, values)
        prev = r.entry_hash
    clean_db.commit()

    report = audit.verify_chain(clean_db)
    assert report["status"] == "ok", (
        "этот тест обязан быть ЗЕЛЁНЫМ: он фиксирует известную границу механизма, а не "
        "дефект")


# ───────────────────── ручка администратора (есть ли вызывающий) ─────────────────────
#
# Проверка целостности без единого вызывающего — наш самый частый класс дефекта:
# механизм написан, его собственные тесты зелёные, а в продукте его не зовёт НИКТО.
# Поэтому здесь проверяется не поведение функции, а НАЛИЧИЕ ДВЕРИ к ней.

def test_integrity_endpoint_is_admin_only(client):
    """Состояние журнала безопасности — не для всех.

    Отчёт называет логины и коды действий: по нему видно, кто чем занимался. Студенту и
    преподавателю там делать нечего.
    """
    from conftest import make_admin, make_teacher
    h = make_admin(client)
    th = make_teacher(client, h)
    assert client.get("/web/admin/audit/integrity").status_code == 401
    assert client.get("/web/admin/audit/integrity", headers=th).status_code == 403
    assert client.get("/web/admin/audit/integrity", headers=h).status_code == 200


def test_integrity_endpoint_reports_a_healthy_journal(client):
    """На живом продукте (вход администратора уже записан) цепочка сходится."""
    from conftest import make_admin
    h = make_admin(client)
    client.post("/auth/login", json={"login": "admin", "password": "adminpass1"})
    r = client.get("/web/admin/audit/integrity", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok", body
    assert body["checked"] >= 1, "проверять было нечего — журнал пуст, хотя вход был"
    assert body["checkpoint"]["head"], "контрольная точка без головы цепочки бесполезна"
    assert body["scope"], "не сказано, какая часть журнала проверена"


def test_integrity_endpoint_reports_tampering(client):
    """Обратный ход НА РУЧКЕ, а не только на функции.

    Отдельно от `test_edit_in_place_is_detected`: там проверялась логика, здесь — что
    испорченный журнал доедет до администратора именно как испорченный, а не превратится
    по дороге в пустой ответ или в 500.
    """
    from conftest import make_admin
    from app.db import SessionLocal
    from app.models import AuditEvent

    h = make_admin(client)
    client.post("/auth/login", json={"login": "admin", "password": "adminpass1"})

    db = SessionLocal()
    try:
        row = db.query(AuditEvent).order_by(AuditEvent.id.asc()).first()
        assert row is not None and row.entry_hash
        row.actor = "подменённый"
        db.commit()
    finally:
        db.close()

    body = client.get("/web/admin/audit/integrity", headers=h).json()
    assert body["status"] == "broken", body
    assert body["problem_count"] >= 1
    #Наружу не уходит содержимое detail — самое вероятное место лишнего.
    assert all("detail" not in p for p in body["problems"])
