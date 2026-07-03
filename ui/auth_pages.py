"""
auth_pages.py — Страница аутентификации (LoginPage).

Вход единый: студент / преподаватель / администратор определяются по логину и
паролю автоматически. При первом запуске на главном ПК, если пароль администратора
ещё не задан, форма предложит его создать (см. _prompt_admin_setup).
"""

from PySide6.QtCore import Qt, QPoint, QPointF, QPropertyAnimation
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPolygonF, QPainterPath
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QFrame, QInputDialog, QGraphicsOpacityEffect
)

from styles import C
from ui_components import HexLogoWidget, AnimatedBackground


def _rgba(hex_color: str, alpha: float) -> str:
    """hex (#rrggbb) → 'rgba(r,g,b,A)' для QSS, где A — целое 0–255 (Qt так разбирает
    надёжнее, чем дробную долю). alpha задаём как 0.0–1.0."""
    a = max(0, min(255, int(round(alpha * 255))))
    try:
        h = (hex_color or "#ffffff").lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{a})"
    except Exception:
        return f"rgba(255,255,255,{a})"


#Облачко-подсказка и интерактивный маскот на экране входа

class _SpeechBubble(QWidget):
    """Облачко с советом НАД головой Вектора на экране входа.

    Скруглённый прямоугольник с «хвостиком» снизу (указывает вниз, на голову маскота)
    и текстом совета внутри. Ширина фиксированная — текст переносится и не обрезается.
    Появляется/прячется плавным fade; мышь не перехватываем."""
    TAIL = 12                 #высота хвостика снизу
    WIDTH = 300               #фиксированная ширина (чтобы текст всегда влезал, не резался)
    MARGIN = 16               #левый/правый внутренний отступ

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedWidth(self.WIDTH)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(self.MARGIN, 12, self.MARGIN, 12 + self.TAIL)
        lay.setSpacing(4)
        self._title = QLabel("💡 Совет Вектора")
        self._title.setStyleSheet(f"color:{C['green']};font-size:13px;font-weight:800;")
        self._text = QLabel("")
        self._text.setWordWrap(True)
        #ширину текста фиксируем явно — тогда перенос и высота считаются точно
        self._text.setFixedWidth(self.WIDTH - 2 * self.MARGIN)
        #крупнее и контрастнее (line-height в Qt QSS не поддерживается — не используем)
        self._text.setStyleSheet(f"color:{C['text']};font-size:13px;font-weight:600;")
        lay.addWidget(self._title)
        lay.addWidget(self._text)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(180)
        #один слот на всё время жизни (без connect/disconnect на каждый показ —
        #иначе PySide шумит RuntimeWarning «Failed to disconnect»). Прячем виджет,
        #только когда анимация довела прозрачность до нуля.
        self._anim.finished.connect(self._on_anim_done)
        self.hide()

    def _on_anim_done(self):
        if self._fx.opacity() <= 0.02:
            self.hide()

    def set_tip(self, text: str):
        self._text.setText(text or "")
        #высоту считаем НАДЁЖНО через heightForWidth текста (sizeHint у wrap-лейбла врёт),
        #иначе длинные советы обрезались. Складываем поля + заголовок + сам текст + хвостик.
        inner_w = self.WIDTH - 2 * self.MARGIN
        th = self._text.heightForWidth(inner_w)
        if th <= 0:
            from PySide6.QtGui import QFontMetrics
            fm = QFontMetrics(self._text.font())
            th = fm.boundingRect(0, 0, inner_w, 10000, Qt.TextWordWrap, text or "").height()
        title_h = self._title.sizeHint().height()
        self.setFixedHeight(12 + title_h + 4 + th + 12 + self.TAIL)

    def fade_in(self):
        self.show(); self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()

    def fade_out(self):
        self._anim.stop()
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        #тело облачка занимает всё, кроме нижней полоски под хвостик
        r = self.rect().adjusted(1, 1, -1, -1 - self.TAIL)
        path = QPainterPath()
        path.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 14, 14)
        #хвостик СНИЗУ по центру — указывает вниз, на голову Вектора
        cx = self.width() // 2
        by = r.y() + r.height()
        tail = QPolygonF([QPointF(cx - 10, by),
                          QPointF(cx, by + self.TAIL),
                          QPointF(cx + 10, by)])
        path.addPolygon(tail)
        p.setPen(QPen(QColor(C['border2']), 1))
        p.setBrush(QBrush(QColor(C['card'])))
        p.drawPath(path.simplified())
        p.end()


