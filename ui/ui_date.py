"""
ui_date.py — валидируемый ввод даты вместо свободного QInputDialog.getText.

Проблема: даты вводились свободным текстом «дд.мм.гггг» без проверки →
мусор («32.13.2026», «завтра», пустая строка) и падения парсера.

Здесь:
  • parse_date / normalize_date — строгая проверка дд.мм.гггг
    (с проверкой реального календаря: 31.02 не пройдёт);
  • ask_date(parent, ...) — диалог с КАЛЕНДАРЁМ (QDateEdit). Пользователь
    физически не может ввести кривую дату. Возвращает 'дд.мм.гггг' или None.
"""
from datetime import datetime, date, timedelta
from typing import Optional

DATE_FMT = "%d.%m.%Y"


def parse_date(text: str) -> Optional[date]:
    """'дд.мм.гггг' → date или None, если дата некорректна."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), DATE_FMT).date()
    except (ValueError, TypeError):
        return None


def normalize_date(text: str) -> Optional[str]:
    """Приводит к каноничному 'дд.мм.гггг' или None."""
    d = parse_date(text)
    return d.strftime(DATE_FMT) if d else None


def today_str() -> str:
    return date.today().strftime(DATE_FMT)


def plus_days_str(days: int) -> str:
    return (date.today() + timedelta(days=days)).strftime(DATE_FMT)


def ask_date(parent, title: str = "Дата", label: str = "Выберите дату:",
             default: Optional[str] = None, min_today: bool = False) -> Optional[str]:
    """
    Диалог выбора даты с календарём. Возвращает 'дд.мм.гггг' или None (отмена).
    Кривую дату ввести нельзя в принципе — это виджет календаря, а не текст.
    """
    try:
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QDateEdit, QPushButton, QLabel
        )
        from PySide6.QtCore import QDate
    except Exception:
        #Если Qt недоступен (например, в тестах) — текстовый фолбэк с проверкой
        return normalize_date(default or today_str())

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(label))

    edit = QDateEdit(dlg)
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("dd.MM.yyyy")
    d0 = parse_date(default) if default else date.today()
    if not d0:
        d0 = date.today()
    edit.setDate(QDate(d0.year, d0.month, d0.day))
    if min_today:
        t = date.today()
        edit.setMinimumDate(QDate(t.year, t.month, t.day))
    lay.addWidget(edit)

    row = QHBoxLayout()
    ok = QPushButton("ОК"); cancel = QPushButton("Отмена")
    row.addStretch(1); row.addWidget(cancel); row.addWidget(ok)
    lay.addLayout(row)
    ok.clicked.connect(dlg.accept)
    cancel.clicked.connect(dlg.reject)

    if dlg.exec() == QDialog.Accepted:
        qd = edit.date()
        return f"{qd.day():02d}.{qd.month():02d}.{qd.year()}"
    return None
