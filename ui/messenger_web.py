"""
messenger_web.py — вкладки «Сообщения»/«Модерация» на ДЕСКТОПЕ через встроенный веб-UI.

Фаза 0 стратегии «один UI»: мессенджер — ОНЛАЙН-подсистема (docs/MESSENGER-PLAN.md §13,
offline-first ему не нужен), поэтому вместо повторного порта на Qt показываем тот же
Vue-мессенджер в QWebEngineView. Так десктоп сразу получает жалобы, модерацию, кнопку ⚙ и
все веб-фиксы ОДНИМ кодом, без дублирования.

Как работает вход: JWT текущей сессии (sync_runner.current_auth) кладём в localStorage SPA
ДО загрузки страницы (иначе роут-гард увёл бы на /login). Веб-клиент помечает себя
X-Client: web, поэтому device-барьер к нему НЕ применяется (см. server deps.device_barrier_
applies) — достаточно валидного токена. Флаг gb.embed прячет собственную навигацию SPA
(см. web/src/layouts/AppShell.vue), чтобы не было «навигации внутри навигации».

Важно: сюда выносим ТОЛЬКО онлайн-фичи. Оффлайн-способные (журнал, Вектор с локальным SQL)
остаются нативными — их встроенный веб-view сломал бы без интернета.
"""
import base64
import json

from PySide6.QtCore import QUrl, QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton

_ERR = "Сообщения доступны только онлайн. Проверьте подключение к серверу и вход в аккаунт."
#Сколько раз и как часто молча пробуем подхватить токен, пока пользователь смотрит на
#вкладку. Токен появляется не мгновенно: фоновый синкер логинится через пару секунд после
#входа, и панель, собранная раньше, иначе навсегда осталась бы с надписью «вы не вошли».
_RETRY_MS = 1500
_RETRY_MAX = 20
#Отсрочка предзагрузки: дать дашборду отрисоваться, потом строить веб-view фоном.
_PRELOAD_MS = 400


def _decode_login(token: str) -> str:
    """Логин (claim `sub`) из JWT без проверки подписи — только чтобы заполнить gb.user
    (роль передаётся отдельно, ей доверяем по дашборду). Не удалось разобрать — пусто."""
    try:
        seg = token.split(".")[1]
        seg += "=" * (-len(seg) % 4)                      # добить base64url до кратности 4
        data = json.loads(base64.urlsafe_b64decode(seg))
        return data.get("sub") or ""
    except Exception:
        return ""


