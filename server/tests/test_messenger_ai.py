"""
test_messenger_ai.py — умные функции мессенджера: поиск по смыслу, сводка, напоминания.

Что здесь защищается (по убыванию цены ошибки):
  • ПРИВАТНОСТЬ. В поиск модель получает ТОЛЬКО запрос — переписку она не видит вовсе.
    В сводке сообщения нужны по существу, поэтому ФИО реальных людей маскируются ДО
    отправки: README обещает заказчику, что персональные данные в облако не уходят;
  • ГРАНИЦЫ. Чужую беседу не найти и не пересказать; сообщения, которые пользователь
    удалил у себя, не всплывают ни в поиске, ни в сводке;
  • ОТКАЗОУСТОЙЧИВОСТЬ. Нет модели — поиск вырождается в обычный полнотекстовый, а сводка
    честно отвечает «не получилось». Ни то, ни другое не роняет чат и ничего не выдумывает;
  • НАПОМИНАНИЯ срабатывают, не задваиваются и не видны чужим.

LLM во всех тестах замокан: боевой провайдер в CI недоступен, а проверяем мы МАРШРУТ и
границы, а не качество формулировок модели.
"""
from datetime import datetime, timedelta, timezone

import pytest

from conftest import make_admin, make_teacher


@pytest.fixture(autouse=True)
def push_on(monkeypatch):
    from app import config, rustore_push
    monkeypatch.setattr(config, "RUSTORE_PROJECT_ID", "test-project")
    monkeypatch.setattr(config, "RUSTORE_SERVICE_TOKEN", "test-token")
    sent = []
    monkeypatch.setattr(rustore_push, "_post", lambda payload: (sent.append(payload), (True, 200, "{}"))[1])
    return sent


def _student(client, admin, login, surname, name, group="ИС-21"):
    r = client.post("/web/admin/students", json={
        "login": login, "surname": surname, "name": name, "group": group,
        "password": "studpass1"}, headers=admin)
    assert r.status_code == 200, r.text


