"""
messenger_view.py — вкладка «Сообщения» на ДЕСКТОПЕ (PySide6).

Порт веб-мессенджера на Qt: тот же REST API (data/messenger_client), НЕ sync-движок
(мессенджер — онлайн-подсистема, см. docs/MESSENGER-PLAN.md §13). Сеть идёт в ФОНОВЫХ
потоках, результат возвращается в GUI сигналами (как VectorSession) — интерфейс не
подвисает. Опрос новых — по QTimer (WebSocket на десктопе можно добавить позже; контракт
API один и тот же).

Левая колонка — вкладки как на вебе: «Чаты» (переписки), «Преподаватели» и «Студенты»
(ПРОСМОТР всех по алфавиту + поиск по ФИО). Клик по человеку открывает личный чат.
"""
import html
import re
import threading

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QTextBrowser, QPushButton, QLabel, QSplitter,
)

import messenger_client as mc

try:
    from styles import C
except Exception:
    C = {"card": "#fff", "card2": "#f3f6f7", "border": "#dfe6e8", "text": "#0d2b30",
         "text2": "#3a565b", "text3": "#6b8085", "green": "#147c8b", "green_glow": "#dbeef0",
         "bg": "#eef5f6"}


# ── §D1: Markdown-lite (порт web/src/utils/markdownLite.js — та же логика на Python) ──
# Экранируем ВЕСЬ пользовательский текст, потом накладываем ограниченный whitelist тегов
# поверх уже безопасного текста — единственные теги в результате мы вставили сами.
def _render_inline_md(escaped: str) -> str:
    codes = []

    def _code(m):
        codes.append(f"<code>{m.group(1)}</code>")
        return f"C{len(codes) - 1}"

    s = re.sub(r"`([^`\n]+)`", _code, escaped)
    s = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__([^_\n]+)__", r"<u>\1</u>", s)
    s = re.sub(r"~~([^~\n]+)~~", r"<s>\1</s>", s)
    s = re.sub(r"\*([^*\n]+)\*", r"<i>\1</i>", s)
    s = re.sub(r"C(\d+)", lambda m: codes[int(m.group(1))], s)
    return s


def render_markdown_lite(raw: str) -> str:
    """Тот же ограниченный набор, что и на вебе: **жирный** *курсив* __подчёркн__ ~~зачёрк~~
    `код` ```блок``` > цитата - список (заголовки # / ## — только там, где это видно веб-
    клиенту как канал; десктоп для простоты применяет их везде)."""
    text = raw or ""
    blocks = []

    def _block(m):
        blocks.append(f"<pre style='background:{C['card2']};padding:6px;border-radius:6px;'>"
                      f"<code>{m.group(1)}</code></pre>")
        return f" B{len(blocks) - 1} "

    escaped = html.escape(text)
    escaped = re.sub(r"```([\s\S]*?)```", _block, escaped)
    out = []
    for line in escaped.split("\n"):
        m = re.match(r"^-\s+(.*)$", line)
        if m:
            out.append(f"&bull; {_render_inline_md(m.group(1))}")
            continue
        m = re.match(r"^&gt;\s?(.*)$", line)
        if m:
            out.append(f"<span style='border-left:2px solid {C['green']};padding-left:6px;"
                       f"opacity:0.85;'>{_render_inline_md(m.group(1))}</span>")
            continue
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            out.append(f"<b style='font-size:15px;'>{_render_inline_md(m.group(1))}</b>")
            continue
        m = re.match(r"^#\s+(.*)$", line)
        if m:
            out.append(f"<b style='font-size:17px;'>{_render_inline_md(m.group(1))}</b>")
            continue
        out.append(_render_inline_md(line))
    result = "<br>".join(out)
    return re.sub(r" B(\d+) ", lambda m: blocks[int(m.group(1))], result)


