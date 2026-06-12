"""
ai_module.py — Модуль для работы с ИИ (OpenRouter API)
"""

import requests
from PySide6.QtCore import QThread, Signal as QSignal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel, QPushButton, QStackedWidget
)

from styles import C
from widgets import btn, title_lbl, field_input
from data_store import get_store as get_gh_store
from utils import clean_ai_text


# ══════════════════════════════════════════════════════════════
#  AI REQUEST THREAD
# ══════════════════════════════════════════════════════════════

class AIRequestThread(QThread):
    """Поток для отправки запроса к ИИ API (OpenRouter)"""
    
    finished = QSignal(str)  # Сигнал при успешном ответе
    error    = QSignal(str)  # Сигнал при ошибке

    def __init__(self, api_key, system_prompt, question, history=None):
        super().__init__()
        self.api_key       = api_key
        self.system_prompt = system_prompt
        self.question      = question
        self.history       = history or []

    def run(self):
        try:
            messages = [{"role": "system", "content": self.system_prompt}]
            messages.extend(self.history[-20:])
            
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "stepfun/step-3.5-flash:free",
                    "messages": messages
                },
                timeout=60
            )
            
            result = resp.json()
            if "choices" not in result:
                self.error.emit(f"Ошибка ответа: {result}")
            else:
                self.finished.emit(result["choices"][0]["message"]["content"])
                
        except Exception as e:
            self.error.emit(str(e))


#  AI WIDGET

class AIWidget(QWidget):
    """Виджет для взаимодействия с ИИ помощником"""
    
    def __init__(self, role, context_fn, back_fn, stack_ref, parent=None):
        super().__init__(parent)
        self.role       = role
        self.context_fn = context_fn  # Функция для получения контекста
        self.back_fn    = back_fn     # Функция для возврата на предыдущую страницу
        self.stack_ref  = stack_ref   # Ссылка на стек виджетов
        self._thread    = None
        self._history   = []
        
        self._build_ui()

    def _build_ui(self):
        """Построить интерфейс ИИ виджета"""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(12)

        # Header with back button
        hdr = QHBoxLayout()
        back = btn("← Назад", "back")
        back.setFixedWidth(100)
        back.clicked.connect(lambda: self.stack_ref.setCurrentWidget(self.back_fn()))
        hdr.addWidget(back)
        hdr.addWidget(title_lbl("🤖  ИИ Помощник", 18), 1)
        hdr.addSpacing(100)
        lay.addLayout(hdr)

        # Chat area (text edit for displaying messages)
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setStyleSheet(
            f"background:{C['card']};border:1px solid {C['border']};border-radius:10px;"
            f"padding:12px;font-size:13px;color:{C['text3']};"
        )
        lay.addWidget(self.chat, 1)

        # Loading indicator
        self.loading = QLabel("⏳ ИИ думает...")
        self.loading.setStyleSheet(f"color:{C['blue']};font-size:12px;")
        self.loading.hide()
        lay.addWidget(self.loading)

        # Input row
        inp_row = QHBoxLayout()
        inp_row.setSpacing(8)
        
        self.inp = field_input("Введите сообщение...")
        self.inp.returnPressed.connect(self._send)
        
        send = btn("Отправить  →", "green")
        send.setFixedWidth(130)
        send.clicked.connect(self._send)
        self.send_btn = send
        
        inp_row.addWidget(self.inp)
        inp_row.addWidget(send)
        lay.addLayout(inp_row)

        self._show_greeting()

    def _show_greeting(self):
        """Показать приветственное сообщение"""
        greetings = {
            "student": "Привет! Я твой учебный помощник.\nМогу рассказать о твоих оценках, посещаемости и среднем балле.",
            "teacher": "Добрый день! Готов помочь с анализом успеваемости группы.",
            "admin":   "Добрый день! Готов предоставить статистику по группам и студентам.",
        }
        self._append_ai(greetings.get(self.role, "Здравствуйте! Чем могу помочь?"))

    def _append_ai(self, text):
        """Добавить сообщение ИИ в чат"""
        self.chat.append(
            f'<span style="color:{C["green"]};font-weight:bold;">ИИ:</span><br>'
            f'<span style="color:{C["text3"]};">{text.replace(chr(10), "<br>")}</span><br>'
        )
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def _send(self):
        """Отправить сообщение ИИ"""
        text = self.inp.text().strip()
        if not text or (self._thread and self._thread.isRunning()):
            return
        
        # Добавить сообщение пользователя в чат
        self.chat.append(
            f'<span style="color:{C["blue"]};font-weight:bold;">Вы:</span>'
            f'<span style="color:{C["text"]};">  {text}</span><br>'
        )
        self.inp.clear()
        
        # Добавить в историю
        self._history.append({"role": "user", "content": text})
        
        # Получить API ключ из GitHub
        gh = get_gh_store()
        api_key = gh.get_api_key() if gh else None
        if not api_key:
            self._append_ai("API ключ не установлен. Обратитесь к администратору.")
            return
        
        # Запустить поток для ИИ запроса
        self.send_btn.setEnabled(False)
        self.inp.setEnabled(False)
        self.loading.show()
        
        self._thread = AIRequestThread(api_key, self.context_fn(), text, list(self._history))
        self._thread.finished.connect(self._on_answer)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _on_answer(self, raw):
        """Обработать ответ ИИ"""
        self.send_btn.setEnabled(True)
        self.inp.setEnabled(True)
        self.loading.hide()
        
        answer = clean_ai_text(raw)
        self._history.append({"role": "assistant", "content": raw})
        self._append_ai(answer)

    def _on_error(self, err):
        """Обработать ошибку ИИ"""
        self.send_btn.setEnabled(True)
        self.inp.setEnabled(True)
        self.loading.hide()
        self._append_ai(f"Ошибка: {err}")
