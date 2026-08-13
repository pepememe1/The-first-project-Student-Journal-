"""
stt.py — Распознавание речи (Speech-to-Text) на базе OpenAI Whisper через faster-whisper
(CTranslate2). Полностью локально: аудио НИКУДА не уходит — важно для ПДн (152-ФЗ) и для
работы офлайн. Русский язык, модель large-v3 (максимальная точность — это критично, ведь
по голосу выставляются оценки/пропуски).

ПРИНЦИП БЕЗОПАСНОСТИ. Этот модуль ТОЛЬКО превращает звук в текст. Он НЕ принимает решений
и ничего не пишет в журнал. Разбор команды преподавателя (кому, что, какая оценка) делает
детерминированный парсер (vector/voice_command.py) с обязательным подтверждением — чтобы
исключить «галлюцинацию» модели в юридически значимом действии.

Зависимости (ставятся отдельно, не в .exe): faster-whisper, а для GPU — nvidia-cublas-cu12
и nvidia-cudnn-cu12 (DLL cuBLAS/cuDNN). Если пакетов нет — is_available() вернёт False, а
интерфейс просто не покажет кнопку голоса (мягкая деградация).

Разделение труда на GPU 6 ГБ (по решению: приоритет точности STT): Whisper large-v3 в int8
на GPU (~2.5–3 ГБ), а LLM-озвучка Вектора — на лёгкой модели Ollama (qwen2.5:3b) или оффлайн.
"""
import os
import log
import threading

#Новый Xet-бэкенд huggingface_hub на части сетей ЗАВИСАЕТ на скачивании крупного файла
#модели (model.bin остаётся 0-байтным .incomplete). Отключаем его — тогда идёт обычная
#надёжная HTTPS-загрузка. Ставить ДО импорта huggingface_hub/faster_whisper.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

#Singleton модели и его защита (загрузка тяжёлая — держим одну на процесс).
_model = None
_model_key = None            #(size, device, compute) — при смене настроек перезагружаем
_lock = threading.Lock()
_dll_dirs_added = False


def _add_cuda_dll_dirs() -> None:
    """Windows: CTranslate2 грузит cuBLAS/cuDNN из пакетов nvidia-*-cu12 (DLL лежат в
    site-packages/nvidia/*/bin). Добавляем эти папки в поиск DLL. ВАЖНО: одного
    os.add_dll_directory мало — cuDNN сам зависит от cublas64_12.dll, а ТРАНЗИТИВНЫЕ
    зависимости Windows ищет по обычному PATH, а не по add_dll_directory. Поэтому те же
    папки ПРОПИСЫВАЕМ и в PATH — иначе 'Library cublas64_12.dll is not found'. На Linux
    не требуется."""
    global _dll_dirs_added
    if _dll_dirs_added or os.name != "nt":
        _dll_dirs_added = True
        return
    try:
        import importlib.util
        spec = importlib.util.find_spec("nvidia")
        roots = list(getattr(spec, "submodule_search_locations", []) or []) if spec else []
        bins = []
        for root in roots:
            for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
                bind = os.path.join(root, sub, "bin")
                if os.path.isdir(bind):
                    bins.append(bind)
                    try:
                        os.add_dll_directory(bind)
                    except OSError:
                        pass
        #Транзитивные зависимости (cudnn→cublas) ищутся по PATH — добавляем в начало.
        if bins:
            os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass
    _dll_dirs_added = True


def is_available() -> bool:
    """Установлен ли движок распознавания (пакет faster-whisper)."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _cuda_ready() -> bool:
    """GPU пригоден ТОЛЬКО если есть CUDA-устройство И установлены cuBLAS+cuDNN. Без
    библиотек загрузка на cuda не падает с ошибкой, а ЗАВИСАЕТ — поэтому проверяем их
    наличие заранее и в этом случае честно уходим на CPU (а не в вечное ожидание)."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() <= 0:
            return False
    except Exception:
        return False
    import importlib.util
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            if importlib.util.find_spec(pkg) is None:
                return False
        except Exception:
            return False
    return True


def _pick_device(prefer: str) -> tuple:
    """(device, compute_type). prefer: 'auto'|'cuda'|'cpu'. На GPU по умолчанию int8_float16
    (веса int8, счёт fp16) — компромисс точность/память для 6 ГБ; на CPU — int8.
    GPU выбираем лишь при реально установленных cuBLAS+cuDNN (иначе завис вместо ошибки)."""
    if prefer in ("cuda", "auto") and _cuda_ready():
        return "cuda", "int8_float16"
    return "cpu", "int8"


