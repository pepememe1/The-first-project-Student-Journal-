"""
tts.py — озвучка ответов «Вектора» на ДЕСКТОПЕ.

Три слоя, сверху вниз (первый доступный — побеждает):
  1. СЕРВЕР (онлайн) — синтез на хосте (Silero), как в вебе. Десктоп-онлайн отдаёт
     нагрузку туда: на боевом ПК ВСГУТУ это GPU, мгновенно. Нужны адрес+токен
     (sync_runner.current_auth) и рабочая сеть.
  2. ЛОКАЛЬНЫЙ Silero — если на машине учителя установлен torch (мощный ПК, но офлайн).
     Красиво и без сети, но torch в .exe не входит — только из исходников/по установке.
  3. Windows SAPI (pyttsx3) — ПОСЛЕДНИЙ рубеж: голос уже есть в любой Windows, ноль
     установки, работает офлайн и на самом слабом ноуте. Скромно, но Вектор ГОВОРИТ.

Проигрывание — через sounddevice (он уже в зависимостях голосового ВВОДА). Речь
асинхронная (отдельный поток, UI не блокируется). Новый ответ ПЕРЕБИВАЕТ предыдущую
озвучку (barge-in), как и в вебе.

Настройки — этого ПК (per-device, local_set): включена ли озвучка и голос (male/female).
По умолчанию: ВКЛЮЧЕНА, голос МУЖСКОЙ.
"""
import io
import os
import re
import html
import wave
import threading

import log

_LOG = log.get("vector.tts")

#Логический голос продукта → спикер Silero (для локального слоя). Держать СИНХРОННО с
#server/app/tts_service.py: male=eugene (натуральнее aidar), female=baya.
_SPEAKERS = {"male": "eugene", "female": "baya"}
_DEFAULT_VOICE = "male"

#Просодия голоса (SSML) — держать СИНХРОННО с server/app/tts_service.py::_PROSODY, чтобы
#локальная озвучка звучала так же живо, как серверная. rate — только словами Silero.
_PROSODY = {
    "male":   {"rate": "medium", "pitch": "high"},
    "female": {"rate": "medium", "pitch": "medium"},
}
_BREAK_SENTENCE = '<break time="450ms"/>'
_BREAK_CLAUSE = '<break time="200ms"/>'


def _ssml(text: str, voice: str) -> str:
    #Паузы на знаках препинания — иначе Silero не «соблюдает точки» (см. tts_service).
    pr = _PROSODY.get(voice, _PROSODY[_DEFAULT_VOICE])
    safe = html.escape(re.sub(r"\s+", " ", text).strip(), quote=False)
    safe = re.sub(r"([.!?…])(\s)", r"\1" + _BREAK_SENTENCE + r"\2", safe)
    safe = re.sub(r"([,;:—])(\s)", r"\1" + _BREAK_CLAUSE + r"\2", safe)
    return f'<speak><prosody rate="{pr["rate"]}" pitch="{pr["pitch"]}">{safe}</prosody></speak>'
_SAMPLE_RATE = 24000
_MAX_CHARS = 800
_MODEL_URL = "https://models.silero.ai/models/tts/ru/v4_ru.pt"

#Поколение озвучки: каждый новый speak() увеличивает счётчик; поток проверяет, что он
#ещё «свежий», прежде чем играть, — так barge-in не даёт старой фразе догнать новую.
_gen = 0
_gen_lock = threading.Lock()

_local_model = None
_local_lock = threading.Lock()


# ── Настройки этого ПК ──────────────────────────────────────────────────────────────
def is_enabled() -> bool:
    """Включена ли озвучка (по умолчанию да — выключает только явное 'off')."""
    try:
        from data_store import local_get
        return str(local_get("tts_enabled", "on")) != "off"
    except Exception:
        return True


def set_enabled(on: bool) -> None:
    try:
        from data_store import local_set
        local_set("tts_enabled", "on" if on else "off")
    except Exception as e:
        _LOG.warning(f"[tts] не сохранил флаг озвучки: {e}")
    if not on:
        stop()


def get_voice() -> str:
    """Выбранный голос ('male' по умолчанию)."""
    try:
        from data_store import local_get
        return "female" if str(local_get("tts_voice", "male")) == "female" else "male"
    except Exception:
        return "male"


def set_voice(voice: str) -> None:
    v = "female" if voice == "female" else "male"
    try:
        from data_store import local_set
        local_set("tts_voice", v)
    except Exception as e:
        _LOG.warning(f"[tts] не сохранил выбор голоса: {e}")


# ── Проигрывание ────────────────────────────────────────────────────────────────────
def stop() -> None:
    """Прервать текущую озвучку (barge-in / выключение)."""
    with _gen_lock:
        global _gen
        _gen += 1
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:
        pass


def _play_samples(samples, sample_rate: int, gen: int) -> bool:
    """Проигрывает numpy-массив float32, если поколение ещё актуально. True — сыграли."""
    import sounddevice as sd
    with _gen_lock:
        if gen != _gen:
            return False            #уже перебили новым ответом — не начинаем
    sd.play(samples, sample_rate)
    sd.wait()                       #блокирует ПОТОК (не UI); stop() прервёт ожидание
    return True


