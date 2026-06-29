"""
styles.py — Дизайн-система GradeBookAI.

Профессиональная, «дорогая» эстетика (ориентир — Linear / Vercel): спокойные
нейтральные поверхности, мягкая глубина вместо жёстких рамок, выразительная
типографика и крупные удобные контролы. Поддержаны ДВЕ нейтральные базы — светлая
и тёмная (полноценная тёмная тема), поверх которых накладывается акцент (фирменная
бирюза ВСГУТУ или одна из цветных тем).

Слои дизайн-системы:
  • ТОКЕНЫ — типографика, отступы (сетка 4px), радиусы, веса, высоты контролов.
    Единые числа, а не «магия», разбросанная по файлам.
  • НЕЙТРАЛИ — NEUTRALS_LIGHT / NEUTRALS_DARK (фон, карточки, границы, текст,
    семантика, тень). Режим (light/dark) выбирает themes.build_palette.
  • АКЦЕНТ — green / green2 / green_glow / blue. Задаётся темой (PRESETS / custom).
  • C — АКТИВНАЯ палитра (нейтрали выбранного режима + акцент). Все фабрики и QSS
    читают C динамически; themes.apply_spec → styles.apply_palette пересобирает всё.

Шрифты — системные (на ПК колледжа Windows → Segoe UI): предсказуемо и офлайн.
Если положить .ttf в папку fonts/ (например, Inter) — подхватятся автоматически
(см. fonts.py), и стек ниже сам предпочтёт их Segoe UI.
"""

#ТОКЕНЫ ──────────────────────────────────────────────────────────────────────
COLLEGE_NAME = "Технологический колледж ВСГУТУ"

#Фирменные шрифты Synapse (как на сайте): Syne — заголовки, DM Sans — текст.
#Они подхватятся автоматически, если положить .ttf в папку fonts/ рядом с программой
#(см. fonts.py). Нет файлов — откатываемся на системный Segoe UI (вид предсказуем,
#офлайн без сбоев). Так дизайн готов к фирменному шрифту без жёсткой зависимости.
FONT_BODY  = "'DM Sans', 'Segoe UI', 'PT Sans', 'Arial', sans-serif"
FONT_TITLE = "'Syne', 'Segoe UI Semibold', 'Segoe UI', 'PT Sans', sans-serif"

#Типографическая шкала (px). База 14 — крупнее прежних 13: читается легче и
#выглядит дороже, без «плотной таблички 2010-х».
FS_DISPLAY = 30   #крупный заголовок экрана
FS_H1      = 24
FS_H2      = 18
FS_H3      = 15
FS_BODY    = 14
FS_SMALL   = 12
FS_TINY    = 11

#Веса шрифта
W_REGULAR  = 400
W_MEDIUM   = 500
W_SEMIBOLD = 600
W_BOLD     = 700
W_EXTRA    = 800

#Отступы — сетка 4px (используем как единый ритм во всех вёрстках)
SP_1, SP_2, SP_3, SP_4, SP_5, SP_6, SP_8 = 4, 8, 12, 16, 20, 24, 32

#Радиусы скругления
R_SM, R_MD, R_LG, R_XL, R_PILL = 8, 12, 16, 20, 999

#Высоты контролов — крупные и «дорогие» (просьба: кнопки не мелкие)
H_INPUT  = 42
H_BTN    = 44
H_BTN_SM = 34


#НЕЙТРАЛИ ────────────────────────────────────────────────────────────────────
#Светлая база — чистый спокойный нейтрал с лёгкой прохладой (не «голый» Bootstrap).
NEUTRALS_LIGHT = {
    "bg":      "#F4F6F8",   #фон окна
    "bg2":     "#ECEFF2",   #сайдбар / подложки
    "card":    "#FFFFFF",   #карточки
    "card2":   "#F4F6F8",   #инпуты / вторичные поверхности
    "border":  "#E4E9ED",   #тихая граница
    "border2": "#D3DBE1",   #граница инпутов
    "text":    "#0F1B22",   #основной текст
    "text3":   "#46555F",   #вторичный
    "text2":   "#7A8893",   #приглушённый / плейсхолдер
    "red":     "#D14343",
    "orange":  "#D9892B",
    "yellow":  "#C99A0C",
    "shadow":  "rgba(15,27,34,0.10)",   #цвет мягкой тени карточек
    "overlay": "rgba(15,27,34,0.40)",   #затемнение под модалками
}