def load_model(size: str = "large-v3", device: str = "auto",
               compute: str = "") -> object | None:
    """Лениво грузит модель Whisper (кэшируется). Возвращает модель или None при ошибке.
    Смена (size/device/compute) вызывает перезагрузку. Первая загрузка large-v3 скачивает
    ~1.5 ГБ весов в кэш HuggingFace (только один раз)."""
    global _model, _model_key
    if not is_available():
        return None
    _add_cuda_dll_dirs()
    dev, comp = _pick_device(device)
    if compute:
        comp = compute
    key = (size, dev, comp)
    with _lock:
        if _model is not None and _model_key == key:
            return _model
        from faster_whisper import WhisperModel
        try:
            m = WhisperModel(size, device=dev, compute_type=comp)
        except Exception as e:
            #GPU не завёлся (нет cuDNN/мало памяти) — пробуем CPU, лишь бы работало.
            log.get("stt").warning(f"[stt] загрузка на {dev}/{comp} не удалась ({e}); откат на CPU int8")
            if dev != "cpu":
                try:
                    m = WhisperModel(size, device="cpu", compute_type="int8")
                    key = (size, "cpu", "int8")
                except Exception as e2:
                    log.get("stt").warning(f"[stt] CPU-загрузка тоже не удалась: {e2}")
                    return None
            else:
                return None
        _model = m
        _model_key = key
        log.get("stt").warning(f"[stt] модель Whisper готова: {size} @ {key[1]}/{key[2]}")
        return _model


def transcribe(samples, sample_rate: int = 16000, language: str = "ru",
               context: str = "", size: str = "large-v3", device: str = "auto",
               compute: str = "") -> dict:
    """Распознаёт РЕЧЬ из массива float32 (моно). Возвращает
    {"ok": bool, "text": str, "error": str, "avg_logprob": float}.

    context — подсказка модели (initial_prompt): например, список ФИО студентов группы и
    ключевые слова («оценка», «пропуск»). Это заметно повышает точность распознавания
    фамилий и терминов в шуме — а точность здесь юридически критична.

    samples ожидается в 16 кГц моно (Whisper внутренне работает на 16 кГц). Если частота
    иная — пересемплируем простым способом (без внешних зависимостей)."""
    m = load_model(size=size, device=device, compute=compute)
    if m is None:
        return {"ok": False, "text": "",
                "error": "Движок распознавания не установлен или не загрузился.",
                "avg_logprob": 0.0}
    try:
        import numpy as np
        audio = np.asarray(samples, dtype=np.float32).flatten()
        if sample_rate != 16000 and audio.size:
            #Линейная передискретизация до 16 кГц (грубо, но для речи достаточно).
            n_out = int(round(audio.size * 16000 / sample_rate))
            if n_out > 0:
                idx = np.linspace(0, audio.size - 1, n_out)
                audio = np.interp(idx, np.arange(audio.size), audio).astype(np.float32)
        #Нормализация амплитуды (тихий микрофон/наушники в плохих условиях).
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if 0 < peak < 0.9:
            audio = (audio / peak * 0.95).astype(np.float32)

        kw = dict(
            language=language,
            task="transcribe",
            beam_size=5,                       #точнее, чем greedy
            vad_filter=True,                   #режем тишину/шум — важно для коротких команд
            vad_parameters={"min_silence_duration_ms": 400},
            condition_on_previous_text=False,  #каждая команда независима — без «залипания»
            initial_prompt=context or None,
            temperature=[0.0, 0.2, 0.4],       #фолбэк-температуры при низкой уверенности
        )
        #hotwords ДОПОЛНИТЕЛЬНО усиливают редкие имена (бурятские ФИО: Самбуева, Гындынова,
        #Баянжаргал…) поверх initial_prompt. Есть не во всех версиях faster-whisper — при
        #TypeError повторяем без него.
        try:
            segments, info = m.transcribe(audio, hotwords=context or None, **kw)
        except TypeError:
            segments, info = m.transcribe(audio, **kw)
        parts, logprobs = [], []
        for s in segments:
            parts.append(s.text)
            if getattr(s, "avg_logprob", None) is not None:
                logprobs.append(s.avg_logprob)
        text = " ".join(p.strip() for p in parts).strip()
        avg = sum(logprobs) / len(logprobs) if logprobs else 0.0
        return {"ok": True, "text": text, "error": "", "avg_logprob": avg}
    except Exception as e:
        return {"ok": False, "text": "", "error": f"Ошибка распознавания: {e}",
                "avg_logprob": 0.0}
