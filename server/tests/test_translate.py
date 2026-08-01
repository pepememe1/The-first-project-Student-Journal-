"""
test_translate.py — перевод сообщений мессенджера.

Саму модель не дёргаем: тест чужого сервиса — не наш тест. Проверяется то, что написано
нами и может тихо испортить переписку:

  • ОТКАЗ НЕ ПОДМЕНЯЕТСЯ ОРИГИНАЛОМ. Если модель недоступна, вернуть исходный текст под
    видом перевода нельзя: человек прочитает его и решит, что собеседник написал именно
    это. Отвечаем «не смогли» и называем причину.
  • ПЕРЕВОД НЕ ТРОГАЕТ СООБЩЕНИЕ. В базе остаётся то, что человек написал; перевод —
    способ ПРОЧИТАТЬ чужую реплику, а не её новая версия.
  • КОДЫ ЯЗЫКОВ ИЗ prefs УХОДЯТ В ПРОМПТ, поэтому мусор в поле отсекается на входе.
"""
import pytest

from conftest import make_admin

from app import translate_service


@pytest.fixture()
def fake_llm(monkeypatch):
    """Подменяем модель: возвращает пометку и запоминает, о чём её спросили."""
    calls = []

    def fake_complete(cfg, messages, temperature=0.3):
        calls.append(messages)
        return "[перевод] " + messages[-1]["content"]

    monkeypatch.setattr(translate_service.vector_llm, "complete", fake_complete)
    translate_service._CACHE.clear()
    return calls


