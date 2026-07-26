"""
notifications_view.py — вкладка «Уведомления» на десктопе (общая для студента и препода).

Почтовый вид: слева список писем (непрочитанные жирным), справа — текст выбранного.
Уведомления порождает СЕРВЕР (выставление оценки, правка расписания), поэтому в синк
они не входят и читаются по HTTP.

⚠️ Offline-first (§1) при этом не нарушается: это ЧТЕНИЕ справочной информации, а не
операция над журналом. Нет связи — показываем последнее загруженное и честно пишем об
этом. Молча отдавать пустой список нельзя: «уведомлений нет» и «не смогли их получить»
для человека совершенно разные вещи.

Тексты писем приходят с сервера ГОТОВЫМИ и здесь не собираются: тон зависит от роли
(студенту дружелюбно, преподавателю официально), и если бы каждая платформа лепила текст
сама, десктоп, сайт и телефон разъехались бы в формулировках.
"""
import log

from PySide6.QtCore import Qt, QThread, Signal as QSignal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QScrollArea, QTextBrowser, QTextEdit, QVBoxLayout, QWidget
)

from styles import C
from widgets import lbl, title_lbl, btn

_LOG = log.get("notifications")

#Подпись типа события. У писем, созданных до появления текста, title/body пустые —
#тогда заголовок берём отсюда, чтобы строка в списке не была пустой.
KIND_LABEL = {
    "grade": "Новая оценка",
    "grade_changed": "Оценка изменена",
    "schedule_changed": "Расписание изменилось",
    "homework": "Домашнее задание",
    "event": "Мероприятие",
    "reminder": "Напоминание",
}

#Оценки — отдельно от «Система» (по просьбе: системные — только то, что пишет админ
#вручную/расписание). ДЗ — отдельно, иначе теряется среди оценок. Мероприятия (олимпиады/
#конкурсы, заводят препод/админ) — тоже отдельно, это не рутинная системная почта.
KIND_FILTER = {"grade": "grades", "grade_changed": "grades", "homework": "homework", "event": "events"}
#(ключ фильтра, подпись) — порядок задаёт порядок пунктов в выпадающем списке.
FILTERS = (("all", "Все"), ("grades", "Оценки"), ("homework", "ДЗ"),
          ("events", "Мероприятия"), ("system", "Система"))


def _in_filter(item: dict, key: str) -> bool:
    if key == "all":
        return True
    return KIND_FILTER.get(item.get("kind") or "", "system") == key


#Точки вместо жирного текста для непрочитанного (порт NotificationsInbox.vue): красная
#закрашенная — непрочитано, серая контурная («выколотая») — прочитано. Иконки маленькие и
#одинаковые для всех строк — генерируем и кэшируем один раз, а не на каждый addItem.
_DOT_ICONS = {}


def _dot_icon(unread: bool) -> QIcon:
    if unread in _DOT_ICONS:
        return _DOT_ICONS[unread]
    size = 10
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if unread:
        p.setBrush(QColor(C.get("red", "#d14343")))
        p.setPen(Qt.NoPen)
    else:
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(C.get("text3", "#6b8085")), 1.4))
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    icon = QIcon(pm)
    _DOT_ICONS[unread] = icon
    return icon


class _BgWorker(QThread):
    """Выполняет fn() в фоне; результат/ошибка — через сигналы (как в schedule_view)."""
    done = QSignal(object)
    error = QSignal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except Exception as e:
            self.error.emit(str(e))


def _client():
    """Клиент с ЖИВОЙ сессией или None (не вошли / нет адреса сервера).

    Берём fresh_auth, а не current_auth: access живёт жёстко 5 ч, и с протухшим токеном
    /me/events отвечал 401 — уведомления «не загрузились», хотя человек в программе.
    fresh_auth тихо продлевает сессию по refresh-токену, без ввода пароля."""
    import sync_runner
    try:
        url, token = sync_runner.fresh_auth()
    except Exception:
        url, token = sync_runner.current_auth()
    if not url or not token:
        return None
    from sync_client import SyncClient
    return SyncClient(url, token=token)


