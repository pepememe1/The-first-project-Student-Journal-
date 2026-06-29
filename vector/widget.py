"""
widget.py — Компаньон «Вектор» (PySide6): панель чата + маскот в полный рост.

МАСКОТ — машина состояний, рисующая настоящий арт Арины (полноростовые спрайты
из папки `emotes/`, см. vector/emotes.py). У каждого спрайта своя ЭМОЦИЯ: пара
«морда + жест» подбирается по состоянию, настроению ответа и намерению — поэтому
Вектор живёт всем диапазоном (радуется, грустит-подбадривает, думает, предупреждает,
удивляется). Подбор — emotes.pick(state, mood, intent).

Состояния машины:
    idle      — Вектор «слушает» (курсор над чатом, ждёт вопрос) → удивлён-насторожен
    thinking  — обдумывание: после отправки вопроса и ещё 1 c после ответа → думает
    speaking  — «говорит» 5–7 c (длительность зависит от длины ответа) → эмоция по ответу
    away      — курсор НЕ над чатом (работа с журналом) → расслаблен, руки в карманах

Логика переключений (ровно по ТЗ):
    • пока вопрос не написан и курсор над чатом         → idle
    • вопрос отправлен                                  → thinking
    • ответ пришёл: ещё 1 секунду держим                → thinking
    • затем «речь» на 5–7 c (по длине ответа)           → speaking (эмоция по mood/intent)
    • речь закончена                                    → idle (будто договорил)
    • курсор ушёл с панели: 2 c ещё висит idle, потом   → away
    • курсор вернулся на панель                         → idle
    • чат свёрнут/отключён → маскот скрывается вместе с панелью
    • чат перенесён вправо (⇄) → спрайт зеркалится по горизонтали

Если папки `emotes/` нет — работает компактная эмодзи-заглушка 🐯, ничего не падает.
"""
import os

from . import emotes

from PySide6.QtCore import (
    Qt, QObject, QThread, Signal, QPropertyAnimation, QPoint, QTimer, QEasingCurve
)
from PySide6.QtGui import QPixmap, QColor, QTransform
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QLineEdit, QFrame, QToolButton, QSizePolicy
)

#Цвета/виджеты проекта (фолбэк, если импорт не удался при изоляции)
try:
    from styles import C
except Exception:
    C = {"card": "#fff", "card2": "#f3f6f7", "border": "#dfe6e8",
         "text": "#0d2b30", "text3": "#3a565b", "green": "#147c8b",
         "blue": "#1f6f8b", "bg": "#eef5f6"}

PANEL_WIDTH = 320

#настройки маскота (арт из vector/emotes.py)
AVATAR_H = 360                        #высота фигуры в боковой шторке, px (полный рост)
AVATAR_H_TAB = 480                    #высота во вкладке «ИИ Помощник» (там места больше)
AVATAR_AR = 0.78                      #ширина виджета = высота × этот коэф. (под фигуру)

THINK_HOLD_AFTER_ANSWER_MS = 1000     #1 c «дообдумывает» после ответа (по ТЗ)
SPEAK_MIN_MS = 5000                   #речь минимум 5 c
SPEAK_MAX_MS = 7000                   #речь максимум 7 c
SPEAK_MS_PER_CHAR = 25                #+25 мс за символ ответа (между 5 и 7 c)
AWAY_DELAY_MS = 2000                  #«ещё пару секунд» idle после ухода курсора

#Состояния машины маскота
ST_IDLE, ST_THINK, ST_SPEAK, ST_AWAY = "idle", "thinking", "speaking", "away"

#Заглушка, пока папки emotes/ нет (компактные эмодзи под состояние)
_FALLBACK_FACE = {ST_IDLE: "🐯", ST_THINK: "🤔", ST_SPEAK: "🗣️", ST_AWAY: "😴"}
_FALLBACK_MOUTH = {ST_IDLE: "•‿•", ST_THINK: "· · ·", ST_SPEAK: "▿", ST_AWAY: "︶"}

_MOOD_TINT = {"happy": "#2e9e5b", "neutral": C.get("green", "#147c8b"), "sad": "#b9772b"}


def speak_duration_ms(text: str) -> int:
    """5–7 секунд в зависимости от длины ответа (по ТЗ)."""
    return max(SPEAK_MIN_MS,
               min(SPEAK_MAX_MS, SPEAK_MIN_MS + len(text or "") * SPEAK_MS_PER_CHAR))