class _LoginMascot(QLabel):
    """Маскот на экране входа. Спокойная поза по умолчанию; при наведении мышки —
    «думающая» поза и облачко с советом (логику показа облачка ведёт LoginPage через
    переданные колбэки on_enter / on_leave)."""

    def __init__(self, default_pm, think_pm, on_enter, on_leave, parent=None):
        super().__init__(parent)
        self._default = default_pm
        self._think = think_pm
        self._on_enter = on_enter
        self._on_leave = on_leave
        self.setPixmap(default_pm)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background:transparent;")

    def enterEvent(self, event):
        if self._think is not None and not self._think.isNull():
            self.setPixmap(self._think)   #«задумался» — пока курсор над Вектором
        try:
            self._on_enter()
        except Exception:
            pass
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setPixmap(self._default)
        try:
            self._on_leave()
        except Exception:
            pass
        super().leaveEvent(event)


def open_site_login(parent=None) -> bool:
    """Открывает сайт журнала в браузере («Войти через сайт»).

    Сайт в перспективе живёт на том же сервере, что и БД, и вход там не требует
    подтверждения устройства (сайт и БД — в одном защищённом месте). Сейчас реализуем
    только саму кнопку: адрес берётся из app_settings.SITE_URL (меняется в коде).
    Авто-вход обратно в приложение после входа на сайте — отдельная задача на будущее.
    Возвращает True, если адрес задан и открыт."""
    from PySide6.QtWidgets import QMessageBox
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtCore import QUrl
    from app_settings import SITE_URL

    url = (SITE_URL or "").strip()
    if not url:
        QMessageBox.information(
            parent, "Сайт не настроен",
            "Адрес сайта пока не задан. Его указывает разработчик в коде "
            "(app_settings.SITE_URL).")
        return False
    QDesktopServices.openUrl(QUrl(url))
    return True


