"""
widget.py — Компаньон «Вектор» (PySide6): панель чата + маскот в полный рост.

МАСКОТ — машина состояний, рисующая арт Арины из папки `emotions/речь/`
(см. vector/speech.py): 4 полноростовых кадра под состояние ЧАТА —
говорит / думает / ждёт / молчит. Это простой слой «что делает помощник прямо
сейчас». Эмоции по успеваемости (морда+жест из emotes/) — отдельный слой и живут
в советах на дашборде студента (см. vector/mascot.py), здесь не используются.

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

Если папки `emotions/речь/` нет — работает компактная эмодзи-заглушка 🐯, ничего не падает.
"""

from . import speech
import log

from PySide6.QtCore import (
    Qt, QObject, QThread, Signal, QPropertyAnimation, QPoint, QTimer, QEasingCurve, QSize
)
from PySide6.QtGui import QPixmap, QTransform, QMovie
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QLineEdit, QFrame, QToolButton
)

#Цвета/виджеты проекта (фолбэк, если импорт не удался при изоляции)
try:
    from styles import C
except Exception:
    C = {"card": "#fff", "card2": "#f3f6f7", "border": "#dfe6e8",
         "text": "#0d2b30", "text3": "#3a565b", "green": "#147c8b",
         "blue": "#1f6f8b", "bg": "#eef5f6"}

PANEL_WIDTH = 400                     #шире прежнего: маскот крупнее, чат лежит поверх него

#настройки маскота (арт из vector/emotes.py)
AVATAR_H = 460                        #высота фигуры в боковой шторке, px (крупный, чат поверх)
AVATAR_H_TAB = 520                    #высота во вкладке «ИИ Помощник» (там места больше)
AVATAR_AR = 0.78                      #ширина виджета = высота × этот коэф. (под фигуру)

THINK_HOLD_AFTER_ANSWER_MS = 1000     #1 c «дообдумывает» после ответа (по ТЗ)
SPEAK_MIN_MS = 5000                   #речь минимум 5 c
SPEAK_MAX_MS = 7000                   #речь максимум 7 c
SPEAK_MS_PER_CHAR = 25                #+25 мс за символ ответа (между 5 и 7 c)
AWAY_DELAY_MS = 2000                  #«ещё пару секунд» idle после ухода курсора
GREET_MS = 1400                       #сколько машет «приветствием» перед речью (на hello)

#Состояния машины маскота
ST_IDLE, ST_THINK, ST_SPEAK, ST_AWAY = "idle", "thinking", "speaking", "away"
ST_GREET = "greeting"                 #машет рукой (на приветствие) — анимир. WebP

#Заглушка, пока папки emotes/ нет (компактные эмодзи под состояние)
_FALLBACK_FACE = {ST_IDLE: "🐯", ST_THINK: "🤔", ST_SPEAK: "🗣️", ST_AWAY: "😴",
                  ST_GREET: "👋"}
_FALLBACK_MOUTH = {ST_IDLE: "•‿•", ST_THINK: "· · ·", ST_SPEAK: "▿", ST_AWAY: "︶",
                   ST_GREET: "•‿•"}

_MOOD_TINT = {"happy": "#2e9e5b", "neutral": C.get("green", "#147c8b"), "sad": "#b9772b"}


def speak_duration_ms(text: str) -> int:
    """5–7 секунд в зависимости от длины ответа (по ТЗ)."""
    return max(SPEAK_MIN_MS,
               min(SPEAK_MAX_MS, SPEAK_MIN_MS + len(text or "") * SPEAK_MS_PER_CHAR))


def _rgba(hex_color: str, alpha: float) -> str:
    """hex (#rrggbb) → 'rgba(r,g,b,A)' для QSS, где A — целое 0–255 (Qt так разбирает
    надёжнее дробной доли). Нужна, чтобы чат лёг ПОЛУПРОЗРАЧНЫМ поверх картинки Вектора."""
    a = max(0, min(255, int(round(alpha * 255))))
    try:
        h = (hex_color or "#ffffff").lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{a})"
    except Exception:
        return f"rgba(255,255,255,{a})"