#Аватар Вектора: спрайтовая машина состояний
class VectorAvatar(QWidget):
    """
    Маскот в полный рост: по состоянию (idle/thinking/speaking/away), настроению и
    намерению выбирает спрайт-эмоцию (морда+жест) из vector/emotes.py и рисует его
    во весь рост. Если папки emotes/ нет — компактная эмодзи-заглушка 🐯.
    set_mirrored(True) зеркалит спрайт (для панели справа).
    """

    def __init__(self, parent=None, height: int = AVATAR_H):
        super().__init__(parent)
        self._h = height
        #ширину виджета считаем от высоты по пропорции фигуры — чтобы маскот был
        #крупным и не «терялся», а KeepAspectRatio не оставлял пустых полей по бокам
        self.setFixedSize(int(height * AVATAR_AR), height)
        self._state = ST_AWAY
        self._mood = "neutral"
        self._intent = "help"
        self._mirrored = False
        self._emote = (emotes.DEFAULT_FACE, emotes.DEFAULT_GESTURE)

        #Фигура/заглушка занимает весь виджет (двигаем pos для лёгкого покачивания)
        self._face = QLabel(self)
        self._face.setAlignment(Qt.AlignCenter)
        self._face.setFixedSize(self.width(), height)
        self._face.move(0, 0)
        self._face.setStyleSheet("font-size:72px;background:transparent;")

        #Подпись-«рот» нужна только эмодзи-заглушке; при наличии арта скрывается
        self._mouth = QLabel(self)
        self._mouth.setAlignment(Qt.AlignCenter)
        self._mouth.setFixedWidth(self.width())
        self._mouth.move(0, height - 26)
        self._mouth.setStyleSheet(
            f"font-size:18px;color:{_MOOD_TINT['neutral']};font-weight:bold;"
            "background:transparent;")

        #Покачивание (живость для thinking/speaking)
        self._bob = QPropertyAnimation(self._face, b"pos")
        self._bob.setLoopCount(-1)
        self._bob.setEasingCurve(QEasingCurve.InOutSine)

        self.set_state(ST_AWAY)   #по умолчанию курсор не над чатом

    #публичные хуки
    def set_mirrored(self, mirrored: bool):
        """Зеркалит спрайт по горизонтали (панель перенесена вправо)."""
        if self._mirrored != mirrored:
            self._mirrored = mirrored
            self._render()

    def set_mood(self, mood: str):
        self._mood = mood if mood in _MOOD_TINT else "neutral"
        self._mouth.setStyleSheet(
            f"font-size:18px;color:{_MOOD_TINT[self._mood]};font-weight:bold;"
            "background:transparent;")

    def state(self) -> str:
        return self._state

    def set_state(self, state: str, intent: str = None):
        """Главный вход машины состояний. Спрайт-эмоцию подбирает emotes.pick()
        по состоянию + текущему настроению + намерению ответа."""
        if state not in (ST_IDLE, ST_THINK, ST_SPEAK, ST_AWAY):
            state = ST_IDLE
        self._state = state
        if intent is not None:
            self._intent = intent
        self._bob.stop()
        self._face.move(0, 0)

        self._emote = emotes.pick(state, self._mood, self._intent)
        if state == ST_THINK:
            self._start_bob(amp=4, dur=460)
        elif state == ST_SPEAK:
            self._start_bob(amp=6, dur=640)
        self._render()

    #внутреннее
    def _render(self):
        pm = emotes.get(self._emote[0], self._emote[1])
        if pm is not None and not pm.isNull():
            if self._mirrored:
                pm = pm.transformed(QTransform().scale(-1, 1),
                                    Qt.SmoothTransformation)
            self._face.setText("")
            self._face.setPixmap(pm.scaled(
                self.width(), self._h, Qt.KeepAspectRatio,
                Qt.SmoothTransformation))
            self._mouth.setText("")
        else:
            #эмодзи-заглушка (папки emotes/ нет)
            self._face.setPixmap(QPixmap())
            self._face.setText(_FALLBACK_FACE[self._state])
            self._mouth.setText(_FALLBACK_MOUTH[self._state])

    def _start_bob(self, amp=6, dur=600):
        base = QPoint(0, 0)
        self._bob.stop()
        self._bob.setDuration(dur)
        self._bob.setKeyValueAt(0.0, base)
        self._bob.setKeyValueAt(0.5, QPoint(base.x(), base.y() - amp))
        self._bob.setKeyValueAt(1.0, base)
        self._bob.start()


#Поток запроса к движку (не блокирует UI)
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


