"""
test_vector_provider.py — Выбор LLM-провайдера Вектора на десктопе.

Ключевой сценарий безопасности (152-ФЗ): у не-админа локально НЕТ токена GigaChat
(сервер вырезает его из pull). Тогда фабрика должна выбрать озвучку ЧЕРЕЗ СЕРВЕР
(ServerProvider), а не падать в оффлайн, — если есть адрес сервера и токен сессии.
"""
from sync import sync_runner
from vector.llm import get_provider


def test_offline_when_kind_offline():
    assert get_provider({"vector_llm": "offline"}).name == "offline"


def test_gigachat_without_creds_uses_server_when_available(monkeypatch):
    """Провайдер=gigachat, но ключа локально нет (не-админ) + сервер доступен →
    озвучка идёт через сервер (токен остаётся на сервере)."""
    monkeypatch.setattr(sync_runner, "current_auth", lambda: ("https://srv", "tok"))
    p = get_provider({"vector_llm": "gigachat"})   # без gigachat_credentials
    assert p.name == "server"


def test_gigachat_without_creds_and_no_server_falls_back_offline(monkeypatch):
    """Нет ни ключа, ни сервера/токена → честный офлайн-шаблонизатор."""
    monkeypatch.setattr(sync_runner, "current_auth", lambda: ("", ""))
    p = get_provider({"vector_llm": "gigachat"})
    assert p.name == "offline"
