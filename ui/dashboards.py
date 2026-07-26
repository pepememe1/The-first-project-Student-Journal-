"""
dashboards.py — Панели управления для студентов, учителей и администраторов
"""

from PySide6.QtCore import Qt, QThread, Signal as QSignal
import log
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QStackedWidget, QFrame, QAbstractItemView, QSizePolicy,
    QCheckBox, QHeaderView
)

from core import GradeBook
from grading import PRACTICE_TYPES
from styles import C

#Типы занятий, из которых собирается статистика оценок студента (распределение,
#списки баллов). Экзамен идёт сюда всегда — это оценка, даже если в средний балл он
#по методике не входит (см. grading.avg_include_exam). ДЗ приехало из PRACTICE_TYPES.
GRADED_TYPES = tuple(PRACTICE_TYPES) + ("Экзамен",)
from widgets import (
    lbl, title_lbl, section_lbl, stat_card, card, btn, separator,
    vector_unavailable_widget
)
from ui_components import Sidebar
from utils import get_subjects_for_group


class _MascotImage(QLabel):
    """Большой маскот-тигр на «Главной» студента, который САМ масштабируется под свой
    размер (адаптив под окно программы). Полный кадр храним в _src и при каждом
    ресайзе пересчитываем уменьшенную версию с сохранением пропорций — так тигр
    растёт/сжимается вместе с колонкой, а не остаётся фиксированным."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._src = None
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setStyleSheet("background:transparent;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(180, 240)

    def set_source(self, pm):
        self._src = pm
        self._rescale()

    def _rescale(self):
        if self._src is None or self._src.isNull():
            self.clear()
            return
        self.setPixmap(self._src.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        self._rescale()
        super().resizeEvent(event)


class VectorTipThread(QThread):
    """Готовит «умный совет» студенту силами Вектора — по фактам из журнала.

    Раньше совет генерировал облачный ИИ-чат; теперь его считает сам Вектор
    (через свои интенты в vector/intents.py), поэтому фича работает офлайн и не
    шлёт ничего наружу. Запускаем в фоне, чтобы не подвешивать интерфейс.

    Вместе с текстом считаем ЭМОЦИЮ маскота (морда+поза) по успеваемости и
    разовым событиям — её рисуем рядом с советом. Картинку (QPixmap) грузим уже
    в GUI-потоке по эмоции/позе, тут возвращаем только их имена (строки)."""
    finished = QSignal(str, str, str)     # text, emotion, pose
    error    = QSignal(str)

    def __init__(self, stud: dict):
        super().__init__()
        self._stud = dict(stud or {})

    def run(self):
        try:
            from vector import VectorScope
            from vector import intents as vintents

            scope = VectorScope(
                role="student",
                group=self._stud.get("g", ""),
                student_f=self._stud.get("f", ""),
                student_n=self._stud.get("n", ""),
            )
            #Цифры берём строго из журнала — как и весь Вектор: средний балл,
            #незакрытые долги и пропуски по всем предметам группы.
            avg     = vintents.intent_average(scope).data.get("average") or 0
            debtors = vintents.intent_debtors(scope).data.get("debtors", [])
            absc    = vintents.intent_absences(scope).data.get("всего", 0)

            parts = []
            if avg:
                parts.append(f"Твой средний балл — {avg}.")
            else:
                parts.append("Оценок по практикам пока нет — самое время начать "
                             "набирать.")
            if debtors:
                reasons = debtors[0].get("reasons", [])
                parts.append("Есть незакрытые долги: " + "; ".join(reasons) + ". "
                             "Загляни к преподавателю и договорись о пересдаче.")
            else:
                parts.append("Долгов нет — так держать!")
            if absc:
                parts.append(f"Пропусков накопилось {absc} ч — старайся не "
                             f"пропускать занятия.")

            #Эмоция маскота: считаем по фактам журнала + разовым событиям.
            #Любой сбой здесь не должен срывать сам совет — падаем на нейтраль.
            emotion, pose = "деф", "деф"
            try:
                from vector import mascot
                data, signature = mascot.gather_student_data(self._stud)
                events = mascot.detect_events(self._stud, signature)
                state = mascot.resolveMascotState(data, events)
                emotion, pose = state["emotion"], state["pose"]
            except Exception:
                pass

            self.finished.emit(" ".join(parts), emotion, pose)
        except Exception as e:
            self.error.emit(str(e))


#STUDENT DASHBOARD

class StudentDashboard(QWidget):
    """Панель студента с журналом, статистикой и ИИ помощником"""
    
    from PySide6.QtCore import Signal as QSignal
    open_subject = QSignal(str)
    open_ai      = QSignal()

    def __init__(self, cur_stud: dict, parent=None):
        super().__init__(parent)
        self.cur_stud = cur_stud
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        sidebar_items = [
            ("__label__", "", "Обучение"),
            ("dash",    "home",      "Главная"),
            ("journal", "clipboard", "Мой журнал"),
            ("schedule","calendar",  "Расписание"),
            ("stats",   "chart",     "Статистика"),
            ("ai",      "bot",       "ИИ Помощник"),
            ("messages", "send",     "Сообщения"),
            ("__label__", "", "Личное"),
            ("profile", "user",      "Профиль"),
            ("settings", "settings", "Настройки"),
        ]
        self.sidebar = Sidebar(sidebar_items)
        self.sidebar.tab_clicked.connect(self._switch)

        self.stack = QStackedWidget()
        self.pages = {}

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.sidebar)
        body.addWidget(self.stack, 1)
        lay.addLayout(body)

        #Все вкладки строятся синхронно при входе — если какая-то «думает» секунды, из
        #этой строки видно какая именно (иначе долгий вход приходится искать вслепую).
        import time as _t
        _marks, _prev = [], _t.perf_counter()
        for _name, _fn in (("дашборд", self._build_dash), ("журнал", self._build_journal),
                           ("расписание", self._build_schedule), ("статистика", self._build_stats),
                           ("ИИ", self._build_ai_page), ("сообщения", self._build_messenger),
                           ("профиль", self._build_profile), ("настройки", self._build_settings)):
            _fn()
            _now = _t.perf_counter()
            _marks.append(f"{_name} {_now - _prev:.2f}")
            _prev = _now
        log.get("dashboards").warning("[тайминг вкладок] %s c", " · ".join(_marks))

        self.sidebar.set_active("dash")

        #У студента боковой шторки-оверлёя Вектора НЕТ (по требованию): ИИ-помощник
        #доступен только вкладкой «ИИ Помощник» в столбце «Обучение». Общая сессия
        #Вектора создаётся лениво самой вкладкой (_build_ai_page → _ensure_vector_session).

    def _ensure_vector_session(self):
        """Общая сессия Вектора (одна история для шторки и вкладки «ИИ Помощник»)."""
        if getattr(self, "vector_session", None) is not None:
            return self.vector_session
        from vector import VectorEngine, VectorScope, get_provider
        from vector.widget import VectorSession
        try:
            from data_store import get_store as _gs
            _cfg0 = _gs()._config()
        except Exception:
            _cfg0 = {}
        eng = VectorEngine(VectorScope(
            role="student", group=self.cur_stud.get("g", ""),
            student_f=self.cur_stud.get("f", ""),
            student_n=self.cur_stud.get("n", "")), get_provider(_cfg0))
        self.vector_engine = eng
        self.vector_session = VectorSession(eng)
        return self.vector_session

    def _build_dash(self):
        """Построить главную страницу студента"""
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setStyleSheet("border:none;")
        
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        #Заголовок
        hdr = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(title_lbl(f"{self.cur_stud['f']} {self.cur_stud['n']}", 22))
        col.addWidget(lbl(f"Группа: {self.cur_stud['g']}", 12, C['text3']))
        hdr.addLayout(col, 1)
        
        lay.addLayout(hdr)
        lay.addWidget(separator())

        #Совет карточка
        tip = QFrame()
        tip.setStyleSheet(
            "background:rgba(14,98,113,0.06);border:1px solid rgba(20,124,139,0.15);border-radius:12px;"
        )
        tip_lay = QVBoxLayout(tip)
        tip_lay.setContentsMargins(16, 12, 16, 12)
        tip_lay.setSpacing(6)
        
        tip_hdr = QHBoxLayout()
        tip_hdr.addWidget(lbl("Умный совет", 12, C['green'], True))
        tip_hdr.addStretch()
        
        self._tip_refresh = QPushButton("↻")
        self._tip_refresh.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid rgba(20,124,139,0.2);color:{C['green']};border-radius:6px;width:26px;height:26px;font-size:14px;}}"
            f"QPushButton:hover{{background:rgba(20,124,139,0.1);}}"
        )
        self._tip_refresh.setFixedSize(28, 28)
        self._tip_refresh.clicked.connect(self._load_tip)
        tip_hdr.addWidget(self._tip_refresh)
        tip_lay.addLayout(tip_hdr)
        
        self._tip_lbl = lbl("Загрузка совета...", 13, C['text3'])
        self._tip_lbl.setWordWrap(True)
        tip_lay.addWidget(self._tip_lbl)
        lay.addWidget(tip)

        #Тело: СЛЕВА адаптивная колонка-тигр (маскот с эмоцией по успеваемости),
        #СПРАВА — статистика и предметы. Тигр в своём столбце даёт ровный левый край
        #контента («текст вровень»). Колонки на stretch — макет тянется под окно.
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        dash_body = QHBoxLayout()
        dash_body.setSpacing(22)
        self._tip_mascot = _MascotImage()
        self._tip_mascot_fx = QGraphicsOpacityEffect(self._tip_mascot)
        self._tip_mascot.setGraphicsEffect(self._tip_mascot_fx)
        self._tip_mascot_fx.setOpacity(1.0)
        dash_body.addWidget(self._tip_mascot, 2)
        content = QVBoxLayout()
        content.setSpacing(16)

        #Статистика
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        subjects = get_subjects_for_group(self.cur_stud['g'])
        self._stat_cards = {}
        
        for label, val, col in [("Предметов", str(len(subjects)), "green"),
                                 ("Средний балл", "—", "blue"),
                                 ("Посещаемость", "—%", "text"),
                                 ("Оценок", "0", "text")]:
            sc = stat_card(label, val, col)
            self._stat_cards[label] = sc
            stats_row.addWidget(sc)
        content.addLayout(stats_row)

        #Список предметов (в правой колонке, справа от тигра)
        content.addWidget(section_lbl("Мои предметы"))
        self._subj_list_lay = QVBoxLayout()
        self._subj_list_lay.setSpacing(8)
        content.addLayout(self._subj_list_lay)
        content.addStretch()
        dash_body.addLayout(content, 5)
        lay.addLayout(dash_body, 1)
        
        w.setWidget(inner)
        self.pages["dash"] = w
        self.stack.addWidget(w)
        self._refresh_dash()
        self._load_tip()

    def _refresh_dash(self):
        """Обновить данные на главной странице"""
        subjects = get_subjects_for_group(self.cur_stud['g'])
        total_g, lec_t, lec_p = [], 0, 0
        
        for subj in subjects:
            book = GradeBook(self.cur_stud['g'], subj)
            s = next((x for x in book.spisok_stud if x.f.lower() == self.cur_stud['f'].lower()), None)
            if not s:
                continue
            
            for l in book.lessons:
                if l.type in GRADED_TYPES:
                    v = s.records.get(l.id, "")
                    try:
                        total_g.append(int(v.split()[0]))
                    except:
                        pass
                elif l.type == "Лекция":
                    lec_t += 1
                    if s.records.get(l.id, "") != "Н":
                        lec_p += 1
        
        avg = f"{sum(total_g) / len(total_g):.1f}" if total_g else "—"
        att = f"{int(lec_p / lec_t * 100)}%" if lec_t else "—%"
        
        #Обновить карточки статистики
        for c_frame in self._stat_cards.values():
            lay = c_frame.layout()
            lbl_text = lay.itemAt(0).widget().text()
            val_w = lay.itemAt(1).widget()
            if lbl_text == "СРЕДНИЙ БАЛЛ":
                val_w.setText(avg)
            elif lbl_text == "ПОСЕЩАЕМОСТЬ":
                val_w.setText(att)
            elif lbl_text == "ОЦЕНОК":
                val_w.setText(str(len(total_g)))

        #Список предметов
        while self._subj_list_lay.count():
            item = self._subj_list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        for subj in subjects:
            book = GradeBook(self.cur_stud['g'], subj)
            s = next((x for x in book.spisok_stud if x.f.lower() == self.cur_stud['f'].lower()), None)
            gs = []
            if s:
                for l in book.lessons:
                    if l.type in GRADED_TYPES:
                        v = s.records.get(l.id, "")
                        try:
                            gs.append(int(v.split()[0]))
                        except:
                            pass
            
            avg_s = f"{sum(gs) / len(gs):.1f}" if gs else "—"
            row = QFrame()
            row.setStyleSheet(
                f"QFrame{{background:{C['card']};border:1px solid {C['border']};border-radius:12px;}}"
                f"QFrame:hover{{border-color:rgba(20,124,139,0.35);}}"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(16, 12, 16, 12)
            
            col_lay = QVBoxLayout()
            col_lay.addWidget(lbl(subj, 14, C['text'], True))
            col_lay.addWidget(lbl(f"{len(gs)} оценок", 11, C['text3']))
            rl.addLayout(col_lay, 1)
            
            g_col = (C['green'] if avg_s != "—" and float(avg_s) >= 4.5
                    else C['blue'] if avg_s != "—" and float(avg_s) >= 3.5
                    else C['orange'] if avg_s != "—"
                    else C['text2'])
            rl.addWidget(lbl(avg_s, 20, g_col, True))
            
            row.setCursor(Qt.PointingHandCursor)
            row.mousePressEvent = lambda e, sj=subj: self._open_subj(sj)
            self._subj_list_lay.addWidget(row)

    def _open_subj(self, subj):
        """Открыть предмет в журнале (переход с «Главной»)."""
        self._switch("journal")
        self._open_subject(subj)

    def _load_tip(self):
        """Умный совет от Вектора — по фактам из журнала, офлайн и без сети.
        Вместе с текстом приходит эмоция маскота (морда+поза) — рисуем картинку."""
        self._tip_lbl.setText("⏳ Загрузка совета...")
        self._tip_thread = VectorTipThread(self.cur_stud)
        self._tip_thread.finished.connect(self._apply_tip)
        self._tip_thread.error.connect(
            lambda _e: self._tip_lbl.setText("Совет сейчас недоступен."))
        self._tip_thread.start()

    def _apply_tip(self, text: str, emotion: str, pose: str):
        """Показывает текст совета и эмоцию маскота рядом с ним (с плавным fade)."""
        self._tip_lbl.setText(text)
        try:
            from vector import mascot
            pm = mascot.getMascotFrame(emotion, pose)
        except Exception:
            pm = None
        if pm is None or pm.isNull():
            self._tip_mascot.clear()
            return
        #_MascotImage сам масштабирует кадр под свой размер (адаптив под окно).
        self._tip_mascot.set_source(pm)
        #плавная смена эмоции: короткий fade-in (по ТЗ — 200–300 мс, без рывка)
        from PySide6.QtCore import QPropertyAnimation
        anim = QPropertyAnimation(self._tip_mascot_fx, b"opacity", self)
        anim.setDuration(250)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
        self._tip_anim = anim          # держим ссылку, чтобы GC не убил анимацию

    def _build_journal(self):
        """Журнал студента в два экрана: (1) крупный список предметов со средним баллом
        справа → клик открывает (2) читаемую таблицу оценок по предмету с кнопкой «назад».
        Галочка «Н = 2» визуально пересчитывает средний (не трогая общий config)."""
        w = QWidget()
        lay = QVBoxLayout(w); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self._journal_stack = QStackedWidget()
        lay.addWidget(self._journal_stack)
        self._cur_subject = None

        # ── Экран 1: список предметов ──────────────────────────────────────────────
        list_page = QWidget()
        lp = QVBoxLayout(list_page); lp.setContentsMargins(28, 24, 28, 24); lp.setSpacing(12)
        hdr = QHBoxLayout()
        hdr.addWidget(title_lbl("Мой журнал"), 1)
        self._absence_chk = QCheckBox("Пропуск «Н» = 2 в среднем")
        self._absence_chk.setChecked(True)
        self._absence_chk.setToolTip("Снимите галочку, чтобы пропуски не занижали средний балл")
        self._absence_chk.setStyleSheet(
            f"QCheckBox{{color:{C['text2']};font-size:13px;}}"
            f"QCheckBox::indicator{{width:18px;height:18px;}}")
        self._absence_chk.stateChanged.connect(self._on_absence_toggle)
        hdr.addWidget(self._absence_chk)
        lp.addLayout(hdr)
        lp.addWidget(lbl("Выберите предмет — откроется таблица оценок.", 12, C['text3']))
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setStyleSheet("border:none;")
        inner = QWidget()
        self._subj_btns_lay = QVBoxLayout(inner)
        self._subj_btns_lay.setContentsMargins(0, 4, 6, 4); self._subj_btns_lay.setSpacing(10)
        self._subj_btns_lay.addStretch()
        scroll.setWidget(inner)
        lp.addWidget(scroll, 1)
        self._journal_stack.addWidget(list_page)

        # ── Экран 2: таблица предмета ──────────────────────────────────────────────
        detail_page = QWidget()
        dp = QVBoxLayout(detail_page); dp.setContentsMargins(28, 24, 28, 24); dp.setSpacing(12)
        dhdr = QHBoxLayout()
        back = btn("← К предметам", "ghost"); back.clicked.connect(self._show_subject_list)
        dhdr.addWidget(back)
        self._detail_title = title_lbl("", 20)
        dhdr.addWidget(self._detail_title, 1)
        self._detail_avg = lbl("", 14, C['text3'])
        dhdr.addWidget(self._detail_avg)
        dp.addLayout(dhdr)
        self._journal_table = QTableWidget()
        self._journal_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._journal_table.setAlternatingRowColors(True)
        self._journal_table.verticalHeader().setVisible(False)
        self._journal_table.verticalHeader().setDefaultSectionSize(46)
        #Крупный читаемый стиль — как в журнале преподавателя.
        self._journal_table.setStyleSheet(
            f"QTableWidget{{font-size:15px;alternate-background-color:{C['bg2']};"
            f"background:{C['card']};gridline-color:{C['border']};}}"
            f"QHeaderView::section{{font-size:13px;font-weight:700;color:{C['text']};"
            f"background:{C['bg2']};border:none;border-bottom:2px solid {C['green']};"
            "padding:8px 10px;}")
        self._journal_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        dp.addWidget(self._journal_table, 1)
        self._journal_stack.addWidget(detail_page)

        self.pages["journal"] = w
        self.stack.addWidget(w)
        self._refresh_subject_list()

    def _avg_cfg(self) -> dict:
        """config с учётом тумблера «Н = 2» — визуальный пересчёт среднего, не сохраняем."""
        try:
            from data_store import get_store
            base = dict(get_store()._config() or {})
        except Exception:
            base = {}
        chk = getattr(self, "_absence_chk", None)
        base["avg_count_absence"] = chk.isChecked() if chk is not None else True
        return base

    def _on_absence_toggle(self):
        self._refresh_subject_list()
        if self._journal_stack.currentIndex() == 1 and self._cur_subject:
            self._open_subject(self._cur_subject, keep_view=True)  # обновить средний в шапке

    def _avg_color(self, avg: float) -> str:
        if avg >= 4.5: return C['green']
        if avg >= 3.5: return C['blue']
        if avg >= 2.5: return C['yellow']
        if avg > 0:    return C['red']
        return C['text3']

    def _refresh_subject_list(self):
        if not hasattr(self, "_subj_btns_lay"):
            return
        while self._subj_btns_lay.count() > 1:      # оставляем финальный stretch
            it = self._subj_btns_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        cfg = self._avg_cfg()
        for subj in get_subjects_for_group(self.cur_stud['g']):
            book = GradeBook(self.cur_stud['g'], subj)
            s = next((x for x in book.spisok_stud
                      if x.f.lower() == self.cur_stud['f'].lower()), None)
            avg = book.calculate_average(s, cfg) if s else 0.0
            self._subj_btns_lay.insertWidget(self._subj_btns_lay.count() - 1,
                                             self._subject_card(subj, avg))

    def _subject_card(self, subj: str, avg: float) -> QFrame:
        #ВАЖНО: карточка — QFrame, а НЕ QPushButton: Qt не рисует дочерние QLabel внутри
        #QPushButton (кнопка перекрывает их), поэтому надписи пропадали. Кликабельность —
        #через mousePressEvent (тот же приём, что у строк на «Главной»).
        fr = QFrame(); fr.setCursor(Qt.PointingHandCursor)
        fr.setStyleSheet(
            f"QFrame{{background:{C['card']};border:1px solid {C['border']};border-radius:12px;}}"
            f"QFrame:hover{{border:1px solid {C['green']};background:{C['bg2']};}}")
        h = QHBoxLayout(fr); h.setContentsMargins(20, 16, 20, 16); h.setSpacing(12)
        name = lbl(subj, 16, C['text'], True); name.setWordWrap(True)
        name.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(name, 1)
        badge = lbl(f"{avg:.2f}" if avg > 0 else "—", 20, self._avg_color(avg), True)
        badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(badge)
        arrow = lbl("›", 20, C['text3'], True)
        arrow.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(arrow)
        fr.mousePressEvent = lambda e, sub=subj: self._open_subject(sub)
        return fr

    def _show_subject_list(self):
        self._refresh_subject_list()
        self._journal_stack.setCurrentIndex(0)

    def _open_subject(self, subj: str, keep_view: bool = False):
        self._cur_subject = subj
        self._detail_title.setText(subj)
        book = GradeBook(self.cur_stud['g'], subj)
        s = next((x for x in book.spisok_stud
                  if x.f.lower() == self.cur_stud['f'].lower()), None)
        avg = book.calculate_average(s, self._avg_cfg()) if s else 0.0
        self._detail_avg.setText(f"Средний: {avg:.2f}" if avg > 0 else "Средний: —")
        self._detail_avg.setStyleSheet(f"color:{self._avg_color(avg)};font-weight:700;")
        self._fill_subject_table(book, s)
        if not keep_view:
            self._journal_stack.setCurrentIndex(1)

    def _fill_subject_table(self, book, s):
        """Вертикальная таблица предмета: занятие | дата | тема | оценка (крупно, с цветом
        оценок и прочерком у неактуальных пересдач). Одна строка на занятие — читаемее
        широкой однострочной таблицы."""
        import grading
        t = self._journal_table
        t.clear()
        t.setColumnCount(4)
        t.setHorizontalHeaderLabels(["Занятие", "Дата", "Тема", "Оценка"])
        rows = []
        for l in book.lessons:
            rows.append((l, 0))
            if l.type == "Экзамен":
                ri = 1
                while getattr(l, f'retake_date{"" if ri == 1 else "_" + str(ri)}', ''):
                    rows.append((l, ri)); ri += 1
        t.setRowCount(len(rows))
        recs = s.records if s else {}
        for r, (l, ri) in enumerate(rows):
            if ri > 0:
                rd = getattr(l, f'retake_date{"" if ri == 1 else "_" + str(ri)}', '')
                name, date, topic = f"Пересдача №{ri}", rd, ""
                rk = l.id + ("_retake" if ri == 1 else f"_retake_{ri}")
                val = recs.get(rk, "")
                if not val:   #прочерк, если предыдущую попытку не заваливал
                    prev_key = l.id if ri == 1 else \
                        l.id + ("_retake" if ri - 1 == 1 else f"_retake_{ri - 1}")
                    if not grading.is_failed(recs.get(prev_key, "")):
                        val = "—"
            else:
                name = f"{l.type} №{l.number}" + (f" ({l.hour}ч)" if l.type == "Лекция" and l.hour else "")
                date, topic, val = (l.date or "—"), (l.topic or ""), recs.get(l.id, "")
            cells = [name, date, topic, val or ""]
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                if c == 3:
                    it.setTextAlignment(Qt.AlignCenter)
                    raw = (text or "").split()[0] if text else ""
                    if raw in ("5", "4", "3", "2"):
                        colors = {"5": "#DBF0E4", "4": "#DCEFF2", "3": "#FBEFD6", "2": "#FAE0DE"}
                        it.setBackground(QColor(colors[raw]))
                    elif raw == "Н":
                        it.setForeground(QColor(C['red']))
                    elif raw == "✓":
                        it.setForeground(QColor(C['green']))
                elif c == 0:
                    it.setForeground(QColor(C['text']))
                else:
                    it.setForeground(QColor(C['text2']))
                t.setItem(r, c, it)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        t.setColumnWidth(3, 90)

    def _build_schedule(self):
        """Вкладка «Расписание» — пары студента по его группе (данные с портала ВСГУТУ,
        кэшируются локально). Ключ привязки строим из ФИО+группы: на общем ПК выбор
        одного студента не утечёт другому."""
        from schedule_view import ScheduleView
        f, n, g = (self.cur_stud.get("f", ""), self.cur_stud.get("n", ""),
                   self.cur_stud.get("g", ""))
        w = ScheduleView(role="student", login=f"{f}|{n}|{g}", app_hint=g)
        self.pages["schedule"] = w
        self.stack.addWidget(w)

    def _build_stats(self):
        """Построить страницу статистики"""
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setStyleSheet("border:none;")
        
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(14)
        
        lay.addWidget(title_lbl("Моя статистика"))
        self._stats_content = QVBoxLayout()
        lay.addLayout(self._stats_content)
        lay.addStretch()
        
        w.setWidget(inner)
        self.pages["stats"] = w
        self.stack.addWidget(w)

    def _refresh_stats(self):
        """Обновить статистику"""
        while self._stats_content.count():
            it = self._stats_content.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        
        subjects = get_subjects_for_group(self.cur_stud['g'])
        dist = {2: 0, 3: 0, 4: 0, 5: 0}
        att_total = att_pres = 0
        by_subj = []
        
        for subj in subjects:
            book = GradeBook(self.cur_stud['g'], subj)
            s = next((x for x in book.spisok_stud if x.f.lower() == self.cur_stud['f'].lower()), None)
            if not s:
                continue
            
            gs = []
            for l in book.lessons:
                if l.type in GRADED_TYPES:
                    v = s.records.get(l.id, "")
                    try:
                        g = int(v.split()[0])
                        gs.append(g)
                        dist[g] += 1
                    except:
                        pass
                elif l.type == "Лекция":
                    att_total += 1
                    if s.records.get(l.id, "") != "Н":
                        att_pres += 1
            
            if gs:
                by_subj.append((subj, sum(gs) / len(gs), len(gs)))
        
        all_g = sum(dist.values())
        avg = f"{sum(k * v for k, v in dist.items()) / all_g:.1f}" if all_g else "—"
        att = f"{int(att_pres / att_total * 100)}%" if att_total else "—"

        #Долги и пропуски (Н/Б/О) — из того же движка, что и «Вектор»/веб (единый расчёт).
        reasons, absc = [], {"Н": 0, "Б": 0, "О": 0, "всего": 0}
        try:
            from vector import VectorScope
            from vector import intents as vintents
            scope = VectorScope(role="student", group=self.cur_stud['g'],
                                student_f=self.cur_stud['f'], student_n=self.cur_stud.get('n', ''))
            absc = vintents.intent_absences(scope).data or absc
            dbt = vintents.intent_debtors(scope).data.get("debtors", [])
            reasons = dbt[0].get("reasons", []) if dbt else []
        except Exception:
            pass

        #Статистика строка (добавлены пропуски и задолженности — раньше их не было)
        sr = QHBoxLayout()
        sr.setSpacing(10)
        for lbl_t, val, col in [("Средний балл", avg, "blue"), ("Посещаемость", att, "text"),
                                 ("Пропусков (ч)", str(absc.get("всего", 0)), "yellow"),
                                 ("Задолженности", str(len(reasons)), "red" if reasons else "green")]:
            sr.addWidget(stat_card(lbl_t, val, col))
        self._stats_content.addLayout(sr)

        #Карта «Задолженности и пропуски»: разбивка Н/Б/О + перечень незакрытых долгов.
        c_da = card()
        dal = QVBoxLayout(c_da)
        dal.setContentsMargins(18, 16, 18, 16)
        dal.addWidget(section_lbl("Задолженности и пропуски"))
        arow = QHBoxLayout(); arow.setSpacing(10)
        arow.addWidget(stat_card("Н (неув.)", str(absc.get("Н", 0)), "red"))
        arow.addWidget(stat_card("Б (болезнь)", str(absc.get("Б", 0)), "text"))
        arow.addWidget(stat_card("О (уваж.)", str(absc.get("О", 0)), "text"))
        dal.addLayout(arow)
        if reasons:
            dal.addWidget(lbl("Незакрытые долги:", 12, C['text2'], True))
            for r in reasons:
                dal.addWidget(lbl("•  " + r, 12, C['text'], wrap=True))
        else:
            dal.addWidget(lbl("Долгов нет — так держать!", 12, C['green']))
        self._stats_content.addWidget(c_da)
        
        #По предметам
        c_subj = card()
        cl = QVBoxLayout(c_subj)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.addWidget(section_lbl("По предметам"))
        
        for subj, avg_s, _cnt in sorted(by_subj, key=lambda x: -x[1]):
            row = QHBoxLayout()
            n = lbl(subj[:40] + "…" if len(subj) > 40 else subj, 12, C['text'])
            n.setFixedWidth(300)
            row.addWidget(n)
            
            bar = QFrame()
            bar.setFixedHeight(4)
            bar.setStyleSheet(f"background:{C['border']};border-radius:2px;")
            row.addWidget(bar, 1)

            col = (C['green'] if avg_s >= 4.5 else C['blue'] if avg_s >= 3.5
                   else C['yellow'] if avg_s >= 2.5 else C['red'])
            row.addWidget(lbl(f"{avg_s:.1f}", 14, col, True))
            cl.addLayout(row)
        
        self._stats_content.addWidget(c_subj)

    def _build_ai_page(self):
        """Вкладка «ИИ Помощник» — Вектор во всю ширину (единственное место Вектора
        у студента; боковой шторки нет)."""
        try:
            from vector.widget import VectorPanel
            self._ensure_vector_session()
            ai = VectorPanel(self.vector_session, docked=False)
        except Exception as _e:
            log.get("dashboards").warning(f"[Vector] вкладка не собралась (студент): {_e}")
            ai = vector_unavailable_widget()
        self.pages["ai"] = ai
        self.stack.addWidget(ai)

    def _build_messenger(self):
        """Вкладка «Сообщения» — веб-мессенджер во встроенном веб-view (Фаза 0 «один UI»,
        см. ui/messenger_web.py). Онлайн-подсистема (§13), offline-first не нужен."""
        try:
            from messenger_web import MessengerWebPanel
            mv = MessengerWebPanel("/student/messages", "student")
        except Exception as _e:
            log.get("dashboards").warning(f"[messenger] вкладка не собралась: {_e}")
            from PySide6.QtWidgets import QLabel
            mv = QLabel("Сообщения недоступны")
        self.pages["messages"] = mv
        self.stack.addWidget(mv)

    def _build_settings(self):
        """Вкладка «Настройки»: оформление (темы), микрофон и озвучка Вектора.
        Раньше это лежало в «Профиле» — вынесли в отдельную вкладку."""
        from theme_ui import ThemeCustomizer
        import theme_service
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)

        identity = {"f": self.cur_stud.get("f", ""), "n": self.cur_stud.get("n", ""),
                    "g": self.cur_stud.get("g", "")}

        def _save(s):
            theme_service.save_user_theme(s, "student", identity)
            win = self.window()
            if hasattr(win, "reapply_current"):
                win.reapply_current()

        lay.addWidget(ThemeCustomizer(
            initial_spec=theme_service.current_spec("student", identity), on_save=_save))
        #Выбор микрофона для голосового ввода (появляется, если стоят пакеты распознавания).
        try:
            from vector.voice_ui import MicSelectorWidget, mic_available
            if mic_available():
                lay.addWidget(MicSelectorWidget())
        except Exception as e:
            log.get("dashboards").warning(f"[settings] выбор микрофона недоступен: {e}")
        #Озвучка ответов Вектора (Голос → Бубнеж → Выкл + голос).
        try:
            from vector.voice_ui import TtsSettingsWidget
            lay.addWidget(TtsSettingsWidget())
        except Exception as e:
            log.get("dashboards").warning(f"[settings] настройки озвучки недоступны: {e}")
        self.pages["settings"] = w
        self.stack.addWidget(w)

    def _build_profile(self):
        """Вкладка «Профиль»: сведения об аккаунте + уведомления."""
        from notifications_view import NotificationsView
        w = QWidget(); lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 20, 24, 20); lay.setSpacing(12)
        lay.addWidget(title_lbl("Профиль", 20))

        name = f"{self.cur_stud.get('f', '')} {self.cur_stud.get('n', '')}".strip()
        grp = self.cur_stud.get("g", "")
        acc = card()
        acc_lay = QVBoxLayout(acc); acc_lay.setContentsMargins(16, 14, 16, 14); acc_lay.setSpacing(2)
        acc_lay.addWidget(lbl(name or "Студент", 16, C['text'], bold=True))
        acc_lay.addWidget(lbl("Студент" + (f" · {grp}" if grp else ""), 12, C['text3']))
        lay.addWidget(acc)

        from avatar_dialog import AvatarSection
        lay.addWidget(AvatarSection("student", {"f": self.cur_stud.get("f", ""),
                                                "n": self.cur_stud.get("n", ""),
                                                "g": self.cur_stud.get("g", "")}))

        #Свой заголовок «Уведомления» есть у самого NotificationsView — отдельный section_lbl
        #здесь дал бы задвоение надписи (правка по отчёту).
        lay.addWidget(NotificationsView(role="student"), 1)
        self.pages["profile"] = w
        self.stack.addWidget(w)

    def _switch(self, key):
        """Переключиться между вкладками"""
        if getattr(self, '_switching', False):
            return
        self._switching = True
        try:
            if key == "stats":
                self._refresh_stats()
            #Журнал открываем со списка предметов (со свежими средними после синка).
            if key == "journal" and hasattr(self, "_journal_stack"):
                self._refresh_subject_list()
                self._journal_stack.setCurrentIndex(0)
            if key in self.pages:
                self.stack.setCurrentWidget(self.pages[key])
                self.sidebar.set_active(key)
            #Ушли с Вектора (у студента шторки нет — значит с любой не-ИИ вкладки) → тишина.
            from vector.widget import hush_if_vector_hidden
            hush_if_vector_hidden(getattr(self, "vector_dock", None), key)
        finally:
            self._switching = False
