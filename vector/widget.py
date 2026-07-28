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
    speaking  — «говорит»: пока играет озвучка (длину ведёт звук); без озвучки — 5–7 c по длине ответа → эмоция по ответу
    away      — курсор НЕ над чатом (работа с журналом) → расслаблен, руки в карманах

Логика переключений (ровно по ТЗ):
    • пока вопрос не написан и курсор над чатом         → idle
    • вопрос отправлен                                  → thinking
    • ответ пришёл: ещё 1 секунду держим                → thinking
    • затем «речь»: пока идёт озвучка (по звуку), без неё — 5–7 c по длине → speaking (эмоция по mood/intent)
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
from PySide6.QtGui import QPixmap, QTransform, QMovie, QTextCharFormat, QColor, QTextCursor
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
TYPE_MS_PER_CHAR_MIN = 12             #нижняя граница интервала печати (иначе таймер не успевает)

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
    #Поля вокруг стеклянной карточки чата и её предел по ширине — 1:1 с вебом
    #(VectorPage.vue: inset-x-8 bottom-4, max-w-3xl). Без предела на широком мониторе
    #переписка растягивалась во всю ширину и читалась строками по полтора метра.
    CHAT_MARGIN_X = 32
    CHAT_MARGIN_BOTTOM = 16
    CHAT_MAX_WIDTH = 768

    def __init__(self, avatar: "VectorAvatar", chat: QWidget, parent=None, grow: bool = False):
        super().__init__(parent)
        self.avatar = avatar
        self.chat = chat
        #grow=True — маскот тянется под высоту контейнера (вкладка «ИИ Помощник», как на
        #сайте). В боковой шторке фигура остаётся фиксированной: там ширина панели задана
        #жёстко, и растягивать нечего.
        self.grow = grow
        self.avatar.setParent(self)
        self.chat.setParent(self)
        self.avatar.lower()
        self.chat.raise_()
        #чтобы при узком окне фигура не «съедалась» — даём контейнеру разумную высоту
        self.setMinimumHeight(220)

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        if self.grow:
            #Фигура занимает всю высоту области, но не шире самой области — иначе на
            #низком и широком окне маскот вылезал бы за края по бокам.
            target = min(h, int(w / AVATAR_AR)) if w else h
            self.avatar.set_height(max(160, target))
        aw, ah = self.avatar.width(), self.avatar.height()
        #маскот СВЕРХУ, по центру по горизонтали — голова и плечи всегда видны.
        self.avatar.move(max(0, (w - aw) // 2), 0)
        #чат СНИЗУ и полупрозрачный: его верхний край — примерно на уровне туловища
        #Вектора, поэтому переписка лежит на нижней части фигуры, не закрывая лицо.
        chat_top = int(ah * self.CHAT_TOP_FRACTION)
        if self.grow:
            cw = min(self.CHAT_MAX_WIDTH, max(240, w - 2 * self.CHAT_MARGIN_X))
            cx = (w - cw) // 2
            ch = max(120, h - chat_top - self.CHAT_MARGIN_BOTTOM)
            self.chat.setGeometry(cx, chat_top, cw, ch)
        else:
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
    def set_height(self, height: int):
        """Перезадать высоту фигуры (ширина считается по пропорции).

        Нужно вкладке «ИИ Помощник»: там маскот должен РАСТИ вместе с окном, как на
        сайте, а не сидеть в жёстких AVATAR_H_TAB пикселей — на широком мониторе
        фиксированная фигура терялась в пустоте. Перерисовываем только при реальном
        изменении: resizeEvent прилетает пачками, и лишний _render дёргал бы QMovie."""
        height = max(120, int(height))
        if height == self._h:
            return
        self._h = height
        width = int(height * AVATAR_AR)
        self.setFixedSize(width, height)
        self._face.setFixedSize(width, height)
        self._face.move(0, 0)
        self._mouth.setFixedWidth(width)
        self._mouth.move(0, height - 26)
        self._render()

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
      • askFailed(err)          — ответить не удалось;
      • speechStarted()         — РЕАЛЬНО пошёл звук озвучки (маскот держит «речь»);
      • speechEnded()           — звук озвучки кончился (маскот → покой).
    """
    messageAdded = Signal(str, str)
    thinkingStarted = Signal()
    answered = Signal(str, str, str)   # text, mood, intent
    askFailed = Signal(str)
    #Границы фактического воспроизведения озвучки — чтобы анимация речи длилась РОВНО
    #столько, сколько играет звук (а не по эвристике длины текста; на длинном ответе она
    #обрывалась раньше речи). Эмитятся из фонового потока tts — Qt доставит их в GUI-поток.
    speechStarted = Signal()
    speechEnded = Signal()

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

    def register_panel(self, panel) -> None:
        """Панель сообщает сессии о себе — нужно, чтобы понять, ГДЕ Вектор сейчас виден
        (вкладка «ИИ Помощник» или боковая шторка) и какой выключатель звука применять."""
        if not hasattr(self, "_panels"):
            self._panels = []
        self._panels.append(panel)

    def _voice_on(self) -> bool:
        """Озвучивать ли ответ прямо сейчас.

        У шторки СВОЙ выключатель звука (tts.dock_enabled): выключенный в ней звук не
        должен молчать во вкладке «ИИ Помощник» — туда за голосом и приходят. Смотрим,
        видна ли сейчас полноэкранная панель (docked=False): если да — решает общий режим
        озвучки, иначе — выключатель шторки."""
        from . import tts
        if not tts.is_enabled():
            return False
        for p in list(getattr(self, "_panels", [])):
            try:
                if not p.docked and p.isVisible():
                    return True
            except RuntimeError:
                continue          #панель уже удалена на стороне C++ — просто пропускаем
        return tts.dock_enabled()

    def _on_answer(self, text, mood, intent):
        self.busy = False
        self._add("Вектор", text)
        self.answered.emit(text, mood, intent)
        #Озвучка ответа вслух (если включена). Здесь, в сессии, — ровно один раз на ответ
        #(панелей несколько, а озвучивать нужно однократно). Изолировано: сбой не ломает чат.
        try:
            from . import tts
            if not self._voice_on():
                return
            #on_start/on_end — границы фактического звука. Прокидываем их наружу сигналами,
            #чтобы каждая панель держала анимацию речи ровно пока играет озвучка. Эмит из
            #фонового потока безопасен: Qt поставит вызов в очередь GUI-потока.
            tts.speak(text, on_start=self.speechStarted.emit, on_end=self.speechEnded.emit)
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
        self._speak_end_timer = QTimer(self)     #конец речи по ЭВРИСТИКЕ (когда озвучки нет)
        self._speak_end_timer.setSingleShot(True)
        self._speak_end_timer.timeout.connect(self._finish_speaking)
        #Пока идёт реальная озвучка — анимацию речи ведёт ЗВУК (speechStarted/Ended), а не
        #эвристический таймер. Флаг гасит `_speak_end_timer`, чтобы он не обрывал длинный ответ.
        self._tts_driving = False
        self._last_intent = "help"

        #Печать ответа по символам (§12, «бубнёж»-темп) — ВЕЗДЕ, включая боковую шторку
        #(docked=True), как на вебе (VectorDock и VectorPage теперь оба печатают). Раньше
        #в шторке печать была отключена («мелькает поверх журнала»), но решение пересмотрено.
        self._typing_timer = QTimer(self)
        self._typing_timer.timeout.connect(self._advance_typing)
        self._typing_full = ""
        self._typing_pos = 0
        self._typing_fmt = None

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
        #Звук ШТОРКИ — свой выключатель (как на вебе, VectorDock.vue): шторка висит поверх
        #журнала, где голос чаще мешает, а на вкладку «ИИ Помощник» за ним и приходят.
        #Общий тумблер озвучки живёт в настройках и этой кнопкой НЕ трогается.
        self._snd_btn = QToolButton()
        self._snd_btn.setToolTip("Озвучка в этой панели")
        self._snd_btn.clicked.connect(self._toggle_dock_sound)
        self._sync_sound_btn()
        side_b = QToolButton(); side_b.setText("⇄"); side_b.setToolTip("Перенести в другую сторону")
        side_b.clicked.connect(self.move_side.emit)
        hide_b = QToolButton(); hide_b.setText("—"); hide_b.setToolTip("Свернуть")
        hide_b.clicked.connect(self.hide_me.emit)
        for b in (self._snd_btn, side_b, hide_b):
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
        #Стеклянная карточка чата — 1:1 с вебом (VectorPage.vue: bg-card/70 + рамка +
        #скругление). Во вкладке подложка чуть плотнее и поля крупнее, чем в шторке: там
        #текста больше и он должен читаться поверх крупной фигуры.
        alpha = 0.72 if self.docked else 0.78
        radius = 12 if self.docked else 14
        pad = 10 if self.docked else 16
        self.chat.setStyleSheet(
            f"QTextEdit{{background:{_rgba(C['card'], alpha)};"
            f"border:1px solid {_rgba(C['border'], 0.6)};border-radius:{radius}px;"
            f"padding:{pad}px;font-size:{'12.5' if self.docked else '13.5'}px;color:{C['text']};}}")
        self.chat.viewport().setStyleSheet("background:transparent;")  #чтобы rgba-подложка просвечивала
        #Во вкладке «ИИ Помощник» фигура РАСТЁТ вместе с окном (как на сайте), в шторке —
        #фиксированная: ширина панели задана жёстко, тянуть нечего.
        self._overlay = _AvatarChatOverlay(self.avatar, self.chat, grow=not self.docked)
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
        #animate=False: это ПРОШЛЫЕ реплики (панель просто открыли/переоткрыли),
        #печатать их по новой было бы раздражающим повтором анимации.
        for who, text in self.session.history:
            self._append(who, text, animate=False)

        #Двойной клик по чату — пропустить анимацию печати и показать ответ целиком
        #(по ТЗ). Ставим фильтр на viewport, а не на сам QTextEdit — так приходят
        #события мыши.
        self.chat.viewport().installEventFilter(self)

        #Сессия должна знать о панели: по видимости полноэкранной панели она решает, какой
        #выключатель звука применять — общий или «звук шторки» (см. _voice_on).
        try:
            self.session.register_panel(self)
        except Exception:
            pass
        #Подписываемся на сигналы общей сессии: текст в чат пишем ТОЛЬКО отсюда
        #(не локально в _send) — поэтому обе панели всегда синхронны и без дублей.
        self.session.messageAdded.connect(self._append)
        self.session.thinkingStarted.connect(self._on_thinking)
        self.session.answered.connect(self._on_session_answer)
        self.session.askFailed.connect(self._on_session_fail)
        #Границы реального звука → анимация речи длится ровно сколько играет озвучка.
        self.session.speechStarted.connect(self._on_speech_started)
        self.session.speechEnded.connect(self._on_speech_ended)

    def _sync_sound_btn(self):
        """Значок кнопки звука — по текущему состоянию выключателя ШТОРКИ."""
        try:
            from . import tts
            on = tts.dock_enabled()
        except Exception:
            on = True
        self._snd_btn.setText("🔊" if on else "🔇")
        self._snd_btn.setToolTip("Озвучка в этой панели включена" if on
                                 else "Озвучка в этой панели выключена")

    def _toggle_dock_sound(self):
        try:
            from . import tts
            tts.set_dock_enabled(not tts.dock_enabled())
        except Exception:
            pass
        self._sync_sound_btn()

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
        elif obj is self.chat.viewport():
            if event.type() == QEvent.MouseButtonDblClick:
                self._skip_speech()
        return super().eventFilter(obj, event)

    def _skip_speech(self):
        """Двойной клик по чату — «пропустить реплику ЦЕЛИКОМ».

        Раньше пропускалась только ПЕЧАТЬ: текст мгновенно дописывался, а Вектор ещё
        полминуты говорил вслух и шевелил губами — то есть просьбу «покажи сразу»
        выполняла лишь треть реплики. Теперь обрываем и звук, и анимацию речи: маскот
        сразу уходит в покой (статика)."""
        self._complete_typing()
        try:
            from . import tts
            tts.stop()
        except Exception:
            pass
        self._tts_driving = False
        self._speak_start_timer.stop()
        self._speak_end_timer.stop()
        self._finish_speaking()

    #чат
    def _append(self, who, text, animate=True):
        #Новое сообщение ВСЕГДА завершает предыдущую печать сразу (по ТЗ: новый вопрос —
        #старый ответ мгновенно целиком), даже если это не ответ Вектора, а реплика «Вы».
        self._complete_typing()
        if who == "Вектор" and animate:
            self._start_typing(text)
            return
        color = C["green"] if who == "Вектор" else C["blue"]
        safe = (text or "").replace("\n", "<br>")
        self.chat.append(
            f'<span style="color:{color};font-weight:bold;">{who}:</span> '
            f'<span style="color:{C["text"]};">{safe}</span><br>')
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _start_typing(self, text):
        """Печать ответа Вектора по символам, в темпе озвучки (см. speak_duration_ms) —
        только во вкладке «ИИ Помощник» (см. docked-проверку в _append)."""
        self._typing_full = text or ""
        self._typing_pos = 0
        cur = self.chat.textCursor()
        cur.movePosition(QTextCursor.End)
        cur.insertHtml(f'<span style="color:{C["green"]};font-weight:bold;">Вектор:</span> ')
        self._typing_fmt = QTextCharFormat()
        self._typing_fmt.setForeground(QColor(C["text"]))
        self.chat.setTextCursor(cur)
        sb = self.chat.verticalScrollBar(); sb.setValue(sb.maximum())
        if not self._typing_full:
            self._end_typing_block()
            return
        dur_ms = speak_duration_ms(self._typing_full)
        interval = max(TYPE_MS_PER_CHAR_MIN, dur_ms / len(self._typing_full))
        self._typing_timer.start(int(interval))

    def _advance_typing(self):
        if self._typing_pos >= len(self._typing_full):
            self._typing_timer.stop()
            return
        ch = self._typing_full[self._typing_pos]
        self._typing_pos += 1
        cur = self.chat.textCursor()
        cur.movePosition(QTextCursor.End)
        cur.insertText(ch, self._typing_fmt)
        self.chat.setTextCursor(cur)
        sb = self.chat.verticalScrollBar(); sb.setValue(sb.maximum())
        if self._typing_pos >= len(self._typing_full):
            self._typing_timer.stop()
            self._end_typing_block()

    def _complete_typing(self):
        """Мгновенно дописать текущий печатаемый ответ целиком (двойной клик по чату,
        либо новое сообщение перебивает недопечатанное — оба случая по ТЗ)."""
        if not self._typing_timer.isActive():
            return
        self._typing_timer.stop()
        remaining = self._typing_full[self._typing_pos:]
        if remaining:
            cur = self.chat.textCursor()
            cur.movePosition(QTextCursor.End)
            cur.insertText(remaining, self._typing_fmt)
        self._end_typing_block()

    def _end_typing_block(self):
        cur = self.chat.textCursor()
        cur.movePosition(QTextCursor.End)
        cur.insertHtml("<br>")
        sb = self.chat.verticalScrollBar(); sb.setValue(sb.maximum())
        self._typing_full = ""
        self._typing_pos = 0

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
        self._last_intent = intent
        #Пока не знаем, будет ли реальная озвучка — сбрасываем флаг. Если пойдёт звук,
        #speechStarted включит его и анимацию поведёт звук; если озвучки нет — эвристика ниже.
        self._tts_driving = False
        #маскот: ответ отправлен, но ещё 1 c «дообдумывает» (по ТЗ), затем speaking. Без
        #озвучки длительность — эвристика по длине ответа; с озвучкой её ведёт сам звук.
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
        #Эвристический конец речи — ТОЛЬКО когда озвучки нет. Если звук идёт, его конец
        #поймает speechEnded (иначе длинный ответ обрывался бы раньше речи).
        if not self._tts_driving:
            self._speak_end_timer.start(dur_ms)

    def _on_speech_started(self):
        """РЕАЛЬНО пошёл звук озвучки → анимацию речи ведёт звук, не эвристика. Синхронно
        со стартом звука переводим маскота в «речь» (отменяя 1-c додумывание и таймер конца)."""
        self._tts_driving = True
        self._speak_start_timer.stop()
        self._speak_end_timer.stop()
        self._busy = True
        self._begin_speaking(0, self._last_intent)

    def _on_speech_ended(self):
        """Звук озвучки кончился → договорил, уходим в покой."""
        if not self._tts_driving:
            return                       #звук этой панели не вёл — ничего не трогаем
        self._tts_driving = False
        self._finish_speaking()

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
        #«Язычок» для разворачивания, когда шторка свёрнута. Раньше это была полоса 🐯 во
        #ВСЮ высоту окна — она читалась как вторая колонка интерфейса и заметно съедала
        #поле зрения ради одной кнопки. Теперь компактная вкладка у края, по вертикали
        #посередине (как на сайте), а полоса-контейнер прозрачная.
        self.restore = QToolButton()
        self.restore.setText("🐯")
        self.restore.setToolTip("Показать Вектора")
        self.restore.setCursor(Qt.PointingHandCursor)
        self.restore.setFixedSize(22, 76)
        self.restore.hide()
        self.restore.clicked.connect(self.show_panel)
        #Контейнер держит язычок по центру высоты и сам ничего не рисует.
        self.restore_host = QWidget()
        self.restore_host.setFixedWidth(22)
        _rv = QVBoxLayout(self.restore_host)
        _rv.setContentsMargins(0, 0, 0, 0)
        _rv.addStretch(1)
        _rv.addWidget(self.restore)
        _rv.addStretch(1)
        self.restore_host.hide()
        self._style_restore("left")
        self.panel.move_side.connect(self.toggle_side)
        self.panel.hide_me.connect(self.hide_panel)

    def _style_restore(self, side: str):
        """Скругляем язычок с той стороны, которой он «торчит» в контент: у левого края
        закруглён правый бок, у правого — левый. Так он читается как вкладка, вытянутая
        из-за края экрана, а не как обрезанная кнопка."""
        r = "border-top-right-radius:8px;border-bottom-right-radius:8px;" if side == "left" \
            else "border-top-left-radius:8px;border-bottom-left-radius:8px;"
        self.restore.setStyleSheet(
            f"QToolButton{{background:{C['card2']};border:1px solid {C['border']};"
            f"font-size:14px;{r}}}"
            f"QToolButton:hover{{background:{C['bg2']};border-color:{C['green']};}}")

    def _insert(self, w, side):
        if side == "left":
            self.body.insertWidget(0, w)
        else:
            self.body.addWidget(w)

    def mount(self, side="left"):
        self.side = side
        self._insert(self.panel, side)
        self._insert(self.restore_host, side)
        self.restore_host.hide()
        self._style_restore(side)
        self._collapsed = False
        self.panel.set_side(side)

    def toggle_side(self):
        self.body.removeWidget(self.panel)
        self.body.removeWidget(self.restore_host)
        self.side = "right" if self.side == "left" else "left"
        self._insert(self.panel, self.side)
        self._insert(self.restore_host, self.side)
        self.restore_host.setVisible(not self.panel.isVisible())
        self._style_restore(self.side)
        #зеркалим маскота, когда панель справа (по ТЗ)
        self.panel.set_side(self.side)

    def is_open(self):
        """Развёрнута ли шторка = виден полноценный Вектор (панель показана, не свёрнута
        до полоски 🐯 и не спрятана под вкладку «ИИ»)."""
        return not self._collapsed and self._suspended is None

    def hide_panel(self):
        #картинки маскота скрываются вместе со всей панелью (по ТЗ)
        self.panel.hide()
        self.restore_host.show()
        self._collapsed = True
        #Закрыли шторку — Вектора больше не видно, глушим озвучку (как на вебе: пропал
        #последний видимый Вектор → тишина). Кнопка «скрыть» доступна только вне вкладки
        #«ИИ», так что здесь мы точно НЕ на полноэкранном Векторе.
        try:
            from . import tts
            tts.stop()
        except Exception:
            pass

    def show_panel(self):
        self.restore_host.hide()
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
        self.restore_host.hide()

    def resume(self):
        """Вернуть шторку в прежнее состояние (ушли с вкладки «ИИ»). Идемпотентно."""
        if self._suspended is None:
            return
        was = self._suspended
        self._suspended = None
        self._collapsed = was["collapsed"]
        if self._collapsed:
            self.panel.hide()
            self.restore_host.show()
        else:
            self.restore_host.hide()
            self.panel.show()


def hush_if_vector_hidden(dock, key):
    """Заглушить озвучку, если после переключения на вкладку `key` Вектора не видно.

    Правило то же, что на вебе: голос звучит, пока виден хоть один Вектор — полноэкранный
    на вкладке «ИИ» ИЛИ развёрнутая боковая шторка. Ушли туда, где Вектора нет (у студента
    любая не-ИИ вкладка; у препода/админа — если шторка свёрнута) → тишина.

    dock — VectorHost или None (у студента шторки нет). Зовётся из `_switch` дашбордов."""
    if key == "ai":
        return                       #полноэкранный Вектор виден — пусть договаривает
    if dock is not None and dock.is_open():
        return                       #боковая шторка открыта — Вектор виден
    try:
        from . import tts
        tts.stop()
    except Exception:
        pass
