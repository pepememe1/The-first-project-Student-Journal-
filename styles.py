"""
styles.py — Дизайн-система GradeBookAI в стиле ВСГУТУ.
Институциональная светлая тема: фирменная бирюза + светлый фон + белые карточки.
Шрифты: системные (Segoe UI / PT Sans) — без загрузки из интернета.
"""

#ПАЛИТРА ВСГУТУ
#Фирменная бирюза вуза + светлые институциональные поверхности.
C = {
    # Светлые фоны
    "bg":          "#EDF2F3",   # фон окна (мягкий светло-бирюзово-серый)
    "bg2":         "#E0E9EB",   # подложки / скроллбары
    "card":        "#FFFFFF",   # белые карточки
    "card2":       "#F3F8F9",   # инпуты / вторичные карточки
    "border":      "#D5E1E4",   # светлая граница
    "border2":     "#BFD2D6",   # граница инпутов
    #Фирменная бирюза (основной акцент — везде, где раньше был зелёный)
    "green":       "#147C8B",   # primary
    "green2":      "#0E6271",   # тёмная бирюза (hover / pressed / градиент)
    "green_glow":  "rgba(20,124,139,0.10)",
    #Светлый cyan-акцент (шапка-градиент / второстепенное)
    "blue":        "#2BA6B8",
    #Тёмный текст на светлом
    "text":        "#16282D",   # основной
    "text3":       "#3F555B",   # вторичный
    "text2":       "#6C8086",   # приглушённый / плейсхолдер
    #Семантика (приглушённая, институциональная)
    "red":         "#C8453E",
    "orange":      "#D9892B",
    "yellow":      "#C99A0C",
}

#Шрифты
#Системные шрифты (на целевых ПК колледжа — Windows / Segoe UI).
#Без загрузки из интернета: предсказуемо и работает офлайн.
COLLEGE_NAME = "Технологический колледж ВСГУТУ"

FONT_BODY  = "'Segoe UI', 'PT Sans', 'Arial', sans-serif"
FONT_TITLE = "'Segoe UI Semibold', 'Segoe UI', 'PT Sans', 'Arial', sans-serif"

#ГЛОБАЛЬНЫЙ СТИЛЬ (QSS — светлая тема ВСГУТУ)
APP_STYLE = f"""
/* ─── База ─────────────────────────────────────────────── */
QWidget {{
    background-color: {C['bg']};
    color: {C['text']};
    font-family: {FONT_BODY};
    font-size: 13px;
}}
QLabel {{
    background-color: transparent;
}}
QMainWindow, QDialog {{
    background-color: {C['bg']};
}}

/* ─── Скроллбары ────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {C['bg2']}; width: 8px; border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {C['border2']}; border-radius: 4px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {C['green']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {C['bg2']}; height: 8px; border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {C['border2']}; border-radius: 4px; min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ─── Карточки ──────────────────────────────────────────── */
QFrame#card {{
    background-color: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 12px;
}}
QFrame#card2 {{
    background-color: {C['card2']};
    border: 1px solid {C['border']};
    border-radius: 10px;
}}

/* ─── Поля ввода ────────────────────────────────────────── */
QLineEdit, QTextEdit, QComboBox, QSpinBox {{
    background-color: {C['card2']};
    border: 1px solid {C['border2']};
    border-radius: 8px;
    padding: 8px 12px;
    color: {C['text']};
    font-family: {FONT_BODY};
    selection-background-color: {C['green']};
    selection-color: #FFFFFF;
    placeholder-text-color: {C['text2']};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border: 1px solid {C['green']};
}}
QComboBox::drop-down {{
    border: none; width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {C['card']};
    border: 1px solid {C['border2']};
    border-radius: 8px;
    color: {C['text']};
    selection-background-color: {C['green_glow']};
    selection-color: {C['green']};
}}

/* ─── Таблицы ───────────────────────────────────────────── */
QTableWidget {{
    background-color: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 10px;
    gridline-color: {C['border']};
    selection-background-color: transparent;
}}
QTableWidget::item {{
    padding: 6px 10px;
    color: {C['text3']};
    border-bottom: 1px solid {C['border']};
    font-family: {FONT_BODY};
}}
QTableWidget::item:selected {{
    background-color: {C['green_glow']};
    color: {C['text']};
}}
QTableWidget::item:hover {{
    background-color: {C['bg']};
}}
QHeaderView::section {{
    background-color: {C['green']};
    color: #FFFFFF;
    border: 1px solid {C['green2']};
    padding: 8px 10px;
    font-size: 11px;
    font-weight: 600;
    font-family: {FONT_BODY};
}}
QHeaderView::section:first {{
    border-top-left-radius: 10px;
}}
QTableCornerButton::section {{
    background-color: {C['green']};
    border: 1px solid {C['green2']};
}}

/* ─── Списки ────────────────────────────────────────────── */
QListWidget {{
    background-color: {C['card']};
    border: 1px solid {C['border']};
    border-radius: 10px;
}}
QListWidget::item {{
    padding: 10px 14px;
    border-bottom: 1px solid {C['border']};
    color: {C['text3']};
    font-family: {FONT_BODY};
}}
QListWidget::item:selected {{
    background-color: {C['green_glow']};
    color: {C['green']};
    border-left: 3px solid {C['green']};
}}
QListWidget::item:hover {{
    background-color: {C['bg']};
    color: {C['text']};
}}

/* ─── Вкладки ───────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {C['border']};
    border-radius: 10px;
    background-color: {C['card']};
    top: -1px;
}}
QTabBar::tab {{
    background-color: {C['card2']};
    border: 1px solid {C['border']};
    color: {C['text3']};
    padding: 8px 18px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
    font-size: 12px;
    font-family: {FONT_BODY};
}}
QTabBar::tab:selected {{
    background-color: {C['card']};
    color: {C['green']};
    border-bottom-color: {C['card']};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    color: {C['text']};
}}

/* ─── Заголовки и метки ─────────────────────────────────── */
QLabel#title {{
    font-size: 22px;
    font-weight: 800;
    color: {C['text']};
    font-family: {FONT_TITLE};
}}
QLabel#subtitle {{
    font-size: 12px;
    color: {C['text3']};
    font-family: {FONT_BODY};
}}
QLabel#section_title {{
    font-size: 16px;
    font-weight: 700;
    color: {C['text']};
    font-family: {FONT_TITLE};
}}
QLabel#badge_green {{
    background-color: {C['green_glow']};
    border: 1px solid {C['green']};
    color: {C['green']};
    border-radius: 100px;
    padding: 3px 10px;
    font-size: 11px;
    font-family: {FONT_BODY};
}}
QLabel#badge_blue {{
    background-color: rgba(43,166,184,0.12);
    border: 1px solid {C['blue']};
    color: {C['blue']};
    border-radius: 100px;
    padding: 3px 10px;
    font-size: 11px;
    font-family: {FONT_BODY};
}}

/* ─── Разделитель ───────────────────────────────────────── */
QSplitter::handle {{
    background-color: {C['border']};
    width: 1px;
    height: 1px;
}}

/* ─── Подсказки ─────────────────────────────────────────── */
QToolTip {{
    background-color: {C['text']};
    border: 1px solid {C['green2']};
    color: #FFFFFF;
    padding: 5px 8px;
    border-radius: 6px;
    font-family: {FONT_BODY};
}}

/* ─── Диалоги ───────────────────────────────────────────── */
QMessageBox {{
    background-color: {C['card']};
}}
QMessageBox QLabel {{
    color: {C['text']};
    font-size: 13px;
    font-family: {FONT_BODY};
}}
"""