#Общая сессия чата: единый «мозг» разговора для нескольких панелей Вектора.
class VectorSession(QObject):
    """Одна история и один движок на ВСЕ панели Вектора (шторка сбоку + отдельная
    вкладка «ИИ Помощник»). Раньше у каждой панели был свой QTextEdit, поэтому
    переписки расходились. Теперь история живёт здесь, а панели лишь отображают её
    и анимируют своего маскота по сигналам сессии.

    Сигналы:
      • messageAdded(who, text) — в историю добавлена реплика (рисуют все панели);
      • thinkingStarted()       — отправлен вопрос (маскот → «думает»);
      • answered(text, mood)    — пришёл ответ (маскот → «говорит»);
      • askFailed(err)          — ответить не удалось.
    """
    messageAdded = Signal(str, str)
    thinkingStarted = Signal()
    answered = Signal(str, str, str)   # text, mood, intent
    askFailed = Signal(str)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.history = []          #[(who, text)] — общая переписка
        self._thread = None
        self.busy = False
        #Приветствие кладём в историю ОДИН раз — обе панели увидят его одинаково.
        try:
            self.history.append(("Вектор", engine.greeting()))
        except Exception:
            self.history.append(("Вектор", "Привет! Я Вектор."))

    def is_busy(self) -> bool:
        return self.busy or (self._thread is not None and self._thread.isRunning())

    def _add(self, who, text):
        self.history.append((who, text))
        self.messageAdded.emit(who, text)

    def ask(self, question: str):
        q = (question or "").strip()
        if not q or self.is_busy():
            return
        self._add("Вы", q)
        self.busy = True
        self.thinkingStarted.emit()
        self._thread = VectorAskThread(self.engine, q)
        self._thread.answered.connect(self._on_answer)
        self._thread.failed.connect(self._on_fail)
        self._thread.start()

    def _on_answer(self, text, mood, intent):
        self.busy = False
        self._add("Вектор", text)
        self.answered.emit(text, mood, intent)

    def _on_fail(self, err):
        self.busy = False
        self._add("Вектор", f"Ой, не получилось ответить: {err}. "
                            f"Попробуй ещё раз или нажми кнопку под чатом.")
        self.askFailed.emit(err)

    def push_proactive(self, text, mood="neutral", intent="help"):
        """Проактивная реплика Вектора (например, по карточке-инсайту)."""
        self._add("Вектор", text)
        self.answered.emit(text, mood, intent)


