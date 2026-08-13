"""
test_tts.py — десктопная озвучка «Вектора» (vector/tts.py).

Реальный Silero/torch и звук в тестах не задействуем: проверяем МАРШРУТ (какой слой
синтеза выбирается), barge-in (поколения) и маппинг голосов, а не саму нейросеть.
"""
import wave
import io

import pytest

from vector import tts


# ── Маппинг голосов и настройки ─────────────────────────────────────────────────────
def test_speaker_mapping():
    assert tts._SPEAKERS["male"] == "eugene"     # натуральнее aidar — голос по умолчанию
    assert tts._SPEAKERS["female"] == "baya"


def test_ssml_has_prosody_and_pauses():
    """Локальный SSML — с просодией и паузами на знаках (паритет с сервером)."""
    s = tts._ssml("Привет. Балл четыре, долгов нет.", "male")
    assert "<prosody" in s and 'rate="medium"' in s
    assert '<break time="450ms"/>' in s and '<break time="200ms"/>' in s


def test_prefs_default_male_enabled():
    """Без сохранённых настроек озвучка включена, голос — мужской (дефолт по ТЗ)."""
    assert tts.get_voice() in ("male", "female")
    assert tts.is_enabled() in (True, False)     # не бросает даже без стора


def test_prefs_roundtrip(monkeypatch):
    """set_voice/get_voice и флаг вкл/выкл ходят через локальные настройки ПК."""
    store = {}
    from data import data_store
    monkeypatch.setattr(data_store, "local_set", lambda k, v: store.__setitem__(k, v) or True)
    monkeypatch.setattr(data_store, "local_get", lambda k, d=None: store.get(k, d))

    tts.set_voice("female")
    assert tts.get_voice() == "female"
    tts.set_voice("male")
    assert tts.get_voice() == "male"

    tts.set_enabled(False)
    assert tts.is_enabled() is False
    tts.set_enabled(True)
    assert tts.is_enabled() is True


# ── Barge-in: поколения ─────────────────────────────────────────────────────────────
def test_stop_bumps_generation():
    """stop() двигает поколение — это и есть отмена ещё не проигранного синтеза."""
    g0 = tts._gen
    tts.stop()
    assert tts._gen == g0 + 1


class _FakeThread:
    """Синхронный поток: start() сразу выполняет target — тест детерминирован."""
    def __init__(self, target=None, args=(), daemon=None):
        self._t, self._a = target, args

    def start(self):
        self._t(*self._a)


def test_speak_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(tts, "get_mode", lambda: "off")
    rec = []
    monkeypatch.setattr(tts, "_worker", lambda t, v, g: rec.append((t, v, g)))
    tts.speak("привет")
    assert rec == [], "выключенная озвучка (режим off) не должна синтезировать"


def test_speak_mumble_uses_mumble_worker(monkeypatch):
    """В режиме «бубнеж» речь идёт через _mumble_worker, а НЕ через серверный/локальный синтез."""
    monkeypatch.setattr(tts, "get_mode", lambda: "mumble")
    monkeypatch.setattr(tts.threading, "Thread", _FakeThread)
    voice_rec, mumble_rec = [], []
    monkeypatch.setattr(tts, "_worker", lambda t, v, g, *a: voice_rec.append(t))
    monkeypatch.setattr(tts, "_mumble_worker", lambda t, v, g, *a: mumble_rec.append(t))
    tts.speak("привет")
    assert mumble_rec == ["привет"] and voice_rec == [], "бубнеж не должен звать синтез речи"


def test_speak_starts_worker_with_current_gen(monkeypatch):
    """speak() перебивает прежнюю речь (gen++) и запускает воркер с текущим поколением
    и выбранным голосом."""
    monkeypatch.setattr(tts, "get_mode", lambda: "voice")
    monkeypatch.setattr(tts, "get_voice", lambda: "female")
    monkeypatch.setattr(tts.threading, "Thread", _FakeThread)
    rec = []
    monkeypatch.setattr(tts, "_worker", lambda t, v, g, *a: rec.append((t, v, g)))

    g0 = tts._gen
    tts.speak("сколько у меня оценок")
    assert tts._gen == g0 + 1                     # stop() внутри speak двинул поколение
    assert rec and rec[0][0] == "сколько у меня оценок"
    assert rec[0][1] == "female"
    assert rec[0][2] == tts._gen                  # воркер получил СВЕЖЕЕ поколение


