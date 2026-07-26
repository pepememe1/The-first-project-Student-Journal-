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


def test_static_intents_are_not_voiced_by_llm(client, monkeypatch):
    """АНТИ-ГАЛЛЮЦИНАЦИЯ (§5): приветствие/справку/благодарность НЕЛЬЗЯ отдавать в LLM.

    Была регрессия: сайт гнал через модель и `hello`, где цифр нет, а есть лишь ПЕРЕЧЕНЬ
    метрик («средний балл», «должники»). Модель дописывала шаблон с плейсхолдерами —
    «Средний балл по группам: [укажите средние баллы]» — вместо реальных данных. Десктоп
    такой guard имел (vector/engine.py::ask), веб — нет. Тест держит паритет.
    """
    from app import vector_llm
    monkeypatch.setattr(vector_llm, "voice",
                        lambda cfg, text, role, question: "LLM_ОЗВУЧИЛ")

    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])

    #Приветствие/справка/благодарность — отдаются КАК ЕСТЬ, LLM не зовём вовсе.
    for msg in ("привет", "что ты умеешь?", "спасибо"):
        r = client.post("/web/vector/ask", json={"message": msg}, headers=th).json()
        assert r["text"] != "LLM_ОЗВУЧИЛ", f"«{msg}» ({r['intent']}) не должен идти в LLM: {r}"

    #А вот ответ С РЕАЛЬНЫМИ ЦИФРАМИ озвучивать можно и нужно (стиль Вектора).
    r = client.post("/web/vector/ask", json={"message": "сколько студентов"},
                    headers=admin).json()
    assert r["intent"] == "group_stats"
    assert r["text"] == "LLM_ОЗВУЧИЛ", f"ответ с цифрами должен озвучиваться LLM: {r}"


def test_offtopic_goes_to_free_chat_not_canned_help(client, monkeypatch):
    """Небанальный/НЕжурнальный вопрос (unknown) уходит в free_chat (small-talk с
    редиректом к учёбе), а не в шаблонную справку. Данные журнала при этом НЕ выдумываются
    (их дают интенты). free_chat замокан — проверяем сам МАРШРУТ."""
    from app import vector_llm
    #context — необязательный 4-й аргумент (заметки «Избранного»), у обычного /vector/ask пуст.
    monkeypatch.setattr(vector_llm, "free_chat",
                        lambda cfg, q, role, context="": f"SMALLTALK:{role}")
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    #Пример НАРОЧНО не про погоду: с появлением реальных метеоданных «какая погода»
    #стала полноценным интентом weather (ответ строится по факту, а не моделью).
    #Здесь проверяется маршрут для вопросов, у которых интента нет вовсе.
    r = client.post("/web/vector/ask",
                    json={"message": "посоветуй что почитать на выходных"}, headers=th).json()
    assert r["intent"] == "unknown", r
    assert r["text"] == "SMALLTALK:teacher", r      # ушёл в free_chat, а не в справку


def test_server_info(client):
    admin = make_admin(client)
    r = client.get("/web/admin/server-info", headers=admin).json()
    assert r["version"] and r["db_kind"] and "crypto_backend" in r
    assert r["counts"]["students"] >= 0
    assert "pdn_field_encrypted" in r and "db_file_encrypted" in r