#Панель Вектора (аватар + чат + меню команд + тулбар)
class VectorPanel(QWidget):
    move_side = Signal()       #просьба перенести влево/вправо
    hide_me = Signal()         #просьба свернуть

    def __init__(self, session, parent=None, docked=True):
        super().__init__(parent)
        #session — общий «мозг» разговора (VectorSession). История и движок общие
        #для шторки и вкладки; панель лишь отображает историю и анимирует маскота.
        self.session = session
        self.engine = session.engine   #совместимость: дашборды правят engine.scope
        self.docked = docked
        self._hovered = False          #курсор сейчас над панелью?
        self._busy = False             #идёт обдумывание/речь?

        #Таймеры сценария маскота
        self._away_timer = QTimer(self)          #idle → away после ухода курсора
        self._away_timer.setSingleShot(True)
        self._away_timer.timeout.connect(self._go_away)
        self._speak_start_timer = QTimer(self)   #1 c thinking после ответа
        self._speak_start_timer.setSingleShot(True)
        self._speak_end_timer = QTimer(self)     #конец речи через 5–7 c
        self._speak_end_timer.setSingleShot(True)
        self._speak_end_timer.timeout.connect(self._finish_speaking)

        if docked:
            self.setFixedWidth(PANEL_WIDTH)
            self.setStyleSheet(
                f"background:{C['card']};border-right:1px solid {C['border']};")
        else:
            #режим «во всю вкладку»: ширину не фиксируем
            self.setStyleSheet(f"background:{C['card']};")
        self._build()

    #сборка интерфейса
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        #Тулбар: имя + перенос + свернуть
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
            #во вкладке кнопки переноса/сворачивания не нужны
            if not self.docked:
                b.hide()
        lay.addLayout(bar)

        #Аватар-маскот: в шторке компактнее, во вкладке «ИИ Помощник» крупнее
        self.avatar = VectorAvatar(height=(AVATAR_H if self.docked else AVATAR_H_TAB))
        lay.addWidget(self.avatar, 0, Qt.AlignHCenter)

        #Чат
        self.chat = QTextEdit(); self.chat.setReadOnly(True)
        self.chat.setStyleSheet(
            f"background:{C['card2']};border:1px solid {C['border']};border-radius:10px;"
            f"padding:10px;font-size:12.5px;color:{C['text']};")
        lay.addWidget(self.chat, 1)

        #МЕНЮ БЫСТРЫХ КОМАНД: ответ мгновенно и без ИИ ────
        lay.addLayout(self._build_quick_commands())

        #Ввод
        row = QHBoxLayout(); row.setSpacing(6)
        self.inp = QLineEdit(); self.inp.setPlaceholderText("Спросить Вектора…")
        self.inp.setStyleSheet(
            f"background:{C['card']};border:1px solid {C['border']};border-radius:8px;"
            f"padding:7px;color:{C['text']};font-size:13px;")
        self.inp.returnPressed.connect(self._send)
        import icons
        from PySide6.QtCore import QSize as _QSize
        send = QPushButton(); send.setFixedSize(44, 38)
        send.setIcon(icons.icon("send", "#FFFFFF", 18)); send.setIconSize(_QSize(18, 18))
        send.setStyleSheet(
            f"QPushButton{{background:{C['green']};border:none;border-radius:8px;}}"
            f"QPushButton:hover{{background:{C['green2']};}}")
        send.clicked.connect(self._send)
        self.send_btn = send
        row.addWidget(self.inp); row.addWidget(send)
        lay.addLayout(row)

        #Проигрываем уже накопленную ОБЩУЮ историю (включая приветствие) — чтобы
        #только что открытая панель показала всю переписку, а не пустой чат.
        for who, text in self.session.history:
            self._append(who, text)

        #Подписываемся на сигналы общей сессии: текст в чат пишем ТОЛЬКО отсюда
        #(не локально в _send) — поэтому обе панели всегда синхронны и без дублей.
        self.session.messageAdded.connect(self._append)
        self.session.thinkingStarted.connect(self._on_thinking)
        self.session.answered.connect(self._on_session_answer)
        self.session.askFailed.connect(self._on_session_fail)

    def _build_quick_commands(self):
        """Кнопки-команды из пула. Нажатие = готовый вопрос = ответ без LLM."""
        from PySide6.QtWidgets import QGridLayout
        try:
            from .faq import QUICK_COMMANDS
            role = getattr(self.engine.scope, "role", "student")
            cmds = QUICK_COMMANDS.get(role, QUICK_COMMANDS["student"])
        except Exception:
            cmds = []
        import icons
        from PySide6.QtCore import QSize as _QSize
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (icon_name, label, question) in enumerate(cmds):
            b = QPushButton("  " + label)
            b.setIcon(icons.icon(icon_name, C["text3"], 15)); b.setIconSize(_QSize(15, 15))
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{C['card2']};border:1px solid {C['border']};"
                f"border-radius:8px;padding:6px 10px;color:{C['text3']};font-size:12px;"
                f"text-align:left;}}"
                f"QPushButton:hover{{color:{C['green']};border-color:{C['green']};}}")
            b.clicked.connect(lambda _=False, q=question: self.ask_command(q))
            grid.addWidget(b, i // 2, i % 2)
        return grid

    #чат
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
        if self.session.is_busy():
            return
        self.inp.clear()
        self.session.ask(question)

    def _send(self):
        q = self.inp.text().strip()
        if not q or self.session.is_busy():
            return
        self.inp.clear()
        #Дальше всё ведёт общая сессия: добавит реплику в историю (messageAdded →
        #_append во всех панелях), поднимет thinking/answered. Так шторка и вкладка
        #остаются в одной переписке.
        self.session.ask(q)

    def _on_thinking(self):
        """Сессия отправила вопрос → маскот «думает», ввод блокируем."""
        self.send_btn.setEnabled(False)
        self._busy = True
        self._away_timer.stop()
        self._speak_end_timer.stop()
        self.avatar.set_state(ST_THINK)

    def _on_session_answer(self, text, mood, intent="help"):
        """Пришёл ответ (текст уже добавлен в чат через messageAdded)."""
        self.send_btn.setEnabled(True)
        self.avatar.set_mood(mood)
        #маскот: ответ отправлен, но ещё 1 c «дообдумывает» (по ТЗ), затем speaking
        #на 5–7 c по длине ответа (эмоция = морда/жест по mood+intent), затем idle.
        dur = speak_duration_ms(text)
        #отвязываем прошлый слот без шумного RuntimeWarning
        prev = getattr(self, "_speak_slot", None)
        if prev is not None:
            try:
                self._speak_start_timer.timeout.disconnect(prev)
            except (RuntimeError, TypeError):
                pass
        self._speak_slot = lambda: self._begin_speaking(dur, intent)
        self._speak_start_timer.timeout.connect(self._speak_slot)
        self._speak_start_timer.start(THINK_HOLD_AFTER_ANSWER_MS)

    def _begin_speaking(self, dur_ms: int, intent: str = "help"):
        self.avatar.set_state(ST_SPEAK, intent=intent)
        self._speak_end_timer.start(dur_ms)

    def _finish_speaking(self):
        """Речь окончена → 1_idle, будто договорил; если курсор не у чата —
        через паузу уйдёт в 4_away."""
        self._busy = False
        self.avatar.set_state(ST_IDLE)
        if not self._hovered:
            self._away_timer.start(AWAY_DELAY_MS)

    def _on_session_fail(self, err):
        """Сессия не смогла ответить (текст ошибки уже добавлен в чат)."""
        self.send_btn.setEnabled(True)
        self._busy = False
        self.avatar.set_state(ST_IDLE)
        if not self._hovered:
            self._away_timer.start(AWAY_DELAY_MS)

    def push_proactive(self, text, mood="neutral", intent="help"):
        """Внешняя проактивная реплика — делегируем общей сессии (увидят все панели)."""
        self.session.push_proactive(text, mood, intent)

    #hover-логика маскота (1_idle ↔ 4_away)
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

    #зеркало при переносе панели
    def set_side(self, side: str):
        """Вызывается хостом: 'left' / 'right'. Справа — спрайт зеркалится."""
        self.avatar.set_mirrored(side == "right")
        if self.docked:
            border = "border-left" if side == "right" else "border-right"
            self.setStyleSheet(
                f"background:{C['card']};{border}:1px solid {C['border']};")


#Хост: вставляет панель в QHBoxLayout дашборда и рулит сторонами
class VectorHost:
    """
    Управляет размещением Вектора в горизонтальном layout дашборда (тот самый
    `body` из TeacherDashboard/StudentDashboard/AdminDashboard).

    Использование в дашборде:
        from vector.widget import VectorSession, VectorPanel, VectorHost
        session = VectorSession(engine)              # общая история чата
        self.vector_host = VectorHost(body, VectorPanel(session, docked=True))
        self.vector_host.mount(side="left")
    """
    def __init__(self, body_layout, panel: VectorPanel):
        self.body = body_layout
        self.panel = panel
        self.side = "left"
        self._collapsed = False        #свёрнут до полоски 🐯?
        self._suspended = None         #состояние, спрятанное на время вкладки «ИИ»
        #Тонкая полоска для разворачивания, когда свёрнут
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
        self._collapsed = False
        self.panel.set_side(side)

    def toggle_side(self):
        self.body.removeWidget(self.panel)
        self.body.removeWidget(self.restore)
        self.side = "right" if self.side == "left" else "left"
        self._insert(self.panel, self.side)
        self._insert(self.restore, self.side)
        self.restore.setVisible(not self.panel.isVisible())
        #зеркалим маскота, когда панель справа (по ТЗ)
        self.panel.set_side(self.side)

    def hide_panel(self):
        #картинки маскота скрываются вместе со всей панелью (по ТЗ)
        self.panel.hide()
        self.restore.show()
        self._collapsed = True

    def show_panel(self):
        self.restore.hide()
        self.panel.show()
        self._collapsed = False

    #Пауза/возврат шторки на время вкладки «ИИ Помощник».
    #Идея: вкладка ИИ — это отдельная панель Вектора во всю ширину, поэтому шторка
    #сбоку на ней лишняя. Прячем её целиком (и панель, и полоску 🐯), запомнив
    #прежнее состояние, а при уходе с вкладки возвращаем ровно как было.
    def suspend(self):
        """Спрятать шторку (вошли во вкладку «ИИ Помощник»). Идемпотентно."""
        if self._suspended is not None:
            return
        #запоминаем: была ли свёрнута и с какой стороны
        self._suspended = {"collapsed": self._collapsed, "side": self.side}
        self.panel.hide()
        self.restore.hide()

    def resume(self):
        """Вернуть шторку в прежнее состояние (ушли с вкладки «ИИ»). Идемпотентно."""
        if self._suspended is None:
            return
        was = self._suspended
        self._suspended = None
        self._collapsed = was["collapsed"]
        if self._collapsed:
            self.panel.hide()
            self.restore.show()
        else:
            self.restore.hide()
            self.panel.show()