#Тёмная база — глубокий нейтральный графит (ориентир Linear), НЕ чёрный. Карточка
#чуть светлее фона: глубина задаётся яркостью поверхности, а не рамкой.
NEUTRALS_DARK = {
    "bg":      "#0E1113",
    "bg2":     "#15181B",
    "card":    "#171B1E",
    "card2":   "#1E2327",
    "border":  "#272D32",
    "border2": "#333A40",
    "text":    "#ECEEF0",
    "text3":   "#AEB8BF",
    "text2":   "#7E8A92",
    "red":     "#F2776B",
    "orange":  "#F0A95A",
    "yellow":  "#E3C152",
    "shadow":  "rgba(0,0,0,0.45)",
    "overlay": "rgba(0,0,0,0.55)",
}

#Фирменный акцент ВСГУТУ (бирюза) — заводской набор акцентных слотов.
DEFAULT_ACCENT = {
    "green":      "#147C8B",
    "green2":     "#0E6271",
    "green_glow": "rgba(20,124,139,0.14)",
    "blue":       "#2BA6B8",
}

#АКТИВНАЯ ПАЛИТРА: старт — светлая база + фирменный акцент. Дальше themes.apply_spec
#переустанавливает C через apply_palette() (в т.ч. в тёмном режиме).
C = {}
C.update(NEUTRALS_LIGHT)
C.update(DEFAULT_ACCENT)


#ГЛОБАЛЬНЫЙ QSS ───────────────────────────────────────────────────────────────
#Собираем в функции: при смене темы (themes.apply_spec → apply_palette) пересобираем
#на новой палитре. Все цвета читаем из C, поэтому один и тот же QSS корректно
#работает и в светлом, и в тёмном режиме (нет хардкода «тёмный текст на светлом»).
def _build_app_style() -> str:
    return f"""
/* ─── База ─────────────────────────────────────────────── */
QWidget {{
    background-color: {C['bg']};
    color: {C['text']};
    font-family: {FONT_BODY};
    font-size: {FS_BODY}px;
}}
QLabel {{ background-color: transparent; }}
QMainWindow, QDialog {{ background-color: {C['bg']}; }}

/* ─── Скроллбары (тонкие, нейтральные) ──────────────────── */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {C['border2']}; border-radius: {R_SM}px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: {C['text2']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {C['border2']}; border-radius: {R_SM}px; min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background: {C['text2']}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ─── Карточки ──────────────────────────────────────────── */
QFrame#card {{
    background-color: {C['card']};
    border: 1px solid {C['border']};
    border-radius: {R_LG}px;
}}
QFrame#card2 {{
    background-color: {C['card2']};
    border: 1px solid {C['border']};
    border-radius: {R_MD}px;
}}

/* ─── Поля ввода ────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
    background-color: {C['card2']};
    border: 1px solid {C['border2']};
    border-radius: {R_SM}px;
    padding: 10px 14px;
    color: {C['text']};
    font-family: {FONT_BODY};
    font-size: {FS_BODY}px;
    selection-background-color: {C['green']};
    selection-color: #FFFFFF;
    placeholder-text-color: {C['text2']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
    border: 1px solid {C['green']};
    background-color: {C['card']};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDateEdit:hover {{
    border: 1px solid {C['text2']};
}}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{
    background-color: {C['card']};
    border: 1px solid {C['border2']};
    border-radius: {R_SM}px;
    padding: 4px;
    color: {C['text']};
    selection-background-color: {C['green_glow']};
    selection-color: {C['green']};
    outline: none;
}}

/* ─── Таблицы (тихая шапка, без жёстких рамок) ──────────── */
QTableWidget, QTableView {{
    background-color: {C['card']};
    border: 1px solid {C['border']};
    border-radius: {R_MD}px;
    gridline-color: transparent;
    selection-background-color: transparent;
    outline: none;
}}
QTableWidget::item, QTableView::item {{
    padding: 8px 12px;
    color: {C['text3']};
    border-bottom: 1px solid {C['border']};
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {C['green_glow']};
    color: {C['text']};
}}
QTableWidget::item:hover, QTableView::item:hover {{
    background-color: {C['bg2']};
}}
QHeaderView::section {{
    background-color: {C['bg2']};
    color: {C['text2']};
    border: none;
    border-bottom: 1px solid {C['border2']};
    padding: 10px 12px;
    font-size: {FS_TINY}px;
    font-weight: {W_SEMIBOLD};
    text-transform: uppercase;
}}
QTableCornerButton::section {{
    background-color: {C['bg2']};
    border: none;
    border-bottom: 1px solid {C['border2']};
}}

/* ─── Списки ────────────────────────────────────────────── */
QListWidget {{
    background-color: {C['card']};
    border: 1px solid {C['border']};
    border-radius: {R_MD}px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 11px 14px;
    border-radius: {R_SM}px;
    color: {C['text3']};
    margin: 1px 2px;
}}
QListWidget::item:selected {{
    background-color: {C['green_glow']};
    color: {C['green']};
}}
QListWidget::item:hover {{
    background-color: {C['bg2']};
    color: {C['text']};
}}

/* ─── Вкладки ───────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {C['border']};
    border-radius: {R_MD}px;
    background-color: {C['card']};
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    border: none;
    color: {C['text2']};
    padding: 9px 18px;
    margin-right: 4px;
    font-size: {FS_SMALL}px;
    font-weight: {W_MEDIUM};
}}
QTabBar::tab:selected {{
    color: {C['green']};
    border-bottom: 2px solid {C['green']};
    font-weight: {W_SEMIBOLD};
}}
QTabBar::tab:hover:!selected {{ color: {C['text']}; }}

/* ─── Заголовки и метки ─────────────────────────────────── */
QLabel#title {{
    font-size: {FS_H1}px; font-weight: {W_EXTRA};
    color: {C['text']}; font-family: {FONT_TITLE};
}}
QLabel#subtitle {{ font-size: {FS_SMALL}px; color: {C['text3']}; }}
QLabel#section_title {{
    font-size: {FS_H2}px; font-weight: {W_BOLD};
    color: {C['text']}; font-family: {FONT_TITLE};
}}
QLabel#badge_green {{
    background-color: {C['green_glow']}; border: 1px solid {C['green']};
    color: {C['green']}; border-radius: {R_PILL}px;
    padding: 4px 12px; font-size: {FS_TINY}px; font-weight: {W_MEDIUM};
}}
QLabel#badge_blue {{
    background-color: rgba(43,166,184,0.14); border: 1px solid {C['blue']};
    color: {C['blue']}; border-radius: {R_PILL}px;
    padding: 4px 12px; font-size: {FS_TINY}px; font-weight: {W_MEDIUM};
}}

/* ─── Чекбоксы / радио ──────────────────────────────────── */
QCheckBox, QRadioButton {{ color: {C['text']}; spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px; }}
QCheckBox::indicator {{
    border: 1px solid {C['border2']}; border-radius: 5px; background: {C['card2']};
}}
QCheckBox::indicator:checked {{ background: {C['green']}; border-color: {C['green']}; }}

/* ─── Разделитель ───────────────────────────────────────── */
QSplitter::handle {{ background-color: {C['border']}; }}

/* ─── Меню ──────────────────────────────────────────────── */
QMenu {{
    background-color: {C['card']}; border: 1px solid {C['border2']};
    border-radius: {R_MD}px; padding: 6px;
}}
QMenu::item {{ padding: 8px 16px; border-radius: {R_SM}px; color: {C['text']}; }}
QMenu::item:selected {{ background-color: {C['green_glow']}; color: {C['green']}; }}

/* ─── Подсказки (нейтральные, читаются в обоих режимах) ──── */
QToolTip {{
    background-color: {C['card2']}; border: 1px solid {C['border2']};
    color: {C['text']}; padding: 6px 10px; border-radius: {R_SM}px;
}}

/* ─── Диалоги ───────────────────────────────────────────── */
QMessageBox {{ background-color: {C['card']}; }}
QMessageBox QLabel {{ color: {C['text']}; font-size: {FS_BODY}px; }}
"""


