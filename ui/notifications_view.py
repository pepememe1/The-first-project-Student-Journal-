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
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QListWidget, QListWidgetItem, QTextBrowser, QVBoxLayout, QWidget
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
    "reminder": "Напоминание",
}

#Виды писем, относящиеся к домашним заданиям. Всё остальное — «Система»: оценки и
#расписание приходят по факту действия преподавателя, а ДЗ — задание лично тебе, и в
#общем потоке оно теряется среди десятков оценок.
HOMEWORK_KINDS = ("homework",)
#(ключ фильтра, подпись) — порядок задаёт порядок пунктов в выпадающем списке.
FILTERS = (("all", "Все"), ("homework", "ДЗ"), ("system", "Система"))


def _in_filter(item: dict, key: str) -> bool:
    if key == "all":
        return True
    is_hw = (item.get("kind") or "") in HOMEWORK_KINDS
    return is_hw if key == "homework" else not is_hw


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
    """Список уведомлений + чтение письма. Годится и студенту, и преподавателю."""

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self._filter_box.setToolTip("Показывать только домашние задания или только системные")
        self._filter_box.currentIndexChanged.connect(lambda _i: self._fill())
        head.addWidget(self._filter_box)
        head.addStretch()
        self._status = lbl("", 12, C['text3'])
        head.addWidget(self._status)
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
            #Шрифт задаём ПОСЛЕ добавления: у элемента вне списка своего шрифта ещё нет,
            #и правка до addItem() теряется.
            self._list.addItem(row)
            if not it.get("read_at"):
                f = row.font(); f.setBold(True); row.setFont(f)
        self._list.blockSignals(False)
        if not self._shown:
            self._text.setPlainText(
                "Домашних заданий пока нет." if key == "homework"
                else "Системных уведомлений пока нет." if key == "system"
                else "Уведомлений пока нет.")

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
            f = row_item.font(); f.setBold(False); row_item.setFont(f)
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


class _NoClient:
    """Заглушка на случай «не вошли/нет адреса сервера»: бросает понятную ошибку в
    фоновом потоке, а не роняет интерфейс обращением к None."""

    def __getattr__(self, _name):
        def _fail(*_a, **_kw):
            raise RuntimeError("нет активной сессии с сервером")
        return _fail
