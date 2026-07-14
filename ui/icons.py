"""
icons.py — фирменный набор линейных иконок (вместо эмодзи).

Иконки — самописные SVG в стиле тонкой линии (как Lucide/Feather): один штрих,
скруглённые концы, сетка 24×24. Рисуются через QtSvg и ПЕРЕКРАШИВАЮТСЯ под текущую
тему (цвет текста или акцент), поэтому одинаково аккуратны в светлой и тёмной теме.
Полностью офлайн — никаких внешних файлов и шрифтов-эмодзи.

Использование:
    from icons import icon
    button.setIcon(icon("home", size=18))          # цвет — текущий вторичный текст
    button.setIcon(icon("home", color="#147C8B"))  # явный цвет (напр. акцент)
"""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter

try:
    from PySide6.QtSvg import QSvgRenderer
    _SVG_OK = True
except Exception:                      #QtSvg недоступен — отдадим пустые иконки (фолбэк)
    _SVG_OK = False

#Тело каждой иконки (path/line/circle), общий каркас <svg> добавляем при отрисовке.
#viewBox 0 0 24 24, fill:none, stroke:{c}. Только контуры — перекраска одним цветом.
_BODY = {
    # ── навигация ──
    "home":         '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
    "presentation": '<path d="M3 4h18"/><path d="M4 4v9a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V4"/>'
                    '<path d="M12 17v3"/><path d="M9.5 20h5"/><path d="M8 11l2.5-2.5L13 11l3-3.5"/>',
    "users":        '<path d="M15.5 20v-1.5a3.5 3.5 0 0 0-3.5-3.5H7a3.5 3.5 0 0 0-3.5 3.5V20"/>'
                    '<circle cx="9.5" cy="8" r="3.2"/>'
                    '<path d="M20.5 20v-1.5a3.5 3.5 0 0 0-2.6-3.4"/><path d="M15.5 5.2a3.2 3.2 0 0 1 0 5.6"/>',
    "user":         '<path d="M5 20v-1.5A4.5 4.5 0 0 1 9.5 14h5a4.5 4.5 0 0 1 4.5 4.5V20"/>'
                    '<circle cx="12" cy="8" r="3.5"/>',
    "school":       '<path d="M3 21h18"/><path d="M5 21V8l7-4 7 4v13"/>'
                    '<path d="M9.5 21v-5h5v5"/><path d="M9.5 11h.01"/><path d="M14.5 11h.01"/>',
    "book":         '<path d="M12 6c-1.6-1.2-4-2-6.5-2H4v13h1.5c2.5 0 4.9.8 6.5 2 1.6-1.2 4-2 6.5-2H20V4h-1.5c-2.5 0-4.9.8-6.5 2z"/>'
                    '<path d="M12 6v13"/>',
    "cpu":          '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx="1"/>'
                    '<path d="M9 3v2M12 3v2M15 3v2M9 19v2M12 19v2M15 19v2M3 9h2M3 12h2M3 15h2M19 9h2M19 12h2M19 15h2"/>',
    "globe":        '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>'
                    '<path d="M12 3c2.5 2.4 3.8 5.6 3.8 9s-1.3 6.6-3.8 9c-2.5-2.4-3.8-5.6-3.8-9S9.5 5.4 12 3z"/>',
    "link":         '<path d="M9.5 14.5 14.5 9.5"/>'
                    '<path d="M8 12.5 6.5 14a3.5 3.5 0 0 0 5 5l1.5-1.5"/>'
                    '<path d="M16 11.5 17.5 10a3.5 3.5 0 0 0-5-5L11 6.5"/>',
    "palette":      '<path d="M12 3a9 9 0 0 0 0 18c1 0 1.6-.8 1.6-1.6 0-.4-.2-.8-.5-1.1-.3-.3-.4-.6-.4-1 0-.8.6-1.3 1.4-1.3H15a5 5 0 0 0 5-5c0-4.4-3.6-8-8-8z"/>'
                    '<circle cx="7.5" cy="11" r="1"/><circle cx="12" cy="7.8" r="1"/><circle cx="16.3" cy="11" r="1"/>',
    "activity":     '<path d="M3 12h4l2.5-7 5 14L17 12h4"/>',
    "bot":          '<rect x="4" y="8" width="16" height="11" rx="2.5"/><path d="M12 8V4.5"/><circle cx="12" cy="3.2" r="1.1"/>'
                    '<circle cx="9" cy="13" r="1"/><circle cx="15" cy="13" r="1"/><path d="M2.5 12.5v3M21.5 12.5v3"/>',
    "clipboard":    '<rect x="5" y="5" width="14" height="16" rx="2"/>'
                    '<path d="M9 5V4a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 4v1"/><path d="M9 11h6M9 15h4"/>',
    "chart":        '<path d="M4 4v16h16"/><path d="M8 16v-4M12 16V8.5M16 16v-7"/>',
    "calendar":     '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M4 9.5h16"/>'
                    '<path d="M8 3v4M16 3v4"/>',
    "star":         '<path d="m12 4 2.5 5 5.5.8-4 3.9 1 5.5-5-2.6-5 2.6 1-5.5-4-3.9 5.5-.8z"/>',
    # ── кнопки/действия ──
    "alert-circle": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5"/><path d="M12 16.2h.01"/>',
    "alert-triangle":'<path d="M12 3.5 2.5 20h19z"/><path d="M12 9.5v5"/><path d="M12 17.2h.01"/>',
    "help":         '<circle cx="12" cy="12" r="9"/>'
                    '<path d="M9.6 9.5a2.4 2.4 0 1 1 3.4 2.2c-.8.4-1 .9-1 1.8"/><path d="M12 16.5h.01"/>',
    "send":         '<path d="M5 12h13"/><path d="m12.5 6 6 6-6 6"/>',
    "save":         '<path d="M5 5a1 1 0 0 1 1-1h10l3 3v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/>'
                    '<path d="M8 4v5h7V4"/><rect x="8" y="13" width="8" height="6"/>',
    "plus":         '<path d="M12 5v14M5 12h14"/>',
    "trash":        '<path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M6 7l1 13h10l1-13"/>',
    "edit":         '<path d="M14 5l5 5"/><path d="M4 20l1-4L16 5l3 3L8 19z"/>',
    "back":         '<path d="M19 12H5"/><path d="m11 6-6 6 6 6"/>',
    "play":         '<path d="M7 5l12 7-12 7z"/>',
    "stop":         '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "refresh":      '<path d="M20 8a8 8 0 1 0 1.5 6"/><path d="M20 3v5h-5"/>',
    "folder":       '<path d="M3 7a2 2 0 0 1 2-2h3.5l2 2.5H19a2 2 0 0 1 2 2V18a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',
    "check":        '<path d="M5 12.5 10 17.5 19.5 7"/>',
    "x":            '<path d="M6 6l12 12M18 6 6 18"/>',
    "key":          '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9"/><path d="m18.5 4.5 2 2"/><path d="m15.5 7.5 2 2"/>',
    "shield":       '<path d="M12 3 5 6v5c0 4.4 3 8.2 7 9 4-0.8 7-4.6 7-9V6z"/>',
    "logout":       '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 12h10"/><path d="m16.5 8 4 4-4 4"/>',
    "layers":       '<path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/>',
    "settings":     '<circle cx="12" cy="12" r="3.2"/>'
                    '<path d="M19.4 13.5a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.2a1.6 1.6 0 0 0-2.7-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H3a2 2 0 1 1 0-4h.2a1.6 1.6 0 0 0 1.1-2.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3 1.6 1.6 0 0 0 .9-1.4V3a2 2 0 1 1 4 0v.2a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7H21a2 2 0 1 1 0 4h-.2a1.6 1.6 0 0 0-1.4.9z"/>',
}

