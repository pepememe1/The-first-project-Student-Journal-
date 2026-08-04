"""
voice_ui.py — Десктопный голосовой ввод для Вектора (кнопка микрофона + распознавание +
ролевой роутинг + подтверждение записи преподавателем).

Поток данных:
    MicButton (нажал→запись, нажал→стоп) → TranscribeThread (Whisper вне UI-потока)
    → route_voice_text():
        • студент/вопрос  → session.ask(текст)          (обычный Q&A Вектора, чтение)
        • препод-команда  → voice_command.parse() → ДИАЛОГ ПОДТВЕРЖДЕНИЯ → запись в БД
Запись идёт тем же путём, что ручная простановка в журнале (DBManager.upsert_grade +
пробуждение синка), поэтому правка сразу уходит на сервер и подхватывается другими ПК.

Безопасность: LLM в цепочке ЗАПИСИ не участвует; преподаватель ВСЕГДА подтверждает
разобранное действие; при неоднозначности — выбор/переспрос, а не догадка.

Всё опционально: если микрофон/распознавание недоступны (пакеты не стоят) — mic_available()
= False и кнопка не показывается.
"""
from datetime import datetime
import log

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QToolButton, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QFrame, QScrollArea, QWidget, QLineEdit, QCheckBox,
)

from . import stt, audio_capture, voice_command


def mic_available() -> bool:
    """Есть ли и захват звука, и движок распознавания."""
    return audio_capture.is_available() and stt.is_available()


def _cfg() -> dict:
    try:
        from data_store import get_store
        return get_store()._config() or {}
    except Exception:
        return {}


def selected_mic_device():
    """Выбранный в Профиле микрофон (индекс) или None (по умолчанию системный)."""
    try:
        from data_store import local_get
        v = local_get("stt_mic_device")
        return int(v) if v is not None and str(v) != "" else None
    except Exception:
        return None


def _save_mic_device(index):
    try:
        from data_store import local_set
        local_set("stt_mic_device", "" if index is None else int(index))
    except Exception as e:
        log.get("voice_ui").warning(f"[voice] не удалось сохранить выбор микрофона: {e}")


# Виджет выбора микрофона (для вкладки «Профиль» на десктопе)
class MicSelectorWidget(QFrame):
    """Выбор микрофона для голосового ввода. Список берётся из системы (sounddevice);
    выбор хранится ЛОКАЛЬНО (это настройка ПК, не синхронизируется). На вебе/телефоне
    микрофон выбирает браузер сам — там этого виджета нет."""

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            from styles import C
        except Exception:
            C = {"text": "#111", "text3": "#666", "card2": "#eee", "border": "#ccc"}
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(6)
        title = QLabel("🎙 Микрофон для голосового ввода")
        title.setStyleSheet(f"color:{C['text']};font-size:14px;font-weight:bold;")
        lay.addWidget(title)

        if not mic_available():
            note = QLabel("Голосовой ввод недоступен на этом ПК: не установлены пакеты "
                          "распознавания (faster-whisper / sounddevice).")
            note.setWordWrap(True); note.setStyleSheet(f"color:{C['text3']};font-size:12px;")
            lay.addWidget(note)
            return

        self._combo = QComboBox()
        self._combo.addItem("Системный по умолчанию", None)
        for idx, name in audio_capture.list_input_devices():
            self._combo.addItem(name, idx)
        cur = selected_mic_device()
        if cur is not None:
            pos = self._combo.findData(cur)
            if pos >= 0:
                self._combo.setCurrentIndex(pos)
        self._combo.currentIndexChanged.connect(
            lambda *_: _save_mic_device(self._combo.currentData()))
        lay.addWidget(self._combo)
        hint = QLabel("Выбор запоминается для этого компьютера. На телефоне и в браузере "
                      "микрофон выбирается автоматически (нужно разрешить доступ).")
        hint.setWordWrap(True); hint.setStyleSheet(f"color:{C['text3']};font-size:11px;")
        lay.addWidget(hint)

