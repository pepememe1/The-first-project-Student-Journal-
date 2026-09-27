"""
test_sync_stale_snapshot.py — устаревший снимок десктопа не откатывает сервер (аудит
22.09.2026, находка F-03, P1).

Механизм дефекта, который держат эти тесты:
  1. Оценку поменяли на сайте или в телефоне — на сервере новая версия с новой меткой.
  2. Старый синк программы того же преподавателя получает её pull-ом, но его слияние
     свежую оценку НЕ принимает (пишет «конфликт» и оставляет у себя прежнее значение).
  3. Полный снимок (на старте сессии и раз в 20 циклов) везёт прежнее значение обратно —
     с ТОЙ серверной меткой, что была у строки при получении.
  4. `/sync/push` решал «применять или нет» по одному содержимому: иное — значит правка.
     Прежнее значение ложилось поверх нового, молча и со свежей серверной меткой.

Правило после починки: строка, основанная на версии не новее хранимой, ничего не меняет.
Настоящая правка клиента несёт более позднюю метку и применяется как раньше.

Обратный ход (проверен): убрать проверку `_based_on_older_version` в push — краснеют
`test_stale_echo_does_not_roll_back_a_newer_server_grade` и
`test_stale_tombstone_does_not_delete_a_revived_lesson`.
"""
from datetime import datetime, timedelta, timezone

from conftest import make_admin


_LESSON = {"id": "STALE-L1", "group_name": "ИС-21", "subject": "Математика",
           "type": "Практика", "number": 1, "topic": "Тест", "date": "01.09.2025"}
_GRADE = {"id": "Иванов|Иван|STALE-L1", "student_f": "Иванов", "student_n": "Иван",
          "lesson_id": "STALE-L1", "grade": "5"}


def _push(client, headers, **entities):
    r = client.post("/sync/push", json={"changes": entities}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _row(model_name: str, key: str):
    from app.db import SessionLocal
    from app.models import SYNC_MODELS
    db = SessionLocal()
    try:
        row = db.get(SYNC_MODELS[model_name], key)
        return None if row is None else {c.name: getattr(row, c.name)
                                         for c in row.__table__.columns}
    finally:
        db.close()


def _server_change(model_name: str, key: str, **fields) -> str:
    """Правка «на сайте»: новая версия строки с новой СЕРВЕРНОЙ меткой. Возвращает метку."""
    from app.db import SessionLocal
    from app.models import SYNC_MODELS
    ts = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
    db = SessionLocal()
    try:
        row = db.get(SYNC_MODELS[model_name], key)
        for k, v in fields.items():
            setattr(row, k, v)
        row.updated_at = ts
        db.commit()
    finally:
        db.close()
    return ts


def test_stale_echo_does_not_roll_back_a_newer_server_grade(client):
    h = make_admin(client)
    _push(client, h, lessons=[_LESSON], grades=[_GRADE])
    first = _row("grades", _GRADE["id"])
    assert first and first["grade"] == "5"
    received_ts = first["updated_at"]          #с этой меткой строку получил десктоп

    _server_change("grades", _GRADE["id"], grade="4")

    #Полный снимок десктопа везёт прежнее значение с меткой той версии, что получил.
    res = _push(client, h, grades=[dict(_GRADE, grade="5", updated_at=received_ts)])
    now = _row("grades", _GRADE["id"])
    assert now["grade"] == "4", (
        "эхо устаревшего снимка откатило свежую серверную оценку — ровно дефект F-03")
    assert res.get("stale", {}).get("grades") == 1, res
    assert "grades" not in (res.get("rejected") or {}), (
        "устаревшая строка — не отказ в правах: старые сборки перестали бы из-за этого "
        "стирать кэш при сверке «сервер = истина», которая их и лечит")


def test_genuine_newer_edit_is_still_applied(client):
    """Обратная сторона: настоящая правка клиента получает метку в момент правки, то
    есть позже серверной версии, — и обязана примениться, как и раньше."""
    h = make_admin(client)
    _push(client, h, lessons=[_LESSON], grades=[dict(_GRADE, grade="3")])
    stored_ts = _row("grades", _GRADE["id"])["updated_at"]
    later = (datetime.fromisoformat(stored_ts) + timedelta(minutes=1)).isoformat()
    res = _push(client, h, grades=[dict(_GRADE, grade="2", updated_at=later)])
    assert _row("grades", _GRADE["id"])["grade"] == "2", res
    #Метку по-прежнему ставит сервер: присланная лишь говорила, на какой версии клиент.
    assert _row("grades", _GRADE["id"])["updated_at"] != later


def test_row_without_timestamp_keeps_the_old_rule(client):
    """Нет метки — судить не о чем: работает прежнее правило «по содержимому». Иначе
    клиенты, не присылающие поле, перестали бы синхронизироваться вовсе."""
    h = make_admin(client)
    _push(client, h, lessons=[_LESSON], grades=[dict(_GRADE, grade="5")])
    _server_change("grades", _GRADE["id"], grade="4")
    _push(client, h, grades=[dict(_GRADE, grade="3")])
    assert _row("grades", _GRADE["id"])["grade"] == "3"


def test_stale_tombstone_does_not_delete_a_revived_lesson(client):
    """Занятие удалили и вернули на сайте; устаревший снимок везёт надгробие с меткой
    того удаления — занятие не должно исчезнуть снова."""
    h = make_admin(client)
    _push(client, h, lessons=[dict(_LESSON, id="STALE-L2", deleted=True)])
    tomb_ts = _row("lessons", "STALE-L2")["updated_at"]
    _server_change("lessons", "STALE-L2", deleted=False)
    res = _push(client, h, lessons=[dict(_LESSON, id="STALE-L2", deleted=True,
                                         updated_at=tomb_ts)])
    assert _row("lessons", "STALE-L2")["deleted"] is False, res
    assert res.get("stale", {}).get("lessons") == 1, res


def test_same_content_echo_is_not_counted(client):
    """Эхо, совпадающее по содержимому, — обычная синхронизация, а не «устаревший
    снимок»: счётчик не должен шуметь на каждом полном цикле."""
    h = make_admin(client)
    _push(client, h, lessons=[_LESSON], grades=[_GRADE])
    ts = _row("grades", _GRADE["id"])["updated_at"]
    res = _push(client, h, grades=[dict(_GRADE, updated_at=ts)])
    assert not res.get("stale"), res


def test_version_comparison_parses_rather_than_compares_strings():
    """«Z» лексикографически больше «+00:00», а isoformat выбрасывает нулевые
    микросекунды: строковое сравнение ошибалось бы ровно на границе."""
    from app.versioning import based_on_older_version as older
    assert older("2026-09-25T10:00:00Z", "2026-09-25T10:00:00.000001+00:00")
    assert not older("2026-09-25T10:00:00.000002+00:00", "2026-09-25T10:00:00.000001Z")
    assert older("2026-09-25T10:00:00+00:00", "2026-09-25T10:00:00+00:00"), \
        "равная версия — тоже не новее: настоящая правка всегда позже"
    assert not older("", "2026-09-25T10:00:00+00:00")
    assert not older("не метка", "2026-09-25T10:00:00+00:00")
    assert not older("2026-09-25T10:00:00+00:00", None)
