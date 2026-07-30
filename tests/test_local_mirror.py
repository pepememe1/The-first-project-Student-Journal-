"""
test_local_mirror.py — зеркало боевой базы в локальную (ui/local_mirror.py).

Зеркало — то, что делает общий Vue-интерфейс совместимым с offline-first: без него
интерфейс на десктопе открылся бы пустым. Закрепляем свойства, потеря которых тихо
ломает копию, а замечается через недели.
"""
import os
import tempfile

import pytest


@pytest.fixture(scope="module")
def local_db():
    """Пустая ЛОКАЛЬНАЯ база серверной схемы (боевую и десктопную не трогаем)."""
    tmp = os.path.join(tempfile.mkdtemp(), "mirror_test.db").replace("\\", "/")
    os.environ["GRADEBOOK_DB_URL"] = f"sqlite:///{tmp}"
    #Путь к серверному пакету добавляет local_api — используем его же логику.
    import local_api
    local_api.LocalAPI()._load_app()
    from app.db import init_db
    init_db()
    yield


@pytest.fixture()
def db(local_db):
    import local_mirror
    session = local_mirror._local_session()
    yield session
    session.close()


class _FakeClient:
    """Подставной сервер: отдаёт заранее заданный ответ /sync/pull."""

    def __init__(self, payload, expect_since=None):
        self.payload = payload
        self.expect_since = expect_since
        self.asked_since = None

    def pull(self, since=""):
        self.asked_since = since
        return self.payload


def test_copies_rows_verbatim(db):
    """Записи ложатся в локальную базу как есть."""
    import local_mirror
    changes = {"groups": [{"id": "grp:К74/1", "name": "К74/1", "subjects": ["Математика"],
                           "updated_at": "2026-07-01T10:00:00+00:00", "deleted": False}]}
    assert local_mirror.apply_changes(db, changes) == 1
    db.commit()
    from app.models import Group
    row = db.get(Group, "grp:К74/1")
    assert row is not None and row.name == "К74/1"


def test_preserves_remote_updated_at(db):
    """КЛЮЧЕВОЕ: метку времени копия НЕ переписывает своей.

    updated_at — часы механизма LWW. Переставив их локальным временем, мы бы навсегда
    рассинхронизировали копию с оригиналом: следующая дельта считала бы наши строки
    новее серверных и перестала бы их обновлять."""
    import local_mirror
    stamp = "2026-06-15T08:30:00+00:00"
    local_mirror.apply_changes(db, {"subjects": [
        {"id": "subj:Физика", "name": "Физика", "updated_at": stamp, "deleted": False}]})
    db.commit()
    from app.models import Subject
    assert db.get(Subject, "subj:Физика").updated_at == stamp


def test_updates_existing_row(db):
    """Повторный приезд той же записи обновляет её, а не плодит вторую."""
    import local_mirror
    for name in ("Информатика", "Информатика и ИКТ"):
        local_mirror.apply_changes(db, {"subjects": [
            {"id": "subj:И", "name": name,
             "updated_at": "2026-07-02T10:00:00+00:00", "deleted": False}]})
    db.commit()
    from app.models import Subject
    assert db.get(Subject, "subj:И").name == "Информатика и ИКТ"


def test_unknown_model_is_skipped(db):
    """Сервер может уметь больше, чем знает эта сборка десктопа — падать нельзя."""
    import local_mirror
    assert local_mirror.apply_changes(db, {"чего_то_новое": [{"id": "x"}]}) == 0


def test_rows_without_key_are_skipped(db):
    import local_mirror
    assert local_mirror.apply_changes(db, {"subjects": [{"name": "без id"}]}) == 0


def test_watermark_moves_only_after_success(db, monkeypatch):
    """Метка дельты двигается ТОЛЬКО после успешного применения.

    Сдвинутая заранее метка потеряла бы данные безвозвратно: следующий заход решил бы,
    что этот кусок уже скачан. Повторная же загрузка безвредна — запись идемпотентна."""
    import local_mirror
    client = _FakeClient({"server_time": "2026-07-10T00:00:00+00:00",
                          "changes": {"subjects": [
                              {"id": "subj:Х", "name": "Химия",
                               "updated_at": "2026-07-09T00:00:00+00:00", "deleted": False}]}})
    res = local_mirror.mirror_once(client=client)
    assert res["ok"] and res["rows"] == 1
    assert res["since"] == "2026-07-10T00:00:00+00:00"

    #Следующий заход обязан попросить дельту ОТ сохранённой метки, а не с нуля.
    client2 = _FakeClient({"server_time": "2026-07-11T00:00:00+00:00", "changes": {}})
    local_mirror.mirror_once(client=client2)
    assert client2.asked_since == "2026-07-10T00:00:00+00:00"


def test_failure_does_not_move_watermark(db):
    """Сорвалась загрузка — метка осталась прежней, кусок скачается снова."""
    import local_mirror

    class _Broken:
        def pull(self, since=""):
            raise RuntimeError("сеть отвалилась")

    before = local_mirror._get_watermark(local_mirror._local_session())
    res = local_mirror.mirror_once(client=_Broken())
    assert res["ok"] is False and res["error"]
    after = local_mirror._get_watermark(local_mirror._local_session())
    assert after == before


def test_no_session_is_not_a_crash():
    """Пользователь ещё не вошёл — честный отказ, а не исключение наружу."""
    import local_mirror
    res = local_mirror.mirror_once(client=None)
    assert res["ok"] is False
