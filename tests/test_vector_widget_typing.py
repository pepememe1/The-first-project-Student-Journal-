"""
test_vector_widget_typing.py — печать ответа Вектора по символам (§12 из плана правок).

Только вкладка «ИИ Помощник» (docked=False) печатает по символам, как веб-версия
(VectorDock — мгновенно, VectorPage — печатает, см. CLAUDE.md §5.3). Боковая шторка
(docked=True) не участвует: она мелькает поверх журнала, и анимация там мешала бы
читать оценки.

Стаб-сессия ниже НЕ ходит ни в БД, ни в сеть — VectorPanel при сборке трогает только
`session.history`/`session.engine.scope.role` и подписывается на сигналы; реального
VectorEngine с SQLite здесь не нужно.
"""
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6", reason="GUI-тест: нужен PySide6")
from PySide6.QtCore import QObject, Signal, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _StubSession(QObject):
    """Минимальный двойник VectorSession — только то, что трогает VectorPanel.__init__."""
    messageAdded = Signal(str, str)
    thinkingStarted = Signal()
    answered = Signal(str, str, str)
    askFailed = Signal(str)
    speechStarted = Signal()
    speechEnded = Signal()

    def __init__(self, history=None):
        super().__init__()
        self.history = history or [("Вектор", "Привет! Я Вектор.")]
        self.engine = SimpleNamespace(scope=SimpleNamespace(role="student"))

    def is_busy(self) -> bool:
        return False

    def ask(self, question: str):
        pass


def _panel(qapp, docked, history=None):
    from vector.widget import VectorPanel
    session = _StubSession(history=history)
    return VectorPanel(session, docked=docked)


def test_docked_panel_appends_instantly(qapp):
    p = _panel(qapp, docked=True)
    p._append("Вектор", "Готовый ответ целиком")
    assert not p._typing_timer.isActive()
    assert "Готовый ответ целиком" in p.chat.toPlainText()


def test_tab_panel_types_gradually(qapp):
    p = _panel(qapp, docked=False)
    text = "Привет, это ответ Вектора"
    p._append("Вектор", text)
    assert p._typing_timer.isActive(), "во вкладке ответ должен печататься, а не появляться сразу"
    assert text not in p.chat.toPlainText(), "текст не должен быть виден целиком сразу"
    #докручиваем таймер вручную — по тику на символ.
    for _ in range(len(text) + 2):
        p._advance_typing()
    assert not p._typing_timer.isActive()
    assert text in p.chat.toPlainText()


def test_double_click_skips_to_full_text(qapp):
    p = _panel(qapp, docked=False)
    text = "Длинный ответ, который печатается медленно по замыслу"
    p._append("Вектор", text)
    assert p._typing_timer.isActive()
    QTest.mouseDClick(p.chat.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
    assert not p._typing_timer.isActive()
    assert text in p.chat.toPlainText()


def test_new_message_completes_previous_typing_instantly(qapp):
    p = _panel(qapp, docked=False)
    old_answer = "Первый ответ ещё печатается, когда пришёл новый вопрос"
    p._append("Вектор", old_answer)
    assert p._typing_timer.isActive()
    #Новый вопрос («Вы») перебивает недопечатанный ответ — тот должен появиться целиком.
    p._append("Вы", "А теперь другой вопрос")
    assert not p._typing_timer.isActive()
    assert old_answer in p.chat.toPlainText()
    assert "А теперь другой вопрос" in p.chat.toPlainText()


def test_history_hydration_does_not_animate(qapp):
    """Уже накопленная переписка при открытии/переоткрытии вкладки не должна
    печататься заново — animate=False в цикле проигрывания истории (VectorPanel.__init__)."""
    history = [("Вектор", "Привет! Я Вектор."), ("Вы", "Привет"),
              ("Вектор", "Старый ответ из прошлой переписки")]
    p = _panel(qapp, docked=False, history=history)
    assert not p._typing_timer.isActive()
    assert "Старый ответ из прошлой переписки" in p.chat.toPlainText()
