"""
parent_dashboard.py — кабинет РОДИТЕЛЯ на десктопе: тот же Vue-SPA в QWebEngineView.

Почему не нативный Qt-порт (решение согласовано):
  • кабинет родителя — целиком ОНЛАЙН-раздел. Журнал ребёнка открывается только после
    подтверждения студентом, само подтверждение живёт на сервере, мессенджер и Вектор
    тоже онлайновые. Локальных данных у родителя нет и по замыслу быть не должно;
  • инвариант offline-first защищает преподавателя в аудитории без сети — а не родителя
    дома. Ради роли, которой офлайн не нужен, дублировать журнал, Вектора и мессенджер на
    Qt значило бы завести второй фронт и вторую очередь багов;
  • это ровно та же Фаза 0 «один UI», по которой уже живут мессенджер и модерация
    (ui/messenger_web.py) — переиспользуем её панель, а не пишем третью.

Отличие от вкладки «Сообщения»: здесь embed=False, то есть SPA показывает СВОЮ навигацию.
Qt-оболочки с вкладками у родителя нет, и со спрятанным сайдбаром он застрял бы на одной
странице без возможности уйти с неё.
"""
from PySide6.QtWidgets import QVBoxLayout, QWidget

from messenger_web import MessengerWebPanel


class ParentDashboard(QWidget):
    """Весь кабинет родителя одним веб-представлением (журнал, Вектор, чаты, профиль)."""

    def __init__(self, parent_info: dict, parent=None):
        super().__init__(parent)
        self._info = parent_info or {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        #route '/parent' — журнал ребёнка; дальше человек ходит по сайдбару самой SPA.
        self._panel = MessengerWebPanel("/parent", "parent", self, embed=False)
        lay.addWidget(self._panel)

    def display_name(self) -> str:
        return (self._info.get("full_name")
                or self._info.get("login")
                or "Родитель")