APP_STYLE = _build_app_style()


#КНОПКИ ───────────────────────────────────────────────────────────────────────
#Крупные, «дорогие» кнопки. Радиус мягкий (не пилюля для основных действий —
#так выглядит профессиональнее), переходы цвета на hover/pressed.
def _build_btn() -> dict:
    return {
    "green": (
        f"QPushButton{{background:{C['green']};color:#FFFFFF;border:none;border-radius:{R_SM}px;"
        f"padding:12px 22px;font-weight:{W_SEMIBOLD};font-size:{FS_BODY}px;font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:{C['green2']};}}"
        f"QPushButton:pressed{{background:{C['green2']};}}"
        f"QPushButton:disabled{{background:{C['border2']};color:{C['text2']};}}"
    ),
    "ghost": (
        f"QPushButton{{background:{C['card']};color:{C['text']};"
        f"border:1px solid {C['border2']};border-radius:{R_SM}px;padding:11px 20px;"
        f"font-size:{FS_BODY}px;font-weight:{W_MEDIUM};font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:{C['green_glow']};color:{C['green']};border-color:{C['green']};}}"
        f"QPushButton:pressed{{background:{C['bg2']};}}"
        f"QPushButton:disabled{{color:{C['text2']};border-color:{C['border']};}}"
    ),
    "red": (
        f"QPushButton{{background:transparent;"
        f"color:{C['red']};border:1px solid {C['red']};border-radius:{R_SM}px;padding:11px 20px;"
        f"font-size:{FS_BODY}px;font-weight:{W_MEDIUM};font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:{C['red']};color:#FFFFFF;}}"
    ),
    "blue": (
        f"QPushButton{{background:transparent;color:{C['blue']};"
        f"border:1px solid {C['blue']};border-radius:{R_SM}px;padding:11px 20px;"
        f"font-size:{FS_BODY}px;font-weight:{W_MEDIUM};font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:{C['blue']};color:#FFFFFF;}}"
    ),
    "back": (
        f"QPushButton{{background:transparent;color:{C['text3']};"
        f"border:1px solid {C['border2']};border-radius:{R_SM}px;padding:9px 16px;"
        f"font-size:{FS_SMALL}px;font-weight:{W_MEDIUM};font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{color:{C['green']};background:{C['green_glow']};border-color:{C['green']};}}"
    ),
    "sm_green": (
        f"QPushButton{{background:{C['green']};color:#FFFFFF;border:none;border-radius:{R_SM}px;"
        f"padding:7px 14px;font-weight:{W_SEMIBOLD};font-size:{FS_SMALL}px;font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:{C['green2']};}}"
    ),
    "sm_ghost": (
        f"QPushButton{{background:{C['card']};color:{C['text3']};"
        f"border:1px solid {C['border2']};border-radius:{R_SM}px;padding:7px 13px;"
        f"font-size:{FS_SMALL}px;font-weight:{W_MEDIUM};font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{color:{C['green']};border-color:{C['green']};background:{C['green_glow']};}}"
    ),
    "sm_red": (
        f"QPushButton{{background:transparent;color:{C['red']};"
        f"border:1px solid {C['red']};border-radius:{R_SM}px;padding:7px 13px;"
        f"font-size:{FS_SMALL}px;font-weight:{W_MEDIUM};font-family:{FONT_BODY};}}"
        f"QPushButton:hover{{background:{C['red']};color:#FFFFFF;}}"
    ),
    }