def ask_server_address(parent=None, first_run: bool = False) -> bool:
    """Окно подключения к серверу с подтверждением устройства.

    Шаги: ввод адреса → запрос на подключение (админ видит его во вкладке «Запросы на
    подключение») → ожидание решения → ввод кода, который выдал админ → «подключение
    успешно». ВАЖНО: окно всегда закрываемо («Позже») — чтобы администратор, у которого
    сервер ещё не запущен, не попал в замкнутый круг. first_run=True добавляет кнопку
    «Работать офлайн». Возвращает True, если устройство подтверждено или адрес сохранён."""
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                    QLineEdit, QPushButton, QApplication, QMessageBox)
    from PySide6.QtCore import Qt, QTimer
    import socket
    import threading
    from app_settings import (get_api_url, set_api_url, set_offline_ack,
                              get_device_id, set_device_connected,
                              SUPPORT_PHONE, SITE_URL)

    dlg = QDialog(parent)
    dlg.setWindowTitle("Подключение к серверу")
    dlg.setMinimumWidth(480)
    v = QVBoxLayout(dlg)
    v.setContentsMargins(22, 20, 22, 18)
    v.setSpacing(10)

    #IP этого ПК — пользователю удобно назвать его поддержке/администратору, а админ
    #опознаёт по нему запрос. lan_ip() уже умеет определять адрес в локальной сети.
    try:
        import server_control
        my_ip = server_control.lan_ip() or "—"
    except Exception:
        my_ip = "—"
    ip_lbl = QLabel(f"IP этого компьютера: {my_ip}")
    ip_lbl.setStyleSheet(f"font-size:12px;font-weight:700;color:{C['text']};")
    v.addWidget(ip_lbl)

    title = QLabel("Пожалуйста, введите API сервера для синхронизации")
    title.setWordWrap(True)
    title.setStyleSheet(f"font-size:15px;font-weight:700;color:{C['text']};")
    v.addWidget(title)

    field = QLineEdit()
    field.setText(get_api_url())
    field.setPlaceholderText("https://...  или  http://адрес:8000")
    field.setMinimumHeight(38)
    v.addWidget(field)

    support = QLabel("За ссылкой подключения и подробной информацией обратитесь в "
                     f"поддержку: {SUPPORT_PHONE}")
    support.setWordWrap(True)
    support.setStyleSheet(f"font-size:12px;color:{C['text3']};")
    v.addWidget(support)

    #Поле кода подтверждения — появляется, когда администратор принял запрос.
    code_field = QLineEdit()
    code_field.setPlaceholderText("Код подтверждения (6 цифр)")
    code_field.setMinimumHeight(38)
    code_field.setMaxLength(6)
    code_field.setVisible(False)
    v.addWidget(code_field)

    status = QLabel("")
    status.setWordWrap(True)
    status.setStyleSheet(f"font-size:12px;color:{C['orange']};")
    v.addWidget(status)

    #Состояние диалога. phase: addr (ввод адреса) | wait (ожидание/код). srv — последний
    #статус с сервера, его кладёт фоновый поллер, читает UI-таймер (сеть не на UI-потоке).
    state = {"ok": False, "phase": "addr", "srv": "", "neterr": False}
    poll = {"on": False}

    def _poller():
        """Фоновый опрос статуса запроса (НЕ на UI-потоке, чтобы окно не подвисало)."""
        import time as _t
        while poll["on"]:
            url = get_api_url(); dev = get_device_id()
            if url and dev:
                try:
                    from sync_client import SyncClient
                    state["srv"] = SyncClient(url).connect_status(dev)
                    state["neterr"] = False
                except Exception:
                    state["neterr"] = True
            _t.sleep(2)

    def _go_success():
        set_device_connected(True)
        state["ok"] = True
        poll["on"] = False
        dlg.accept()

    def _set_phase_addr():
        state["phase"] = "addr"
        code_field.setVisible(False)
        b_connect.setVisible(True); b_later.setVisible(True)
        b_verify.setVisible(False); b_cancel.setVisible(False)
        if first_run:
            b_off.setVisible(True)

    def _set_phase_wait():
        state["phase"] = "wait"
        b_connect.setVisible(False); b_later.setVisible(False)
        if first_run:
            b_off.setVisible(False)
        b_cancel.setVisible(True)

    def _tick():
        """UI-таймер: переносит статус из фонового поллера в интерфейс."""
        if state["phase"] != "wait":
            return
        if state["neterr"]:
            status.setText("Сервер недоступен — повторяем попытку...")
        srv = state["srv"]
        if srv == "approved":
            status.setText("Подключение успешно!")
            _go_success()
        elif srv == "code_issued":
            status.setText("Администратор принял запрос. Введите код, который он вам "
                           "сообщил, и нажмите «Подтвердить».")
            code_field.setVisible(True)
            b_verify.setVisible(True)
            code_field.setFocus()
        elif srv == "pending":
            status.setText("Запрос отправлен. Ожидаем подтверждения администратором...")
        elif srv == "rejected":
            status.setText("Подключение отклонено администратором.")
            _set_phase_addr()
            state["srv"] = ""
        elif srv == "none" and not state["neterr"]:
            status.setText("Запрос не найден на сервере — отправьте заново.")
            _set_phase_addr()
            state["srv"] = ""

    timer = QTimer(dlg)
    timer.setInterval(700)
    timer.timeout.connect(_tick)

    def _connect():
        url = field.text().strip()
        if not url:
            status.setText("Введите адрес сервера или нажмите «Позже».")
            return
        set_api_url(url)
        dev = get_device_id()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from sync_client import SyncClient
            res = SyncClient(url).connect_request(dev, socket.gethostname())
        except Exception:
            QApplication.restoreOverrideCursor()
            QMessageBox.information(
                dlg, "Сервер не ответил",
                "Адрес сохранён, но сервер сейчас не ответил. Если он ещё "
                "запускается — попробуйте «Подключиться» снова чуть позже.")
            return
        finally:
            QApplication.restoreOverrideCursor()
        #Устройство уже одобрено ранее (повторный заход) — сразу успех.
        if (res or {}).get("status") == "approved":
            _go_success()
            return
        state["srv"] = "pending"
        _set_phase_wait()
        status.setText("Запрос отправлен. Ожидаем подтверждения администратором...")
        poll["on"] = True
        threading.Thread(target=_poller, daemon=True).start()
        timer.start()

    def _verify():
        code = code_field.text().strip()
        if not code:
            status.setText("Введите код, который сообщил администратор.")
            return
        url = get_api_url(); dev = get_device_id()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from sync_client import SyncClient
            SyncClient(url).connect_verify(dev, code)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            status.setText(_http_detail(e) or "Неверный код подтверждения.")
            return
        finally:
            QApplication.restoreOverrideCursor()
        status.setText("Подключение успешно!")
        _go_success()

    def _later():
        poll["on"] = False
        dlg.reject()

    def _offline():
        set_offline_ack(True)
        poll["on"] = False
        dlg.reject()

    #Кнопки. Часть видна только на своём шаге (переключается _set_phase_*).
    row = QHBoxLayout()
    b_connect = QPushButton("Подключиться"); b_connect.setDefault(True)
    b_connect.clicked.connect(_connect)
    field.returnPressed.connect(_connect)
    row.addWidget(b_connect)

    b_verify = QPushButton("Подтвердить"); b_verify.setVisible(False)
    b_verify.clicked.connect(_verify)
    code_field.returnPressed.connect(_verify)
    row.addWidget(b_verify)

    b_cancel = QPushButton("Отмена"); b_cancel.setVisible(False)
    b_cancel.clicked.connect(_later)
    row.addWidget(b_cancel)

    b_later = QPushButton("Позже")
    b_later.clicked.connect(_later)
    row.addWidget(b_later)

    b_off = QPushButton("Работать офлайн"); b_off.setVisible(bool(first_run))
    b_off.clicked.connect(_offline)
    if first_run:
        row.addWidget(b_off)
    v.addLayout(row)

    #Кнопка «Войти через сайт» — отдельной строкой, если адрес сайта задан в коде.
    if (SITE_URL or "").strip():
        site_btn = QPushButton("🌐 Войти через сайт")
        site_btn.setCursor(Qt.PointingHandCursor)
        site_btn.clicked.connect(lambda: open_site_login(dlg))
        v.addWidget(site_btn)

    #Закрытие окна любым способом гасит фоновый поллер.
    dlg.finished.connect(lambda _=0: poll.__setitem__("on", False))

    dlg.exec()
    poll["on"] = False
    return state["ok"]


