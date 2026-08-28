"""
test_translate.py — перевод сообщений мессенджера (29.08.2026: локальный Argos вместо Google).

Сам переводчик не дёргаем: тест чужой модели — не наш тест, да и ставить сотни мегабайт
моделей в прогон незачем (тот же приём, что у Whisper и Silero — движок мокается).
Подменяем `translate_service._argos_translate` и проверяем то, что написано нами и
может тихо испортить переписку:

  • 🔒 ТЕКСТ НЕ УХОДИТ НАРУЖУ. Главное свойство после замены движка: в модуле не должно
    остаться НИ ОДНОГО сетевого вызова. Раньше текст личной переписки уезжал в Google
    целиком — трансграничная передача ПДн без уведомления Роскомнадзора и без
    возможности оформить поручение обработки.
  • ОТКАЗ НЕ ПОДМЕНЯЕТСЯ ОРИГИНАЛОМ. Если переводчик недоступен, вернуть исходный текст
    под видом перевода нельзя: человек прочитает его и решит, что собеседник написал
    именно это. Отвечаем «не смогли» и называем причину.
  • ПЕРЕВОД НЕ ТРОГАЕТ СООБЩЕНИЕ. В базе остаётся то, что человек написал; перевод —
    способ ПРОЧИТАТЬ чужую реплику, а не её новая версия.
  • КОДЫ ЯЗЫКОВ ИЗ prefs ВАЛИДИРУЮТСЯ на входе.
  • ЖЁСТКИЙ ТАЙМАУТ остаётся, хотя сети больше нет: Argos считает на процессоре и
    синхронно, а на боевой машине одно ядро.
"""
import pytest

from conftest import make_admin

from app import translate_service


@pytest.fixture()
def fake_engine(monkeypatch):
    """Подменяем сам вызов модели: возвращает пометку и запоминает параметры.

    ⚠️ `engine_available` подменяем ТОЖЕ. Без этого все случаи ниже упирались бы в
    честный отказ «переводчик не установлен» — на машине прогона моделей Argos нет и
    быть не должно."""
    calls = []

    def fake(text, src, dst):
        calls.append((text, src, dst))
        return "[перевод] " + text

    monkeypatch.setattr(translate_service, "_argos_translate", fake)
    monkeypatch.setattr(translate_service, "engine_available", lambda: True)
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


def test_same_language_is_not_sent_to_the_engine(fake_engine):
    """Уже на нужном языке — запрос в сеть вообще не идёт."""
    out = translate_service.translate("Привет, как дела", "ru")
    assert out["ok"] and out["text"] == "Привет, как дела"
    assert fake_engine == [], "Google дёрнули там, где переводить нечего"


# ── Отказы ───────────────────────────────────────────────────────────────────────────
def test_unavailable_translator_is_an_honest_refusal(monkeypatch):
    """Молчаливый возврат оригинала хуже отказа: человек решит, что перевод сделан."""
    #Предпосылка: пакет ЕСТЬ, но перевод не удался. Без этой подмены случай упёрся бы
    #в более ранний отказ «переводчик не установлен» и проверял бы не то.
    monkeypatch.setattr(translate_service, "engine_available", lambda: True)
    monkeypatch.setattr(translate_service, "_argos_translate", lambda *a, **k: "")
    translate_service._CACHE.clear()
    out = translate_service.translate("Hello there", "ru")
    assert out["ok"] is False
    assert out["text"] == ""
    assert "недоступен" in out["reason"]


def test_engine_exception_does_not_break_the_chat(monkeypatch):
    """Перевод — дополнение. Падение (сеть легла/Google отклонил) не имеет права
    ронять запрос — та же гарантия, что была у LLM-версии."""
    def boom(*a, **k):
        raise RuntimeError("сеть легла")
    monkeypatch.setattr(translate_service, "_argos_translate", boom)
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

    monkeypatch.setattr(translate_service, "engine_available", lambda: True)
    monkeypatch.setattr(translate_service, "_argos_translate", slow)
    monkeypatch.setattr(translate_service, "_REQUEST_TIMEOUT_S", 0.05)
    translate_service._CACHE.clear()
    out = translate_service.translate("Hello", "ru")
    assert out["ok"] is False
    assert "недоступен" in out["reason"]


def test_unknown_language_is_refused():
    assert translate_service.translate("Hello", "de")["ok"] is False
    assert translate_service.translate("", "ru")["ok"] is False