class MessengerWebPanel(QWidget):
    """Веб-UI мессенджера/модерации в десктоп-вкладке.

    route_path — путь внутри SPA ('/admin/messages', '/admin/moderation', '/teacher/messages',
    '/student/messages'); role — роль текущего пользователя (для gb.user и роут-гарда SPA)."""

    def __init__(self, route_path: str, role: str, parent=None):
        super().__init__(parent)
        self._route = route_path
        self._role = role
        self._view = None
        self._built = False
        #Защита от ПОВТОРНОГО входа в сборку: создание QWebEngineView прокручивает цикл
        #событий, и за это время успевает прилететь отложенный showEvent (или тик таймера).
        #Без флага панель собирала веб-view ДВАЖДЫ — в окне появлялись два мессенджера.
        self._building = False
        self._tries = 0
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        #Фон самой панели — под тему: пока веб-view грузится, область не должна светиться
        #белым (заметно на тёмной теме).
        try:
            from styles import C
            self.setObjectName("gbMessengerPanel")
            self.setAutoFillBackground(True)
            #Селектор по objectName — иначе правило каскадом легло бы на дочерние виджеты.
            self.setStyleSheet(f"#gbMessengerPanel{{background:{C.get('bg', '#ffffff')};}}")
        except Exception:
            pass
        #Ждём токен, пока вкладка на экране (см. _RETRY_MS): сессия могла ещё не
        #авторизоваться на сервере в момент сборки дашборда.
        self._timer = QTimer(self)
        self._timer.setInterval(_RETRY_MS)
        self._timer.timeout.connect(self._tick)
        #ПРЕДЗАГРУЗКА: строим веб-view сразу после входа, не дожидаясь открытия вкладки —
        #тогда к моменту клика страница уже готова. Но не синхронно в конструкторе: две
        #инициализации QtWebEngine затормозили бы появление дашборда (вход и так чинили).
        #Небольшая отсрочка отдаёт первый кадр окну, а загрузка идёт фоном.
        self._message("Загрузка…", retry=False)
        QTimer.singleShot(_PRELOAD_MS, self._render)

    def showEvent(self, e):
        """Панель строится ЛЕНИВО и переживает «ещё нет токена»: при каждом показе вкладки
        пробуем снова. Раньше вход проверялся один раз в конструкторе, и если дашборд
        собрался до авторизации, вкладка навсегда показывала «Вы не вошли в аккаунт»."""
        super().showEvent(e)
        if not self._built:
            self._render()

    def hideEvent(self, e):
        #Таймер НЕ гасим: панель должна догрузиться в ФОНЕ, пока пользователь на других
        #вкладках. Иначе сборка откладывалась до первого открытия «Сообщений», и человек
        #смотрел на пустой экран несколько секунд. Таймер сам остановится, когда соберётся
        #(_render) или когда исчерпает попытки (_tick).
        super().hideEvent(e)

    def _tick(self):
        self._tries += 1
        if self._built or self._tries > _RETRY_MAX:
            self._timer.stop()
            return
        self._render(auto=True)

    def _clear(self):
        self._view = None
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)          #убрать с экрана СРАЗУ (deleteLater отложен)
                w.deleteLater()

    def _message(self, text: str, retry: bool = True):
        """Диагностика вместо общего «нет связи» + кнопка повтора (ручной путь, если
        автоповтор исчерпан или сервер подняли позже)."""
        self._clear()
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        self._lay.addStretch(1)
        self._lay.addWidget(lbl)
        if retry:
            btn = QPushButton("Повторить")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedWidth(160)
            btn.clicked.connect(self._retry_clicked)
            self._lay.addWidget(btn, 0, Qt.AlignCenter)
        self._lay.addStretch(1)

    def _retry_clicked(self):
        self._tries = 0
        self._render()

    def _render(self, auto: bool = False):
        """Собрать веб-view, если есть адрес и токен; иначе показать причину и ждать."""
        if self._built or self._building:
            return
        try:
            from sync_runner import current_auth
            url, token = current_auth()
        except Exception:
            url, token = ("", "")
        if not url:
            self._message("Не задан адрес сервера. Укажите сервер в настройках и войдите.")
            return
        if not token:
            self._message("Ожидание входа на сервер… Если сообщение не исчезает, нажмите «Повторить».")
            if not auto and not self._timer.isActive():
                self._timer.start()
            return
        try:
            self._building = True
            self._clear()
            self._build_web(self._lay, url.rstrip("/"), token)
            self._built = True
            self._timer.stop()
        except Exception as _e:
            #QtWebEngine недоступен/не инициализировался — не роняем вкладку, показываем причину.
            try:
                from log import get as _log
                _log("messenger_web").warning(f"[messenger_web] веб-view не собрался: {_e}")
            except Exception:
                pass
            self._message(_ERR)
        finally:
            #Снимаем ВСЕГДА: иначе после неудачной сборки панель осталась бы заблокированной
            #и кнопка «Повторить» ничего бы не делала.
            self._building = False

    def _build_web(self, lay, base, token):
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineScript

        if self._view is not None:         #страховка от второго веб-view в одной панели
            return

        login = _decode_login(token)
        user = json.dumps({"login": login, "role": self._role, "name": login})
        #Кладём сессию в localStorage ДО загрузки SPA (DocumentCreation): токен = refresh,
        #сам объект пользователя, флаг embed. json.dumps даёт корректные JS-строковые литералы.
        js = (
            "try{"
            f"localStorage.setItem('gb.access',{json.dumps(token)});"
            f"localStorage.setItem('gb.refresh',{json.dumps(token)});"
            f"localStorage.setItem('gb.user',{json.dumps(user)});"
            "localStorage.setItem('gb.embed','1');"
            "}catch(e){}"
        )
        script = QWebEngineScript()
        script.setName("gb-embed-auth")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(js)

        view = QWebEngineView(self)
        #ПКМ отдаём СТРАНИЦЕ: своё меню Chromium («Назад/Обновить/Сохранить страницу/
        #Посмотреть код») выдавало десктопную обёртку и перебивало контекстное меню
        #сообщения. Пользователю нужно меню мессенджера, а не браузера.
        view.setContextMenuPolicy(Qt.NoContextMenu)
        #Фон страницы — из активной палитры. По умолчанию QtWebEngine красит холст БЕЛЫМ,
        #и на тёмной теме при открытии вкладки резко вспыхивал белый экран, пока SPA не
        #отрисуется. Берём C динамически: палитра меняется (тема по расписанию).
        try:
            from PySide6.QtGui import QColor
            from styles import C
            view.page().setBackgroundColor(QColor(C.get("bg", "#ffffff")))
        except Exception:
            pass
        view.page().scripts().insert(script)
        view.load(QUrl(f"{base}{self._route}?embed=1"))
        lay.addWidget(view)
        self._view = view