def _wav_to_samples(data: bytes):
    """WAV-байты (с сервера) → (numpy float32 [-1,1], sample_rate)."""
    import numpy as np
    with wave.open(io.BytesIO(data), "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    arr = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    return arr, sr


# ── Слой 1: сервер ──────────────────────────────────────────────────────────────────
def _server_wav(text: str, voice: str):
    """WAV-байты с сервера или None (нет сети/токена/движка)."""
    try:
        from sync_runner import current_auth
        url, token = current_auth()
    except Exception:
        url, token = ("", "")
    if not (url and token):
        return None
    try:
        from sync_client import SyncClient
        return SyncClient(url, token).tts(text, voice=voice)
    except Exception as e:
        _LOG.info(f"[tts] серверный синтез недоступен ({e}) — падаю на локальный")
        return None


# ── Слой 2: локальный Silero ────────────────────────────────────────────────────────
def _local_available() -> bool:
    try:
        import numpy  # noqa: F401
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def _model_path() -> str:
    root = os.environ.get("GRADEBOOK_TTS_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "gradebook-tts")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "v4_ru.pt")


def _load_local():
    global _local_model
    with _local_lock:
        if _local_model is not None:
            return _local_model
        import torch
        path = _model_path()
        if not (os.path.exists(path) and os.path.getsize(path) > 0):
            import urllib.request
            tmp = path + ".part"
            urllib.request.urlretrieve(_MODEL_URL, tmp)
            os.replace(tmp, path)
        model = torch.package.PackageImporter(path).load_pickle("tts_models", "model")
        model.to("cpu")
        _local_model = model
        return _local_model


def _local_samples(text: str, voice: str):
    """numpy-сэмплы от локального Silero или None."""
    if not _local_available():
        return None
    try:
        import numpy as np
        model = _load_local()
        speaker = _SPEAKERS.get(voice, _SPEAKERS[_DEFAULT_VOICE])
        try:
            audio = model.apply_tts(ssml_text=_ssml(text, voice), speaker=speaker,
                                    sample_rate=_SAMPLE_RATE)
        except Exception:
            audio = model.apply_tts(text=text, speaker=speaker, sample_rate=_SAMPLE_RATE,
                                    put_accent=True, put_yo=True)
        arr = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        return arr.astype("float32"), _SAMPLE_RATE
    except Exception as e:
        _LOG.info(f"[tts] локальный Silero не сработал ({e}) — падаю на SAPI")
        return None


# ── Слой 3: Windows SAPI (pyttsx3) ──────────────────────────────────────────────────
def _speak_sapi(text: str, voice: str, gen: int) -> None:
    """Последний рубеж: системный синтез Windows. Своё проигрывание (блокирует поток)."""
    try:
        import pyttsx3
    except Exception:
        _LOG.info("[tts] pyttsx3 не установлен — озвучка недоступна")
        return
    try:
        engine = pyttsx3.init()
        want_female = (voice == "female")
        ru = []
        for v in engine.getProperty("voices") or []:
            name = (getattr(v, "name", "") or "").lower()
            vid = (getattr(v, "id", "") or "").lower()
            langs = " ".join(str(x).lower() for x in (getattr(v, "languages", []) or []))
            if ("russ" in name or "ru" in langs or "russian" in name or "rhvoice" in vid
                    or "ирин" in name):
                ru.append(v)
        #Пол по имени. RHVoice — открытый синтезатор с хорошими русскими голосами; если он
        #установлен, ПРЕДПОЧИТАЕМ его (звучит лучше стандартной «Ирины»). Имена RHVoice:
        #муж — aleksandr/anton/artemiy, жен — anna/elena/irina/victoria.
        female_hint = ("irina", "ирина", "anna", "elena", "victoria", "female", "женск")
        male_hint = ("aleksandr", "anton", "artemiy", "pavel", "павел", "male", "мужск", "dmitri")

        def _is_rhvoice(v):
            return "rhvoice" in (getattr(v, "id", "") or "").lower()

        def _matches_gender(v):
            nm = (getattr(v, "name", "") or "").lower()
            hints = female_hint if want_female else male_hint
            return any(h in nm for h in hints)

        #Приоритет: RHVoice+пол → RHVoice любой → системный RU+пол → любой RU → дефолт.
        chosen = (next((v for v in ru if _is_rhvoice(v) and _matches_gender(v)), None)
                  or next((v for v in ru if _is_rhvoice(v)), None)
                  or next((v for v in ru if _matches_gender(v)), None)
                  or (ru[0] if ru else None))
        if chosen is not None:
            engine.setProperty("voice", chosen.id)
        #Мужской — чуть живее/легче (SAPI не даёт питч, играем скоростью).
        engine.setProperty("rate", 180 if want_female else 190)
        with _gen_lock:
            if gen != _gen:
                return
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        _LOG.warning(f"[tts] SAPI-озвучка не удалась: {e}")


# ── Публичный вход ──────────────────────────────────────────────────────────────────
def _worker(text: str, voice: str, gen: int) -> None:
    #Слой 1: сервер.
    wav = _server_wav(text, voice)
    if wav:
        try:
            samples, sr = _wav_to_samples(wav)
            if _play_samples(samples, sr, gen):
                return
        except Exception as e:
            _LOG.info(f"[tts] не проиграл серверный WAV ({e})")
    #Слой 2: локальный Silero.
    local = _local_samples(text, voice)
    if local is not None:
        try:
            if _play_samples(local[0], local[1], gen):
                return
        except Exception as e:
            _LOG.info(f"[tts] не проиграл локальный синтез ({e})")
    #Слой 3: SAPI.
    _speak_sapi(text, voice, gen)


def speak(text: str) -> None:
    """Озвучить ответ Вектора (асинхронно). Ничего не делает, если выключено/пусто.
    Прерывает предыдущую озвучку. Никогда не бросает — звук не должен ронять чат."""
    t = (text or "").strip()
    if not t or not is_enabled():
        return
    if len(t) > _MAX_CHARS:
        t = t[:_MAX_CHARS]
    stop()                          #barge-in: гасим прежнюю речь и берём новое поколение
    with _gen_lock:
        gen = _gen
    voice = get_voice()
    threading.Thread(target=_worker, args=(t, voice, gen), daemon=True).start()