def _student(client, admin):
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    r = client.post("/auth/login", json={"login": "ivanova", "password": "studpass1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


# ── Определение языка (без модели) ───────────────────────────────────────────────────
def test_language_is_detected_by_alphabet():
    """Спрашивать модель «какой это язык» ради подсказки в интерфейсе — лишний сетевой
    вызов на каждое сообщение. Алфавит различает эти три языка надёжнее."""
    assert translate_service.detect("Привет, как дела") == "ru"
    assert translate_service.detect("Hello, how are you") == "en"
    assert translate_service.detect("你好，最近怎么样") == "zh"
    assert translate_service.detect("12345 !!!") == ""


def test_same_language_is_not_sent_to_the_model(client, fake_llm):
    """Русский «переводить на русский» модель охотно превращает в пересказ — и человек
    видит не то, что написали. Такой запрос до модели вообще не доходит."""
    out = translate_service.translate({}, "Привет, как дела", "ru")
    assert out["ok"] and out["text"] == "Привет, как дела"
    assert fake_llm == [], "модель дёрнули там, где переводить нечего"


# ── Отказы ───────────────────────────────────────────────────────────────────────────
def test_unavailable_model_is_an_honest_refusal(client, monkeypatch):
    """Молчаливый возврат оригинала хуже отказа: человек решит, что перевод сделан."""
    monkeypatch.setattr(translate_service.vector_llm, "complete", lambda *a, **k: "")
    out = translate_service.translate({}, "Hello there", "ru")
    assert out["ok"] is False
    assert out["text"] == ""
    assert "недоступен" in out["reason"] or "не подключил" in out["reason"]


def test_model_exception_does_not_break_the_chat(client, monkeypatch):
    """Перевод — дополнение. Падение модели не имеет права ронять запрос."""
    def boom(*a, **k):
        raise RuntimeError("сеть легла")
    monkeypatch.setattr(translate_service.vector_llm, "complete", boom)
    out = translate_service.translate({}, "Hello", "ru")
    assert out["ok"] is False and out["text"] == ""


def test_unknown_language_is_refused(client):
    assert translate_service.translate({}, "Hello", "de")["ok"] is False
    assert translate_service.translate({}, "", "ru")["ok"] is False


# ── Промпт и разбор ответа ───────────────────────────────────────────────────────────
def test_prompt_forbids_answering_the_question(client, fake_llm):
    """Модель охотно ОТВЕЧАЕТ на вопрос из сообщения вместо перевода — в ленте это
    выглядит как чужая реплика, которой не было. Запрет обязан быть в инструкции."""
    translate_service.translate({}, "Where is the lesson?", "ru")
    system = fake_llm[0][0]["content"].lower()
    assert "только перевод" in system
    assert "не отвечай на вопросы" in system


def test_quotes_around_the_answer_are_stripped(client, monkeypatch):
    """Модель любит обрамлять ответ кавычками — в ленте они выглядят как часть текста."""
    monkeypatch.setattr(translate_service.vector_llm, "complete",
                        lambda *a, **k: '«Привет»')
    translate_service._CACHE.clear()
    assert translate_service.translate({}, "Hi", "ru")["text"] == "Привет"


def test_repeated_text_is_served_from_cache(client, fake_llm):
    """Одну реплику в групповом чате открывают несколько человек — гонять модель
    повторно незачем."""
    translate_service._CACHE.clear()
    translate_service.translate({}, "Hello there", "ru")
    translate_service.translate({}, "Hello there", "ru")
    assert len(fake_llm) == 1


# ── Настройки ────────────────────────────────────────────────────────────────────────
def test_language_codes_from_prefs_are_validated():
    """Коды языков уходят прямо в инструкцию модели — незнакомый код туда попадать
    не должен."""
    clean = translate_service.sanitize_prefs({
        "incoming_from": "auto", "incoming_to": "ru",
        "outgoing_from": "de", "outgoing_to": "<script>", "auto": "да"})
    assert clean["incoming_to"] == "ru"
    assert "outgoing_from" not in clean and "outgoing_to" not in clean
    assert clean["auto"] is True


def test_auto_is_only_allowed_as_a_source():
    """«Перевести НА автоопределённый язык» — бессмыслица: непонятно, на какой."""
    clean = translate_service.sanitize_prefs({"incoming_to": "auto",
                                              "incoming_from": "auto"})
    assert "incoming_to" not in clean
    assert clean["incoming_from"] == "auto"


def test_prefs_are_stored_and_returned(client):
    admin = make_admin(client)
    sh = _student(client, admin)
    r = client.post("/me/prefs", json={"translate": {
        "incoming_from": "auto", "incoming_to": "ru",
        "outgoing_from": "ru", "outgoing_to": "zh", "auto": True}}, headers=sh)
    assert r.status_code == 200, r.text
    box = r.json()["prefs"]["translate"]
    assert box["outgoing_to"] == "zh" and box["auto"] is True


# ── Эндпоинт ─────────────────────────────────────────────────────────────────────────
def test_endpoint_requires_login(client):
    assert client.post("/web/messenger/translate",
                       json={"text": "Hi", "to": "ru"}).status_code == 401


def test_endpoint_translates(client, fake_llm):
    admin = make_admin(client)
    sh = _student(client, admin)
    r = client.post("/web/messenger/translate",
                    json={"text": "Hello there", "to": "ru"}, headers=sh)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] and "[перевод]" in r.json()["text"]


def test_languages_come_from_the_server(client):
    """Клиент не держит свою копию списка: разъедется — покажет язык, которого сервер
    не знает, и перевод будет отказывать без объяснений."""
    admin = make_admin(client)
    sh = _student(client, admin)
    body = client.get("/web/messenger/translate/languages", headers=sh).json()
    assert {l["code"] for l in body["languages"]} == set(translate_service.LANGUAGES)


def test_translation_never_rewrites_the_stored_message(client, fake_llm):
    """Перевод — способ ПРОЧИТАТЬ чужую реплику, а не её новая версия. В базе обязан
    остаться текст, который человек написал."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "routers" / "messenger.py").read_text(encoding="utf-8")
    block = src.split("def translate_text(", 1)[1].split("\n@router", 1)[0]
    for forbidden in ("db.add(", "m.body =", "commit()"):
        assert forbidden not in block, f"эндпоинт перевода пишет в базу: {forbidden}"