def _http_detail(exc) -> str:
    """Достаёт человекочитаемое сообщение об ошибке из ответа сервера (поле detail)."""
    try:
        resp = getattr(exc, "response", None)
        if resp is not None:
            return (resp.json() or {}).get("detail", "") or ""
    except Exception:
        pass
    return ""


#LOGIN PAGE (STUDENT & TEACHER)

class LoginPage(QWidget):
    """Страница входа для студентов и учителей"""
    
    from PySide6.QtCore import Signal as QSignal
    login_student = QSignal(dict)
    login_teacher = QSignal(str, dict)
    login_admin   = QSignal()

    def __init__(self, teachers_db: dict, parent=None):
        super().__init__(parent)
        self.teachers_db   = teachers_db
        self._role         = "student"

        #Живой фон: частицы + «соты» + мягкие пятна (только на экране входа).
        self._bg = AnimatedBackground(self, animated=True)
        self._bg.lower()

        #Бренд в левом верхнем углу окна (лого GB + название), поверх фона. HexLogoWidget
        #рисуется В ЦВЕТАХ ТЕМЫ — поэтому значок сам меняется вместе со сменой темы
        #(тёмная/светлая, кастомный акцент). Позиция задаётся в resizeEvent.
        self._brand = QWidget(self)
        _bl = QHBoxLayout(self._brand)
        _bl.setContentsMargins(0, 0, 0, 0)
        _bl.setSpacing(8)
        _blogo = HexLogoWidget(30)
        _blogo.setFixedSize(30, 30)
        _bname = QLabel("GradeBookAI")
        _bname.setStyleSheet(f"font-size:15px;font-weight:800;color:{C['text']};background:transparent;")
        _bl.addWidget(_blogo)
        _bl.addWidget(_bname)
        self._brand.adjustSize()
        self._brand.raise_()

        #Футер по центру у нижнего края окна (те же надписи, что на сайте).
        self._footer = QLabel(
            "© 2026 GradeBookAI · Технологический колледж ВСГУТУ · команда Synapse", self)
        self._footer.setStyleSheet(f"color:{C['text3']};font-size:11px;background:transparent;")
        self._footer.adjustSize()
        self._footer.raise_()

        #Советы Вектора (для облачка при наведении) — берём из общего источника.
        try:
            from vector.faq import LOGIN_TIPS
            self._tips = list(LOGIN_TIPS)
        except Exception:
            self._tips = ["Логин и пароль выдаёт администратор колледжа."]
        self._tip_idx = 0

        #Main layout
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        outer.setContentsMargins(0, 0, 0, 0)

        #Ряд: Вектор (слева) + карточка входа. КАРТОЧКА держится строго по центру окна,
        #а Вектор стоит слева от неё; справа добавляем равный отступ-балансир (ширина
        #маскота + зазор), поэтому карточка не «съезжает» вправо. Маскот — дефолтная
        #поза из арта Арины (деф+деф). Если арта нет — карточка просто центрируется одна.
        GAP = 40
        row = QHBoxLayout()
        row.setSpacing(0)
        self._mascot = self._make_mascot()
        row.addStretch(1)
        if self._mascot is not None:
            row.addWidget(self._mascot, 0, Qt.AlignVCenter)
            row.addSpacing(GAP)

        #Card frame
        c = QFrame()
        self._login_card = c          #ссылка нужна, чтобы облачко совета не залезало на карточку
        c.setObjectName("loginCard")
        c.setFixedWidth(420)
        c.setStyleSheet(
            "QFrame#loginCard{"
            f"  background:{C['card']};"
            f"  border:1px solid {C['border2']};"
            "  border-radius:18px;"
            "}"
        )
        lay = QVBoxLayout(c)
        lay.setContentsMargins(36, 30, 36, 30)
        lay.setSpacing(12)

        #Logo
        hex_w = HexLogoWidget(54)
        hex_w.setFixedSize(54, 54)
        hex_row = QHBoxLayout()
        hex_row.setAlignment(Qt.AlignCenter)
        hex_row.addWidget(hex_w)
        lay.addLayout(hex_row)

        #Title
        t_lbl = QLabel("GradeBookAI")
        t_lbl.setAlignment(Qt.AlignCenter)
        t_lbl.setStyleSheet(
            f"font-size:24px;font-weight:800;color:{C['text']};"
            "margin-top:6px;margin-bottom:0px;"
        )
        
        sub_lbl = QLabel("Система учёта успеваемости")
        sub_lbl.setAlignment(Qt.AlignCenter)
        sub_lbl.setStyleSheet(f"font-size:12px;color:{C['text3']};margin-bottom:0px;")
        college_lbl = QLabel("Технологический колледж ВСГУТУ")
        college_lbl.setAlignment(Qt.AlignCenter)
        college_lbl.setStyleSheet(
            f"font-size:12px;font-weight:700;color:{C['green']};margin-bottom:4px;"
        )
        lay.addWidget(t_lbl)
        lay.addWidget(sub_lbl)
        lay.addWidget(college_lbl)

        #Поля входа: логин + пароль
        lay.addSpacing(6)
        lay.addWidget(self._mk_label("Логин"))
        self.login_inp = self._mk_input("Введите логин")
        lay.addWidget(self.login_inp)
        lay.addSpacing(8)
        lay.addWidget(self._mk_label("Пароль"))
        self.pass_inp = self._mk_input("••••••••", password=True)
        lay.addWidget(self.pass_inp)
        lay.addSpacing(12)
        b_go = self._mk_btn("Войти")
        b_go.clicked.connect(self._do_login)
        self.login_inp.returnPressed.connect(self._do_login)
        self.pass_inp.returnPressed.connect(self._do_login)
        lay.addWidget(b_go)

        #Сообщение об ошибке
        self.err_lbl = QLabel("")
        self.err_lbl.setWordWrap(True)
        self.err_lbl.setStyleSheet(
            f"color:{C['red']};background:rgba(200,69,62,0.08);"
            f"border:1px solid rgba(200,69,62,0.25);border-radius:8px;"
            "padding:8px 12px;font-size:12px;margin-top:4px;"
        )
        self.err_lbl.hide()
        lay.addWidget(self.err_lbl)

        hint = QLabel("Студенты и преподаватели входят по логину и паролю, "
                      "которые выдал администратор.")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color:{C['text3']};font-size:11px;margin-top:8px;")
        lay.addWidget(hint)

        #Адрес сервера доступен для смены ДО входа любому клиенту: через Serveo он
        #меняется при каждом запуске, и студент/преподаватель должен ввести свежий
        #сам, не заходя в админку.
        srv_btn = QPushButton("⚙ Сервер синхронизации")
        srv_btn.setCursor(Qt.PointingHandCursor)
        srv_btn.setFlat(True)
        srv_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;color:{C['text3']};"
            "font-size:11px;}"
            f"QPushButton:hover{{color:{C['green']};}}")
        srv_btn.clicked.connect(self._open_server_settings)
        lay.addWidget(srv_btn, alignment=Qt.AlignCenter)

        #Вход через сайт — если адрес сайта задан в коде (app_settings.SITE_URL).
        try:
            from app_settings import SITE_URL
        except Exception:
            SITE_URL = ""
        if (SITE_URL or "").strip():
            site_btn = QPushButton("🌐 Войти через сайт")
            site_btn.setCursor(Qt.PointingHandCursor)
            site_btn.setFlat(True)
            site_btn.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;color:{C['text3']};"
                "font-size:11px;}"
                f"QPushButton:hover{{color:{C['green']};}}")
            site_btn.clicked.connect(lambda: open_site_login(self))
            lay.addWidget(site_btn, alignment=Qt.AlignCenter)

        row.addWidget(c, 0, Qt.AlignVCenter)
        #Справа — геройский блок (заголовок + фишки): заполняет прежде пустую часть
        #экрана и «продаёт» продукт. Раскладка: Вектор слева · карточка · герой справа.
        row.addSpacing(GAP)
        row.addWidget(self._build_hero(), 0, Qt.AlignVCenter)
        row.addStretch(1)
        outer.addLayout(row)

        #Облачко-подсказка Вектора живёт поверх всего; позицию задаём при наведении.
        self._tip_bubble = _SpeechBubble(self)

    def _make_mascot(self):
        """Интерактивный Вектор слева от формы. По умолчанию — спокойная поза (деф+деф);
        при наведении мышки переходит в «думающую» позу (думает+думает) и показывает
        облачко с советом. Прозрачные PNG из арта Арины (vector/emotes.py). Нет арта —
        возвращаем None, форма показывается одна (ничего не ломается)."""
        try:
            from vector import emotes
            base = emotes.get(emotes.DEFAULT_FACE, emotes.DEFAULT_GESTURE)
            if base is None or base.isNull():
                return None
            think = emotes.get("думает", "думает")
            H = 560
            base_pm = base.scaledToHeight(H, Qt.SmoothTransformation)
            think_pm = (think.scaledToHeight(H, Qt.SmoothTransformation)
                        if (think is not None and not think.isNull()) else base_pm)
            return _LoginMascot(base_pm, think_pm,
                                self._on_mascot_enter, self._on_mascot_leave)
        except Exception as e:
            print(f"[login] маскот не загрузился: {e}")
            return None

    #--- интерактив маскота: «думает» + облачко с советом при наведении ---
    def _on_mascot_enter(self):
        """Курсор над Вектором: показываем следующий совет в облачке у его головы."""
        if not getattr(self, "_tip_bubble", None) or self._mascot is None:
            return
        tip = self._tips[self._tip_idx % len(self._tips)]
        self._tip_idx += 1
        self._tip_bubble.set_tip(tip)
        bw, bh = self._tip_bubble.width(), self._tip_bubble.height()
        #облачко НАД головой Вектора (по центру фигуры), хвостиком вниз — лицо открыто
        tl = self._mascot.mapTo(self, QPoint(0, 0))
        cx = tl.x() + self._mascot.width() // 2
        x = cx - bw // 2
        y = tl.y() - bh - 6
        x = max(8, min(x, self.width() - bw - 8))  #в пределах окна по горизонтали
        y = max(8, y)                              #если сверху мало места — прижмём к верху
        self._tip_bubble.move(x, y)
        self._tip_bubble.fade_in()

    def _on_mascot_leave(self):
        if getattr(self, "_tip_bubble", None):
            self._tip_bubble.fade_out()

    def _build_hero(self) -> QWidget:
        """Геройский блок справа от карточки — ОДНА цельная «стеклянная» панель.

        Раньше это были разрозненные тёмные коробки с плохим контрастом («чёрная
        таблица»). Теперь весь текст лежит на ОДНОЙ полупрозрачной подложке из цвета
        карточки темы: пара card↔text по дизайну контрастна, поэтому читается и на
        светлой, и на тёмной теме. Внутри — заголовок, подзаголовок, ровные строки-фишки
        и бейдж хакатона."""
        from widgets import title_lbl
        panel = QFrame()
        panel.setObjectName("heroPanel")
        panel.setMaximumWidth(340)
        panel.setStyleSheet(
            f"QFrame#heroPanel{{background:{_rgba(C['card'], 0.92)};"
            f"border:1px solid {C['border2']};border-radius:18px;}}")
        v = QVBoxLayout(panel)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(12)

        head = title_lbl("Журнал, который думает вместе с вами", 24)
        head.setWordWrap(True)
        v.addWidget(head)

        sub = QLabel("Электронный журнал с ИИ-помощником «Вектор»: оценки, средний балл, "
                     "долги и пропуски — понятно и под рукой.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{C['text3']};font-size:13px;")
        v.addWidget(sub)

        v.addSpacing(4)
        for icon_name, text in (("bot", "ИИ-помощник «Вектор»"),
                                ("globe", "Работает офлайн"),
                                ("shield", "Безопасно — по 152-ФЗ")):
            v.addLayout(self._hero_feature(icon_name, text))

        v.addSpacing(6)
        badge = QLabel("🏆  Победитель хакатона «Мы — будущее IT Бурятии»")
        badge.setWordWrap(True)
        badge.setStyleSheet(
            f"color:{C['green']};background:{_rgba(C['green'], 0.10)};"
            f"border:1px solid {_rgba(C['green'], 0.28)};border-radius:10px;"
            "padding:8px 12px;font-size:12px;font-weight:700;")
        v.addWidget(badge)

        try:
            from core import APP_VERSION
            ver = QLabel(f"GradeBookAI · {APP_VERSION}")
            ver.setStyleSheet(f"color:{C['text3']};font-size:10px;")
            v.addWidget(ver)
        except Exception:
            pass
        return panel

    def _hero_feature(self, icon_name: str, text: str) -> QHBoxLayout:
        """Строка-фишка: цветной кружок с иконкой + контрастная подпись (без коробок)."""
        import icons
        from PySide6.QtCore import QSize
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.icon(icon_name, C['green'], 18).pixmap(QSize(18, 18)))
        ic.setFixedSize(22, 22)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(
            f"background:{_rgba(C['green'], 0.12)};border-radius:11px;")
        t = QLabel(text)
        t.setStyleSheet(f"color:{C['text']};font-size:13px;font-weight:600;")
        h.addWidget(ic)
        h.addWidget(t, 1)
        return h

    def _open_server_settings(self):
        """Открывает окно ввода адреса сервера (смена/ввод вручную с экрана входа)."""
        ask_server_address(self, first_run=False)

    #Helper methods
    def _mk_label(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color:{C['text3']};font-size:11px;font-weight:600;"
            "margin-bottom:0px;"
        )
        return l

    def _mk_input(self, placeholder: str, password=False) -> QLineEdit:
        f = QLineEdit()
        f.setPlaceholderText(placeholder)
        if password:
            f.setEchoMode(QLineEdit.Password)
        f.setFixedHeight(40)
        f.setStyleSheet(
            f"QLineEdit{{"
            f"  background:{C['card2']};"
            f"  border:1px solid {C['border2']};"
            f"  border-radius:9px;"
            f"  padding:0px 12px;"
            f"  font-size:13px;"
            f"  color:{C['text']};"
            f"}}"
            f"QLineEdit:focus{{"
            f"  border:1px solid {C['green']};"
            f"  background:{C['card']};"
            f"}}"
        )
        return f

    def _mk_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setFixedHeight(42)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{C['green']};color:#FFFFFF;"
            "border:none;border-radius:10px;"
            "font-size:14px;font-weight:600;}"
            f"QPushButton:hover{{background:{C['green2']};}}"
            f"QPushButton:pressed{{background:{C['green2']};}}"
        )
        return b

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._bg.setGeometry(0, 0, self.width(), self.height())
        #Бренд — в левый верхний угол; футер — по центру у нижнего края окна.
        if getattr(self, "_brand", None) is not None:
            self._brand.move(24, 18)
        if getattr(self, "_footer", None) is not None:
            self._footer.adjustSize()
            self._footer.move((self.width() - self._footer.width()) // 2,
                              self.height() - self._footer.height() - 14)

    def _show_err(self, msg):
        self.err_lbl.setText(msg)
        self.err_lbl.show()

    def _do_login(self):
        """Единый вход по логину и паролю. Роль определяется автоматически."""
        self.err_lbl.hide()
        login = self.login_inp.text().strip()
        pw    = self.pass_inp.text()
        if not login:
            self._show_err("Введите логин")
            return

        from data_store import get_store, AccountLocked
        store = get_store()

        #Свежий ПК (у друга / новая установка): локальных данных ещё нет. Прежде
        #чем проверять вход, пробуем залогиниться на сервер этими же кредами и
        #подтянуть данные — иначе войти было бы нечем (нет ни пользователей, ни
        #пароля админа). Офлайн / неверные креды — тихо пропускаем.
        self._online_bootstrap(login, pw)

        #Первый запуск на хост-ПК: пароль администратора не задан НИГДЕ (и
        #локально, и не подтянулся с сервера выше). Просим задать его.
        if login == store.get_admin_login() and not store.has_admin_password():
            self._prompt_admin_setup(store)
            return

        try:
            res = store.authenticate(login, pw)
        except AccountLocked as e:
            mins = e.seconds // 60 + 1
            self._show_err(f"Слишком много неверных попыток. "
                           f"Повторите через {mins} мин.")
            return
        except Exception as e:
            self._show_err(f"Ошибка входа: {e}")
            return
        if not res:
            self._show_err("Неверный логин или пароль")
            return
        self.login_inp.clear()
        self.pass_inp.clear()
        role = res.get("role")
        #Запоминаем сессию (логин + роль) для персистентного входа: при следующем старте
        #программа сама восстановит этот аккаунт по сохранённому токену, без ввода пароля.
        try:
            from app_settings import set_saved_session
            set_saved_session(login, role)
        except Exception as e:
            print(f"[login] сессия не сохранена: {e}")
        if role == "admin":
            self.login_admin.emit()
        elif role == "teacher":
            self.login_teacher.emit(res["name"], res["data"])
        elif role == "student":
            self.login_student.emit(res["stud"])

    def _online_bootstrap(self, login, pw):
        """Если задан адрес сервера — логинимся к API этими кредами и тянем данные
        в локальную базу. Позволяет ПЕРВЫЙ вход на чистом ПК: пользователей и хеш
        пароля админа берём с сервера. Офлайн/неверные креды — тихо пропускаем,
        дальше сработает обычная локальная проверка."""
        try:
            from app_settings import get_api_url
            url = get_api_url()
            if not url:
                return
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import Qt
            from sync_client import SyncClient
            import sync_engine
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                c = SyncClient(url)
                if not c.health():        #быстрая проверка (3с): офлайн → выходим,
                    return                #чтобы вход не висел на таймауте логина
                c.login(login, pw)        #неверные креды → исключение
                sync_engine.sync_once(c)  #подтянуть данные с сервера в SQLite
            finally:
                QApplication.restoreOverrideCursor()
        except Exception as e:
            print(f"[login] онлайн-подтягивание пропущено: {e}")

    def _prompt_admin_setup(self, store):
        """Диалог первичной установки пароля администратора (только хост-ПК)."""
        QMessageBox.information(
            self, "Первый запуск",
            "Пароль администратора ещё не задан. Сейчас нужно его создать — "
            "это делается один раз на главном ПК. Остальные компьютеры получат "
            "доступ автоматически после синхронизации.")
        pw1, ok = QInputDialog.getText(
            self, "Пароль администратора",
            "Придумайте пароль (не менее 8 символов):", QLineEdit.Password)
        if not ok:
            return
        if len(pw1) < 8:
            self._show_err("Пароль должен быть не короче 8 символов")
            return
        pw2, ok = QInputDialog.getText(
            self, "Подтверждение", "Повторите пароль:", QLineEdit.Password)
        if not ok:
            return
        if pw1 != pw2:
            self._show_err("Пароли не совпадают")
            return
        if store.setup_admin_password(pw1):
            from audit import log_event
            log_event("admin_password_created", store.get_admin_login())
            #ВАЖНО: этот путь идёт мимо authenticate(), поэтому фоновую
            #синхронизацию запускаем здесь вручную — иначе созданные админом
            #данные не уйдут на сервер (и не создастся серверный админ).
            try:
                from sync_runner import start as _sync_start
                _sync_start(store.get_admin_login(), pw1, "admin")
            except Exception as e:
                print(f"[sync] не удалось запустить после first-run: {e}")
            self.login_inp.clear()
            self.pass_inp.clear()
            #Запоминаем сессию админа и для этого пути (он идёт мимо _do_login).
            try:
                from app_settings import set_saved_session
                set_saved_session(store.get_admin_login(), "admin")
            except Exception:
                pass
            QMessageBox.information(self, "Готово", "Пароль администратора создан.")
            self.login_admin.emit()
        else:
            self._show_err("Не удалось сохранить пароль (возможно, он уже задан)")

    def update_teachers(self, db):
        self.teachers_db = db
