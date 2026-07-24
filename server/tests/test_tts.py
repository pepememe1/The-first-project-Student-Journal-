"""
test_tts.py — серверная озвучка «Вектора» (Text-to-Speech).

Движок Silero (torch) в CI не ставим — мокаем синтез. Проверяем КОНТРАКТ эндпоинтов и
логику tts_service (кэш, маппинг голосов, обрезка длины, guard админом), а не саму
нейросеть.
"""
from conftest import make_admin, make_teacher


# ── Эндпоинт /web/vector/tts ────────────────────────────────────────────────────────
def test_tts_requires_auth(client):
    """Без токена — 401 (озвучка не публична)."""
    r = client.post("/web/vector/tts", json={"text": "привет"})
    assert r.status_code == 401, r.text


def test_tts_returns_audio(client, monkeypatch):
    """Успех: отдаём WAV с audio/wav. Синтез замокан — torch не нужен."""
    from app import tts_service
    monkeypatch.setattr(tts_service, "synthesize",
                        lambda text, voice="male", engine="silero": {
                            "ok": True, "audio": b"RIFFfake",
                            "mime": "audio/wav", "error": ""})
    admin = make_admin(client)
    r = client.post("/web/vector/tts", json={"text": "средний балл четыре"}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("audio/wav")
    assert r.content == b"RIFFfake"


def test_tts_empty_text_400(client):
    admin = make_admin(client)
    r = client.post("/web/vector/tts", json={"text": "   "}, headers=admin)
    assert r.status_code == 400, r.text


def test_tts_engine_unavailable_503(client, monkeypatch):
    """Движок не поднялся (нет torch/модели) → 503 (клиент откатится на браузерный синтез)."""
    from app import tts_service
    monkeypatch.setattr(tts_service, "synthesize",
                        lambda text, voice="male", engine="silero": {
                            "ok": False, "audio": b"", "mime": "", "error": "нет движка"})
    admin = make_admin(client)
    r = client.post("/web/vector/tts", json={"text": "привет"}, headers=admin)
    assert r.status_code == 503, r.text


def test_tts_disabled_by_admin_503(client, monkeypatch):
    """Админ выключил озвучку глобально (tts_enabled=false) → 503, синтез даже не зовём."""
    from app import tts_service
    called = {"n": 0}

    def _synth(text, voice="male", engine="silero"):
        called["n"] += 1
        return {"ok": True, "audio": b"x", "mime": "audio/wav", "error": ""}
    monkeypatch.setattr(tts_service, "synthesize", _synth)

    admin = make_admin(client)
    assert client.post("/web/admin/ai-config", json={"tts_enabled": False},
                       headers=admin).status_code == 200
    r = client.post("/web/vector/tts", json={"text": "привет"}, headers=admin)
    assert r.status_code == 503, r.text
    assert called["n"] == 0, "при выключенной озвучке синтез вызывать нельзя"


def test_tts_status_reports_flag_and_voices(client, monkeypatch):
    """status = (движок доступен И админ не выключил) + список голосов для UI."""
    from app import tts_service
    monkeypatch.setattr(tts_service, "is_available", lambda: True)
    admin = make_admin(client)
    r = client.get("/web/vector/tts/status", headers=admin).json()
    assert r["available"] is True
    assert set(r["voices"].keys()) == {"male", "female"}

    #Админ выключил — статус становится недоступным несмотря на живой движок.
    client.post("/web/admin/ai-config", json={"tts_enabled": False}, headers=admin)
    r2 = client.get("/web/vector/tts/status", headers=admin).json()
    assert r2["available"] is False


def test_tts_enabled_persists_in_ai_config(client):
    """Флаг tts_enabled читается/сохраняется через admin ai-config (дефолт — вкл)."""
    admin = make_admin(client)
    assert client.get("/web/admin/ai-config", headers=admin).json()["tts_enabled"] is True
    client.post("/web/admin/ai-config", json={"tts_enabled": False}, headers=admin)
    assert client.get("/web/admin/ai-config", headers=admin).json()["tts_enabled"] is False


def test_tts_status_teacher_allowed(client, monkeypatch):
    """Озвучка — для всех ролей (не только админ). Преподаватель тоже видит статус."""
    from app import tts_service
    monkeypatch.setattr(tts_service, "is_available", lambda: True)
    admin = make_admin(client)
    th = make_teacher(client, admin, subjects=["Мат"])
    r = client.get("/web/vector/tts/status", headers=th)
    assert r.status_code == 200, r.text


# ── Логика tts_service (кэш, голоса, длина) — без реального Silero ──────────────────
class _FakeModel:
    """Подделка модели Silero: запоминает speaker и озвучиваемый текст (SSML или обычный)."""
    def __init__(self):
        self.calls = []

    def apply_tts(self, speaker, sample_rate, text=None, ssml_text=None,
                  put_accent=None, put_yo=None):
        self.calls.append({"speaker": speaker, "text": text, "ssml": ssml_text})
        return [0.0, 0.1, -0.1]     # «сэмплы» — _to_wav замокан, содержимое неважно

    def spoken(self, i=0):
        """Что реально ушло в синтез (SSML-путь основной, text — откат)."""
        c = self.calls[i]
        return c["ssml"] or c["text"] or ""


def _patch_engine(monkeypatch):
    """Включаем движок в обход torch: is_available→True, _load→фейк, _to_wav→байты."""
    from app import tts_service
    tts_service._cache.clear()
    fake = _FakeModel()
    monkeypatch.setattr(tts_service, "is_available", lambda engine="silero": True)
    monkeypatch.setattr(tts_service, "_load", lambda: fake)
    monkeypatch.setattr(tts_service, "_to_wav", lambda audio, sr: b"WAV:" + bytes(len(audio)))
    return tts_service, fake


def test_synthesize_voice_mapping(monkeypatch):
    """male→eugene, female→baya, неизвестный голос→дефолт (eugene)."""
    tts_service, fake = _patch_engine(monkeypatch)
    assert tts_service.synthesize("текст один", "male")["ok"]
    assert tts_service.synthesize("текст два", "female")["ok"]
    assert tts_service.synthesize("текст три", "нет-такого")["ok"]
    speakers = [c["speaker"] for c in fake.calls]
    assert speakers == ["eugene", "baya", "eugene"], speakers


def test_synthesize_caches_by_voice_and_text(monkeypatch):
    """Повтор (тот же голос+текст) берётся из кэша — модель НЕ зовётся второй раз."""
    tts_service, fake = _patch_engine(monkeypatch)
    a = tts_service.synthesize("привет вектор", "male")
    b = tts_service.synthesize("привет вектор", "male")
    assert a["audio"] == b["audio"]
    assert len(fake.calls) == 1, "второй раз должен был отдаться кэш"
    #Другой голос на тот же текст — уже отдельный синтез.
    tts_service.synthesize("привет вектор", "female")
    assert len(fake.calls) == 2


def test_synthesize_truncates_long_text(monkeypatch):
    """Слишком длинный текст обрезается (_MAX_CHARS) — защита слабого VPS."""
    tts_service, fake = _patch_engine(monkeypatch)
    long = "а" * (tts_service._MAX_CHARS + 500)
    tts_service.synthesize(long, "male")
    #Текст уходит в SSML-обёртке — проверяем, что «а» осталось ровно _MAX_CHARS.
    assert fake.spoken(0).count("а") == tts_service._MAX_CHARS


def test_synthesize_wraps_ssml_with_prosody(monkeypatch):
    """Основной путь — SSML с просодией голоса (живее, а не «диктор»)."""
    tts_service, fake = _patch_engine(monkeypatch)
    tts_service.synthesize("привет вектор", "male")
    ssml = fake.calls[0]["ssml"]
    assert ssml and ssml.startswith("<speak>") and "<prosody" in ssml
    assert 'rate="medium"' in ssml and 'pitch="high"' in ssml


def test_ssml_inserts_pauses_on_punctuation(monkeypatch):
    """На точках/запятых вставляются паузы <break> — иначе Silero «тараторит»."""
    tts_service, _ = _patch_engine(monkeypatch)
    s = tts_service._ssml("Привет. Балл четыре, долгов нет.", "male")
    assert '<break time="450ms"/>' in s      # пауза после точки
    assert '<break time="200ms"/>' in s      # пауза после запятой


def test_ssml_escapes_special_chars(monkeypatch):
    """Символы <, >, & экранируются — иначе SSML-разметка ломается."""
    tts_service, _ = _patch_engine(monkeypatch)
    s = tts_service._ssml("2 < 3 & 5 > 4", "male")
    assert "&lt;" in s and "&amp;" in s and "&gt;" in s


def test_synthesize_empty_text(monkeypatch):
    tts_service, fake = _patch_engine(monkeypatch)
    r = tts_service.synthesize("   ", "male")
    assert r["ok"] is False
    assert not fake.calls


def test_engine_registry_and_unknown_falls_back(monkeypatch):
    """Движок выбирается конфигом; неизвестный — откат на дефолт (silero), а не ошибка.
    Задел под клон-голос на GPU: новый движок добавляется в _RENDERERS без правок synthesize."""
    tts_service, fake = _patch_engine(monkeypatch)
    assert "silero" in tts_service._RENDERERS
    #Неизвестный движок не роняет синтез — откатывается на silero.
    r = tts_service.synthesize("привет", "male", engine="нет-такого")
    assert r["ok"] is True and len(fake.calls) == 1


def test_synthesize_without_engine(monkeypatch):
    """Нет torch → ok=False с причиной, без падения."""
    from app import tts_service
    tts_service._cache.clear()
    monkeypatch.setattr(tts_service, "is_available", lambda engine="silero": False)
    r = tts_service.synthesize("привет", "male")
    assert r["ok"] is False and r["error"]
