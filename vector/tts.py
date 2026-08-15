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

Настройки — этого ПК (per-device, local_set): режим озвучки (voice — настоящий синтез /
mumble — «бубнеж» блипами / off — тишина) и голос (male/female). По умолчанию: режим
'voice', голос МУЖСКОЙ.
"""
import io
import os
import re
import html
import wave
import base64
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
#Три режима озвучки: 'voice' (настоящий синтез), 'mumble' («бубнеж» — имитация речи
#блипами, как голоса персонажей в Undertale/Deltarune), 'off' (тишина).
_MODES = ("voice", "mumble", "off")
_MODE_LABELS = {"voice": "Голос включён", "mumble": "Бубнеж", "off": "Озвучка выключена"}


def get_mode() -> str:
    """Текущий режим озвучки. Мигрирует со старого 'tts_enabled' (вкл/выкл)."""
    try:
        from data.data_store import local_get
        m = str(local_get("tts_mode", ""))
        if m in _MODES:
            return m
        return "off" if str(local_get("tts_enabled", "on")) == "off" else "voice"
    except Exception:
        return "voice"


def set_mode(mode: str) -> None:
    m = mode if mode in _MODES else "voice"
    try:
        from data.data_store import local_set
        local_set("tts_mode", m)
    except Exception as e:
        _LOG.warning(f"[tts] не сохранил режим озвучки: {e}")
    if m == "off":
        stop()


def is_enabled() -> bool:
    """Совместимость: озвучка не выключена (режим ≠ 'off')."""
    return get_mode() != "off"


def set_enabled(on: bool) -> None:
    """Совместимость со старым вкл/выкл: включить = режим 'voice', выключить = 'off'."""
    set_mode("voice" if on else "off")


def get_voice() -> str:
    """Выбранный голос ('male' по умолчанию)."""
    try:
        from data.data_store import local_get
        return "female" if str(local_get("tts_voice", "male")) == "female" else "male"
    except Exception:
        return "male"


def set_voice(voice: str) -> None:
    v = "female" if voice == "female" else "male"
    try:
        from data.data_store import local_set
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
        from sync.sync_runner import current_auth
        url, token = current_auth()
    except Exception:
        url, token = ("", "")
    if not (url and token):
        return None
    try:
        from sync.sync_client import SyncClient
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


# ── Уведомления о фактическом воспроизведении ───────────────────────────────────────
# Маскот на десктопе анимирует «речь» РОВНО пока идёт звук: колбэки on_start/on_end
# зовём вокруг настоящего проигрывания. Оба защищены поколением (gen) — устаревший, уже
# перебитый barge-in'ом воркер молчит, анимацию ведёт актуальный ответ (или сам stop()).
def _fire(cb, gen: int) -> None:
    if cb is None:
        return
    with _gen_lock:
        if gen != _gen:
            return
    try:
        cb()
    except Exception:
        pass


def _play_cb(samples, sr, gen, on_start, on_end) -> bool:
    """Проиграть сэмплы, оповестив о старте/конце звука (для анимации речи)."""
    _fire(on_start, gen)
    try:
        return _play_samples(samples, sr, gen)
    finally:
        _fire(on_end, gen)


def _speak_sapi_cb(text, voice, gen, on_start, on_end) -> None:
    _fire(on_start, gen)
    try:
        _speak_sapi(text, voice, gen)
    finally:
        _fire(on_end, gen)


# ── Публичный вход ──────────────────────────────────────────────────────────────────
def _worker(text: str, voice: str, gen: int, on_start=None, on_end=None) -> None:
    #Слой 1: сервер.
    wav = _server_wav(text, voice)
    if wav:
        try:
            samples, sr = _wav_to_samples(wav)
            if _play_cb(samples, sr, gen, on_start, on_end):
                return
        except Exception as e:
            _LOG.info(f"[tts] не проиграл серверный WAV ({e})")
    #Слой 2: локальный Silero.
    local = _local_samples(text, voice)
    if local is not None:
        try:
            if _play_cb(local[0], local[1], gen, on_start, on_end):
                return
        except Exception as e:
            _LOG.info(f"[tts] не проиграл локальный синтез ({e})")
    #Слой 3: SAPI.
    _speak_sapi_cb(text, voice, gen, on_start, on_end)


# Паузы на пунктуации (сек) — из-за них бубнеж «дышит» как речь, а не тарахтит монотонно.
_MUMBLE_PAUSE = {",": 0.20, ";": 0.22, ":": 0.22, ".": 0.34, "!": 0.36, "?": 0.40,
                 "…": 0.42, "—": 0.14, "-": 0.10, "\n": 0.34}
# Фрагмент бубнежа (голос Влада, ~27 мс, int16 PCM моно @22050). Base64 вынесен в модуль
# `_mumble_data.py` (генерируется из vector_mumble.mp3) — так он бандлится в .exe как обычный
# модуль, без путей к арту, и работает офлайн. Тембр НЕ трогаем — только повторяем встык с
# шагом и поднимаем общую громкость.
_MUMBLE_SR = 22050
_MUMBLE_GAIN = 1.15        #чуть громче оригинала (~15%) — по просьбе; тембр не меняем
_MUMBLE_STEP = 0.0825     #шаг склейки: фрагмент 27 мс + пауза ~55 мс между повторами
_MUMBLE_CHAR = 0.058      #«речевое» время на символ (темп проговаривания)

_MUMBLE_GRAIN = None       #ленивый кэш распакованного фрагмента (numpy float32)


def _mumble_grain():
    """Распаковать встроенный фрагмент бубнежа в float32 (кэшируется)."""
    global _MUMBLE_GRAIN
    if _MUMBLE_GRAIN is None:
        import numpy as np
        from . import _mumble_data
        raw = base64.b64decode(_mumble_data.B64)
        g = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        _MUMBLE_GRAIN = (g * _MUMBLE_GAIN).astype(np.float32)
    return _MUMBLE_GRAIN


def _mumble_segments(text: str):
    """Разложить фразу на отрезки: (речь, длительность) и (пауза, длительность). Речь —
    непрерывный прогон букв ДО знака препинания, пауза — сам знак."""
    segs = []
    run = 0.0
    for ch in text:
        if ch in _MUMBLE_PAUSE:
            if run > 0:
                segs.append((True, run)); run = 0.0
            segs.append((False, _MUMBLE_PAUSE[ch]))
        elif ch.isalnum():
            run += _MUMBLE_CHAR
        elif ch == " ":
            run += _MUMBLE_CHAR * 0.6
        else:
            run += _MUMBLE_CHAR * 0.5
    if run > 0:
        segs.append((True, run))
    return segs


def _mumble_samples(text: str, voice: str = None):
    """«Бубнеж»: фрагмент голоса Влада, СКЛЕЕННЫЙ циклично (шаг _MUMBLE_STEP), пока идёт
    «речь», с паузами на знаках препинания. Один звук — без мужского/женского (у бубнежа
    выбор голоса не показывается). Считается локально, без сети и без TTS. `voice` не используется."""
    import numpy as np
    g = _mumble_grain()
    sr = _MUMBLE_SR
    segs = _mumble_segments(text)
    if not any(sp for sp, _ in segs):
        return None
    total = int(sum(d for _, d in segs) * sr) + len(g) + 4
    out = np.zeros(total, dtype=np.float32)
    step = max(1, int(sr * _MUMBLE_STEP))
    t = 0.0
    for speaking, dur in segs:
        if speaking:
            pos, stop = int(t * sr), int((t + dur) * sr)
            while pos < stop:
                end = min(pos + len(g), total)
                out[pos:end] += g[:end - pos]      #блипы не наложены (шаг > длины) → без клиппинга
                pos += step
        t += dur
    np.clip(out, -1.0, 1.0, out=out)
    return out, sr


def _mumble_worker(text: str, voice: str, gen: int, on_start=None, on_end=None) -> None:
    try:
        res = _mumble_samples(text, voice)
        if res is not None:
            _play_cb(res[0], res[1], gen, on_start, on_end)
        else:
            #Нет букв (пусто) — звука не будет, но конец речи отметить надо, иначе анимация зависнет.
            _fire(on_start, gen)
            _fire(on_end, gen)
    except Exception as e:
        _LOG.info(f"[tts] бубнеж не сыграл: {e}")
        _fire(on_end, gen)


def speak(text: str, on_start=None, on_end=None) -> None:
    """Озвучить ответ Вектора (асинхронно) по текущему режиму. Ничего не делает, если
    режим 'off' или текст пуст. Прерывает предыдущую озвучку. Никогда не бросает.

    on_start/on_end — колбэки вокруг РЕАЛЬНОГО воспроизведения (для анимации речи маскота:
    пока идёт звук — играет speaking). Зовутся из фонового потока и защищены поколением,
    так что перебитый barge-in'ом синтез их не дёрнет. Работают для всех слоёв (сервер/
    локальный Silero/SAPI) и для бубнежа — т.е. и для «нормального» голоса тоже."""
    t = (text or "").strip()
    mode = get_mode()
    if not t or mode == "off":
        return
    if len(t) > _MAX_CHARS:
        t = t[:_MAX_CHARS]
    stop()                          #barge-in: гасим прежнюю речь и берём новое поколение
    with _gen_lock:
        gen = _gen
    voice = get_voice()
    target = _mumble_worker if mode == "mumble" else _worker
    threading.Thread(target=target, args=(t, voice, gen, on_start, on_end), daemon=True).start()