#Кнопки
BTN = {
    "green": (
        f"QPushButton{{background:{C['green']};color:#FFFFFF;border:none;border-radius:9px;"
        f"padding:9px 18px;font-weight:600;font-size:13px;font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:{C['green2']};}}"
        f"QPushButton:pressed{{background:{C['green2']};}}"
        f"QPushButton:disabled{{background:{C['border2']};color:{C['text2']};}}"
    ),
    "ghost": (
        f"QPushButton{{background:{C['card']};color:{C['text3']};"
        f"border:1px solid {C['border2']};border-radius:9px;padding:8px 16px;"
        f"font-size:13px;font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:{C['green_glow']};color:{C['green']};border-color:{C['green']};}}"
        f"QPushButton:pressed{{background:{C['bg2']};}}"
    ),
    "red": (
        f"QPushButton{{background:rgba(200,69,62,0.10);color:{C['red']};"
        f"border:1px solid rgba(200,69,62,0.35);border-radius:9px;padding:8px 16px;"
        f"font-size:13px;font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:rgba(200,69,62,0.18);}}"
    ),
    "blue": (
        f"QPushButton{{background:rgba(43,166,184,0.12);color:{C['blue']};"
        f"border:1px solid rgba(43,166,184,0.35);border-radius:9px;padding:8px 16px;"
        f"font-size:13px;font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:rgba(43,166,184,0.20);}}"
    ),
    "back": (
        f"QPushButton{{background:{C['card']};color:{C['text3']};"
        f"border:1px solid {C['border']};border-radius:9px;padding:7px 14px;"
        f"font-size:12px;font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{color:{C['green']};background:{C['green_glow']};border-color:{C['green']};}}"
    ),
    "sm_green": (
        f"QPushButton{{background:{C['green']};color:#FFFFFF;border:none;border-radius:7px;"
        f"padding:5px 11px;font-weight:600;font-size:12px;font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:{C['green2']};}}"
    ),
    "sm_ghost": (
        f"QPushButton{{background:{C['card']};color:{C['text3']};"
        f"border:1px solid {C['border2']};border-radius:7px;padding:5px 10px;"
        f"font-size:11px;font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{color:{C['green']};border-color:{C['green']};}}"
    ),
    "sm_red": (
        f"QPushButton{{background:rgba(200,69,62,0.10);color:{C['red']};"
        f"border:1px solid rgba(200,69,62,0.35);border-radius:7px;padding:5px 10px;"
        f"font-size:11px;font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:rgba(200,69,62,0.18);}}"
    ),
}

#Кнопки боковой панели
SB_NORMAL = (
    f"QPushButton{{background:transparent;color:{C['text3']};border:none;border-radius:9px;"
    f"padding:9px 10px;text-align:left;font-size:13px;font-family:{FONT_BODY};}}"
    f"QPushButton:hover{{background:{C['green_glow']};color:{C['green']};}}"
    f"QPushButton:pressed{{background:{C['bg2']};}}"
)
SB_ACTIVE = (
    f"QPushButton{{background:{C['green_glow']};color:{C['green']};"
    f"border:1px solid {C['green']};border-radius:9px;padding:9px 10px;"
    f"text-align:left;font-size:13px;font-weight:600;font-family:{FONT_BODY};}}"
)

#Константы
DEFAULT_GROUPS   = ["к74/1", "к74/2", "к74/3", "к75/0"]
DEFAULT_SUBJECTS = [
    "Компьютерные сети",
    "Основы алгоритмизации и программирования",
    "Основы проектирования баз данных",
    "Разработка программных модулей",
]