# Виджет озвучки Вектора (для вкладки «Профиль» на десктопе)
class TtsSettingsWidget(QFrame):
    """Настройка озвучки ответов Вектора: кнопка-циклер режима (Голос → Бубнеж → Выкл) и
    голос (мужской/женский, виден только в режиме «Голос»). Настройка ЭТОГО ПК (локально).

    Бубнеж — имитация речи короткими сигналами (как голоса персонажей в Undertale), без
    сети и без TTS. Онлайн голос считает сервер, офлайн — этот ПК (даже голосом Windows)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        try:
            from styles import C
        except Exception:
            C = {"text": "#111", "text3": "#666", "card2": "#eee", "border": "#ccc",
                 "green": "#147C8B"}
        self._C = C
        from . import tts
        self._tts = tts
        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(6)
        title = QLabel("🔊 Озвучка Вектора")
        title.setStyleSheet(f"color:{C['text']};font-size:14px;font-weight:bold;")
        lay.addWidget(title)

        #Кнопка-циклер: Голос → Бубнеж → Выкл → Голос.
        self._mode_btn = QPushButton()
        self._mode_btn.setCursor(Qt.PointingHandCursor)
        self._mode_btn.clicked.connect(self._on_cycle)
        lay.addWidget(self._mode_btn)

        self._mode_hint = QLabel("Нажмите, чтобы переключить: Голос → Бубнеж → Выкл")
        self._mode_hint.setStyleSheet(f"color:{C['text3']};font-size:11px;")
        lay.addWidget(self._mode_hint)

        #Выбор голоса — только для режима «Голос».
        self._voice_row = QWidget()
        row = QHBoxLayout(self._voice_row); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(8)
        vlabel = QLabel("Голос:")
        vlabel.setStyleSheet(f"color:{C['text3']};font-size:12px;")
        row.addWidget(vlabel)
        self._combo = QComboBox()
        self._combo.addItem("Мужской", "male")
        self._combo.addItem("Женский", "female")
        pos = self._combo.findData(tts.get_voice())
        if pos >= 0:
            self._combo.setCurrentIndex(pos)
        self._combo.currentIndexChanged.connect(self._on_voice)
        row.addWidget(self._combo, 1)
        self._preview_btn = QPushButton("Прослушать")
        self._preview_btn.clicked.connect(self._preview)
        row.addWidget(self._preview_btn)
        lay.addWidget(self._voice_row)

        hint = QLabel("Онлайн голос считает сервер, без интернета — этот компьютер. Бубнеж "
                      "работает всегда. Настройка запоминается для этого ПК.")
        hint.setWordWrap(True); hint.setStyleSheet(f"color:{C['text3']};font-size:11px;")
        lay.addWidget(hint)
        self._sync_mode()

    def _sync_mode(self):
        mode = self._tts.get_mode()
        self._mode_btn.setText("  " + self._tts.mode_label())
        C = self._C
        on = mode != "off"
        # Кнопка активного режима — акцентная, выключенная — приглушённая.
        col = C.get("green", "#147C8B") if on else C.get("text3", "#666")
        self._mode_btn.setStyleSheet(
            f"QPushButton{{text-align:left;padding:8px 12px;border-radius:8px;"
            f"border:1px solid {col};color:{col};font-size:13px;font-weight:600;}}")
        self._voice_row.setVisible(mode == "voice")

    def _on_cycle(self):
        self._tts.cycle_mode()
        self._sync_mode()
        if self._tts.get_mode() == "mumble":
            self._tts.speak("Привет! Я Вектор.")   # сразу дать услышать бубнеж

    def _on_voice(self, *_):
        self._tts.set_voice(self._combo.currentData())

    def _preview(self):
        #Короткая проба выбранным голосом — услышать разницу тут же.
        self._tts.set_voice(self._combo.currentData())
        self._tts.speak("Привет! Я Вектор. Буду озвучивать ответы этим голосом.")


# Распознавание в отдельном потоке (Whisper тяжёлый — не морозим UI)
class TranscribeThread(QThread):
    done = Signal(dict)      #{"ok","text","error","avg_logprob"}

    def __init__(self, samples, context="", parent=None):
        super().__init__(parent)
        self._samples = samples
        self._context = context

    def run(self):
        cfg = _cfg()
        res = stt.transcribe(
            self._samples,
            sample_rate=audio_capture.SAMPLE_RATE,
            language="ru",
            context=self._context,
            size=cfg.get("stt_model", "large-v3"),
            device=cfg.get("stt_device", "auto"),
            compute=cfg.get("stt_compute", ""),
        )
        self.done.emit(res)


# Кнопка микрофона: нажал → запись, нажал → стоп → распознавание
class MicButton(QToolButton):
    transcribed = Signal(str)      #распознанный текст
    failed = Signal(str)           #сообщение об ошибке
    stateChanged = Signal(str)     #"idle" | "recording" | "transcribing"

    def __init__(self, get_context=None, parent=None):
        super().__init__(parent)
        #get_context() → строка-подсказка для Whisper (ФИО группы и т.п.); может быть None
        self._get_context = get_context
        self._recorder = None
        self._thread = None
        self._state = "idle"
        self.setCheckable(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 38)
        self.setToolTip("Голосовой ввод")
        self._apply_style()
        self.clicked.connect(self._toggle)
        #Мигание во время записи.
        self._blink = QTimer(self); self._blink.setInterval(500)
        self._blink.timeout.connect(self._tick_blink)
        self._blink_on = False

    #── визуал ──────────────────────────────────────────────────────────────────────
    def _apply_style(self):
        try:
            from styles import C
        except Exception:
            C = {"card2": "#eee", "border": "#ccc", "green": "#147C8B",
                 "red": "#d33", "text": "#111"}
        if self._state == "recording":
            bg = C["red"] if self._blink_on else "#ffffff"
            fg = "#ffffff" if self._blink_on else C["red"]
            self.setText("●"); self.setToolTip("Идёт запись… нажмите, чтобы остановить")
            self.setStyleSheet(
                f"QToolButton{{background:{bg};color:{fg};border:1px solid {C['red']};"
                f"border-radius:8px;font-size:16px;font-weight:bold;}}")
        elif self._state == "transcribing":
            self.setText("…"); self.setToolTip("Распознаю речь…")
            self.setStyleSheet(
                f"QToolButton{{background:{C['card2']};color:{C['green']};"
                f"border:1px solid {C['green']};border-radius:8px;font-size:18px;}}")
        else:
            self.setText("🎤"); self.setToolTip("Голосовой ввод")
            self.setStyleSheet(
                f"QToolButton{{background:{C['card2']};border:1px solid {C['border']};"
                f"border-radius:8px;font-size:15px;}}"
                f"QToolButton:hover{{border-color:{C['green']};}}")

    def _set_state(self, s: str):
        self._state = s
        self._apply_style()
        self.stateChanged.emit(s)

    def _tick_blink(self):
        self._blink_on = not self._blink_on
        self._apply_style()

    #── запись/распознавание ─────────────────────────────────────────────────────────
    def _toggle(self):
        if self._state == "recording":
            self._stop_and_transcribe()
        elif self._state == "idle":
            self._start()

    def _start(self):
        if not mic_available():
            self.failed.emit("Голосовой ввод недоступен: не установлены пакеты "
                             "распознавания (faster-whisper / sounddevice).")
            return
        self._recorder = audio_capture.Recorder(device=selected_mic_device())
        if not self._recorder.start():
            self._recorder = None
            self.failed.emit("Не удалось открыть микрофон. Проверьте выбор устройства "
                             "в Профиле и разрешение на микрофон.")
            return
        self._blink_on = True
        self._set_state("recording")
        self._blink.start()
        #Пока пользователь говорит — В ФОНЕ грузим модель Whisper (первый раз за сессию это
        #~8с CUDA-прогрева). К моменту, когда отпустят кнопку, модель уже готова → команда
        #распознаётся сразу, без ожидания загрузки.
        self._warm_up_async()

    def _warm_up_async(self):
        import threading

        def _warm():
            try:
                cfg = _cfg()
                stt.load_model(size=cfg.get("stt_model", "large-v3"),
                               device=cfg.get("stt_device", "auto"),
                               compute=cfg.get("stt_compute", ""))
            except Exception:
                pass
        threading.Thread(target=_warm, daemon=True).start()

    def _stop_and_transcribe(self):
        self._blink.stop()
        samples = self._recorder.stop() if self._recorder else None
        self._recorder = None
        if samples is None or getattr(samples, "size", 0) == 0:
            self._set_state("idle")
            self.failed.emit("Пустая запись — попробуйте ещё раз.")
            return
        self._set_state("transcribing")
        context = ""
        try:
            if self._get_context:
                context = self._get_context() or ""
        except Exception:
            context = ""
        self._thread = TranscribeThread(samples, context=context, parent=self)
        self._thread.done.connect(self._on_transcribed)
        self._thread.start()

    def _on_transcribed(self, res: dict):
        self._set_state("idle")
        if not res.get("ok"):
            self.failed.emit(res.get("error") or "Не удалось распознать речь.")
            return
        text = (res.get("text") or "").strip()
        if not text:
            self.failed.emit("Речь не распознана — повторите чётче, ближе к микрофону.")
            return
        self.transcribed.emit(text)


# Данные для команды преподавателя (ростер + занятия сегодня) — из локальной БД
def _today_str() -> str:
    return datetime.now().strftime("%d.%m.%Y")


def teacher_roster_and_lessons(group: str, subject: str):
    """(roster, today_lessons) для группы+предмета. roster=[(фамилия,имя)];
    today_lessons=[{"id","label"}] — занятия с сегодняшней датой."""
    roster, lessons = [], []
    try:
        from core import GradeBook
        book = GradeBook(group, subject)
        roster = [(s.f, s.n) for s in book.spisok_stud]
        today = _today_str()
        for l in book.lessons:
            if (getattr(l, "date", "") or "") == today:
                label = f"{l.type} №{getattr(l, 'number', '')} · {l.date}"
                lessons.append({"id": l.id, "label": label})
    except Exception as e:
        log.get("voice_ui").warning(f"[voice] не удалось собрать ростер/занятия: {e}")
    return roster, lessons


def _write_grade(surname: str, name: str, lesson_id: str, value: str) -> bool:
    """Запись значения (оценка/Н/Б/О/✓) тем же путём, что ручная простановка в журнале."""
    try:
        from core import DBManager
        conn = DBManager.get_conn()
        cur = conn.cursor()
        DBManager.upsert_grade(cur, (surname, name, lesson_id, value))
        conn.commit(); conn.close()
        try:
            from sync_runner import trigger
            trigger()
        except Exception:
            pass
        _refresh_teacher_journal()   #перечитать открытый журнал, чтобы оценка появилась сразу
        return True
    except Exception as e:
        log.get("voice_ui").warning(f"[voice] запись не удалась: {e}")
        return False


def _refresh_teacher_journal():
    """Перезагружает открытый журнал преподавателя, чтобы голосовая правка отобразилась
    в таблице немедленно (write идёт мимо in-memory GradeBook, поэтому таблицу надо
    обновить). Ищем дашборд утиной типизацией — без жёсткой зависимости vector→ui."""
    try:
        from PySide6.QtWidgets import QApplication, QWidget
        done = set()
        for top in QApplication.topLevelWidgets():
            for w in [top] + top.findChildren(QWidget):
                if id(w) in done:
                    continue
                done.add(id(w))
                if hasattr(w, "_reload_journal") and hasattr(w, "book"):
                    try:
                        w._reload_journal()
                    except Exception:
                        pass
    except Exception as e:
        log.get("voice_ui").warning(f"[voice] обновление журнала не удалось: {e}")


_ACTION_LABEL = {"grade": "оценку", "present": "присутствие (✓)",
                 "absent_n": "пропуск (Н)", "absent_b": "пропуск по болезни (Б)",
                 "absent_o": "пропуск по уважительной (О)"}


def _write_grades_batch(items, lesson_id: str) -> int:
    """Пишет ПАКЕТ правок одной транзакцией + один раз будит синк и обновляет журнал
    (быстрее, чем построчно). items — список WriteItem. Возвращает число записанных."""
    ok = 0
    try:
        from core import DBManager
        conn = DBManager.get_conn(); cur = conn.cursor()
        for it in items:
            try:
                DBManager.upsert_grade(cur, (it.surname, it.name, lesson_id, it.value))
                ok += 1
            except Exception as e:
                log.get("voice_ui").warning(f"[voice] запись {it.who} не удалась: {e}")
        conn.commit(); conn.close()
    except Exception as e:
        log.get("voice_ui").warning(f"[voice] пакетная запись не удалась: {e}")
    try:
        from sync_runner import trigger
        trigger()
    except Exception:
        pass
    _refresh_teacher_journal()
    return ok


def _create_lesson(group: str, subject: str, ltype: str, topic: str) -> bool:
    """Создаёт занятие СЕГОДНЯ тем же путём, что кнопка «+ Занятие» в журнале."""
    try:
        from core import GradeBook
        book = GradeBook(group, subject)
        book.add_lesson(ltype, topic=topic, date=_today_str())   #save_to_db внутри
        try:
            from sync_runner import trigger
            trigger()
        except Exception:
            pass
        _refresh_teacher_journal()
        return True
    except Exception as e:
        log.get("voice_ui").warning(f"[voice] создание занятия не удалось: {e}")
        return False


# Диалог подтверждения записи (обязателен для преподавателя)
class ConfirmWriteDialog(QDialog):
    """Показывает распознанную фразу и разобранное действие; при однофамильцах — выбор
    студента. Пишем ТОЛЬКО после явного «Подтвердить»."""

    def __init__(self, cmd: voice_command.ParsedCommand, parent=None):
        super().__init__(parent)
        self.cmd = cmd
        self.chosen_student = cmd.student
        self.setWindowTitle("Подтверждение записи")
        self.setMinimumWidth(420)
        try:
            from styles import C
        except Exception:
            C = {"text": "#111", "text3": "#666", "green": "#147C8B", "card": "#fff"}
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 16); lay.setSpacing(10)

        heard = QLabel(f"🎙 Распознано: «{cmd.heard}»")
        heard.setWordWrap(True)
        heard.setStyleSheet(f"color:{C['text3']};font-size:12px;")
        lay.addWidget(heard)

        #Выбор студента при однофамильцах.
        self._combo = None
        if cmd.candidates and cmd.student is None:
            lay.addWidget(QLabel("Несколько студентов с такой фамилией — выберите:"))
            self._combo = QComboBox()
            for (f, n) in cmd.candidates:
                self._combo.addItem(f"{f} {n}", (f, n))
            lay.addWidget(self._combo)

        line = QFrame(); line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color:{C.get('border', '#ccc')};")
        lay.addWidget(line)

        self._summary = QLabel(self._summary_text())
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(f"color:{C['text']};font-size:14px;font-weight:bold;")
        lay.addWidget(self._summary)
        if self._combo is not None:
            self._combo.currentIndexChanged.connect(
                lambda *_: self._summary.setText(self._summary_text()))

        btns = QHBoxLayout(); btns.addStretch(1)
        cancel = QPushButton("Отмена"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Подтвердить и записать")
        ok.setStyleSheet(
            f"QPushButton{{background:{C['green']};color:#fff;border:none;"
            f"border-radius:8px;padding:8px 14px;font-weight:bold;}}")
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel); btns.addWidget(ok)
        lay.addLayout(btns)

    def _current_student(self):
        if self._combo is not None:
            return self._combo.currentData()
        return self.chosen_student

    def _summary_text(self) -> str:
        who = self._current_student()
        who_s = f"{who[0]} {who[1]}" if who else "…"
        act = {"grade": "оценку", "present": "присутствие (✓)",
               "absent_n": "пропуск (Н)", "absent_b": "пропуск по болезни (Б)",
               "absent_o": "пропуск по уважительной (О)"}.get(self.cmd.action, self.cmd.action)
        return f"{who_s}: {act} «{self.cmd.value}»\nЗа: {self.cmd.lesson_label}"

    def _accept(self):
        self.chosen_student = self._current_student()
        if not self.chosen_student:
            return
        self.accept()


# Диалог подтверждения ПАКЕТА правок (несколько студентов / вся группа / первые N)
class BatchConfirmDialog(QDialog):
    """Показывает СПИСОК всех разобранных правок (кому что) + предупреждения (кого
    пропустили). Пишем ТОЛЬКО после явного подтверждения. Массовое действие — поэтому
    список виден целиком."""

    def __init__(self, result, group: str, parent=None):
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("Подтверждение записи")
        self.setMinimumWidth(460)
        try:
            from styles import C
        except Exception:
            C = {"text": "#111", "text3": "#666", "green": "#147C8B", "card": "#fff",
                 "card2": "#eee", "border": "#ccc", "orange": "#c60", "red": "#d33"}
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 16); lay.setSpacing(10)

        heard = QLabel(f"🎙 Распознано: «{result.heard}»")
        heard.setWordWrap(True); heard.setStyleSheet(f"color:{C['text3']};font-size:12px;")
        lay.addWidget(heard)

        title = QLabel(f"Записать {len(result.items)} правк(и) за: {result.lesson_label}"
                       f"  ·  группа {group}")
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{C['text']};font-size:14px;font-weight:bold;")
        lay.addWidget(title)

        #Список правок (скролл — на случай всей группы).
        box = QScrollArea(); box.setWidgetResizable(True); box.setMaximumHeight(280)
        inner = QWidget(); il = QVBoxLayout(inner); il.setContentsMargins(6, 6, 6, 6); il.setSpacing(3)
        for it in result.items:
            row = QLabel(f"• {it.who} — {_ACTION_LABEL.get(it.action, it.action)} «{it.value}»")
            row.setStyleSheet(f"color:{C['text']};font-size:13px;")
            il.addWidget(row)
        il.addStretch(1)
        box.setWidget(inner)
        box.setStyleSheet(f"QScrollArea{{border:1px solid {C.get('border','#ccc')};"
                          f"border-radius:8px;background:{C.get('card2','#f4f4f4')};}}")
        lay.addWidget(box)

        #Предупреждения (кого пропустили) — не блокируют, но видны.
        for w in (result.warnings or []):
            wl = QLabel("⚠ " + w); wl.setWordWrap(True)
            wl.setStyleSheet(f"color:{C.get('orange','#c60')};font-size:12px;")
            lay.addWidget(wl)

        btns = QHBoxLayout(); btns.addStretch(1)
        cancel = QPushButton("Отмена"); cancel.clicked.connect(self.reject)
        ok = QPushButton(f"Подтвердить и записать ({len(result.items)})")
        ok.setStyleSheet(f"QPushButton{{background:{C['green']};color:#fff;border:none;"
                         f"border-radius:8px;padding:8px 14px;font-weight:bold;}}")
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel); btns.addWidget(ok)
        lay.addLayout(btns)


# Диалог создания занятия («создай сегодня лекцию по теме …»)
class CreateLessonDialog(QDialog):
    def __init__(self, plan, group: str, subject: str, today: str, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("Создать занятие")
        self.setMinimumWidth(440)
        try:
            from styles import C
        except Exception:
            C = {"text": "#111", "text3": "#666", "green": "#147C8B", "card2": "#eee",
                 "border": "#ccc"}
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 16); lay.setSpacing(10)
        heard = QLabel(f"🎙 {plan.type} · сегодня {today} · {group} / {subject}")
        heard.setWordWrap(True)
        heard.setStyleSheet(f"color:{C['text']};font-size:14px;font-weight:bold;")
        lay.addWidget(heard)
        lay.addWidget(QLabel("Тема занятия (можно поправить):"))
        self._topic = QLineEdit(plan.topic or "")
        self._topic.setPlaceholderText("Тема занятия")
        self._topic.setStyleSheet(f"border:1px solid {C.get('border','#ccc')};"
                                  f"border-radius:6px;padding:7px;color:{C['text']};")
        lay.addWidget(self._topic)
        btns = QHBoxLayout(); btns.addStretch(1)
        cancel = QPushButton("Отмена"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Создать занятие")
        ok.setStyleSheet(f"QPushButton{{background:{C['green']};color:#fff;border:none;"
                         f"border-radius:8px;padding:8px 14px;font-weight:bold;}}")
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel); btns.addWidget(ok)
        lay.addLayout(btns)

    def topic(self) -> str:
        return self._topic.text().strip()


# Подсказки по функционалу и примеры команд (кнопка «?» у микрофона), по ролям
VOICE_HELP = {
    "student": [
        ("Спросите голосом или текстом", [
            "Какой у меня средний балл?",
            "Есть ли у меня задолженности?",
            "Сколько у меня пропусков?",
            "Как у меня с успеваемостью?",
            "Покажи моё расписание.",
        ]),
        ("Как пользоваться", [
            "Нажмите 🎤, говорите чётко, нажмите ещё раз (стоп).",
            "Микрофон выбирается в «Профиле».",
            "Вектор отвечает по реальным данным журнала — не выдумывает.",
        ]),
    ],
    "teacher": [
        ("Вопросы (чтение)", [
            "Какой средний балл группы?",
            "Назови студентов группы.",
            "Кто должники?",
            "Какой средний балл у Иванова?",
            "Сколько пропусков у Петрова?",
        ]),
        ("Оценки и посещаемость (с подтверждением)", [
            "Иванову пять.",
            "Иванову пять, Петрову четыре, Сидоровой три.",
            "Иванову и Петрову по четыре.",
            "Всей группе пять.",
            "Первым десяти по списку четыре.",
            "Петров болеет.  ·  Сидоров по уважительной.  ·  Иванов не пришёл.",
        ]),
        ("Занятия", [
            "Создай сегодня лекцию по теме «Введение в модули».",
            "Создай сегодня практику по теме «Циклы».",
        ]),
        ("Важно", [
            "Любая запись сначала показывается на подтверждение — ничего не пишется молча.",
            "При неоднозначности (два однофамильца, неясная оценка) Вектор переспросит.",
            "Оценки ставятся за СЕГОДНЯШНЕЕ занятие текущей группы/предмета.",
        ]),
    ],
    "admin": [
        ("Спросите голосом или текстом", [
            "Сколько студентов в системе?",
            "Сколько преподавателей?",
            "Сколько групп?",
            "Дай сводку по заведению.",
        ]),
        ("Как пользоваться", [
            "Нажмите 🎤, говорите, нажмите ещё раз (стоп).",
            "Голосовой ввод включается в «Настройки ИИ».",
        ]),
    ],
}


class VoiceHelpPopup(QDialog):
    """Подсказки и примеры голосовых команд для конкретной роли."""

    def __init__(self, role: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Голосовой ввод — что можно сказать")
        self.setMinimumWidth(460)
        try:
            from styles import C
        except Exception:
            C = {"text": "#111", "text3": "#666", "green": "#147C8B", "card2": "#eee",
                 "border": "#ccc"}
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 16, 18, 16); lay.setSpacing(8)
        head = QLabel("🎙 Примеры команд Вектора")
        head.setStyleSheet(f"color:{C['text']};font-size:16px;font-weight:bold;")
        lay.addWidget(head)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setMaximumHeight(460)
        inner = QWidget(); il = QVBoxLayout(inner); il.setContentsMargins(4, 4, 4, 4); il.setSpacing(6)
        for section, examples in VOICE_HELP.get(role, VOICE_HELP["student"]):
            sl = QLabel(section)
            sl.setStyleSheet(f"color:{C['green']};font-size:13px;font-weight:bold;margin-top:6px;")
            il.addWidget(sl)
            for ex in examples:
                el = QLabel("• " + ex); el.setWordWrap(True)
                el.setStyleSheet(f"color:{C['text']};font-size:13px;")
                il.addWidget(el)
        il.addStretch(1)
        scroll.setWidget(inner)
        scroll.setStyleSheet(f"QScrollArea{{border:1px solid {C.get('border','#ccc')};"
                             f"border-radius:8px;background:{C.get('card2','#f4f4f4')};}}")
        lay.addWidget(scroll)

        close = QPushButton("Понятно")
        close.setStyleSheet(f"QPushButton{{background:{C['green']};color:#fff;border:none;"
                            f"border-radius:8px;padding:8px 14px;font-weight:bold;}}")
        close.clicked.connect(self.accept)
        row = QHBoxLayout(); row.addStretch(1); row.addWidget(close)
        lay.addLayout(row)


def show_voice_help(role: str, parent=None):
    VoiceHelpPopup(role, parent).exec()


# Ролевой роутинг распознанного текста
def _info(on_info, msg):
    if on_info:
        on_info(msg)


def route_voice_text(parent, session, scope, text: str, on_info=None):
    """Куда направить распознанную фразу.
      • Студент/админ или ВОПРОС           → session.ask(text) (обычный Q&A Вектора).
      • Препод, «создай … занятие»          → диалог создания → запись.
      • Препод, ПАКЕТ простановок           → диалог со списком правок → запись всех.
    on_info(msg) — колбэк для служебных сообщений в чате.
    """
    role = getattr(scope, "role", "student")

    #Студент/админ: только чтение — сразу в Q&A.
    if role != "teacher":
        session.ask(text)
        return

    group = getattr(scope, "group", "") or ""
    subject = getattr(scope, "subject", "") or ""
    roster, today_lessons = teacher_roster_and_lessons(group, subject)
    r = voice_command.parse_batch(text, roster, today_lessons)

    #Вопрос → обычный Q&A.
    if r.is_question or r.kind == "question":
        session.ask(text)
        return

    #Ошибка разбора — показать причину (не гадаем).
    if r.kind == "error":
        _info(on_info, f"🎙 «{r.heard}». {r.error}")
        return

    #Создание занятия.
    if r.kind == "lesson":
        dlg = CreateLessonDialog(r.lesson, group, subject, _today_str(), parent)
        if dlg.exec() != QDialog.Accepted:
            _info(on_info, "🎙 Создание занятия отменено.")
            return
        topic = dlg.topic()
        ok = _create_lesson(group, subject, r.lesson.type, topic)
        _info(on_info, (f"✅ Создано занятие: {r.lesson.type}"
                        + (f" «{topic}»" if topic else "") + " за сегодня.") if ok
              else "⚠ Не удалось создать занятие — попробуйте вручную.")
        return

    #Пакет простановок.
    if r.kind == "grades" and r.items:
        dlg = BatchConfirmDialog(r, group, parent)
        if dlg.exec() != QDialog.Accepted:
            _info(on_info, "🎙 Запись отменена.")
            return
        n = _write_grades_batch(r.items, r.lesson_id)
        extra = ""
        if r.warnings:
            extra = f" Пропущено: {len(r.warnings)} (см. предупреждения)."
        _info(on_info, f"✅ Записано правок: {n} из {len(r.items)} за {r.lesson_label}.{extra}"
              if n else "⚠ Не удалось записать — попробуйте вручную в журнале.")
        return

    #На всякий случай — в Q&A.
    session.ask(text)
