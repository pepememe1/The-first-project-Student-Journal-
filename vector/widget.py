"""
widget.py — Компаньон «Вектор» (PySide6): панель чата + спрайтовый маскот.

МАСКОТ — машина состояний на 4 картинках (кладутся в папку `vector_assets/`):

    1_idle.png      — статика: Вектор «слушает» (курсор над чатом, ждёт вопрос)
    2_thinking.png  — обдумывание: после отправки вопроса и ещё 1 c после ответа
    3_speaking.png  — открыт рот: «говорит» 5–7 c (длительность зависит от длины ответа)
    4_away.png      — ожидание: курсор НЕ над чатом (пользователь работает с журналом)

Логика переключений (ровно по ТЗ):
    • пока вопрос не написан и курсор над чатом         → 1_idle
    • вопрос отправлен                                  → 2_thinking
    • ответ пришёл: ещё 1 секунду держим                → 2_thinking
    • затем «речь» на 5–7 c (по длине ответа)           → 3_speaking
    • речь закончена                                    → 1_idle (будто договорил)
    • курсор ушёл с панели: 2 c ещё висит 1_idle, потом → 4_away
    • курсор вернулся на панель                         → 1_idle
    • чат свёрнут/отключён → картинки скрываются вместе с панелью
    • чат перенесён вправо (⇄) → спрайт зеркалится по горизонтали

Поддерживаются и АНИМИРОВАННЫЕ состояния: вместо одного файла можно положить
папку с кадрами — `vector_assets/idle/*.png` (кадры листаются по таймеру).
Если арта ещё нет — работает векторная заглушка 🐯, ничего не падает.
"""
import os

from PySide6.QtCore import Qt, QThread, Signal, QPropertyAnimation, QPoint, QTimer, QEasingCurve
from PySide6.QtGui import QPixmap, QColor, QTransform
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QLineEdit, QFrame, QToolButton, QSizePolicy
)

# Цвета/виджеты проекта (фолбэк, если импорт не удался при изоляции)
try:
    from styles import C
except Exception:
    C = {"card": "#fff", "card2": "#f3f6f7", "border": "#dfe6e8",
         "text": "#0d2b30", "text3": "#3a565b", "green": "#147c8b",
         "blue": "#1f6f8b", "bg": "#eef5f6"}

PANEL_WIDTH = 320

# ── настройки маскота ─────────────────────────────────────────
ASSETS_DIR = "vector_assets"          # рядом с exe/main.py
AVATAR_SIZE = 140                     # размер вывода спрайта, px

THINK_HOLD_AFTER_ANSWER_MS = 1000     # 1 c «дообдумывает» после ответа (по ТЗ)
SPEAK_MIN_MS = 5000                   # речь минимум 5 c
SPEAK_MAX_MS = 7000                   # речь максимум 7 c
SPEAK_MS_PER_CHAR = 25                # +25 мс за символ ответа (между 5 и 7 c)
AWAY_DELAY_MS = 2000                  # «ещё пару секунд» idle после ухода курсора
FRAME_MS = 160                        # скорость листания кадров, если папка с кадрами

# Состояния (имена = имена файлов/папок в vector_assets)
ST_IDLE, ST_THINK, ST_SPEAK, ST_AWAY = "idle", "thinking", "speaking", "away"

# Какие имена файлов ищем для каждого состояния (в порядке приоритета)
_STATE_FILES = {
    ST_IDLE:  ["1_idle.png", "idle.png", "1.png"],
    ST_THINK: ["2_thinking.png", "thinking.png", "2.png"],
    ST_SPEAK: ["3_speaking.png", "speaking.png", "3.png"],
    ST_AWAY:  ["4_away.png", "away.png", "waiting.png", "4.png"],
}

# Заглушки, пока Арина не нарисовала арт
_FALLBACK_FACE = {ST_IDLE: "🐯", ST_THINK: "🤔", ST_SPEAK: "🗣️", ST_AWAY: "😴"}
_FALLBACK_MOUTH = {ST_IDLE: "•‿•", ST_THINK: "· · ·", ST_SPEAK: "▿", ST_AWAY: "︶"}

_MOOD_TINT = {"happy": "#2e9e5b", "neutral": C.get("green", "#147c8b"), "sad": "#b9772b"}