def _headers(client, login, password="studpass1"):
    r = client.post("/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


def _uid(client, admin, login):
    for s in client.get("/web/admin/students", headers=admin).json()["students"]:
        if s.get("login") == login:
            return s["id"]
    raise AssertionError(login)


def _chat(client, headers, peer_id):
    r = client.post(f"/web/messenger/chats/direct/{peer_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


def _say(client, headers, conv_id, text):
    r = client.post(f"/web/messenger/chats/{conv_id}/messages",
                    json={"body": text}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _setup_chat(client):
    """Двое студентов одной группы и личный чат между ними."""
    admin = make_admin(client)
    _student(client, admin, "ivanova", "Иванова", "Мария")
    _student(client, admin, "petrov", "Петров", "Пётр")
    h1 = _headers(client, "ivanova")
    conv = _chat(client, h1, _uid(client, admin, "petrov"))
    return admin, h1, _headers(client, "petrov"), conv


# ── §17. Поиск по смыслу ────────────────────────────────────────────────────────────
def test_ai_search_finds_by_synonym_from_model(client, monkeypatch):
    """Модель расширяет «домашка» до «дз» — и сообщение находится, хотя слова в нём нет."""
    from app import messenger_ai
    monkeypatch.setattr(messenger_ai, "expand_query", lambda cfg, q: ["дз", "задание"])
    _admin, h1, _h2, conv = _setup_chat(client)
    _say(client, h1, conv, "Не забудь про дз по базам данных")
    _say(client, h1, conv, "Погода сегодня отличная")

    r = client.get(f"/web/messenger/chats/{conv}/messages/ai-search?q=домашка", headers=h1)
    assert r.status_code == 200, r.text
    bodies = [m["body"] for m in r.json()["messages"]]
    assert any("дз по базам" in b for b in bodies), bodies
    assert not any("Погода" in b for b in bodies), bodies


def test_ai_search_never_sends_messages_to_model(client, monkeypatch):
    """КЛЮЧЕВОЕ: модель видит ТОЛЬКО запрос. Переписка ей не показывается."""
    seen = []
    from app import messenger_ai, vector_llm

    def spy(cfg, messages, temperature=0.3):
        seen.append(messages)
        return "дз, задание"
    monkeypatch.setattr(vector_llm, "complete", spy)

    _admin, h1, _h2, conv = _setup_chat(client)
    _say(client, h1, conv, "СЕКРЕТНОЕ СОДЕРЖИМОЕ ПЕРЕПИСКИ")
    client.get(f"/web/messenger/chats/{conv}/messages/ai-search?q=домашка", headers=h1)

    blob = str(seen)
    assert "СЕКРЕТНОЕ СОДЕРЖИМОЕ" not in blob, "переписка утекла в модель при поиске"
    assert "домашка" in blob, "запрос до модели не дошёл"


def test_ai_search_degrades_to_plain_search_without_model(client, monkeypatch):
    """Модели нет → расширений нет, но прямые совпадения всё равно находятся."""
    from app import vector_llm
    monkeypatch.setattr(vector_llm, "complete", lambda cfg, m, temperature=0.3: "")
    _admin, h1, _h2, conv = _setup_chat(client)
    _say(client, h1, conv, "встреча по практике в четверг")

    r = client.get(f"/web/messenger/chats/{conv}/messages/ai-search?q=практике", headers=h1)
    assert r.status_code == 200, r.text
    assert r.json()["expanded"] == []
    assert len(r.json()["messages"]) == 1


def test_ai_search_ranks_direct_match_above_synonym(client, monkeypatch):
    """То, что человек написал сам, весомее придуманного моделью синонима."""
    from app import messenger_ai
    monkeypatch.setattr(messenger_ai, "expand_query", lambda cfg, q: ["задание"])
    _admin, h1, _h2, conv = _setup_chat(client)
    _say(client, h1, conv, "какое там задание было")
    _say(client, h1, conv, "скинь домашку пожалуйста")

    r = client.get(f"/web/messenger/chats/{conv}/messages/ai-search?q=домашку", headers=h1)
    assert "домашку" in r.json()["messages"][0]["body"], r.json()["messages"]


def test_ai_search_requires_participation(client):
    admin, h1, _h2, conv = _setup_chat(client)
    outsider = make_teacher(client, admin, subjects=["Математика"])
    r = client.get(f"/web/messenger/chats/{conv}/messages/ai-search?q=привет", headers=outsider)
    assert r.status_code == 403, r.text


def test_ai_search_skips_messages_cleared_by_me(client, monkeypatch):
    """Очищенная у себя история не должна воскресать через умный поиск."""
    from app import messenger_ai
    monkeypatch.setattr(messenger_ai, "expand_query", lambda cfg, q: [])
    _admin, h1, _h2, conv = _setup_chat(client)
    _say(client, h1, conv, "старое сообщение про практику")
    assert client.delete(f"/web/messenger/chats/{conv}?clear_only=1",
                         headers=h1).status_code == 200

    r = client.get(f"/web/messenger/chats/{conv}/messages/ai-search?q=практику", headers=h1)
    assert r.json()["messages"] == [], r.json()


# ── §18. Сводка ─────────────────────────────────────────────────────────────────────
def test_summary_masks_real_names_before_sending(client, monkeypatch):
    """ФИО реальных людей не должны уезжать в облачную модель."""
    seen = []
    from app import vector_llm

    def spy(cfg, messages, temperature=0.3):
        seen.append(messages)
        return "• Обсудили практику"
    monkeypatch.setattr(vector_llm, "complete", spy)

    _admin, h1, h2, conv = _setup_chat(client)
    _say(client, h1, conv, "Иванова Мария не придёт на практику")
    _say(client, h2, conv, "хорошо, передам")
    _say(client, h1, conv, "спасибо")

    r = client.get(f"/web/messenger/chats/{conv}/summary", headers=h1)
    assert r.status_code == 200, r.text
    assert r.json()["summary"] == "• Обсудили практику"

    blob = str(seen)
    assert "Иванова" not in blob and "Мария" not in blob, f"ФИО утекло в модель: {blob}"
    assert "Студент" in blob, "обезличивание должно сохранять смысл фразы"


def test_summary_says_honestly_when_model_unavailable(client, monkeypatch):
    """Нет модели → пустая сводка и причина, а НЕ выдуманный текст."""
    from app import vector_llm
    monkeypatch.setattr(vector_llm, "complete", lambda cfg, m, temperature=0.3: "")
    _admin, h1, h2, conv = _setup_chat(client)
    for t in ("раз", "два", "три"):
        _say(client, h1, conv, t)

    r = client.get(f"/web/messenger/chats/{conv}/summary", headers=h1)
    assert r.json() == {"summary": "", "reason": "no_model", "messages": 3}, r.json()


def test_summary_is_cached_until_new_message(client, monkeypatch):
    """Повторное нажатие не должно снова платить за токены."""
    calls = {"n": 0}
    from app import vector_llm

    def counting(cfg, messages, temperature=0.3):
        calls["n"] += 1
        return f"сводка {calls['n']}"
    monkeypatch.setattr(vector_llm, "complete", counting)

    _admin, h1, _h2, conv = _setup_chat(client)
    for t in ("раз", "два", "три"):
        _say(client, h1, conv, t)

    first = client.get(f"/web/messenger/chats/{conv}/summary", headers=h1).json()
    second = client.get(f"/web/messenger/chats/{conv}/summary", headers=h1).json()
    assert first["summary"] == second["summary"] and second["cached"] is True
    assert calls["n"] == 1, "сводка пересчиталась без новых сообщений"

    _say(client, h1, conv, "четыре")
    third = client.get(f"/web/messenger/chats/{conv}/summary", headers=h1).json()
    assert third["cached"] is False and calls["n"] == 2


def test_summary_needs_a_real_conversation(client, monkeypatch):
    """Два сообщения пересказывать нечего — не тратим запрос к модели."""
    from app import vector_llm
    monkeypatch.setattr(vector_llm, "complete",
                        lambda cfg, m, temperature=0.3: pytest.fail("модель не нужна"))
    _admin, h1, _h2, conv = _setup_chat(client)
    _say(client, h1, conv, "привет")
    r = client.get(f"/web/messenger/chats/{conv}/summary", headers=h1)
    assert r.json()["reason"] == "too_short", r.json()


def test_summary_requires_participation(client):
    admin, h1, _h2, conv = _setup_chat(client)
    outsider = make_teacher(client, admin, subjects=["Математика"])
    assert client.get(f"/web/messenger/chats/{conv}/summary",
                      headers=outsider).status_code == 403


# ── §19. Напоминания ────────────────────────────────────────────────────────────────
def test_reminder_suggested_from_message_text(client):
    _admin, h1, _h2, conv = _setup_chat(client)
    mid = _say(client, h1, conv, "Сдать отчёт завтра в 15:00")
    r = client.get(f"/web/messenger/messages/{mid}/reminder-suggest", headers=h1)
    assert r.status_code == 200, r.text
    assert r.json()["matched"] == "завтра" and r.json()["when"], r.json()


def test_reminder_not_suggested_without_date(client):
    """Нет даты — нет подсказки. Ложное предложение раздражает сильнее отсутствия."""
    _admin, h1, _h2, conv = _setup_chat(client)
    mid = _say(client, h1, conv, "скинь конспект пожалуйста")
    assert client.get(f"/web/messenger/messages/{mid}/reminder-suggest",
                      headers=h1).json()["when"] == ""


def test_reminder_fires_once_into_events(client):
    """Наступившее напоминание превращается в уведомление — и ровно один раз."""
    _admin, h1, _h2, conv = _setup_chat(client)
    mid = _say(client, h1, conv, "созвон по практике")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    r = client.post(f"/web/messenger/messages/{mid}/reminder",
                    json={"when": past}, headers=h1)
    assert r.status_code == 200, r.text

    def reminders_in_events():
        items = client.get("/me/events?filter=all&limit=100", headers=h1).json()["items"]
        return [i for i in items if i["kind"] == "reminder"]

    fired = reminders_in_events()
    assert len(fired) == 1, fired
    assert "созвон по практике" in fired[0]["body"], fired[0]
    #Повторный заход не должен задваивать уведомление.
    assert len(reminders_in_events()) == 1


def test_future_reminder_does_not_fire_yet(client):
    _admin, h1, _h2, conv = _setup_chat(client)
    mid = _say(client, h1, conv, "экзамен")
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    client.post(f"/web/messenger/messages/{mid}/reminder", json={"when": future}, headers=h1)

    items = client.get("/me/events?filter=all&limit=100", headers=h1).json()["items"]
    assert not [i for i in items if i["kind"] == "reminder"]
    #…но в списке своих напоминаний оно видно.
    assert len(client.get("/web/messenger/reminders", headers=h1).json()["reminders"]) == 1


def test_reminder_text_is_a_snapshot(client):
    """Автор отредактировал сообщение — напоминание осталось прежним."""
    _admin, h1, _h2, conv = _setup_chat(client)
    mid = _say(client, h1, conv, "принести справку завтра")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    client.post(f"/web/messenger/messages/{mid}/reminder", json={"when": past}, headers=h1)
    client.patch(f"/web/messenger/messages/{mid}", json={"body": "отбой, не надо"}, headers=h1)

    items = client.get("/me/events?filter=all&limit=100", headers=h1).json()["items"]
    fired = [i for i in items if i["kind"] == "reminder"][0]
    assert "принести справку" in fired["body"], fired


def test_reminder_is_private_to_its_owner(client):
    _admin, h1, h2, conv = _setup_chat(client)
    mid = _say(client, h1, conv, "экзамен 20 июля")
    rid = client.post(f"/web/messenger/messages/{mid}/reminder",
                      json={"when": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
                      headers=h1).json()["reminder"]["id"]

    assert client.get("/web/messenger/reminders", headers=h2).json()["reminders"] == []
    assert client.delete(f"/web/messenger/reminders/{rid}", headers=h2).status_code == 404
    assert client.delete(f"/web/messenger/reminders/{rid}", headers=h1).status_code == 200


def test_reminder_needs_participation(client):
    admin, h1, _h2, conv = _setup_chat(client)
    mid = _say(client, h1, conv, "завтра в 10:00")
    outsider = make_teacher(client, admin, subjects=["Математика"])
    assert client.post(f"/web/messenger/messages/{mid}/reminder",
                       json={}, headers=outsider).status_code == 403


def test_reminder_without_date_and_without_when_is_rejected(client):
    _admin, h1, _h2, conv = _setup_chat(client)
    mid = _say(client, h1, conv, "скинь конспект")
    r = client.post(f"/web/messenger/messages/{mid}/reminder", json={}, headers=h1)
    assert r.status_code == 400, r.text