# ── §D6: системные сообщения — те же шаблоны "событие:аргументы", что отдаёт сервер ────
def format_system_message(body: str) -> str:
    # Разделитель — \x1f (Unit Separator), НЕ ':': id участника сам вида "stud:login",
    # и split(':') расклеивал бы его на куски (сервер шлёт события через тот же символ,
    # см. routers/messenger.py::_system).
    parts = (body or "").split("\x1f")
    kind = parts[0]
    rest = parts[1:]
    if kind in ("user_joined", "user_left"):
        name = (rest[1] if len(rest) > 1 else "") or (rest[0] if rest else "Участник")
        return f"{name} вступил(а) в беседу" if kind == "user_joined" else f"{name} покинул(а) беседу"
    if kind == "title_changed":
        return f"Название изменено на «{rest[0] if rest else ''}»"
    if kind == "pin_added":
        return "📌 Сообщение закреплено"
    if kind == "pin_removed":
        return "Сообщение откреплено"
    return body


class _Bus(QObject):
    """Мост фон→GUI: сигналы доставляют результаты сетевых вызовов в главный поток."""
    chats = Signal(list)
    directory = Signal(list)
    history = Signal(str, list)         # conv_id, messages
    opened = Signal(str, str)           # conv_id, title
    status = Signal(str)                # текст статуса (ошибка связи/«пусто») или ""


def _run(fn):
    """Запустить функцию в демон-потоке (сеть не блокирует UI)."""
    threading.Thread(target=fn, daemon=True).start()