class NotificationsView(QWidget):
    """Список уведомлений + чтение письма. Годится и студенту, и преподавателю.

    `role`/`groups` — только для кнопки «Мероприятие» (§12): создавать её может лишь
    teacher/admin, а список групп для выбора аудитории берём у вызывающего дашборда
    (десктоп офлайн-first — своих групп он и так уже знает локально, см. teacher_dashboard.
    py::_ensure_vector_session, лишний REST-запрос за тем же списком не нужен)."""

    def __init__(self, parent=None, role: str = "", groups=None):
        super().__init__(parent)
        self._role = role or ""
        self._groups = list(groups or [])
        self._workers = []
        self._items = []        #все загруженные письма
        self._shown = []        #те, что сейчас в списке (после фильтра) — строка ↔ письмо
        self._loading = False
        self._build()
        #НЕ грузим здесь: при сборке дашборда серверная сессия ещё не готова → первый запрос
        #падал в «Нет связи», и приходилось жать «Обновить». Грузим в showEvent — когда вкладку
        #реально открыли (к этому моменту вход выполнен).

    def showEvent(self, event):
        super().showEvent(event)
        #Автообновление при показе вкладки (без повторов, если запрос уже в пути).
        if not self._loading:
            self.reload()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(title_lbl("Уведомления", 20))
        head.addSpacing(12)
        self._filter_box = QComboBox()
        for _key, label in FILTERS:
            self._filter_box.addItem(label)
        self._filter_box.setToolTip("Показать только один вид уведомлений")
        self._filter_box.currentIndexChanged.connect(lambda _i: self._fill())
        head.addWidget(self._filter_box)
        head.addStretch()
        self._status = lbl("", 12, C['text3'])
        head.addWidget(self._status)
        #§12: мероприятие/событие — заводит только препод/админ (сервер тоже проверит роль).
        if self._role in ("teacher", "admin"):
            event_b = btn("Мероприятие", "ghost")
            event_b.clicked.connect(self._open_create_event)
            head.addWidget(event_b)
        refresh_b = btn("Обновить", "ghost")
        refresh_b.clicked.connect(self.reload)
        head.addWidget(refresh_b)
        self._read_all_b = btn("Прочитать все", "ghost")
        self._read_all_b.clicked.connect(self._mark_all)
        head.addWidget(self._read_all_b)
        lay.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)
        self._list = QListWidget()
        self._list.setMinimumWidth(320)
        self._list.currentRowChanged.connect(self._open)
        body.addWidget(self._list, 1)

        self._text = QTextBrowser()
        self._text.setOpenExternalLinks(False)
        body.addWidget(self._text, 2)
        lay.addLayout(body, 1)

    #Загрузка

    def reload(self):
        self._loading = True
        self._status.setText("Загружаем…")
        self._run(lambda: (_client() or _NoClient()).list_notifications(),
                  self._on_loaded, self._on_failed)

    def _run(self, fn, on_done, on_error):
        w = _BgWorker(fn)
        w.done.connect(on_done)
        w.error.connect(on_error)
        #Держим ссылку: сборщик мусора убил бы поток на середине запроса.
        self._workers.append(w)
        w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        w.start()

    def _on_loaded(self, data):
        self._loading = False
        self._items = (data or {}).get("items", []) or []
        unread = (data or {}).get("unread", 0)
        self._status.setText(
            f"Непрочитанных: {unread}" if unread else "Все уведомления прочитаны")
        self._read_all_b.setEnabled(bool(unread))
        self._fill()

    def _on_failed(self, msg):
        self._loading = False
        _LOG.warning(f"[уведомления] не загрузились: {msg}")
        #Список НЕ чистим: показать пустоту при обрыве связи значило бы соврать, что
        #уведомлений нет. Оставляем прошлые и говорим, что данные могли устареть.
        self._status.setText("Нет связи с сервером — показаны загруженные ранее")

    def _fill(self):
        key = FILTERS[max(0, self._filter_box.currentIndex())][0]
        #Отдельный список показанных писем: при включённом фильтре номер строки больше
        #не совпадает с индексом в self._items, и _open открывал бы чужое письмо.
        self._shown = [it for it in self._items if _in_filter(it, key)]
        self._list.blockSignals(True)
        self._list.clear()
        for it in self._shown:
            title = it.get("title") or KIND_LABEL.get(it.get("kind"), "Уведомление")
            when = (it.get("created_at") or "")[:10]
            row = QListWidgetItem(f"{title}\n{when}")
            #Точка вместо жирного (см. _dot_icon): красная закрашенная — непрочитано,
            #контурная — прочитано.
            row.setIcon(_dot_icon(not it.get("read_at")))
            self._list.addItem(row)
        self._list.blockSignals(False)
        if not self._shown:
            _EMPTY = {"homework": "Домашних заданий пока нет.", "grades": "Оценок пока нет.",
                     "events": "Мероприятий пока нет.", "system": "Системных уведомлений пока нет."}
            self._text.setPlainText(_EMPTY.get(key, "Уведомлений пока нет."))

    #Чтение

    def _open(self, row: int):
        if row < 0 or row >= len(self._shown):
            return
        it = self._shown[row]
        title = it.get("title") or KIND_LABEL.get(it.get("kind"), "Уведомление")
        body = it.get("body") or "Откройте журнал, чтобы посмотреть подробности."
        when = (it.get("created_at") or "").replace("T", " ")[:16]
        self._text.setHtml(
            f"<h3 style='margin-bottom:4px'>{title}</h3>"
            f"<p style='color:{C['text3']};font-size:12px;margin-top:0'>{when}</p>"
            f"<p style='font-size:14px;line-height:1.5'>{body}</p>")

        if it.get("read_at"):
            return
        #Помечаем прочитанным оптимистично: письмо человек уже открыл. Не дойдёт запрос —
        #худшее последствие в том, что счётчик сойдётся только при следующей загрузке.
        it["read_at"] = "now"
        row_item = self._list.item(row)
        if row_item:
            row_item.setIcon(_dot_icon(False))
        eid = it.get("id") or ""
        if eid:
            self._run(lambda: (_client() or _NoClient()).mark_notification_read(eid),
                      lambda _r: None, lambda _e: None)

    def _mark_all(self):
        for it in self._items:
            it["read_at"] = it.get("read_at") or "now"
        self._fill()
        self._status.setText("Все уведомления прочитаны")
        self._read_all_b.setEnabled(False)
        self._run(lambda: (_client() or _NoClient()).mark_all_notifications_read(),
                  lambda _r: None, lambda _e: None)

    # ── §12: создать мероприятие/событие (олимпиада, конкурс и т.п.) ────────────────────
    def _open_create_event(self):
        dlg = _CreateEventDialog(self._role, self._groups, self)
        dlg.exec()


