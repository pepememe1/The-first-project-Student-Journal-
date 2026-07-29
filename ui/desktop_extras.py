"""
desktop_extras.py — способности, которые есть ТОЛЬКО у десктопа, поверх общего Vue-кабинета.

Зачем этот модуль вообще существует. Кабинет переезжает на общий Vue-интерфейс, и это
правильно: один код на сайт, телефон и программу. Но у десктопа есть вещи, которых в
браузере нет и не будет — микрофон с локальным распознаванием (голосовые оценки, §5.2)
и управление сервером на ЭТОЙ машине. Если просто заменить кабинет веб-страницей, они
исчезнут вместе с нативными экранами. Это была бы не унификация интерфейса, а потеря
функции.

Поэтому: страницы — общие, десктопные способности — рядом, нативным слоем поверх.

⚠️ Панель Вектора здесь НЕ дубль веб-Вектора. Веб-Вектор умеет спрашивать и отвечать;
нативный вдобавок СЛУШАЕТ микрофон и умеет записывать оценки голосом — на сервер звук
не уходит (152-ФЗ), распознавание идёт на этой машине. Когда голосовой ввод появится в
общем интерфейсе, этот слой станет не нужен и снимется целиком.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

import log

_LOG = log.get("desktop_extras")


def make_vector_session(role: str, context: dict):
    """Сессия Вектора для нативной панели ('None' — если собрать не удалось).

    `context` — ЯВНЫЙ словарь (group/subject/teacher_groups), а не чтение виджетов
    журнала: раньше преподавательский контекст брался прямо из выпадающих списков
    нативного экрана, а в веб-кабинете их нет. Явный контекст заодно честнее — видно,
    что именно знает Вектор."""
    try:
        from vector import VectorEngine, VectorScope, get_provider
        from vector.widget import VectorSession
        try:
            from data_store import get_store
            cfg = get_store()._config()
        except Exception:
            cfg = {}
        scope = VectorScope(role=role,
                            group=context.get("group", ""),
                            subject=context.get("subject") or None,
                            teacher_groups=context.get("teacher_groups") or [])
        return VectorSession(VectorEngine(scope, get_provider(cfg)))
    except Exception as e:
        _LOG.warning(f"[extras] сессия Вектора не собралась: {e}")
        return None


class VoiceVectorOverlay(QWidget):
    """Нативная шторка Вектора поверх веб-кабинета (микрофон и голосовые оценки).

    `ok` — удалось ли собрать. False значит «десктопных способностей не будет», но сам
    кабинет при этом работает: терять весь экран из-за микрофона нельзя."""

    def __init__(self, role: str, context: dict, parent=None):
        super().__init__(parent)
        self.ok = False
        self.session = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        session = make_vector_session(role, context or {})
        if session is None:
            return
        try:
            from vector.widget import VectorPanel
            #docked=True — та же шторка, что и в нативных кабинетах: узкая, с язычком,
            #сворачивается. Отдельный вид ради этого места заводить незачем.
            panel = VectorPanel(session, docked=True)
            lay.addWidget(panel)
            self.session = session
            self.panel = panel
            self.ok = True
        except Exception as e:
            _LOG.warning(f"[extras] панель Вектора не собралась: {e}")


def voice_available() -> bool:
    """Есть ли на этой машине голосовой ввод (пакеты + микрофон).

    Проверяем ДО показа: кнопка микрофона, которая ничего не делает, хуже её отсутствия."""
    try:
        from vector.voice_ui import mic_available
        return bool(mic_available())
    except Exception:
        return False