class MessengerView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = ""              # id активной беседы
        self._title = ""               # заголовок активной беседы
        self._last_id = 0              # последний показанный id (для опроса)
        self._tab = "chats"            # chats | teacher | student
        self._msgs = {}
        #Черновики (клиент-only, docs/MESSENGER-ADDON-PLAN-GPT.md «Черновики»): недописанное
        #сохраняется при переключении чата в памяти сессии (без диска — мессенджер и так
        #не синкует состояние между устройствами, см. §5.4 CLAUDE.md).
        self._drafts = {}
        self._bus = _Bus()
        self._bus.chats.connect(self._render_chats)
        self._bus.directory.connect(self._render_directory)
        self._bus.history.connect(self._render_history)
        self._bus.opened.connect(self._on_opened)
        self._bus.status.connect(self._render_status)
        self._build()

        self._timer = QTimer(self)
        self._timer.setInterval(3500)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._refresh()

    # ── UI ────────────────────────────────────────────────────────────────────────────
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)

        # Левая колонка: вкладки + поиск + статус + список
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)

        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self._tab_btns = {}
        for key, label in (("chats", "Чаты"), ("teacher", "Преподаватели"), ("student", "Студенты")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self._set_tab(k))
            tabs.addWidget(b)
            self._tab_btns[key] = b
        lv.addLayout(tabs)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск по ФИО…")
        self._search.textChanged.connect(self._on_search)
        lv.addWidget(self._search)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{C['text3']};font-size:12px;padding:2px 4px;")
        self._status.setVisible(False)
        lv.addWidget(self._status)

        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_item)
        self._list.setStyleSheet(
            f"QListWidget{{border:1px solid {C['border']};border-radius:8px;background:{C['card']};}}"
            f"QListWidget::item{{padding:8px;border-bottom:1px solid {C['border']};}}")
        lv.addWidget(self._list, 1)
        left.setMinimumWidth(250)
        split.addWidget(left)

        # Правая колонка: заголовок + лента + композер
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        self._header = QLabel("Выберите чат или найдите человека")
        self._header.setStyleSheet(f"font-weight:700;font-size:15px;color:{C['text']};padding:4px;")
        rv.addWidget(self._header)
        self._thread = QTextBrowser()
        self._thread.setOpenExternalLinks(False)
        self._thread.setStyleSheet(
            f"QTextBrowser{{border:1px solid {C['border']};border-radius:8px;background:{C['bg']};padding:8px;}}")
        rv.addWidget(self._thread, 1)
        comp = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Сообщение… (/vector — спросить ИИ)")
        self._input.returnPressed.connect(self._send)
        self._input.setEnabled(False)
        self._send_btn = QPushButton("Отправить")
        self._send_btn.clicked.connect(self._send)
        self._send_btn.setEnabled(False)
        self._send_btn.setStyleSheet(
            f"QPushButton{{background:{C['green']};color:#fff;border:none;border-radius:8px;padding:8px 16px;}}"
            f"QPushButton:disabled{{background:{C['border']};}}")
        comp.addWidget(self._input, 1)
        comp.addWidget(self._send_btn)
        rv.addLayout(comp)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([290, 610])

        self._style_tabs()

    def _style_tabs(self):
        for key, b in self._tab_btns.items():
            active = key == self._tab
            b.setChecked(active)
            b.setStyleSheet(
                f"QPushButton{{border:none;border-radius:6px;padding:6px 4px;font-weight:600;font-size:12px;"
                f"color:{C['green'] if active else C['text3']};"
                f"background:{C.get('green_glow', C['card2']) if active else 'transparent'};}}")

    # ── Логика вкладок/поиска ───────────────────────────────────────────────────────────
    def _set_tab(self, key):
        self._tab = key
        self._style_tabs()
        self._refresh()

    def _on_search(self, *_):
        self._refresh()

    def _refresh(self):
        q = self._search.text().strip()
        if self._tab == "chats":
            self._status.setVisible(False)
            self.reload_chats()
            return
        role = self._tab

        def work():
            data = mc.users(role, q)
            if data is None:
                self._bus.status.emit("Нет связи с сервером")
                return
            self._bus.status.emit("")
            self._bus.directory.emit(data.get("users", []))
        _run(work)

    # ── Загрузка данных (фон → сигналы) ─────────────────────────────────────────────────
    def reload_chats(self):
        def work():
            data = mc.chats()
            if data is None:
                self._bus.status.emit("Нет связи с сервером")
                return
            self._bus.chats.emit(data.get("chats", []))
        _run(work)

    def _load_history(self, conv_id):
        def work():
            data = mc.messages(conv_id)
            self._bus.history.emit(conv_id, (data or {}).get("messages", []))
        _run(work)

    def _poll(self):
        # Обновляем список чатов (только на вкладке «Чаты») и, если открыт чат, тянем новое.
        if self._tab == "chats":
            self.reload_chats()
        if not self._active:
            return
        conv, last = self._active, self._last_id

        def work():
            data = mc.messages(conv, after=last)
            msgs = (data or {}).get("messages", [])
            if msgs:
                self._bus.history.emit(conv, msgs)
        _run(work)

    # ── Рендер (GUI-поток) ──────────────────────────────────────────────────────────────
    def _render_status(self, text):
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def _render_chats(self, chats):
        if self._tab != "chats":
            return
        q = self._search.text().strip().lower()
        if q:
            chats = [c for c in chats if q in (c.get("title") or "").lower()]
        self._list.clear()
        for c in chats:
            title = c.get("title") or "Диалог"
            unread = c.get("unread") or 0
            label = f"{title}" + (f"   ● {unread}" if unread else "")
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, {"kind": "chat", "id": c.get("conversation_id"), "title": title})
            self._list.addItem(it)
        if self._list.count() == 0:
            self._render_status("Нет переписок — откройте человека во вкладке «Студенты»/«Преподаватели».")
        else:
            self._status.setVisible(False)

    def _render_directory(self, users):
        if self._tab == "chats":
            return
        self._list.clear()
        for u in users:
            sub = (", ".join(u.get("subjects") or []) if u.get("role") == "teacher"
                   else ("гр. " + (u.get("group_name") or "—")))
            dot = "● " if u.get("online") else ""
            it = QListWidgetItem(f"{dot}{u.get('full_name') or '—'}   —   {sub}")
            it.setData(Qt.UserRole, {"kind": "user", "id": u.get("id"), "title": u.get("full_name")})
            self._list.addItem(it)
        if self._list.count() == 0:
            self._render_status("Никого не найдено.")

    def _on_item(self, item):
        d = item.data(Qt.UserRole) or {}
        if d.get("kind") == "chat":
            self._enter(d["id"], d["title"])
        elif d.get("kind") == "user":
            uid = d["id"]

            def work():
                data = mc.open_direct(uid)
                if data:
                    self._bus.opened.emit(data.get("conversation_id", ""), d.get("title") or "")
            _run(work)

    def _on_opened(self, conv_id, title):
        if conv_id:
            self._search.clear()
            self._set_tab("chats")
            self._enter(conv_id, title)

    def _enter(self, conv_id, title):
        if self._active:
            self._drafts[self._active] = self._input.text()
        self._active = conv_id
        self._title = title or "Диалог"
        self._last_id = 0
        self._msgs = {}
        self._header.setText(self._title)
        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._input.setText(self._drafts.get(conv_id, ""))
        self._thread.setHtml("")
        self._load_history(conv_id)

    def _render_history(self, conv_id, msgs):
        if conv_id != self._active or not isinstance(msgs, list):
            return
        # Сливаем по id (история и догрузка новых), затем перерисовываем целиком.
        for m in msgs:
            self._msgs[m["id"]] = m
        ordered = sorted(self._msgs.values(), key=lambda m: m["id"])
        if ordered:
            self._last_id = ordered[-1]["id"]
        self._thread.setHtml(self._html(ordered))
        sb = self._thread.verticalScrollBar()
        sb.setValue(sb.maximum())
        if self._last_id:
            conv, last = self._active, self._last_id
            _run(lambda: mc.read(conv, last))

    def _html(self, msgs):
        parts = ["<div style='font-family:sans-serif;'>"]
        for m in msgs:
            #§D6: системное сообщение — центрированная серая строка, не пузырь.
            if m.get("kind") == "system":
                text = html.escape(format_system_message(m.get("body") or ""))
                parts.append(f"<div style='text-align:center;color:{C['text3']};"
                            f"font-size:11px;margin:6px 0;'>{text}</div>")
                continue
            mine = m.get("mine")
            deleted = m.get("deleted")
            #§D1: Markdown-lite вместо сырого текста; §D8 — упоминания подсвечены жирным.
            body = "Сообщение удалено" if deleted else render_markdown_lite(m.get("body") or "")
            body = re.sub(r"@!?[A-Za-zА-Яа-яЁё]+", lambda mm: f"<u>{mm.group(0)}</u>", body)
            name = html.escape(m.get("sender_name") or "")
            align = "right" if mine else "left"
            bg = C["green"] if mine else C["card"]
            fg = "#ffffff" if mine else C["text"]
            head = f"<div style='font-size:10px;color:{C['green']};'>{name}</div>" if (name and not mine) else ""
            #§D3: реакции — простая строка эмодзи+счётчик под текстом (без интерактива в Qt-порте).
            reactions = m.get("reactions") or []
            react_html = ""
            if reactions:
                react_html = ("<div style='margin-top:3px;font-size:11px;'>"
                             + " ".join(f"{r['emoji']} {r['count']}" for r in reactions) + "</div>")
            parts.append(
                f"<div style='text-align:{align};margin:4px 0;'>"
                f"<div style='display:inline-block;max-width:70%;background:{bg};color:{fg};"
                f"padding:6px 10px;border-radius:12px;text-align:left;'>{head}{body}{react_html}</div></div>")
        parts.append("</div>")
        return "".join(parts)

    def _send(self):
        text = self._input.text().strip()
        if not text or not self._active:
            return
        self._input.clear()
        self._drafts.pop(self._active, None)
        conv, last = self._active, self._last_id

        def work():
            mc.send(conv, text)
            data = mc.messages(conv, after=last)
            self._bus.history.emit(conv, (data or {}).get("messages", []))
        _run(work)
