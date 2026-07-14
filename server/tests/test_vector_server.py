"""
test_vector_server.py — Вектор (оффлайн-интенты: help/привет/статистика по делу) +
инфо-панель «Сервер».
"""
from conftest import make_admin, make_teacher


def test_vector_help_and_greeting_intents(client):
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    # «что ты умеешь» у преподавателя → подсказка, НЕ статистика по группам
    r = client.post("/web/vector/ask", json={"message": "что ты умеешь?"}, headers=th).json()
    assert r["intent"] == "help", r
    assert "умею" in r["text"].lower()
    # приветствие
    r2 = client.post("/web/vector/ask", json={"message": "привет"}, headers=th).json()
    assert r2["intent"] == "hello", r2
    # админ: «что умеешь» → help; «сколько студентов» → счётчики
    assert client.post("/web/vector/ask", json={"message": "что умеешь"}, headers=admin).json()["intent"] == "help"
    assert client.post("/web/vector/ask", json={"message": "сколько студентов"}, headers=admin).json()["intent"] == "group_stats"


def test_server_info(client):
    admin = make_admin(client)
    r = client.get("/web/admin/server-info", headers=admin).json()
    assert r["version"] and r["db_kind"] and "crypto_backend" in r
    assert r["counts"]["students"] >= 0
    assert "pdn_field_encrypted" in r and "db_file_encrypted" in r
