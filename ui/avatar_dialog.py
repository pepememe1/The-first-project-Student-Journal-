"""
avatar_dialog.py — загрузка/обрезка аватарки на ДЕСКТОПЕ (Qt).

Кроппер: выбираем файл, двигаем (перетаскивание) и масштабируем (ползунок/колесо) картинку
в круглой рамке, чтобы «определить границы и нормально поставить», затем сохраняем. Экспорт —
квадрат 256×256 JPEG (data:URL) — тот же формат, что на вебе (prefs.avatar). Плюс готовая
секция avatar_section() для встраивания в настройки: превью + «Изменить».
"""
import base64

from PySide6.QtCore import Qt, QPoint, QRect, QBuffer, QByteArray
from PySide6.QtGui import QPixmap, QPainter, QImage, QPainterPath, QColor
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider, QFileDialog,
    QTextEdit,
)

VP = 256          # размер вьюпорта/экспорта в пикселях


class _CropCanvas(QWidget):
    """Квадрат VP×VP: рисует картинку с pan/zoom под круглой маской; экспорт — 256×256 JPEG."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(VP, VP)
        self._pix = None
        self._base = 1.0        # «cover»-масштаб
        self._zoom = 1.0        # множитель поверх cover
        self._off = QPoint(0, 0)
        self._last = None

    def has_image(self) -> bool:
        return self._pix is not None

    def load(self, pix: QPixmap):
        self._pix = pix
        self._base = max(VP / max(1, pix.width()), VP / max(1, pix.height()))
        self._zoom = 1.0
        w, h = pix.width() * self._base, pix.height() * self._base
        self._off = QPoint(int((VP - w) / 2), int((VP - h) / 2))
        self.update()

    def set_zoom(self, z: float):
        self._zoom = max(1.0, min(5.0, z))
        self._clamp()
        self.update()

    def _clamp(self):
        if not self._pix:
            return
        s = self._base * self._zoom
        w, h = self._pix.width() * s, self._pix.height() * s
        self._off = QPoint(min(0, max(int(VP - w), self._off.x())),
                           min(0, max(int(VP - h), self._off.y())))

    def mousePressEvent(self, e):
        self._last = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._last and self._pix:
            p = e.position().toPoint()
            self._off += p - self._last
            self._last = p
            self._clamp()
            self.update()

    def mouseReleaseEvent(self, e):
        self._last = None

    def wheelEvent(self, e):
        if self._pix:
            self.set_zoom(self._zoom + (0.1 if e.angleDelta().y() > 0 else -0.1))

    def _render(self, painter: QPainter):
        if not self._pix:
            return
        s = self._base * self._zoom
        painter.drawPixmap(QRect(self._off.x(), self._off.y(),
                                 int(self._pix.width() * s), int(self._pix.height() * s)),
                           self._pix)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addEllipse(0, 0, VP, VP)           # круглая рамка-превью
        p.setClipPath(path)
        p.fillRect(0, 0, VP, VP, QColor("#eef2f3"))
        self._render(p)

    def export_dataurl(self) -> str:
        """Обрезанный квадрат 256×256 → data:URL (JPEG). Хранится квадратом, а круглым его
        делает уже отображение (маска), как на вебе."""
        if not self._pix:
            return ""
        img = QImage(VP, VP, QImage.Format_RGB32)
        img.fill(QColor("#ffffff"))
        pr = QPainter(img)
        pr.setRenderHint(QPainter.SmoothPixmapTransform)
        self._render(pr)
        pr.end()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.WriteOnly)
        img.save(buf, "JPEG", 85)
        return "data:image/jpeg;base64," + base64.b64encode(bytes(ba)).decode("ascii")


def _pixmap_from_dataurl(data_url: str) -> QPixmap:
    pix = QPixmap()
    try:
        if data_url and "," in data_url:
            pix.loadFromData(base64.b64decode(data_url.split(",", 1)[1]))
    except Exception:
        pass
    return pix


class AvatarDialog(QDialog):
    """Модалка обрезки. После exec(): result_value() = None (отмена) | '' (удалить) | data:URL."""

    def __init__(self, current: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Аватарка")
        self._value = None
        lay = QVBoxLayout(self)

        self._canvas = _CropCanvas()
        lay.addWidget(self._canvas, 0, Qt.AlignCenter)
        if current:
            pix = _pixmap_from_dataurl(current)
            if not pix.isNull():
                self._canvas.load(pix)

        hint = QLabel("Перетаскивайте и масштабируйте, чтобы поместить в рамку.")
        hint.setStyleSheet("color:#6b8085;font-size:12px;")
        hint.setAlignment(Qt.AlignCenter)
        lay.addWidget(hint)

        sl = QSlider(Qt.Horizontal)
        sl.setMinimum(100)
        sl.setMaximum(500)
        sl.setValue(100)
        sl.valueChanged.connect(lambda v: self._canvas.set_zoom(v / 100))
        lay.addWidget(sl)

        pick = QPushButton("Выбрать изображение")
        pick.clicked.connect(self._pick)
        lay.addWidget(pick)

        row = QHBoxLayout()
        save = QPushButton("Сохранить")
        save.clicked.connect(self._save)
        rm = QPushButton("Удалить")
        rm.clicked.connect(self._remove)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        row.addWidget(save)
        row.addWidget(rm)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Изображение", "", "Изображения (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            pix = QPixmap(path)
            if not pix.isNull():
                self._canvas.load(pix)

    def _save(self):
        if not self._canvas.has_image():
            self.reject()
            return
        self._value = self._canvas.export_dataurl()
        self.accept()

    def _remove(self):
        self._value = ""
        self.accept()

    def result_value(self):
        return self._value


class AvatarSection(QWidget):
    """Секция «Профиль»: аватарка + «О себе» (со счётчиком остатка) + цвет плашки.

    Всё это ПУБЛИЧНО — другие видят карточку в мессенджере. Поля те же, что на вебе
    (prefs.avatar / prefs.bio / prefs.profile_color), поэтому профиль общий для платформ.
    Сохраняем через avatar_service (локальный кэш + prefs-роуминг)."""

    def __init__(self, role: str, identity: dict = None, parent=None):
        super().__init__(parent)
        self._role = role
        self._identity = identity or {}
        root = QVBoxLayout(self)
        #Поля по краям: без них секция «склеивалась» с панелью и левым краем окна.
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        #Строка аватарки
        row = QHBoxLayout()
        row.setSpacing(12)
        self._preview = QLabel()
        self._preview.setFixedSize(64, 64)
        self._preview.setAlignment(Qt.AlignCenter)
        row.addWidget(self._preview, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(4)
        col.addStretch(1)
        title = QLabel("Аватарка")
        title.setStyleSheet("font-weight:700;font-size:14px;")
        col.addWidget(title)
        btn = QPushButton("Изменить…")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedWidth(140)
        btn.clicked.connect(self._edit)
        col.addWidget(btn)
        col.addStretch(1)
        row.addLayout(col)
        row.addStretch(1)
        root.addLayout(row)

        self._build_bio(root)
        self._build_colors(root)
        self._build_win_login(root)
        self._refresh()

    # ── Вход по Windows (выключатель + стирание сохранённого пароля) ────────────────
    def _build_win_login(self, root):
        """Показываем секцию только там, где такой вход возможен (Windows). Включение
        происходит на экране входа (там есть пароль); здесь — статус и отключение."""
        try:
            import win_login
            if not win_login.available():
                return
        except Exception:
            return
        cap = QLabel("Вход по Windows")
        cap.setStyleSheet("font-weight:700;font-size:14px;")
        root.addWidget(cap)
        row = QHBoxLayout()
        self._win_state = QLabel()
        self._win_state.setWordWrap(True)
        self._win_state.setStyleSheet("color:#6b8085;font-size:12px;")
        row.addWidget(self._win_state, 1)
        self._win_btn = QPushButton()
        self._win_btn.setCursor(Qt.PointingHandCursor)
        self._win_btn.setFixedWidth(160)
        self._win_btn.clicked.connect(self._toggle_win_login)
        row.addWidget(self._win_btn, 0, Qt.AlignRight)
        root.addLayout(row)
        self._refresh_win_login()

    def _refresh_win_login(self):
        import win_login
        who = win_login.enabled_login()
        if who:
            self._win_state.setText(
                f"Включён для «{who}». Пароль хранится на этом ПК в зашифрованном виде "
                "(DPAPI) и открывается подтверждением Windows.")
            self._win_btn.setText("Отключить")
        else:
            self._win_state.setText(
                "Выключен. Включить можно на экране входа — программа предложит это после "
                "входа по паролю. Только для личного компьютера.")
            self._win_btn.setText("Отключён")
            self._win_btn.setEnabled(False)

    def _toggle_win_login(self):
        """Отключение = СТИРАНИЕ сохранённого пароля (не просто флаг)."""
        import win_login
        from PySide6.QtWidgets import QMessageBox
        if not win_login.enabled_login():
            return
        ok = QMessageBox.question(
            self.window(), "Вход по Windows",
            "Отключить вход по Windows и стереть сохранённый пароль с этого компьютера?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if ok == QMessageBox.Yes:
            win_login.disable()
            self._win_btn.setEnabled(False)
            self._refresh_win_login()

    # ── «О себе» ────────────────────────────────────────────────────────────────────
    def _build_bio(self, root):
        import avatar_service
        cap = QLabel("О себе")
        cap.setStyleSheet("font-weight:700;font-size:14px;")
        root.addWidget(cap)
        self._bio = QTextEdit()
        self._bio.setPlaceholderText("Короткий текст — его видят другие в вашем профиле.")
        self._bio.setFixedHeight(70)
        self._bio.setPlainText(avatar_service.get_bio(self._role, self._identity))
        self._bio.textChanged.connect(self._on_bio_changed)
        root.addWidget(self._bio)

        line = QHBoxLayout()
        self._counter = QLabel()
        self._counter.setStyleSheet("color:#6b8085;font-size:12px;")
        line.addWidget(self._counter)
        line.addStretch(1)
        save = QPushButton("Сохранить")
        save.setCursor(Qt.PointingHandCursor)
        save.setFixedWidth(140)
        save.clicked.connect(self._save_bio)
        line.addWidget(save)
        root.addLayout(line)
        self._update_counter()

    def _on_bio_changed(self):
        """Жёстко держим лимит: сервер всё равно обрежет, но пользователь должен видеть
        границу СРАЗУ, а не терять хвост текста после сохранения."""
        import avatar_service
        text = self._bio.toPlainText()
        if len(text) > avatar_service.BIO_LIMIT:
            cur = self._bio.textCursor()
            pos = cur.position()
            self._bio.blockSignals(True)
            self._bio.setPlainText(text[:avatar_service.BIO_LIMIT])
            cur.setPosition(min(pos, avatar_service.BIO_LIMIT))
            self._bio.setTextCursor(cur)
            self._bio.blockSignals(False)
        self._update_counter()

    def _update_counter(self):
        import avatar_service
        left = avatar_service.BIO_LIMIT - len(self._bio.toPlainText())
        self._counter.setText(f"Осталось символов: {left}")

    def _save_bio(self):
        import avatar_service
        avatar_service.save_profile(self._role, self._identity, bio=self._bio.toPlainText())

    # ── Цвет плашки профиля ─────────────────────────────────────────────────────────
    def _build_colors(self, root):
        """Те же пресеты, что у темы оформления (themes.PRESETS) — один список на всю
        программу, чтобы палитры профиля и темы не разъезжались."""
        import avatar_service
        cap = QLabel("Цвет профиля")
        cap.setStyleSheet("font-weight:700;font-size:14px;")
        root.addWidget(cap)
        try:
            from themes import PRESETS
        except Exception:
            return
        self._color = avatar_service.get_profile_color(self._role, self._identity)
        self._swatches = {}
        grid = QHBoxLayout()
        grid.setSpacing(6)
        for preset in PRESETS:
            pid = preset.get("id", "")
            accent = preset.get("accent", "#888888")
            b = QPushButton()
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(26, 26)
            b.setToolTip(preset.get("name", pid))
            b.clicked.connect(lambda _=False, i=pid: self._pick_color(i))
            self._swatches[pid] = (b, accent)
            grid.addWidget(b)
        grid.addStretch(1)
        root.addLayout(grid)
        self._paint_swatches()

    def _paint_swatches(self):
        """Выбранный кружок обводим — видно, какой цвет активен."""
        for pid, (b, accent) in getattr(self, "_swatches", {}).items():
            border = "3px solid #ffffff" if pid == self._color else "1px solid rgba(0,0,0,0.15)"
            b.setStyleSheet(
                f"QPushButton{{background:{accent};border:{border};border-radius:13px;}}")

    def _pick_color(self, preset_id: str):
        import avatar_service
        self._color = preset_id
        self._paint_swatches()
        avatar_service.save_profile(self._role, self._identity, color=preset_id)

    def _circle(self, pix) -> QPixmap:
        """64×64 круглый pixmap: аватар (если есть) либо аккуратный серый плейсхолдер."""
        out = QPixmap(64, 64)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addEllipse(0, 0, 64, 64)
        p.setClipPath(path)
        if pix is not None and not pix.isNull():
            p.drawPixmap(0, 0, 64, 64, pix)
        else:
            p.fillRect(0, 0, 64, 64, QColor("#dfe6e8"))
            p.setPen(QColor("#6b8085"))
            f = p.font()
            f.setPixelSize(11)
            p.setFont(f)
            p.drawText(0, 0, 64, 64, Qt.AlignCenter, "фото")
        p.end()
        return out

    def _refresh(self):
        import avatar_service
        data_url = avatar_service.get_avatar(self._role, self._identity)
        pix = _pixmap_from_dataurl(data_url) if data_url else QPixmap()
        self._preview.setPixmap(self._circle(pix if not pix.isNull() else None))

    def _edit(self):
        import avatar_service
        cur = avatar_service.get_avatar(self._role, self._identity)
        dlg = AvatarDialog(current=cur, parent=self.window())
        if dlg.exec() and dlg.result_value() is not None:
            avatar_service.save_avatar(dlg.result_value(), self._role, self._identity)
            self._refresh()