#Псевдонимы — удобные смысловые имена под конкретные пункты приложения.
_ALIAS = {
    "dash": "home", "journal": "clipboard", "students": "users", "teachers": "presentation",
    "groups": "school", "subjects": "book", "api": "cpu", "pg": "globe", "server": "globe",
    "requests": "link", "theme": "palette", "mon": "activity", "ai": "bot",
    "stats": "chart", "profile": "user", "debtors": "alert-circle", "risk": "alert-triangle",
    "summary": "clipboard", "groups_q": "layers",
}


def _resolve(name: str) -> str:
    return _ALIAS.get(name, name)


def has(name: str) -> bool:
    """Есть ли иконка с таким именем/псевдонимом."""
    return _resolve(name) in _BODY


def pixmap(name: str, color=None, size: int = 20) -> QPixmap:
    """QPixmap иконки нужного цвета и размера (с учётом DPI). Пусто — если нет иконки."""
    body = _BODY.get(_resolve(name))
    if not (_SVG_OK and body):
        pm = QPixmap(size, size); pm.fill(Qt.transparent); return pm
    if color is None:
        from styles import C
        color = C.get("text3", "#46555F")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="2" stroke-linecap="round" '
           f'stroke-linejoin="round">{body}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    #DPI-чёткость: рисуем в увеличенный буфер и помечаем devicePixelRatio.
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color=None, size: int = 20) -> QIcon:
    """QIcon иконки (для setIcon на кнопках). Перекрашивается под цвет темы."""
    return QIcon(pixmap(name, color, size))