BTN = _build_btn()

#КНОПКИ САЙДБАРА ───────────────────────────────────────────────────────────────
#Держим в СЛОВАРЕ SB (а не в строковых константах): словарь мутируется на месте при
#смене темы, и места вызова (widgets.sb_btn, Sidebar) видят новые значения без
#переимпорта. SB_NORMAL/SB_ACTIVE — алиасы для обратной совместимости.
def _build_sb() -> dict:
    return {
        "normal": (
            f"QPushButton{{background:transparent;color:{C['text3']};border:none;border-radius:{R_SM}px;"
            f"padding:11px 14px;text-align:left;font-size:{FS_BODY}px;font-weight:{W_MEDIUM};font-family:{FONT_BODY};}}"
            f"QPushButton:hover{{background:{C['green_glow']};color:{C['green']};}}"
            f"QPushButton:pressed{{background:{C['bg2']};}}"
        ),
        "active": (
            f"QPushButton{{background:{C['green_glow']};color:{C['green']};"
            f"border:none;border-radius:{R_SM}px;padding:11px 14px;"
            f"text-align:left;font-size:{FS_BODY}px;font-weight:{W_SEMIBOLD};font-family:{FONT_BODY};}}"
        ),
    }


SB = _build_sb()
SB_NORMAL = SB["normal"]   #алиас для обратной совместимости
SB_ACTIVE = SB["active"]   #алиас для обратной совместимости


def apply_palette(colors: dict) -> None:
    """Переустанавливает активную палитру на лету (вызывается из themes.apply_spec).

    Почему именно так:
      • C — общий словарь, его МУТИРУЕМ на месте (clear+update), поэтому все модули,
        сделавшие `from styles import C`, продолжают видеть ту же ссылку с новыми
        цветами, а фабрики виджетов (lbl/badge/stat_card/...) читают C динамически и
        строят новые виджеты уже в новой палитре;
      • BTN и SB — тоже словари и тоже мутируются на месте, чтобы `from styles import
        BTN`/`SB` в widgets.py/ui_components.py не «застряли» на старых строках;
      • APP_STYLE — модульная строка глобального QSS; пересобираем и переустанавливаем,
        вызывающий код сам делает QApplication.setStyleSheet(styles.APP_STYLE).
    Уже построенные виджеты с инлайн-стилем перекрашиваются при пересборке дашборда.
    """
    global APP_STYLE, SB_NORMAL, SB_ACTIVE
    C.clear(); C.update(colors)
    APP_STYLE = _build_app_style()
    BTN.clear(); BTN.update(_build_btn())
    SB.clear(); SB.update(_build_sb())
    SB_NORMAL = SB["normal"]
    SB_ACTIVE = SB["active"]


#КОНСТАНТЫ ─────────────────────────────────────────────────────────────────────
DEFAULT_GROUPS   = ["к74/1", "к74/2", "к74/3", "к75/0"]
DEFAULT_SUBJECTS = [
    "Компьютерные сети",
    "Основы алгоритмизации и программирования",
    "Основы проектирования баз данных",
    "Разработка программных модулей",
]
