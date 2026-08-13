"""
audio_capture.py — Захват звука с микрофона для голосового ввода (десктоп).

Пишет моно 16 кГц float32 — «родной» формат Whisper (без лишней передискретизации).
Работает через sounddevice (PortAudio). Если пакет не установлен — is_available() = False,
и кнопка голоса просто не появится (мягкая деградация, как и в stt.py).

Выбор микрофона: list_input_devices() отдаёт (index, name); выбранный индекс приходит в
Recorder(device=...). На вебе/телефоне захват делает браузер (getUserMedia) — этот модуль
только для десктопа.
"""
import threading
import log

SAMPLE_RATE = 16000        #родная частота Whisper — пишем сразу в ней
_CHANNELS = 1


def is_available() -> bool:
    try:
        import sounddevice  # noqa: F401
        import numpy  # noqa: F401
        return True
    except Exception:
        return False


def list_input_devices() -> list[tuple[int, str]]:
    """Список микрофонов: [(device_index, name), ...]. Пусто, если пакета нет."""
    if not is_available():
        return []
    try:
        import sounddevice as sd
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append((i, d.get("name", f"Устройство {i}")))
        return out
    except Exception:
        return []


class Recorder:
    """Запись с микрофона по схеме start()/stop(). stop() возвращает numpy float32 (моно,
    16 кГц). Поток аудио складываем в буфер; всё потокобезопасно (callback идёт из потока
    PortAudio). Ограничение длительности — предохранитель от бесконечной записи."""

    def __init__(self, device: int | None = None, max_seconds: int = 60):
        self.device = device
        self.max_seconds = max_seconds
        self._frames = []
        self._stream = None
        self._lock = threading.Lock()
        self._recording = False

    def _callback(self, indata, frames, time_info, status):
        import numpy as np
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy().reshape(-1).astype(np.float32))

    def start(self) -> bool:
        if not is_available() or self._recording:
            return False
        import sounddevice as sd
        self._frames = []
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=_CHANNELS, dtype="float32",
                device=self.device, callback=self._callback,
            )
            self._recording = True
            self._stream.start()
            return True
        except Exception as e:
            log.get("audio_capture").warning(f"[audio] не удалось открыть микрофон (device={self.device}): {e}")
            self._stream = None
            self._recording = False
            return False

    def stop(self):
        """Останавливает запись и возвращает numpy float32 (или None, если пусто/ошибка)."""
        if not self._recording:
            return None
        self._recording = False
        try:
            if self._stream is not None:
                self._stream.stop(); self._stream.close()
        except Exception:
            pass
        self._stream = None
        try:
            import numpy as np
            with self._lock:
                if not self._frames:
                    return None
                audio = np.concatenate(self._frames)
            return audio
        except Exception as e:
            log.get("audio_capture").warning(f"[audio] сборка записи не удалась: {e}")
            return None

    @property
    def is_recording(self) -> bool:
        return self._recording
