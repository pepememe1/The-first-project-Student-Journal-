"""
test_translate.py — перевод сообщений мессенджера (3.5.5: Google Translate вместо LLM).

Сам Google не дёргаем: тест чужого сервиса — не наш тест. Подменяем
`translate_service._google_translate` и проверяем то, что написано нами и может тихо
испортить переписку:

  • ОТКАЗ НЕ ПОДМЕНЯЕТСЯ ОРИГИНАЛОМ. Если переводчик недоступен, вернуть исходный текст
    под видом перевода нельзя: человек прочитает его и решит, что собеседник написал
    именно это. Отвечаем «не смогли» и называем причину.
  • ПЕРЕВОД НЕ ТРОГАЕТ СООБЩЕНИЕ. В базе остаётся то, что человек написал; перевод —
    способ ПРОЧИТАТЬ чужую реплику, а не её новая версия.
  • КОДЫ ЯЗЫКОВ ИЗ prefs ВАЛИДИРУЮТСЯ на входе (уходят в реальный запрос к Google).
  • ЖЁСТКИЙ ТАЙМАУТ: у deep_translator своего таймаута нет, поэтому обёртка
    (_executor + future.result(timeout=...)) обязана сама оборвать зависший запрос.
"""
import pytest

from conftest import make_admin

from app import translate_service


@pytest.fixture()
def fake_google(monkeypatch):
    """Подменяем сам HTTP-вызов к Google Translate: возвращает пометку и запоминает,
    с какими параметрами его звали."""
    calls = []

    def fake(text, src, dst):
        calls.append((text, src, dst))
        return "[перевод] " + text

    monkeypatch.setattr(translate_service, "_google_translate", fake)
    translate_service._CACHE.clear()
    return calls


def _student(client, admin):
    client.post("/web/admin/students", json={
        "login": "ivanova", "surname": "Иванова", "name": "Мария", "group": "ИС-21",
        "password": "studpass1"}, headers=admin)
    r = client.post("/auth/login", json={"login": "ivanova", "password": "studpass1"})
    return {"Authorization": f"Bearer {r.json()['access_token']}", "X-Client": "web"}


# ── Определение языка (без сети) ─────────────────────────────────────────────────────
def test_language_is_detected_by_alphabet():
    """Спрашивать переводчик «какой это язык» ради подсказки в интерфейсе — лишний
    сетевой вызов на каждое сообщение. Алфавит различает эти три языка надёжнее."""
    assert translate_service.detect("Привет, как дела") == "ru"
    assert translate_service.detect("Hello, how are you") == "en"
    assert translate_service.detect("你好，最近怎么样") == "zh"
    assert translate_service.detect("12345 !!!") == ""


def test_same_language_is_not_sent_to_google(fake_google):
    """Уже на нужном языке — запрос в сеть вообще не идёт."""
    out = translate_service.translate("Привет, как дела", "ru")
    assert out["ok"] and out["text"] == "Привет, как дела"
    assert fake_google == [], "Google дёрнули там, где переводить нечего"


# ── Отказы ───────────────────────────────────────────────────────────────────────────
def test_unavailable_translator_is_an_honest_refusal(monkeypatch):
    """Молчаливый возврат оригинала хуже отказа: человек решит, что перевод сделан."""
    monkeypatch.setattr(translate_service, "_google_translate", lambda *a, **k: "")
    translate_service._CACHE.clear()
    out = translate_service.translate("Hello there", "ru")
    assert out["ok"] is False
    assert out["text"] == ""
    assert "недоступен" in out["reason"]


def test_google_exception_does_not_break_the_chat(monkeypatch):
    """Перевод — дополнение. Падение (сеть легла/Google отклонил) не имеет права
    ронять запрос — та же гарантия, что была у LLM-версии."""
    def boom(*a, **k):
        raise RuntimeError("сеть легла")
    monkeypatch.setattr(translate_service, "_google_translate", boom)
    translate_service._CACHE.clear()
    out = translate_service.translate("Hello", "ru")
    assert out["ok"] is False and out["text"] == ""


def test_hung_request_is_cut_by_the_hard_timeout(monkeypatch):
    """У deep_translator НЕТ своего таймаута — голый зависший HTTP-запрос иначе держал
    бы поток вечно. Подменяем предел на мгновенный, а сам вызов — на «спящий дольше
    предела»: обёртка обязана вернуть честный отказ, а не подвиснуть вместе с ним."""
    import time as _time

    def slow(*a, **k):
        _time.sleep(0.3)
        return "не должно долететь"

    monkeypatch.setattr(translate_service, "_google_translate", slow)
    monkeypatch.setattr(translate_service, "_REQUEST_TIMEOUT_S", 0.05)
    translate_service._CACHE.clear()
    out = translate_service.translate("Hello", "ru")
    assert out["ok"] is False
    assert "недоступен" in out["reason"]


def test_unknown_language_is_refused():
    assert translate_service.translate("Hello", "de")["ok"] is False
    assert translate_service.translate("", "ru")["ok"] is False


# ── Коды языков переданы правильно ───────────────────────────────────────────────────
def test_chinese_uses_google_specific_code(fake_google):
    """Google принимает китайский как «zh-CN», а не голое «zh» — наш внутренний код
    обязан маппиться перед запросом, иначе Google тихо не поймёт параметр."""
    translate_service.translate("Hello", "zh")
    assert fake_google[0][2] == "zh"   # _google_translate получает НАШ код...
    # ...а маппинг на google-код проверяем напрямую, без сети:
    assert translate_service._GOOGLE_LANG["zh"] == "zh-CN"


def test_repeated_text_is_served_from_cache(fake_google):
    """Одну реплику в групповом чате открывают несколько человек — гонять переводчик
    повторно незачем."""
    translate_service._CACHE.clear()
    translate_service.translate("Hello there", "ru")
    translate_service.translate("Hello there", "ru")
    assert len(fake_google) == 1


# ── Настройки ────────────────────────────────────────────────────────────────────────
def test_language_codes_from_prefs_are_validated():
    """Коды языков уходят прямо в запрос к Google — незнакомый код туда попадать
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


def test_endpoint_translates(client, fake_google):
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


def test_translation_never_rewrites_the_stored_message():
    """Перевод — способ ПРОЧИТАТЬ чужую реплику, а не её новая версия. В базе обязан
    остаться текст, который человек написал."""
    import pathlib
    #⚠️ Мессенджер — ПАКЕТ, а не файл (разрез 3.7.7): читаем ВЕСЬ каталог и склеиваем.
    #Раньше здесь стоял путь к `messenger.py`, и после разреза тест упал с ENOENT. Это
    #хороший исход: читай он один модуль из восьми, эндпоинт мог бы переехать в соседний,
    #и проверка молча перестала бы что-либо проверять, оставаясь зелёной.
    pkg = pathlib.Path(__file__).resolve().parents[1] / "app" / "routers" / "messenger"
    src = "\n".join(f.read_text(encoding="utf-8") for f in sorted(pkg.glob("*.py")))
    assert "def translate_text(" in src, "эндпоинт перевода не найден в пакете мессенджера"
    block = src.split("def translate_text(", 1)[1].split("\n@router", 1)[0]
    for forbidden in ("db.add(", "m.body =", "commit()"):
        assert forbidden not in block, f"эндпоинт перевода пишет в базу: {forbidden}"