def _find_assets_dir() -> str:
    """Ищем vector_assets рядом с программой и рядом с пакетом vector."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.getcwd(), ASSETS_DIR),
        os.path.join(os.path.dirname(here), ASSETS_DIR),
        os.path.join(here, ASSETS_DIR),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return ""


def _load_state_frames(base: str, state: str) -> list:
    """
    Кадры состояния:
      • папка vector_assets/<state>/ с PNG — анимация (кадры по алфавиту);
      • одиночный файл из _STATE_FILES — статичная картинка (1 кадр).
    Пусто — будет заглушка.
    """
    frames = []
    if not base:
        return frames
    folder = os.path.join(base, state)
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            if fn.lower().endswith(".png"):
                pm = QPixmap(os.path.join(folder, fn))
                if not pm.isNull():
                    frames.append(pm)
        if frames:
            return frames
    for fn in _STATE_FILES.get(state, []):
        path = os.path.join(base, fn)
        if os.path.isfile(path):
            pm = QPixmap(path)
            if not pm.isNull():
                return [pm]
    return frames


def speak_duration_ms(text: str) -> int:
    """5–7 секунд в зависимости от длины ответа (по ТЗ)."""
    return max(SPEAK_MIN_MS,
               min(SPEAK_MAX_MS, SPEAK_MIN_MS + len(text or "") * SPEAK_MS_PER_CHAR))


# ══════════════════════════════════════════════════════════════
#  Аватар Вектора: спрайтовая машина состояний
# ══════════════════════════════════════════════════════════════
class VectorAvatar(QWidget):
    """
    Переключает PNG-состояния маскота. Если PNG не найдены — эмодзи-заглушка.
    set_mirrored(True) зеркалит спрайт (для панели справа).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(PANEL_WIDTH - 24, AVATAR_SIZE + 36)
        self._state = ST_AWAY
        self._mood = "neutral"
        self._mirrored = False
        self._frame_i = 0

        base = _find_assets_dir()
        self._frames = {s: _load_state_frames(base, s)
                        for s in (ST_IDLE, ST_THINK, ST_SPEAK, ST_AWAY)}

        # Картинка/заглушка (позиционируется вручную — чтобы анимировать pos)
        self._face = QLabel(self)
        self._face.setAlignment(Qt.AlignCenter)
        self._face.setFixedSize(AVATAR_SIZE, AVATAR_SIZE)
        self._face.move((self.width() - AVATAR_SIZE) // 2, 4)
        self._face.setStyleSheet("font-size:64px;")

        # Подпись-«рот» нужна только заглушке; при наличии PNG скрывается
        self._mouth = QLabel(self)
        self._mouth.setAlignment(Qt.AlignCenter)
        self._mouth.setFixedWidth(self.width())
        self._mouth.move(0, AVATAR_SIZE + 8)
        self._mouth.setStyleSheet(
            f"font-size:18px;color:{_MOOD_TINT['neutral']};font-weight:bold;")

        # Покачивание (живость для thinking/speaking) и листание кадров
        self._bob = QPropertyAnimation(self._face, b"pos")
        self._bob.setLoopCount(-1)
        self._bob.setEasingCurve(QEasingCurve.InOutSine)
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._next_frame)

        self.set_state(ST_AWAY)   # по умолчанию курсор не над чатом

    # ── публичные хуки ────────────────────────────────────────
    def set_sprites(self, **kwargs):
        """
        Подключить арт из кода: set_sprites(idle="a.png", speaking=["1.png","2.png"]).
        Обычно не нужно — файлы из vector_assets подхватываются автоматически.
        """
        for state, val in kwargs.items():
            if state not in self._frames:
                continue
            paths = [val] if isinstance(val, str) else list(val or [])
            frames = [QPixmap(p) for p in paths]
            frames = [f for f in frames if not f.isNull()]
            if frames:
                self._frames[state] = frames
        self._apply_frame()

    def set_mirrored(self, mirrored: bool):
        """Зеркалит спрайт по горизонтали (панель перенесена вправо)."""
        if self._mirrored != mirrored:
            self._mirrored = mirrored
            self._apply_frame()

    def set_mood(self, mood: str):
        self._mood = mood if mood in _MOOD_TINT else "neutral"
        self._mouth.setStyleSheet(
            f"font-size:18px;color:{_MOOD_TINT[self._mood]};font-weight:bold;")

    def state(self) -> str:
        return self._state

    def set_state(self, state: str):
        """Главный вход машины состояний."""
        if state not in self._frames:
            state = ST_IDLE
        self._state = state
        self._frame_i = 0
        self._frame_timer.stop()
        self._bob.stop()
        self._face.move((self.width() - AVATAR_SIZE) // 2, 4)

        frames = self._frames[state]
        if len(frames) > 1:
            self._frame_timer.start(FRAME_MS)   # анимация из папки с кадрами
        if state == ST_THINK:
            self._start_bob(amp=4, dur=420)
        elif state == ST_SPEAK:
            self._start_bob(amp=7, dur=620)
        self._apply_frame()

    # ── внутреннее ────────────────────────────────────────────
    def _apply_frame(self):
        frames = self._frames.get(self._state) or []
        if frames:
            pm = frames[self._frame_i % len(frames)]
            if self._mirrored:
                pm = pm.transformed(QTransform().scale(-1, 1),
                                    Qt.SmoothTransformation)
            self._face.setText("")
            self._face.setPixmap(pm.scaled(
                AVATAR_SIZE, AVATAR_SIZE, Qt.KeepAspectRatio,
                Qt.SmoothTransformation))
            self._mouth.setText("")
        else:
            # эмодзи-заглушка
            self._face.setPixmap(QPixmap())
            self._face.setText(_FALLBACK_FACE[self._state])
            self._mouth.setText(_FALLBACK_MOUTH[self._state])

    def _start_bob(self, amp=6, dur=600):
        base = QPoint((self.width() - AVATAR_SIZE) // 2, 4)
        self._bob.stop()
        self._bob.setDuration(dur)
        self._bob.setKeyValueAt(0.0, base)
        self._bob.setKeyValueAt(0.5, QPoint(base.x(), base.y() - amp))
        self._bob.setKeyValueAt(1.0, base)
        self._bob.start()

    def _next_frame(self):
        frames = self._frames.get(self._state) or []
        if len(frames) > 1:
            self._frame_i = (self._frame_i + 1) % len(frames)
            self._apply_frame()


# ══════════════════════════════════════════════════════════════
#  Поток запроса к движку (не блокирует UI)
# ══════════════════════════════════════════════════════════════
class VectorAskThread(QThread):
    answered = Signal(str, str, str)     # text, mood, intent
    failed = Signal(str)

    def __init__(self, engine, question):
        super().__init__()
        self.engine = engine
        self.question = question

    def run(self):
        try:
            resp = self.engine.ask(self.question)
            self.answered.emit(resp.text, resp.mood, resp.intent)
        except Exception as e:
            self.failed.emit(str(e))


# ══════════════════════════════════════════════════════════════
#  Панель Вектора (аватар + чат + меню команд + тулбар)
# ══════════════════════════════════════════════════════════════
class VectorPanel(QWidget):
    move_side = Signal()       # просьба перенести влево/вправо
    hide_me = Signal()         # просьба свернуть

    def __init__(self, engine, parent=None, docked=True):
        super().__init__(parent)
        self.engine = engine
        self._thread = None
        self.docked = docked
        self._hovered = False          # курсор сейчас над панелью?
        self._busy = False             # идёт обдумывание/речь?

        # Таймеры сценария маскота
        self._away_timer = QTimer(self)          # idle → away после ухода курсора
        self._away_timer.setSingleShot(True)
        self._away_timer.timeout.connect(self._go_away)
        self._speak_start_timer = QTimer(self)   # 1 c thinking после ответа
        self._speak_start_timer.setSingleShot(True)
        self._speak_end_timer = QTimer(self)     # конец речи через 5–7 c
        self._speak_end_timer.setSingleShot(True)
        self._speak_end_timer.timeout.connect(self._finish_speaking)

        if docked:
            self.setFixedWidth(PANEL_WIDTH)
            self.setStyleSheet(
                f"background:{C['card']};border-right:1px solid {C['border']};")
        else:
            # режим «во всю вкладку»: ширину не фиксируем
            self.setStyleSheet(f"background:{C['card']};")
        self._build()

    # ── сборка интерфейса ─────────────────────────────────────
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        # Тулбар: имя + перенос + свернуть
        bar = QHBoxLayout()
        bar.setSpacing(4)
        name = QLabel("Вектор")
        name.setStyleSheet(f"color:{C['text']};font-size:15px;font-weight:bold;")
        bar.addWidget(name, 1)
        side_b = QToolButton(); side_b.setText("⇄"); side_b.setToolTip("Перенести в другую сторону")
        side_b.clicked.connect(self.move_side.emit)
        hide_b = QToolButton(); hide_b.setText("—"); hide_b.setToolTip("Свернуть")
        hide_b.clicked.connect(self.hide_me.emit)
        for b in (side_b, hide_b):
            b.setStyleSheet(
                f"QToolButton{{color:{C['text3']};border:none;font-size:16px;"
                f"padding:2px 6px;}}QToolButton:hover{{color:{C['green']};}}")
            bar.addWidget(b)
            # во вкладке кнопки переноса/сворачивания не нужны
            if not self.docked:
                b.hide()
        lay.addLayout(bar)

        # Аватар-маскот
        self.avatar = VectorAvatar()
        lay.addWidget(self.avatar, 0, Qt.AlignHCenter)

        # Чат
        self.chat = QTextEdit(); self.chat.setReadOnly(True)
        self.chat.setStyleSheet(
            f"background:{C['card2']};border:1px solid {C['border']};border-radius:10px;"
            f"padding:10px;font-size:12.5px;color:{C['text']};")
        lay.addWidget(self.chat, 1)

        # ── МЕНЮ БЫСТРЫХ КОМАНД: ответ мгновенно и без ИИ ────
        lay.addLayout(self._build_quick_commands())

        # Ввод
        row = QHBoxLayout(); row.setSpacing(6)
        self.inp = QLineEdit(); self.inp.setPlaceholderText("Спросить Вектора…")
        self.inp.setStyleSheet(
            f"background:{C['card']};border:1px solid {C['border']};border-radius:8px;"
            f"padding:7px;color:{C['text']};font-size:13px;")
        self.inp.returnPressed.connect(self._send)
        send = QPushButton("→"); send.setFixedWidth(40)
        send.setStyleSheet(
            f"background:{C['green']};color:#fff;border:none;border-radius:8px;"
            f"font-size:16px;font-weight:bold;")
        send.clicked.connect(self._send)
        self.send_btn = send
        row.addWidget(self.inp); row.addWidget(send)
        lay.addLayout(row)

        self._append("Вектор", self.engine.greeting())

    def _build_quick_commands(self):
        """Кнопки-команды из пула. Нажатие = готовый вопрос = ответ без LLM."""
        from PySide6.QtWidgets import QGridLayout
        try:
            from .faq import QUICK_COMMANDS
            role = getattr(self.engine.scope, "role", "student")
            cmds = QUICK_COMMANDS.get(role, QUICK_COMMANDS["student"])
        except Exception:
            cmds = []
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (label, question) in enumerate(cmds):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{C['card2']};border:1px solid {C['border']};"
                f"border-radius:8px;padding:5px 8px;color:{C['text3']};font-size:11.5px;"
                f"text-align:left;}}"
                f"QPushButton:hover{{color:{C['green']};border-color:{C['green']};}}")
            b.clicked.connect(lambda _=False, q=question: self.ask_command(q))
            grid.addWidget(b, i // 2, i % 2)
        return grid

    # ── чат ───────────────────────────────────────────────────
    def _append(self, who, text):
        color = C["green"] if who == "Вектор" else C["blue"]
        safe = (text or "").replace("\n", "<br>")
        self.chat.append(
            f'<span style="color:{color};font-weight:bold;">{who}:</span> '
            f'<span style="color:{C["text"]};">{safe}</span><br>')
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def ask_command(self, question: str):
        """Программная отправка готовой команды (кнопки меню)."""
        if self._thread and self._thread.isRunning():
            return
        self.inp.setText(question)
        self._send()

    def _send(self):
        q = self.inp.text().strip()
        if not q or (self._thread and self._thread.isRunning()):
            return
        self._append("Вы", q)
        self.inp.clear()
        self.send_btn.setEnabled(False)

        # ── маскот: вопрос отправлен → 2_thinking ──
        self._busy = True
        self._away_timer.stop()
        self._speak_end_timer.stop()
        self.avatar.set_state(ST_THINK)

        self._thread = VectorAskThread(self.engine, q)
        self._thread.answered.connect(self._on_answer)
        self._thread.failed.connect(self._on_fail)
        self._thread.start()

    def _on_answer(self, text, mood, intent):
        self.send_btn.setEnabled(True)
        self.avatar.set_mood(mood)
        self._append("Вектор", text)
        # ── маскот: ответ отправлен, но ещё 1 c «дообдумывает» (по ТЗ),
        #    затем 3_speaking на 5–7 c по длине ответа, затем 1_idle ──
        dur = speak_duration_ms(text)
        # отвязываем прошлый слот без шумного RuntimeWarning
        prev = getattr(self, "_speak_slot", None)
        if prev is not None:
            try:
                self._speak_start_timer.timeout.disconnect(prev)
            except (RuntimeError, TypeError):
                pass
        self._speak_slot = lambda: self._begin_speaking(dur)
        self._speak_start_timer.timeout.connect(self._speak_slot)
        self._speak_start_timer.start(THINK_HOLD_AFTER_ANSWER_MS)

    def _begin_speaking(self, dur_ms: int):
        self.avatar.set_state(ST_SPEAK)
        self._speak_end_timer.start(dur_ms)

    def _finish_speaking(self):
        """Речь окончена → 1_idle, будто договорил; если курсор не у чата —
        через паузу уйдёт в 4_away."""
        self._busy = False
        self.avatar.set_state(ST_IDLE)
        if not self._hovered:
            self._away_timer.start(AWAY_DELAY_MS)

    def _on_fail(self, err):
        self.send_btn.setEnabled(True)
        self._busy = False
        self.avatar.set_state(ST_IDLE)
        self._append("Вектор", f"Ой, не получилось ответить: {err}. "
                               f"Попробуй ещё раз или нажми кнопку под чатом.")
        if not self._hovered:
            self._away_timer.start(AWAY_DELAY_MS)

    def push_proactive(self, text, mood="neutral"):
        """Внешняя проактивная реплика (например, по карточке-инсайту)."""
        self.avatar.set_mood(mood)
        self._append("Вектор", text)
        self._busy = True
        self._away_timer.stop()
        self._begin_speaking(speak_duration_ms(text))

    # ── hover-логика маскота (1_idle ↔ 4_away) ────────────────
    def enterEvent(self, event):
        """Курсор над чатом → 1_idle (если Вектор не думает/не говорит)."""
        self._hovered = True
        self._away_timer.stop()
        if not self._busy and self.avatar.state() == ST_AWAY:
            self.avatar.set_state(ST_IDLE)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Курсор ушёл → ещё пару секунд 1_idle, затем 4_away."""
        self._hovered = False
        if not self._busy:
            self._away_timer.start(AWAY_DELAY_MS)
        super().leaveEvent(event)

    def _go_away(self):
        if not self._hovered and not self._busy:
            self.avatar.set_state(ST_AWAY)

    # ── зеркало при переносе панели ───────────────────────────
    def set_side(self, side: str):
        """Вызывается хостом: 'left' / 'right'. Справа — спрайт зеркалится."""
        self.avatar.set_mirrored(side == "right")
        if self.docked:
            border = "border-left" if side == "right" else "border-right"
            self.setStyleSheet(
                f"background:{C['card']};{border}:1px solid {C['border']};")


# ══════════════════════════════════════════════════════════════
#  Хост: вставляет панель в QHBoxLayout дашборда и рулит сторонами
# ══════════════════════════════════════════════════════════════
class VectorHost:
    """
    Управляет размещением Вектора в горизонтальном layout дашборда (тот самый
    `body` из TeacherDashboard/StudentDashboard/AdminDashboard).

    Использование в дашборде:
        from vector.widget import VectorPanel, VectorHost
        panel = VectorPanel(engine)
        self.vector_host = VectorHost(body, panel)   # body — QHBoxLayout
        self.vector_host.mount(side="left")
    """
    def __init__(self, body_layout, panel: VectorPanel):
        self.body = body_layout
        self.panel = panel
        self.side = "left"
        # Тонкая полоска для разворачивания, когда свёрнут
        self.restore = QToolButton()
        self.restore.setText("🐯")
        self.restore.setToolTip("Показать Вектора")
        self.restore.setFixedWidth(28)
        self.restore.setStyleSheet(
            f"QToolButton{{background:{C['card2']};border:none;font-size:18px;}}"
            f"QToolButton:hover{{background:{C['bg']};}}")
        self.restore.hide()
        self.restore.clicked.connect(self.show_panel)
        self.panel.move_side.connect(self.toggle_side)
        self.panel.hide_me.connect(self.hide_panel)

    def _insert(self, w, side):
        if side == "left":
            self.body.insertWidget(0, w)
        else:
            self.body.addWidget(w)

    def mount(self, side="left"):
        self.side = side
        self._insert(self.panel, side)
        self._insert(self.restore, side)
        self.restore.hide()
        self.panel.set_side(side)

    def toggle_side(self):
        self.body.removeWidget(self.panel)
        self.body.removeWidget(self.restore)
        self.side = "right" if self.side == "left" else "left"
        self._insert(self.panel, self.side)
        self._insert(self.restore, self.side)
        self.restore.setVisible(not self.panel.isVisible())
        # зеркалим маскота, когда панель справа (по ТЗ)
        self.panel.set_side(self.side)

    def hide_panel(self):
        # картинки маскота скрываются вместе со всей панелью (по ТЗ)
        self.panel.hide()
        self.restore.show()

    def show_panel(self):
        self.restore.hide()
        self.panel.show()
