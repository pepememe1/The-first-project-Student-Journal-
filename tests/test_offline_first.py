"""
test_offline_first.py — главное обещание десктопа: кабинет работает БЕЗ СЕТИ.

Почему тестом, а не проверкой руками. Кабинет переехал на общий Vue-интерфейс, и путь до
данных стал длиннее: страница → локальный сервер → локальная копия базы. Любое звено
можно нечаянно завязать на боевой сервер (мы это уже проделали: запасной путь ходил на
домен и всё падало по CORS), а заметно это станет только у человека без интернета — то
есть в аудитории колледжа, где сеть и пропадает.

Здесь сеть недоступна ПО ПОСТРОЕНИЮ: адрес боевого сервера пуст, живого токена нет.
Если тест зелёный — журнал откроется и офлайн.
"""
import os
import tempfile
import urllib.error
import urllib.request

import pytest

import local_api


@pytest.fixture(scope="module")
def offline_api():
    """Локальный сервер на своей базе, БЕЗ доступа к бою."""
    tmp = os.path.join(tempfile.mkdtemp(), "offline_test.db").replace("\\", "/")
    os.environ["GRADEBOOK_DB_URL"] = f"sqlite:///{tmp}"
    srv = local_api.LocalAPI()
    if not srv.start():
        pytest.skip(f"серверный пакет недоступен: {srv.error}")
    yield srv
    srv.stop()


def _seed(login="offstud"):
    """Данные, которые «уже скачаны» — как после первого входа с сетью."""
    from app.db import SessionLocal
    from app.models import Grade, Group, Lesson, User
    db = SessionLocal()
    try:
        db.merge(User(id=f"stud:{login}", login=login, role="student",
                      surname="Офлайнов", name="Иван", group_name="К74/1",
                      deleted=False, updated_at="2026-07-01T00:00:00+00:00"))
        db.merge(Group(id="grp:К74/1", name="К74/1", subjects=["Физика"],
                       deleted=False, updated_at="2026-07-01T00:00:00+00:00"))
        #⚠️ Термин берём ТЕКУЩИЙ, а не зашитый числом. Раньше здесь стояло
        #year="2026/2027", semester=1 — и тест сломался, как только сдвинули границу
        #учебного года (3.6): занятие оказалось в «будущем» термине, журнал по умолчанию
        #показывал пустой список, а падение выглядело как поломка офлайн-режима, хотя
        #проверяет он совсем другое — что журнал открывается без сети.
        from app.db import default_term
        _ty, _ts = default_term()
        db.merge(Lesson(id="les:off1", group_name="К74/1", subject="Физика",
                        type="Практика", number=1, date="2026-09-01",
                        year=_ty, semester=_ts, deleted=False,
                        updated_at="2026-07-01T00:00:00+00:00"))
        db.merge(Grade(id=f"stud:{login}|les:off1", student_id=f"stud:{login}",
                       student_f="Офлайнов", student_n="Иван", lesson_id="les:off1",
                       grade="5", deleted=False,
                       updated_at="2026-07-01T00:00:00+00:00"))
        db.commit()
    finally:
        db.close()


def _get(url, token):
    req = urllib.request.Request(url, headers={"X-Client": "web",
                                              "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, ""


def test_no_network_is_really_simulated(monkeypatch):
    """Страховка от самообмана: если тест случайно получит доступ к бою, он проверит не то,
    что заявлено. Поэтому сеть гасим явно и убеждаемся, что её действительно нет."""
    monkeypatch.setattr("sync_runner.fresh_auth", lambda: ("", ""))
    from sync_runner import fresh_auth
    assert fresh_auth() == ("", ""), "тест обязан работать без боевого сервера"


def test_journal_opens_without_network(offline_api, monkeypatch):
    """Оценки и предметы приходят из ЛОКАЛЬНОЙ копии — сеть не нужна вовсе."""
    monkeypatch.setattr("sync_runner.fresh_auth", lambda: ("", ""))
    _seed()
    token, _ = local_api.issue_local_session("offstud", "student")
    assert token, "сессия для локального сервера обязана выпускаться и офлайн"

    code, body = _get(offline_api.url("/web/student/overview"), token)
    assert code == 200, body
    assert "Офлайнов" in body, "имя студента обязано прийти из локальной копии"

    code, body = _get(offline_api.url("/web/student/journal"), token)
    assert code == 200, body
    assert "Физика" in body, "предмет обязан прийти из локальной копии"


def test_spa_itself_is_served_offline(offline_api):
    """Сама страница тоже локальная: взятая с сайта, без интернета она не открылась бы."""
    try:
        with urllib.request.urlopen(offline_api.url("/"), timeout=10) as r:
            assert r.status == 200
    except urllib.error.HTTPError as e:      # pragma: no cover
        pytest.fail(f"интерфейс не отдался локально: {e.code}")


def test_mirror_failure_offline_is_not_fatal(monkeypatch):
    """Нет сети — зеркало просто не обновится. Оно НЕ должно ни падать, ни чистить копию:
    уже скачанные данные и есть offline-first."""
    monkeypatch.setattr("sync_runner.fresh_auth", lambda: ("", ""))
    import local_mirror
    res = local_mirror.mirror_once()
    assert res["ok"] is False and res["error"], "офлайн-зеркало обязано вернуть причину"
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        assert db.query(User).count() > 0, "копию нельзя терять из-за отсутствия сети"
    finally:
        db.close()
