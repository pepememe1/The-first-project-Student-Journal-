"""
test_stt_mode.py — чем распознавать речь: настройка админа `stt_mode`
(GET /web/vector/stt/status, POST /web/vector/stt).

Три режима — 'auto' (Whisper там, где он есть, иначе недоступно), 'server' (только
Whisper, задел на закупку машины с видеокартой) и 'browser' (распознаёт браузер).

Главное, что здесь закрепляется: без движка ответ обязан быть честным отказом, а НЕ тихой
подменой на браузерное распознавание — и в 'server', и в умолчании 'auto' (с 22.10.2026,
решение Ярослава: голос уходил облаку браузера у всех, хотя никто этого не выбирал).
Подмена нарушила бы именно то решение, ради которого режим включают: звук с ПДн не
должен уходить третьей стороне. Ровно этот класс ошибок («защита включена, а работает
иначе») уже стоил проекту потери хешей паролей на бою.
"""
from conftest import make_admin, make_teacher


def _set_mode(client, admin, mode):
    r = client.post("/web/admin/ai-config", json={"stt_mode": mode}, headers=admin)
    assert r.status_code == 200, r.text


def _status(client, headers):
    r = client.get("/web/vector/stt/status", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _fake_engine(monkeypatch, installed: bool):
    """Подменяем НАЛИЧИЕ движка: faster-whisper в CI не ставим (как и в тестах TTS)."""
    from app import stt_service
    monkeypatch.setattr(stt_service, "is_available", lambda: installed)


def test_auto_never_hands_the_voice_to_the_browser(client, monkeypatch):
    """Умолчание без Whisper — честное «недоступно» с причиной, а не браузер: голос с
    фамилиями студентов уходил бы облаку браузера (Chrome — Google) без чьего-либо
    решения. Обратный ход (проверен): вернуть отдачу браузеру в `auto` — краснеет."""
    admin = make_admin(client)
    _fake_engine(monkeypatch, False)
    st = _status(client, admin)
    assert st["mode"] == "auto"
    assert st["available"] is False and st["engine"] == "", st
    assert "браузер" in st["reason"], "админу нужна подсказка, как включить явно"


def test_non_admin_gets_a_reason_without_admin_advice(client, monkeypatch):
    """Не-админу «администратор может включить» бесполезно — ему причина и что делать
    (живой прогон 27.10.2026: тост с советом админу перекрывал поле ввода у студента)."""
    admin = make_admin(client)
    teacher = make_teacher(client, admin)
    _fake_engine(monkeypatch, False)
    st = _status(client, teacher)
    assert st["available"] is False and st["reason"], st
    assert "дминистратор" not in st["reason"] and "текстом" in st["reason"], st["reason"]


def test_browser_is_still_available_by_explicit_choice(client, monkeypatch):
    """Явный выбор админа работает и без Whisper: отказ касается только умолчания."""
    admin = make_admin(client)
    _set_mode(client, admin, "browser")
    _fake_engine(monkeypatch, False)
    st = _status(client, admin)
    assert st["available"] is True and st["engine"] == "browser"


def test_auto_prefers_whisper_when_installed(client, monkeypatch):
    """Есть движок — берём его: «у кого локально работает, тот пользуется Whisper».
    Внутри программы это локальный сервер, поэтому звук не покидает компьютер."""
    admin = make_admin(client)
    _fake_engine(monkeypatch, True)
    st = _status(client, admin)
    assert st["engine"] == "whisper" and st["installed"] is True


def test_server_mode_refuses_honestly_without_engine(client, monkeypatch):
    """«Whisper для всех» на машине без движка = честное «недоступно» с причиной."""
    admin = make_admin(client)
    _set_mode(client, admin, "server")
    _fake_engine(monkeypatch, False)
    st = _status(client, admin)
    assert st["available"] is False
    assert st["engine"] == "", "тихая подмена браузером недопустима"
    assert st["reason"], "человеку нужна причина, а не пустая кнопка"


def test_browser_mode_disables_server_recognition(client, monkeypatch):
    """Режим «браузер» отключает серверный движок, даже если он установлен: иначе
    настройка была бы декоративной, а устаревший клиент продолжал бы грузить хост."""
    admin = make_admin(client)
    _set_mode(client, admin, "browser")
    _fake_engine(monkeypatch, True)
    assert _status(client, admin)["engine"] == "browser"
    r = client.post("/web/vector/stt", files={"file": ("a.webm", b"x", "audio/webm")},
                    headers=admin)
    assert r.status_code == 503
    assert "администратор" in r.json()["detail"].lower()


def test_mode_is_shared_by_all_roles(client, monkeypatch):
    """Настройка ОБЩАЯ: преподаватель обязан получить тот же движок, что назначил админ —
    иначе «включить для всех» не работало бы как обещано."""
    admin = make_admin(client)
    teach = make_teacher(client, admin, subjects=["Математика"])
    _set_mode(client, admin, "browser")
    _fake_engine(monkeypatch, True)
    assert _status(client, teach)["engine"] == "browser"


def test_unknown_mode_falls_back_to_auto(client, monkeypatch):
    """Мусор в конфиге (ручная правка, старый клиент) не должен ломать голосовой ввод."""
    admin = make_admin(client)
    _set_mode(client, admin, "нет-такого-режима")
    _fake_engine(monkeypatch, True)
    st = _status(client, admin)
    assert st["mode"] == "auto" and st["engine"] == "whisper"


def test_admin_sees_whether_engine_installed(client, monkeypatch):
    """В настройках ИИ админ видит правду о хосте — иначе он включил бы «для всех» на
    машине без движка и отключил голосовой ввод всему колледжу."""
    admin = make_admin(client)
    _fake_engine(monkeypatch, False)
    cfg = client.get("/web/admin/ai-config", headers=admin).json()
    assert cfg["stt_installed"] is False
    assert cfg["stt_mode"] == "auto"


def test_stt_mode_is_not_writable_by_teacher(client):
    """Общая настройка — только админу (тот же ролевой скоуп, что у остальных настроек ИИ)."""
    admin = make_admin(client)
    teach = make_teacher(client, admin, subjects=["Математика"])
    r = client.post("/web/admin/ai-config", json={"stt_mode": "browser"}, headers=teach)
    assert r.status_code == 403