class _AvatarChatOverlay(QWidget):
    """Контейнер, где маскот лежит ФОНОМ, а история чата — полупрозрачным слоем поверх.

    Раньше аватар и чат стояли друг под другом; по просьбе делаем «чат поверх Вектора»:
    фигуру увеличиваем, а переписку кладём сверху с полупрозрачной подложкой — Вектор
    просвечивает по краям и между строк, но текст остаётся читаемым. Геометрию детей
    раскладываем вручную (аватар фиксированного размера — центрируем сверху; чат тянем
    на всю площадь)."""

    #Доля высоты ФИГУРЫ, на которой начинается чат сверху: 0 — голова, 1 — ноги.
    #~0.42 = примерно уровень туловища: голова и плечи Вектора открыты, чат лежит ниже.
    CHAT_TOP_FRACTION = 0.42

    def __init__(self, avatar: "VectorAvatar", chat: QWidget, parent=None):
        super().__init__(parent)
        self.avatar = avatar
        self.chat = chat
        self.avatar.setParent(self)
        self.chat.setParent(self)
        self.avatar.lower()
        self.chat.raise_()
        #чтобы при узком окне фигура не «съедалась» — даём контейнеру разумную высоту
        self.setMinimumHeight(220)

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        aw, ah = self.avatar.width(), self.avatar.height()
        #маскот СВЕРХУ, по центру по горизонтали — голова и плечи всегда видны.
        self.avatar.move(max(0, (w - aw) // 2), 0)
        #чат СНИЗУ и полупрозрачный: его верхний край — примерно на уровне туловища
        #Вектора, поэтому переписка лежит на нижней части фигуры, не закрывая лицо.
        chat_top = int(ah * self.CHAT_TOP_FRACTION)
        self.chat.setGeometry(0, chat_top, w, max(150, h - chat_top))
        super().resizeEvent(event)


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
        self._movie = None            #QMovie анимированного WebP (если арт-анимации есть)
        self._movie_state = None      #для какого состояния сейчас крутится _movie

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
        """Главный вход машины состояний. Кадр берём из vector/speech.py по
        состоянию чата (говорит/думает/ждёт/молчит). intent/mood на кадр речи не
        влияют — это отдельный, более простой слой «что делает помощник в чате»
        (эмоции по успеваемости живут отдельно, в советах на дашборде)."""
        if state not in (ST_IDLE, ST_THINK, ST_SPEAK, ST_AWAY, ST_GREET):
            state = ST_IDLE
        self._state = state
        if intent is not None:
            self._intent = intent
        self._bob.stop()
        self._face.move(0, 0)

        #Покачивание-имитация ТОЛЬКО для статичного арта и только в «речи». Если есть
        #анимированный WebP — персонаж и так живёт (рот/уши/хвост), фейковое покачивание
        #не нужно (иначе двойное движение). При «думает» стоит спокойно в любом случае.
        if state == ST_SPEAK and not speech.anim_path(state):
            self._start_bob(amp=6, dur=640)
        self._render()

    #внутреннее
    def _render(self):
        #ПРИОРИТЕТ 1 — анимированный WebP состояния (живой маскот, общий формат с вебом).
        apath = speech.anim_path(self._state)
        if apath:
            self._play_anim(apath)
            self._mouth.setText("")
            return
        #ПРИОРИТЕТ 2 — статичный PNG-кадр состояния (старый арт emotions/речь).
        self._stop_anim()
        pm = speech.get(self._state)
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
            #ПРИОРИТЕТ 3 — эмодзи-заглушка (арта нет вовсе)
            self._face.setPixmap(QPixmap())
            self._face.setText(_FALLBACK_FACE[self._state])
            self._mouth.setText(_FALLBACK_MOUTH[self._state])

    def _play_anim(self, path: str):
        """Проигрывает анимированный WebP состояния в QLabel через QMovie. Кадр вписан
        по высоте виджета с сохранением пропорций. Если состояние не сменилось — не
        перезапускаем (чтобы idle не «дёргался» при повторных set_state)."""
        if self._movie is not None and self._movie_state == self._state:
            return
        self._stop_anim()
        mv = QMovie(path)
        if not mv.isValid():
            self._movie = None
            return
        #Масштаб по высоте виджета, ширина — по пропорции первого кадра.
        mv.jumpToFrame(0)
        sz = mv.currentImage().size()
        if sz.height() > 0:
            w = max(1, round(sz.width() * self._h / sz.height()))
            mv.setScaledSize(QSize(min(w, self.width()), self._h))
        self._face.setText("")
        self._face.setPixmap(QPixmap())
        self._face.setMovie(mv)
        mv.start()
        self._movie = mv
        self._movie_state = self._state

    def _stop_anim(self):
        """Останавливает и снимает текущий QMovie (перед статикой/сменой анимации)."""
        if self._movie is not None:
            self._movie.stop()
            self._face.setMovie(None)
            self._movie = None
            self._movie_state = None

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
        #Новый вопрос перебивает предыдущую озвучку сразу (barge-in), не дожидаясь ответа:
        #Вектор не договаривает старое, пока пользователь уже спросил другое. Отменяет и
        #ещё не проигранный синтез (по поколению внутри tts). Одна сессия на все панели —
        #поэтому здесь, а не в панели (иначе синтез запускался бы по разу на каждую панель).
        try:
            from . import tts
            tts.stop()
        except Exception:
            pass
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
        #Озвучка ответа вслух (если включена). Здесь, в сессии, — ровно один раз на ответ
        #(панелей несколько, а озвучивать нужно однократно). Изолировано: сбой не ломает чат.
        try:
            from . import tts
            tts.speak(text)
        except Exception:
            pass

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

        #ОВЕРЛЕЙ: маскот фоном, история чата — полупрозрачным слоем ПОВЕРХ него.
        self.avatar = VectorAvatar(height=(AVATAR_H if self.docked else AVATAR_H_TAB))
        self.chat = QTextEdit(); self.chat.setReadOnly(True)
        #Подложка чата ПОЛУПРОЗРАЧНАЯ — нижняя часть фигуры Вектора мягко просвечивает
        #сквозь переписку (чат лежит на туловище/ногах, лицо сверху открыто).
        self.chat.setStyleSheet(
            f"QTextEdit{{background:{_rgba(C['card'], 0.72)};"
            f"border:1px solid {_rgba(C['border'], 0.6)};border-radius:12px;"
            f"padding:10px;font-size:12.5px;color:{C['text']};}}")
        self.chat.viewport().setStyleSheet("background:transparent;")  #чтобы rgba-подложка просвечивала
        self._overlay = _AvatarChatOverlay(self.avatar, self.chat)
        lay.addWidget(self._overlay, 1)

        #Ввод + квадратная кнопка команд (всплывающее меню, как в телеграме)
        row = QHBoxLayout(); row.setSpacing(6)
        import icons
        from PySide6.QtCore import QSize as _QSize
        self._cmd_btn = QToolButton()
        self._cmd_btn.setFixedSize(38, 38)
        self._cmd_btn.setIcon(icons.icon("layers", C["text3"], 18)); self._cmd_btn.setIconSize(_QSize(18, 18))
        self._cmd_btn.setCursor(Qt.PointingHandCursor)
        self._cmd_btn.setToolTip("Быстрые команды")
        self._cmd_btn.setStyleSheet(
            f"QToolButton{{background:{C['card2']};border:1px solid {C['border']};"
            f"border-radius:8px;}}"
            f"QToolButton:hover{{border-color:{C['green']};}}")
        #клик тоже открывает/закрывает (для тач-экранов), наведение — основной сценарий
        self._cmd_btn.clicked.connect(self._toggle_cmd_menu)

        self.inp = QLineEdit(); self.inp.setPlaceholderText("Спросить Вектора…")
        self.inp.setStyleSheet(
            f"background:{C['card']};border:1px solid {C['border']};border-radius:8px;"
            f"padding:7px;color:{C['text']};font-size:13px;")
        self.inp.returnPressed.connect(self._send)
        send = QPushButton(); send.setFixedSize(44, 38)
        send.setIcon(icons.icon("send", "#FFFFFF", 18)); send.setIconSize(_QSize(18, 18))
        send.setStyleSheet(
            f"QPushButton{{background:{C['green']};border:none;border-radius:8px;}}"
            f"QPushButton:hover{{background:{C['green2']};}}")
        send.clicked.connect(self._send)
        self.send_btn = send

        #Кнопка голосового ввода (микрофон). Показываем, только если админ ВКЛЮЧИЛ STT
        #(config.stt_enabled — синхронизируется на все аккаунты) И на этой машине стоят
        #пакеты распознавания (faster-whisper/sounddevice). Иначе мягко отсутствует.
        self.mic_btn = None
        self.help_btn = None
        try:
            from .voice_ui import MicButton, mic_available
            if self._stt_enabled() and mic_available():
                self.mic_btn = MicButton(get_context=self._voice_context)
                self.mic_btn.transcribed.connect(self._on_voice_text)
                self.mic_btn.failed.connect(self._on_voice_failed)
                #Маленькая «?» рядом с микрофоном: подсказки и примеры команд по роли.
                self.help_btn = QToolButton()
                self.help_btn.setText("?")
                self.help_btn.setCursor(Qt.PointingHandCursor)
                self.help_btn.setFixedSize(26, 38)
                self.help_btn.setToolTip("Что можно сказать голосом")
                self.help_btn.setStyleSheet(
                    f"QToolButton{{background:{C['card2']};border:1px solid {C['border']};"
                    f"border-radius:8px;color:{C['text2']};font-weight:bold;font-size:14px;}}"
                    f"QToolButton:hover{{border-color:{C['green']};color:{C['green']};}}")
                self.help_btn.clicked.connect(self._show_voice_help)
        except Exception as e:
            log.get("widget").warning(f"[vector] голосовой ввод недоступен: {e}")

        row.addWidget(self._cmd_btn); row.addWidget(self.inp)
        if self.mic_btn is not None:
            row.addWidget(self.mic_btn)
        if self.help_btn is not None:
            row.addWidget(self.help_btn)
        row.addWidget(send)
        lay.addLayout(row)

        #Всплывающее меню команд (скрыто; появляется при наведении на кнопку команд).
        self._over_cmd_btn = False
        self._over_cmd_menu = False
        self._cmd_hide_timer = QTimer(self); self._cmd_hide_timer.setSingleShot(True)
        self._cmd_hide_timer.timeout.connect(self._maybe_hide_cmd_menu)
        self._cmd_menu = self._build_command_menu()
        self._cmd_btn.installEventFilter(self)
        self._cmd_menu.installEventFilter(self)

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

    #Всплывающее меню быстрых команд (телеграм-стиль: висит над кнопкой команд)
    def _build_command_menu(self) -> QFrame:
        """Меню-команды из пула в всплывающей плашке. Нажатие = готовый вопрос без LLM.
        Появляется при наведении на квадратную кнопку команд, прячется при уходе курсора
        (если не навели на само меню) — поведение управляется eventFilter + таймером."""
        try:
            from .faq import QUICK_COMMANDS
            role = getattr(self.engine.scope, "role", "student")
            cmds = QUICK_COMMANDS.get(role, QUICK_COMMANDS["student"])
        except Exception:
            cmds = []
        import icons
        from PySide6.QtCore import QSize as _QSize
        frame = QFrame(self)
        frame.setObjectName("cmdMenu")
        frame.setStyleSheet(
            f"QFrame#cmdMenu{{background:{C['card']};border:1px solid {C['border']};"
            f"border-radius:12px;}}")
        v = QVBoxLayout(frame); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(4)
        for icon_name, label, question in cmds:
            b = QPushButton("  " + label)
            b.setIcon(icons.icon(icon_name, C["text3"], 15)); b.setIconSize(_QSize(15, 15))
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{background:{C['card2']};border:1px solid {C['border']};"
                f"border-radius:8px;padding:7px 12px;color:{C['text3']};font-size:12px;"
                f"text-align:left;}}"
                f"QPushButton:hover{{color:{C['green']};border-color:{C['green']};}}")
            b.clicked.connect(lambda _=False, q=question: self._run_command(q))
            v.addWidget(b)
        frame.hide()
        return frame

    def _run_command(self, question: str):
        """Клик по команде в меню: отправляем и сразу прячем плашку."""
        self._cmd_menu.hide()
        self.ask_command(question)

    def _show_cmd_menu(self):
        m = self._cmd_menu
        if m is None:
            return
        self._cmd_hide_timer.stop()
        m.adjustSize()
        #позиционируем плашку НАД кнопкой команд (если сверху мало места — под ней)
        btn_tl = self._cmd_btn.mapTo(self, QPoint(0, 0))
        x = min(btn_tl.x(), max(4, self.width() - m.width() - 4))
        y = btn_tl.y() - m.height() - 6
        if y < 4:
            y = btn_tl.y() + self._cmd_btn.height() + 6
        m.move(max(4, x), y)
        m.show(); m.raise_()

    def _maybe_hide_cmd_menu(self):
        if not (self._over_cmd_btn or self._over_cmd_menu):
            self._cmd_menu.hide()

    def _toggle_cmd_menu(self):
        if self._cmd_menu.isVisible():
            self._cmd_menu.hide()
        else:
            self._show_cmd_menu()

    def eventFilter(self, obj, event):
        """Наведение на кнопку команд или на само меню держит плашку открытой; уход
        курсора с обоих — прячет её с небольшой задержкой (чтобы можно было перевести
        мышь с кнопки на меню, как в телеграме)."""
        from PySide6.QtCore import QEvent
        if obj is self._cmd_btn:
            if event.type() == QEvent.Enter:
                self._over_cmd_btn = True; self._show_cmd_menu()
            elif event.type() == QEvent.Leave:
                self._over_cmd_btn = False; self._cmd_hide_timer.start(240)
        elif obj is self._cmd_menu:
            if event.type() == QEvent.Enter:
                self._over_cmd_menu = True; self._cmd_hide_timer.stop()
            elif event.type() == QEvent.Leave:
                self._over_cmd_menu = False; self._cmd_hide_timer.start(240)
        return super().eventFilter(obj, event)

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

    #── Голосовой ввод ───────────────────────────────────────────────────────────────
    def _stt_enabled(self) -> bool:
        """Включён ли голосовой ввод админом (config.stt_enabled). По умолчанию — выкл."""
        try:
            from data_store import get_store
            return bool((get_store()._config() or {}).get("stt_enabled", False))
        except Exception:
            return False

    def _show_voice_help(self):
        """Попап с примерами голосовых команд для текущей роли."""
        try:
            from .voice_ui import show_voice_help
            role = getattr(self.engine.scope, "role", "student")
            show_voice_help(role, self)
        except Exception as e:
            log.get("widget").warning(f"[vector] подсказка недоступна: {e}")

    def _voice_context(self):
        """Подсказка для Whisper: реальные ФИО студентов текущей группы + ключевые слова.
        Повышает точность распознавания фамилий и терминов (важно юридически)."""
        try:
            from .voice_command import stt_context
            from data_store import get_store
            grp = getattr(self.engine.scope, "group", "") or ""
            roster = []
            if grp:
                for s in (get_store().get_students() or []):
                    if s.get("group", "") == grp:
                        roster.append((s.get("surname", ""), s.get("name", "")))
            return stt_context(roster)
        except Exception:
            return ""

    def _on_voice_text(self, text: str):
        """Распознанный текст → ролевой роутинг (вопрос в Q&A / команда препода → запись)."""
        if self.session.is_busy():
            return
        try:
            from .voice_ui import route_voice_text
            route_voice_text(self, self.session, self.engine.scope, text,
                             on_info=self._voice_info)
        except Exception as e:
            self._voice_info(f"🎙 Не удалось обработать голосовую команду: {e}")

    def _on_voice_failed(self, msg: str):
        self._voice_info("🎙 " + msg)

    def _voice_info(self, msg: str):
        """Служебное сообщение Вектора в чат (ошибки распознавания, итог записи)."""
        try:
            self.session.push_proactive(msg, mood="neutral", intent="help")
        except Exception:
            self._append("Вектор", msg)

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
        #На ПРИВЕТСТВИЕ (intent hello) Вектор сначала МАШЕТ рукой (greeting ~1.4 c), потом
        #переходит к речи. На остальное — сразу речь. (intent="help" при повторе — чтобы
        #не зациклить приветствие.)
        if intent == "hello" and speech.anim_path("greeting"):
            self.avatar.set_state(ST_GREET)
            QTimer.singleShot(GREET_MS, lambda: self._begin_speaking(dur_ms, "help"))
            return
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