# ── Коды языков переданы правильно ───────────────────────────────────────────────────
def test_language_codes_go_through_unchanged(fake_engine):
    """У Argos коды — обычные ISO 639-1, то есть РОВНО наши ключи LANGUAGES.

    Таблица соответствий, которая была нужна Google (у него упрощённый китайский
    «zh-CN», а не «zh»), исчезла вместе с ним — и это на одну молчаливую ошибку
    меньше. Сторож на то, что её не завели заново «на всякий случай»."""
    translate_service.translate("Hello", "zh")
    assert fake_engine[0][2] == "zh"
    assert not hasattr(translate_service, "_GOOGLE_LANG"), \
        "вернулась таблица кодов Google — значит вернулся и он сам"


def test_repeated_text_is_served_from_cache(fake_engine):
    """Одну реплику в групповом чате открывают несколько человек — гонять переводчик
    повторно незачем."""
    translate_service._CACHE.clear()
    translate_service.translate("Hello there", "ru")
    translate_service.translate("Hello there", "ru")
    assert len(fake_engine) == 1


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


def test_endpoint_translates(client, fake_engine):
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


# ── 🔒 Текст не уходит наружу ────────────────────────────────────────────────────────
def test_translate_never_reaches_the_network():
    """🔥 ГЛАВНОЕ СВОЙСТВО ЗАМЕНЫ: в модуле перевода нет ни одного сетевого вызова.

    Проверяем ОТСУТСТВИЕ обхода, а не наличие вызова Argos. Причина: вернуть Google
    можно одной строкой импорта, и никакой функциональный тест этого не заметит —
    перевод будет работать, просто текст личной переписки студентов снова начнёт
    уезжать иностранному юрлицу. Флага «использовать Google» мы не завели намеренно
    (его однажды переключат «на время, чтобы проверить»), и этот сторож — вторая
    половина того же решения.

    Обратный ход: верните `from deep_translator import GoogleTranslator` в модуль —
    краснеет."""
    import io
    import os
    src = io.open(os.path.join(os.path.dirname(translate_service.__file__),
                               "translate_service.py"), encoding="utf-8").read()
    #Отрезаем докстринг модуля: он ОБЯЗАН объяснять, почему Google убрали, и запрет на
    #само слово сделал бы объяснение невозможным. Проверяем исполняемую часть.
    body = src.split('"""', 2)[-1]
    for forbidden in ("deep_translator", "GoogleTranslator", "requests.", "urllib",
                      "httpx", "http://", "https://", "socket"):
        assert forbidden not in body, (
            f"в исполняемой части модуля перевода появилось «{forbidden}» — "
            f"текст переписки снова может уйти наружу")


def test_pivot_goes_through_english_when_there_is_no_direct_model(monkeypatch):
    """Пары ru->zh у Argos нет — перевод обязан идти через английский.

    ⚠️ Пивот делаем САМИ, а не полагаемся на догадливость библиотеки: свежие версии
    строят составной путь, старые нет, и поведение молча зависело бы от версии пакета
    на конкретной машине."""
    seen = []

    class _Eng:
        def __init__(self, a, b):
            self.a, self.b = a, b

        def translate(self, text):
            seen.append((self.a, self.b))
            return text + f"|{self.a}->{self.b}"

    def fake_direct(src, dst):
        #Прямой пары ru->zh нет, всё остальное есть — ровно как в каталоге Argos.
        if {src, dst} == {"ru", "zh"}:
            return None
        return _Eng(src, dst)

    monkeypatch.setattr(translate_service, "_direct", fake_direct)
    out = translate_service._argos_translate("Привет", "ru", "zh")
    assert seen == [("ru", "en"), ("en", "zh")], f"пивот пошёл не через английский: {seen}"
    assert out.endswith("|en->zh")


def test_missing_model_is_an_honest_error_not_silent_original(monkeypatch):
    """Модели нет — исключение, а НЕ возврат исходного текста.

    Возврат оригинала под видом перевода — худший исход: человек прочитает чужую
    реплику на незнакомом языке и решит, что собеседник написал именно это."""
    monkeypatch.setattr(translate_service, "_direct", lambda src, dst: None)
    with pytest.raises(RuntimeError):
        translate_service._argos_translate("Привет", "ru", "zh")


def test_engine_not_installed_is_reported_by_reason(monkeypatch):
    """Пакета нет — причина названа прямо, а не «попробуйте позже».

    Администратор должен прочитать «не установлен», а не гадать про сеть, которой
    здесь больше нет вовсе."""
    monkeypatch.setattr(translate_service, "engine_available", lambda: False)
    translate_service._CACHE.clear()
    r = translate_service.translate("Hello", "ru")
    assert r["ok"] is False
    assert "не установлен" in r["reason"].lower()
