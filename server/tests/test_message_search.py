"""Полнотекстовый поиск по сообщениям: FTS5 + BM25 (исследование 20.10.2026)."""
from conftest import make_admin, make_teacher

from app import message_search


def _people(client):
    admin = make_admin(client)
    t = make_teacher(client, admin)
    return admin, t


def _conv(client, t):
    return client.post("/web/messenger/chats/saved", headers=t).json()["conversation_id"]


def _search(client, h, conv, q):
    r = client.get(f"/web/messenger/chats/{conv}/messages/search", params={"q": q}, headers=h)
    assert r.status_code == 200, r.text
    return [m["body"] for m in r.json()["messages"]]


def test_message_older_than_the_last_2000_is_found(client):
    """Обратный ход прежнего дефекта: поиск смотрел только последние 2000 сообщений, и
    старое не находилось вовсе — молча."""
    from app.db import SessionLocal
    from app.models import Message
    admin, t = _people(client)
    conv = _conv(client, t)
    client.post(f"/web/messenger/chats/{conv}/messages",
                json={"body": "Пароль от вайфая в 728: зебра"}, headers=t)
    with SessionLocal() as db:
        db.add_all(Message(conversation_id=conv, sender_id="teach:teacher1",
                           body=f"шум {i}", created_at="2026-10-20T00:00:00", kind="text")
                   for i in range(2100))
        db.commit()
    assert _search(client, t, conv, "зебра") == ["Пароль от вайфая в 728: зебра"]


def test_word_forms_are_found_by_stem(client):
    admin, t = _people(client)
    conv = _conv(client, t)
    client.post(f"/web/messenger/chats/{conv}/messages",
                json={"body": "Не забыть выставить оценки за контрольную"}, headers=t)
    assert _search(client, t, conv, "оценкой") == ["Не забыть выставить оценки за контрольную"]
    assert _search(client, t, conv, "ОЦЕНКАМ") == ["Не забыть выставить оценки за контрольную"]
    #Честная граница: «оценок» (родительный множественного с беглой гласной) по основе
    #не сводится — так же, как у полного стеммера Snowball. Найдёт «оценк», не «оценок».
    assert message_search.stem("оценок") == "оценок"
    assert _search(client, t, conv, "химия") == []


def test_yo_and_ye_are_the_same_letter(client):
    admin, t = _people(client)
    conv = _conv(client, t)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "Ещё одна пятёрка"}, headers=t)
    assert _search(client, t, conv, "пятерка") == ["Ещё одна пятёрка"]


def test_query_syntax_cannot_break_the_search(client):
    admin, t = _people(client)
    conv = _conv(client, t)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "обычный текст"}, headers=t)
    for q in ['"', 'текст"* OR', "NEAR(", "-текст", "*", "a:b"]:
        r = client.get(f"/web/messenger/chats/{conv}/messages/search", params={"q": q}, headers=t)
        assert r.status_code == 200, (q, r.text)


def test_edited_and_deleted_messages_follow_the_index(client):
    """Индекс ведут триггеры базы: правка текста и удаление видны поиску сразу."""
    admin, t = _people(client)
    conv = _conv(client, t)
    m = client.post(f"/web/messenger/chats/{conv}/messages",
                    json={"body": "встреча в среду"}, headers=t).json()
    mid = m.get("id") or m["message"]["id"]
    client.patch(f"/web/messenger/messages/{mid}", json={"body": "встреча в пятницу"}, headers=t)
    assert _search(client, t, conv, "среда") == []
    assert _search(client, t, conv, "пятница") == ["встреча в пятницу"]
    client.delete(f"/web/messenger/messages/{mid}", headers=t)
    assert _search(client, t, conv, "пятница") == []


def test_without_fts_the_old_search_still_works(client, monkeypatch):
    admin, t = _people(client)
    conv = _conv(client, t)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "Когда экзамен?"}, headers=t)
    monkeypatch.setattr(message_search, "candidate_ids", lambda *a, **k: None)
    assert _search(client, t, conv, "экзамен") == ["Когда экзамен?"]


def test_stem_and_query_builder():
    assert message_search.stem("оценками") == "оценк"
    assert message_search.stem("дз") == "дз"
    assert message_search.build_query('оценки "по" математике') == '"оценк"* "по"* "математик"*'


def test_cleared_history_does_not_crowd_out_visible_matches(client, monkeypatch):
    """Находка Полковника 21.10.2026: кандидаты брались из индекса ДО фильтра видимости.
    После «очистить историю» лучшие по BM25 совпадения могли целиком лежать в очищенной
    старине — фильтр их отбрасывал, и поиск отвечал пусто при живом совпадении."""
    from app.db import SessionLocal
    from app.models import Message
    admin, t = _people(client)
    conv = _conv(client, t)
    with SessionLocal() as db:       #короткие и с повтором — по BM25 они ЛУЧШЕ нового
        db.add_all(Message(conversation_id=conv, sender_id="teach:teacher1",
                           body="зебра зебра", created_at="2026-01-01T00:00:00", kind="text")
                   for _ in range(5))
        db.commit()
    r = client.delete(f"/web/messenger/chats/{conv}?clear_only=true", headers=t)
    assert r.status_code == 200, r.text
    client.post(f"/web/messenger/chats/{conv}/messages",
                json={"body": "зебра пришла после очистки истории беседы"}, headers=t)
    monkeypatch.setattr(message_search, "CANDIDATES", 3)
    assert _search(client, t, conv, "зебра") == ["зебра пришла после очистки истории беседы"]


def test_a_piece_of_a_word_is_found_by_trigrams(client):
    """Разбор Ярослава 21.10.2026 (n-граммные индексы): кусок из середины слова
    находится, в любом регистре; короче трёх букв — не фрагмент, а обычное слово."""
    admin, t = _people(client)
    conv = _conv(client, t)
    client.post(f"/web/messenger/chats/{conv}/messages",
                json={"body": "Лабораторная по ПРОГРАММИРОВАНИЮ"}, headers=t)
    client.post(f"/web/messenger/chats/{conv}/messages", json={"body": "зебра в 728"}, headers=t)
    assert _search(client, t, conv, "граммир") == ["Лабораторная по ПРОГРАММИРОВАНИЮ"]
    assert _search(client, t, conv, "ЕБРА") == ["зебра в 728"]
    assert _search(client, t, conv, "ебра 728") == ["зебра в 728"]
    assert _search(client, t, conv, "еб") == []
    assert message_search.fragment_query('ебра "x" a_b') == '"ебра"'

