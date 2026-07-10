"""
stt_service.py — ЗАГОТОВКА серверного распознавания речи (Speech-to-Text) для веба.

Идея (по решению): STT — способность ХОСТА, где крутится сервер и БД. На будущем ПК
ВСГУТУ (с видеокартой) достаточно установить faster-whisper — и веб/телефон смогут слать
туда аудио, а сервер вернёт текст. Пока пакет не установлен на хосте — эндпоинт честно
отвечает 503 (веб-кнопка голоса тогда просто не показывается).

Мы НЕ распознаём в браузере: Whisper тяжёлый, а на телефоне это нереально. Аудио пишет
браузер (getUserMedia + MediaRecorder) и шлёт на сервер; сервер (этот модуль) распознаёт
локально на хосте — данные не уходят третьим лицам (важно для ПДн).

Модель/устройство берутся из синхронизированного конфига админа (stt_model/stt_device) —
те же настройки, что и в десктопе.
"""
import os
import tempfile
import threading

#Отключаем Xet-бэкенд HF (виснет на скачивании крупного model.bin на части сетей).
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

_model = None
_model_key = None
_lock = threading.Lock()


def is_available() -> bool:
    """Установлен ли движок распознавания НА ХОСТЕ (пакет faster-whisper)."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


_dll_added = False


def _add_cuda_dll_dirs() -> None:
    """Windows-хост: DLL cuBLAS/cuDNN лежат в site-packages/nvidia/*/bin. Добавляем в
    поиск DLL и в PATH (транзитивная зависимость cudnn→cublas ищется по PATH)."""
    global _dll_added
    if _dll_added or os.name != "nt":
        _dll_added = True
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
        if bins:
            os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass
    _dll_added = True


def _cuda_ready() -> bool:
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() <= 0:
            return False
        import importlib.util
        for pkg in ("nvidia.cublas", "nvidia.cudnn"):
            if importlib.util.find_spec(pkg) is None:
                return False
        return True
    except Exception:
        return False


def _load(size: str, device: str):
    global _model, _model_key
    _add_cuda_dll_dirs()
    dev = "cuda" if (device in ("auto", "cuda") and _cuda_ready()) else "cpu"
    comp = "int8_float16" if dev == "cuda" else "int8"
    key = (size, dev, comp)
    with _lock:
        if _model is not None and _model_key == key:
            return _model
        from faster_whisper import WhisperModel
        try:
            m = WhisperModel(size, device=dev, compute_type=comp)
        except Exception:
            m = WhisperModel(size, device="cpu", compute_type="int8")
            key = (size, "cpu", "int8")
        _model = m
        _model_key = key
        return _model


def transcribe_bytes(data: bytes, filename: str = "audio", language: str = "ru",
                     size: str = "large-v3", device: str = "auto",
                     context: str = "") -> dict:
    """Распознаёт загруженный аудиофайл (webm/ogg/wav/m4a — декодирует av/ffmpeg внутри
    faster-whisper). Возвращает {"ok","text","error"}."""
    if not is_available():
        return {"ok": False, "text": "",
                "error": "Распознавание не установлено на сервере-хосте."}
    suffix = os.path.splitext(filename)[1] or ".webm"
    path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(data)
            path = f.name
        model = _load(size, device)
        segments, _info = model.transcribe(
            path, language=language, beam_size=5, vad_filter=True,
            condition_on_previous_text=False, initial_prompt=context or None)
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"ok": True, "text": text, "error": ""}
    except Exception as e:
        return {"ok": False, "text": "", "error": f"Ошибка распознавания: {e}"}
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
