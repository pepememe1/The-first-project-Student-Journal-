"""
dashboards.py — Панели управления для студентов, учителей и администраторов
"""

from datetime import datetime, timedelta
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QTableWidget, QTableWidgetItem,
    QLabel, QPushButton, QStackedWidget, QComboBox, QTextEdit, QMessageBox,
    QFileDialog, QInputDialog, QDialog, QGridLayout, QFrame, QHeaderView,
    QAbstractItemView, QListWidget, QListWidgetItem, QApplication
)

from core import GradeBook, Student, DBManager, APP_VERSION
from subjects import load_subjects
from styles import C, BTN
from widgets import (
    lbl, title_lbl, section_lbl, btn, stat_card, card, card2,
    field_input, combo, separator, badge
)
from ui_components import Sidebar
from ai_module import AIWidget, AIRequestThread
from utils import get_api_key, get_groups, get_subjects_for_group, clean_ai_text

try:
    from security import secure_store
except ImportError:
    secure_store = None


# ══════════════════════════════════════════════════════════════
#  STUDENT DASHBOARD
# ══════════════════════════════════════════════════════════════

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
            ("dash",    "🏠", "Главная"),
            ("journal", "📋", "Мой журнал"),
            ("stats",   "📊", "Статистика"),
            ("ai",      "🤖", "ИИ Помощник"),
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

        self._build_dash()
        self._build_journal()
        self._build_stats()
        self._build_ai_page()

        self.sidebar.set_active("dash")

        # ── Вектор постоянно слева (⇄ — вправо, — свернуть/вернуть 🐯) ──
        try:
            from vector.widget import VectorPanel, VectorHost
            eng = getattr(self, "vector_engine", None)
            if eng is None:
                from vector import VectorEngine, VectorScope, get_provider
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
            self.vector_dock = VectorHost(body, VectorPanel(eng, docked=True))
            self.vector_dock.mount(side="left")
        except Exception as _e:
            print(f"[Vector] панель сбоку (студент): {_e}")

    def _build_dash(self):
        """Построить главную страницу студента"""
        w = QScrollArea()
        w.setWidgetResizable(True)
        w.setStyleSheet("border:none;")
        
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(16)

        # Заголовок
        hdr = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(title_lbl(f"{self.cur_stud['f']} {self.cur_stud['n']}", 22))
        col.addWidget(lbl(f"Группа: {self.cur_stud['g']}", 12, C['text3']))
        hdr.addLayout(col, 1)
        
        ai_btn = btn("🤖  ИИ Помощник", "blue")
        ai_btn.clicked.connect(lambda: self._switch("ai"))
        hdr.addWidget(ai_btn)
        lay.addLayout(hdr)
        lay.addWidget(separator())

        # Совет карточка
        tip = QFrame()
        tip.setStyleSheet(
            f"background:rgba(14,98,113,0.06);border:1px solid rgba(20,124,139,0.15);border-radius:12px;"
        )
        tip_lay = QVBoxLayout(tip)
        tip_lay.setContentsMargins(16, 12, 16, 12)
        tip_lay.setSpacing(6)
        
        tip_hdr = QHBoxLayout()
        tip_hdr.addWidget(lbl("💡  Умный совет", 12, C['green'], True))
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

        # Статистика
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
        lay.addLayout(stats_row)

        # Список предметов
        lay.addWidget(section_lbl("Мои предметы"))
        self._subj_list_lay = QVBoxLayout()
        self._subj_list_lay.setSpacing(8)
        lay.addLayout(self._subj_list_lay)
        lay.addStretch()
        
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
                if l.type in ("Практика", "Экзамен"):
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
        
        # Обновить карточки статистики
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

        # Список предметов
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
                    if l.type in ("Практика", "Экзамен"):
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
        """Открыть предмет в журнале"""
        self._switch("journal")
        if hasattr(self, "_journal_combo"):
            idx = self._journal_combo.findText(subj)
            if idx >= 0:
                self._journal_combo.setCurrentIndex(idx)
            self._load_journal()

    def _load_tip(self):
        """Загрузить умный совет от ИИ"""
        api = get_api_key()
        if not api:
            self._tip_lbl.setText("Умный совет недоступен — API ключ не установлен.")
            return
        
        self._tip_lbl.setText("⏳ Загрузка совета...")
        
        subjects = get_subjects_for_group(self.cur_stud['g'])
        lines = []
        for subj in subjects:
            book = GradeBook(self.cur_stud['g'], subj)
            s = next((x for x in book.spisok_stud if x.f.lower() == self.cur_stud['f'].lower()), None)
            if not s:
                continue
            
            gs, misses = [], 0
            for l in book.lessons:
                if l.type in ("Практика", "Экзамен"):
                    v = s.records.get(l.id, "")
                    try:
                        gs.append(int(v.split()[0]))
                    except:
                        pass
                elif l.type == "Лекция" and s.records.get(l.id, "") == "Н":
                    misses += 1
            
            lines.append(f"{subj}: оценки {','.join(map(str, gs)) or 'нет'}, пропусков: {misses}")
        
        prompt = (f"Ты дружелюбный помощник студента {self.cur_stud['n']}.\n"
                  "Напиши ОДИН короткий совет (2-4 предложения). Только русский, без markdown.\n"
                  f"Данные:\n" + "\n".join(lines or ["Данных пока нет"]))
        
        self._tip_thread = AIRequestThread(api, "", prompt)
        self._tip_thread.finished.connect(lambda t: self._tip_lbl.setText(clean_ai_text(t)))
        self._tip_thread.error.connect(lambda e: self._tip_lbl.setText("Не удалось загрузить совет."))
        self._tip_thread.start()

    def _build_journal(self):
        """Построить страницу журнала"""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)
        
        hdr = QHBoxLayout()
        hdr.addWidget(title_lbl("Журнал оценок"))
        hdr.addStretch()
        
        self._journal_combo = combo(get_subjects_for_group(self.cur_stud['g']))
        self._journal_combo.currentTextChanged.connect(self._load_journal)
        hdr.addWidget(self._journal_combo)
        lay.addLayout(hdr)
        
        self._journal_table = QTableWidget()
        self._journal_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self._journal_table, 1)
        
        self.pages["journal"] = w
        self.stack.addWidget(w)
        self._load_journal()

    def _load_journal(self):
        """Загрузить журнал для выбранного предмета"""
        subj = self._journal_combo.currentText()
        book = GradeBook(self.cur_stud['g'], subj)
        s = next((x for x in book.spisok_stud if x.f.lower() == self.cur_stud['f'].lower()), None)
        
        if not s:
            self._journal_table.setRowCount(0)
            self._journal_table.setColumnCount(2)
            self._journal_table.setHorizontalHeaderLabels(["Фамилия", "Имя"])
            return
        
        col_defs = []
        for l in book.lessons:
            col_defs.append((l, 0))
            if l.type == "Экзамен":
                ri = 1
                while getattr(l, f'retake_date{"" if ri == 1 else "_" + str(ri)}', ''):
                    col_defs.append((l, ri))
                    ri += 1
        
        self._journal_table.setColumnCount(2 + len(col_defs))
        self._journal_table.setRowCount(1)
        
        headers = ["Фамилия", "Имя"]
        for l, ri in col_defs:
            if ri > 0:
                rd = getattr(l, f'retake_date{"" if ri == 1 else "_" + str(ri)}', '')
                headers.append(f"Пересдача {ri}\n{rd}")
            elif l.type == "Лекция":
                headers.append(f"Лекция {l.number}{f' ({l.hour}-й ч.)' if l.hour else ''}\n{l.date}\n{l.topic[:20]}")
            elif l.type == "Экзамен":
                headers.append(f"Экзамен №{l.number}\n{l.date}\n{l.topic[:20]}")
            else:
                headers.append(f"Практика {l.number}\n{l.date}\n{l.topic[:20]}")
        
        self._journal_table.setHorizontalHeaderLabels(headers)
        self._journal_table.setItem(0, 0, QTableWidgetItem(s.f))
        self._journal_table.setItem(0, 1, QTableWidgetItem(s.n))
        
        for ci, (l, ri) in enumerate(col_defs):
            rk = l.id + ("_retake" if ri == 1 else f"_retake_{ri}" if ri > 1 else "")
            val = s.records.get(rk if ri > 0 else l.id, "")

            # Пересдача касается только заваливших предыдущую попытку.
            # Если студент сдал — в его строке прочерк, а не пустая ячейка.
            if ri > 0 and not val:
                prev_key = l.id if ri == 1 else (
                    l.id + ("_retake" if ri - 1 == 1 else f"_retake_{ri - 1}"))
                prev = (s.records.get(prev_key, "") or "").strip()
                failed = prev.startswith(("2", "Н")) or "Не зачтено" in prev
                if not failed:
                    val = "—"

            it = QTableWidgetItem(val)
            it.setTextAlignment(Qt.AlignCenter)
            
            if val in ("5", "4", "3", "2"):
                colors = {"5": "#DBF0E4", "4": "#DCEFF2", "3": "#FBEFD6", "2": "#FAE0DE"}
                it.setBackground(QColor(colors.get(val, "#FFFFFF")))
            elif val == "Н":
                it.setForeground(QColor(C['red']))
            elif val == "✓":
                it.setForeground(QColor(C['green']))
            
            self._journal_table.setItem(0, 2 + ci, it)
        
        self._journal_table.resizeColumnsToContents()
        self._journal_table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)

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
                if l.type in ("Практика", "Экзамен"):
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
        
        # Статистика строка
        sr = QHBoxLayout()
        sr.setSpacing(10)
        for lbl_t, val, col in [("Средний балл", avg, "blue"), ("Посещаемость", att, "text"),
                                 ("Отличных", str(dist[5]), "green"), ("Неудов.", str(dist[2]), "text")]:
            sr.addWidget(stat_card(lbl_t, val, col))
        self._stats_content.addLayout(sr)
        
        # По предметам
        c_subj = card()
        cl = QVBoxLayout(c_subj)
        cl.setContentsMargins(18, 16, 18, 16)
        cl.addWidget(section_lbl("По предметам"))
        
        for subj, avg_s, cnt in sorted(by_subj, key=lambda x: -x[1]):
            row = QHBoxLayout()
            n = lbl(subj[:40] + "…" if len(subj) > 40 else subj, 12, C['text'])
            n.setFixedWidth(300)
            row.addWidget(n)
            
            bar = QFrame()
            bar.setFixedHeight(4)
            bar.setStyleSheet(f"background:{C['border']};border-radius:2px;")
            row.addWidget(bar, 1)
            
            pct = int((avg_s - 1) / 4 * 100)
            col = (C['green'] if avg_s >= 4.5 else C['blue'] if avg_s >= 3.5
                   else C['yellow'] if avg_s >= 2.5 else C['red'])
            row.addWidget(lbl(f"{avg_s:.1f}", 14, col, True))
            cl.addLayout(row)
        
        self._stats_content.addWidget(c_subj)

    def _build_ai_page(self):
        """Вкладка «ИИ Помощник» — теперь Вектор (вместо облачного чата)."""
        try:
            from vector import VectorEngine, VectorScope, get_provider
            from vector.widget import VectorPanel
            try:
                from data_store import get_store
                _cfg = get_store()._config()
            except Exception:
                _cfg = {}
            scope = VectorScope(
                role="student",
                group=self.cur_stud.get("g", ""),
                student_f=self.cur_stud.get("f", ""),
                student_n=self.cur_stud.get("n", ""),
            )
            self.vector_engine = VectorEngine(scope, get_provider(_cfg))
            ai = VectorPanel(self.vector_engine, docked=False)
        except Exception as _e:
            print(f"[Vector] вкладка не собралась (студент): {_e}")
            ai = AIWidget(
                role="student",
                context_fn=lambda: self._build_student_context(),
                back_fn=lambda: self.pages.get("dash"),
                stack_ref=self.stack
            )
        self.pages["ai"] = ai
        self.stack.addWidget(ai)

    def _build_student_context(self):
        """Построить контекст для ИИ"""
        subjects = get_subjects_for_group(self.cur_stud['g'])
        lines = []
        
        for subj in subjects:
            book = GradeBook(self.cur_stud['g'], subj)
            s = next((x for x in book.spisok_stud if x.f.lower() == self.cur_stud['f'].lower()), None)
            if not s:
                continue
            
            gs, miss = [], 0
            for l in book.lessons:
                if l.type in ("Практика", "Экзамен"):
                    v = s.records.get(l.id, "")
                    try:
                        gs.append(f"{l.type} №{l.number}: {int(v.split()[0])}")
                    except:
                        pass
                elif l.type == "Лекция" and s.records.get(l.id, "") == "Н":
                    miss += 1
            
            lines.append(f"Предмет: {subj}\n" + ("\n".join(gs) or "  оценок нет") + f"\n  пропусков: {miss}")
        
        return (
            f"Ты ИИ-ассистент электронного журнала.\n"
            f"Студент: {self.cur_stud['f']} {self.cur_stud['n']}, группа {self.cur_stud['g']}.\n"
            "Обращайся на 'ты'. Только русский язык, без markdown, кратко.\n\n"
            "ДАННЫЕ СТУДЕНТА:\n" + "\n\n".join(lines)
        )

    def _switch(self, key):
        """Переключиться между вкладками"""
        if getattr(self, '_switching', False):
            return
        self._switching = True
        try:
            if key == "stats":
                self._refresh_stats()
            if key in self.pages:
                self.stack.setCurrentWidget(self.pages[key])
                self.sidebar.set_active(key)
        finally:
            self._switching = False