class _CreateEventDialog(QDialog):
    """§12: форма «Мероприятие» (олимпиада, конкурс, выступление и т.п.).

    Препод шлёт только своим группам (мультивыбор чекбоксами — свои группы уже
    известны локально, см. NotificationsView.__init__). Админ может выбрать «Все
    группы» (groups=[] — сервер трактует пустой список как «всем») или перечислить
    конкретные группы вручную (у админа на десктопе нет готового списка всех групп
    под рукой, а тянуть его отдельным REST-запросом ради одной формы избыточно)."""

    def __init__(self, role: str, groups: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новое мероприятие")
        self.setMinimumWidth(420)
        self._role = role
        self._groups = list(groups or [])
        self._group_checks = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        lay.addWidget(lbl("Заголовок", 12, C['text3']))
        self._title = QLineEdit()
        self._title.setPlaceholderText("Например: Олимпиада по программированию")
        lay.addWidget(self._title)

        lay.addWidget(lbl("Описание", 12, C['text3']))
        self._body = QTextEdit()
        self._body.setPlaceholderText("Подробности: когда, где, как участвовать…")
        self._body.setFixedHeight(100)
        lay.addWidget(self._body)

        lay.addWidget(lbl("Кому отправить", 12, C['text3']))
        if self._role == "admin":
            self._all_groups = QCheckBox("Все группы")
            self._all_groups.setChecked(True)
            self._all_groups.toggled.connect(self._toggle_manual)
            lay.addWidget(self._all_groups)
            self._manual = QLineEdit()
            self._manual.setPlaceholderText("Или перечислите группы через запятую")
            self._manual.setEnabled(False)
            lay.addWidget(self._manual)
        else:
            self._all_groups = None
            self._manual = None
            box = QWidget()
            box_lay = QVBoxLayout(box)
            box_lay.setContentsMargins(0, 0, 0, 0)
            box_lay.setSpacing(2)
            for g in self._groups:
                cb = QCheckBox(g)
                cb.setChecked(True)
                box_lay.addWidget(cb)
                self._group_checks.append(cb)
            if not self._groups:
                box_lay.addWidget(lbl("Нет своих групп — некому отправлять.", 12, C['text3']))
            scroll = QScrollArea()
            scroll.setWidget(box)
            scroll.setWidgetResizable(True)
            scroll.setMaximumHeight(140)
            lay.addWidget(scroll)

        row = QHBoxLayout()
        row.addStretch()
        cancel_b = btn("Отмена", "ghost")
        cancel_b.clicked.connect(self.reject)
        row.addWidget(cancel_b)
        self._send_b = btn("Отправить", "green")
        self._send_b.clicked.connect(self._submit)
        row.addWidget(self._send_b)
        lay.addLayout(row)

    def _toggle_manual(self, all_checked: bool):
        self._manual.setEnabled(not all_checked)

    def _selected_groups(self) -> list:
        if self._role == "admin":
            if self._all_groups.isChecked():
                return []
            return [g.strip() for g in self._manual.text().split(",") if g.strip()]
        return [cb.text() for cb in self._group_checks if cb.isChecked()]

    def _submit(self):
        title = self._title.text().strip()
        body = self._body.toPlainText().strip()
        if not title or not body:
            QMessageBox.warning(self, "Мероприятие", "Заполните заголовок и описание.")
            return
        groups = self._selected_groups()
        if self._role != "admin" and not groups:
            QMessageBox.warning(self, "Мероприятие", "Выберите хотя бы одну группу.")
            return
        self._send_b.setEnabled(False)
        self._send_b.setText("Отправляем…")
        w = _BgWorker(lambda: (_client() or _NoClient()).create_event(title, body, groups))
        w.done.connect(lambda _r: self._on_sent())
        w.error.connect(self._on_failed)
        self._worker = w
        w.start()

    def _on_sent(self):
        QMessageBox.information(self, "Мероприятие", "Отправлено.")
        self.accept()

    def _on_failed(self, msg: str):
        self._send_b.setEnabled(True)
        self._send_b.setText("Отправить")
        QMessageBox.warning(self, "Мероприятие", f"Не удалось отправить: {msg}")


class _NoClient:
    """Заглушка на случай «не вошли/нет адреса сервера»: бросает понятную ошибку в
    фоновом потоке, а не роняет интерфейс обращением к None."""

    def __getattr__(self, _name):
        def _fail(*_a, **_kw):
            raise RuntimeError("нет активной сессии с сервером")
        return _fail