def test_speak_fires_start_end_callbacks(monkeypatch):
    """on_start/on_end зовутся ВОКРУГ реального воспроизведения (анимация речи маскота
    длится ровно пока играет звук)."""
    monkeypatch.setattr(tts, "get_mode", lambda: "voice")
    monkeypatch.setattr(tts.threading, "Thread", _FakeThread)
    monkeypatch.setattr(tts, "_server_wav", lambda text, voice: b"WAV")
    monkeypatch.setattr(tts, "_wav_to_samples", lambda data: (["s"], 24000))
    order = []
    monkeypatch.setattr(tts, "_play_samples",
                        lambda s, sr, g: order.append("play") or True)
    tts.speak("длинный ответ", on_start=lambda: order.append("start"),
              on_end=lambda: order.append("end"))
    assert order == ["start", "play", "end"], "старт → звук → конец, строго в этом порядке"


def test_speak_callbacks_skipped_for_stale_generation(monkeypatch):
    """Колбэки перебитого barge-in'ом воркера молчат (защита по поколению) — иначе
    устаревший конец речи погасил бы анимацию свежего ответа."""
    monkeypatch.setattr(tts, "_play_samples", lambda s, sr, g: True)
    fired = []
    stale = tts._gen - 1                            # уже неактуальное поколение
    tts._play_cb(["s"], 24000, stale,
                 on_start=lambda: fired.append("start"),
                 on_end=lambda: fired.append("end"))
    assert fired == [], "устаревшее поколение не должно дёргать анимацию"


# ── Выбор слоя синтеза (сервер → локальный Silero → SAPI) ───────────────────────────
def _mock_layers(monkeypatch):
    played = []
    monkeypatch.setattr(tts, "_play_samples", lambda s, sr, g: played.append(s) or True)
    monkeypatch.setattr(tts, "_wav_to_samples", lambda data: ([f"srv:{data}"], 24000))
    return played


def test_worker_prefers_server(monkeypatch):
    played = _mock_layers(monkeypatch)
    monkeypatch.setattr(tts, "_server_wav", lambda text, voice: b"WAV")
    local_called = {"n": 0}; sapi_called = {"n": 0}
    monkeypatch.setattr(tts, "_local_samples", lambda t, v: local_called.__setitem__("n", 1))
    monkeypatch.setattr(tts, "_speak_sapi", lambda t, v, g: sapi_called.__setitem__("n", 1))

    tts._worker("привет", "male", tts._gen)
    assert played == [["srv:b'WAV'"]]
    assert local_called["n"] == 0 and sapi_called["n"] == 0, "сервер сыграл — дальше не идём"


def test_worker_falls_back_to_local(monkeypatch):
    played = _mock_layers(monkeypatch)
    monkeypatch.setattr(tts, "_server_wav", lambda text, voice: None)   # нет сети/токена
    monkeypatch.setattr(tts, "_local_samples", lambda t, v: (["local"], 24000))
    sapi_called = {"n": 0}
    monkeypatch.setattr(tts, "_speak_sapi", lambda t, v, g: sapi_called.__setitem__("n", 1))

    tts._worker("привет", "male", tts._gen)
    assert played == [["local"]]
    assert sapi_called["n"] == 0, "локальный Silero сыграл — SAPI не нужен"


def test_worker_falls_back_to_sapi(monkeypatch):
    _mock_layers(monkeypatch)
    monkeypatch.setattr(tts, "_server_wav", lambda text, voice: None)
    monkeypatch.setattr(tts, "_local_samples", lambda t, v: None)       # нет torch
    sapi = {"text": None, "voice": None}
    monkeypatch.setattr(tts, "_speak_sapi",
                        lambda t, v, g: sapi.update(text=t, voice=v))

    tts._worker("нет сети совсем", "female", tts._gen)
    assert sapi == {"text": "нет сети совсем", "voice": "female"}, "последний рубеж — SAPI"


# ── Декодирование серверного WAV ────────────────────────────────────────────────────
def test_wav_to_samples_roundtrip():
    """Серверный WAV (int16 моно) корректно раскладывается в сэмплы и частоту."""
    np = pytest.importorskip("numpy")   # numpy может быть не установлен в CI — тогда пропуск
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(np.array([0, 16384, -16384, 32767], dtype="<i2").tobytes())
    samples, sr = tts._wav_to_samples(buf.getvalue())
    assert sr == 24000
    assert len(samples) == 4
    assert -1.0 <= float(samples.min()) and float(samples.max()) <= 1.0
