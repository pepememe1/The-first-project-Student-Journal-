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

from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer
from PySide6.QtWidgets import (
    QToolButton, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QFrame,
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
        print(f"[voice] не удалось сохранить выбор микрофона: {e}")


#──────────────────────────────────────────────────────────────────────────────────
# Виджет выбора микрофона (для вкладки «Профиль» на десктопе)
#──────────────────────────────────────────────────────────────────────────────────
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


#──────────────────────────────────────────────────────────────────────────────────
# Распознавание в отдельном потоке (Whisper тяжёлый — не морозим UI)
#──────────────────────────────────────────────────────────────────────────────────
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


#──────────────────────────────────────────────────────────────────────────────────
# Кнопка микрофона: нажал → запись, нажал → стоп → распознавание
#──────────────────────────────────────────────────────────────────────────────────
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


#──────────────────────────────────────────────────────────────────────────────────
# Данные для команды преподавателя (ростер + занятия сегодня) — из локальной БД
#──────────────────────────────────────────────────────────────────────────────────
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
        print(f"[voice] не удалось собрать ростер/занятия: {e}")
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
        print(f"[voice] запись не удалась: {e}")
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
        print(f"[voice] обновление журнала не удалось: {e}")


#──────────────────────────────────────────────────────────────────────────────────
# Диалог подтверждения записи (обязателен для преподавателя)
#──────────────────────────────────────────────────────────────────────────────────
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


#──────────────────────────────────────────────────────────────────────────────────
# Ролевой роутинг распознанного текста
#──────────────────────────────────────────────────────────────────────────────────
def route_voice_text(parent, session, scope, text: str,
                     on_info=None):
    """Куда направить распознанную фразу.
      • Вопрос / не-команда / студент  → session.ask(text) (обычный Q&A Вектора).
      • Команда препода (запись)        → parse → ДИАЛОГ подтверждения → запись.
    on_info(msg) — колбэк для показа служебных сообщений в чате (ошибки разбора и т.п.).
    """
    role = getattr(scope, "role", "student")

    #Студент/админ: только чтение — сразу в Q&A.
    if role != "teacher":
        session.ask(text)
        return

    group = getattr(scope, "group", "") or ""
    subject = getattr(scope, "subject", "") or ""
    roster, today_lessons = teacher_roster_and_lessons(group, subject)
    cmd = voice_command.parse(text, roster, today_lessons)

    #Вопрос или не-команда записи → обычный Q&A.
    if cmd.is_question or cmd.action not in voice_command.WRITE_ACTIONS:
        session.ask(text)
        return

    #Команда записи, но неоднозначная/ошибочная (не однофамильцы) → показать причину.
    if not cmd.ok and not cmd.candidates:
        if on_info:
            on_info(f"🎙 «{cmd.heard}». {cmd.error}")
        else:
            session.ask(text)
        return

    #Готовая команда (или выбор из однофамильцев) → подтверждение.
    dlg = ConfirmWriteDialog(cmd, parent)
    if dlg.exec() != QDialog.Accepted:
        if on_info:
            on_info("🎙 Запись отменена.")
        return
    who = dlg.chosen_student
    ok = _write_grade(who[0], who[1], cmd.lesson_id, cmd.value)
    if on_info:
        if ok:
            act = {"grade": "оценка", "present": "присутствие",
                   "absent_n": "пропуск (Н)", "absent_b": "болезнь (Б)",
                   "absent_o": "уважительная (О)"}.get(cmd.action, cmd.action)
            on_info(f"✅ Записано: {who[0]} {who[1]} — {act} «{cmd.value}» "
                    f"за {cmd.lesson_label}.")
        else:
            on_info("⚠ Не удалось записать — попробуйте вручную в журнале.")
