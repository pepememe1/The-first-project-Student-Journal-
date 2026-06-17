"""
main.py — единая точка входа GradeBookAI (Release 2.2).
Модульная архитектура: main_window.MainAppWindow.
"""
import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from main_window import MainAppWindow


def _get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_icon() -> QIcon:
    base_dir = _get_app_dir()
    for name in ("icon.ico", "icon.png", "icon.jpg"):
        path = os.path.join(base_dir, name)
        if os.path.exists(path):
            return QIcon(path)
    return QIcon()


def _bootstrap_org_key():
    """Готовит общий ключ шифрования организации (DEK) при старте.

    На одиночном ПК (PostgreSQL не настроен) ничего не спрашивает — работает
    локальный ключ. При общей базе PostgreSQL запрашивает «пароль установки»:
    на первом ПК — создаёт, на остальных — вводится один раз для получения ключа.
    """
    from PySide6.QtWidgets import QMessageBox, QInputDialog, QLineEdit
    import keyvault
    import security

    def _prompt_create():
        QMessageBox.information(
            None, "Пароль установки",
            "Это первый компьютер с общей базой. Придумайте «пароль установки» — "
            "общий секрет для всех ПК колледжа. Его нужно будет ввести по одному "
            "разу на каждом компьютере. Это НЕ пароль администратора.")
        p1, ok = QInputDialog.getText(None, "Пароль установки",
                                      "Придумайте пароль установки (мин. 8 символов):",
                                      QLineEdit.Password)
        if not ok or len(p1) < 8:
            if ok:
                QMessageBox.warning(None, "Слишком короткий",
                                    "Пароль установки должен быть не короче 8 символов.")
            return None
        p2, ok = QInputDialog.getText(None, "Подтверждение",
                                      "Повторите пароль установки:", QLineEdit.Password)
        if not ok or p1 != p2:
            if ok:
                QMessageBox.warning(None, "Не совпадает", "Пароли не совпадают.")
            return None
        return p1

    def _prompt_enter():
        p, ok = QInputDialog.getText(
            None, "Пароль установки",
            "Введите «пароль установки» колледжа (задан на первом ПК):",
            QLineEdit.Password)
        return p if ok else None

    try:
        dek, mode = keyvault.ensure_dek(prompt_create=_prompt_create,
                                        prompt_enter=_prompt_enter)
    except Exception as e:
        print(f"[org-key] ошибка: {e}")
        dek, mode = None, "error"

    if mode == "org" and dek:
        security.set_data_key(dek)
        print("🔑 Общий ключ организации загружен")
    elif mode == "error":
        QMessageBox.critical(
            None, "Нет ключа шифрования",
            "Не удалось получить общий ключ организации (нет связи с сервером, "
            "отмена или неверный пароль установки).\n\nБез него работать с общей "
            "базой нельзя — иначе данные на разных ПК рассинхронизируются.\n\n"
            "Проверьте подключение к серверу и повторите запуск.")
        sys.exit(1)
    # mode == "local" — PostgreSQL не настроен, используется локальный ключ.


def main():
    # Инициализация базы данных (SQLite + опционально PostgreSQL)
    from core import DBManager
    if DBManager.init():
        print("✅ Работаем с PostgreSQL")
    else:
        print("ℹ️  Работаем с локальным SQLite")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    #Проверка криптографии: без пакета cryptography шифрование ПДн недоступно.
    #Раньше приложение молча откатывалось на слабый самописный шифр — для боевой
    #эксплуатации (152-ФЗ) это недопустимо, поэтому честно останавливаемся.
    try:
        from security import CRYPTO_AVAILABLE
    except Exception:
        CRYPTO_AVAILABLE = False
    if not CRYPTO_AVAILABLE:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None, "Не установлен компонент защиты",
            "Для работы с персональными данными требуется пакет «cryptography».\n\n"
            "Установите его командой:\n    pip install cryptography\n\n"
            "Без него запуск невозможен: данные нельзя зашифровать надёжно.")
        sys.exit(1)

    # Общий ключ шифрования организации (для общей базы PostgreSQL на нескольких ПК).
    # Если PostgreSQL не настроен — шаг тихо пропускается (используется локальный ключ).
    _bootstrap_org_key()

    #Шрифты Syne + DM Sans (фирменный стиль Synapse)
    try:
        from fonts import load_fonts
        load_fonts()
    except Exception as e:
        print(f"[Fonts] {e}")

    icon = get_icon()
    app.setWindowIcon(icon)

    window = MainAppWindow()
    window.setWindowIcon(icon)
    window.show()
    window.raise_()
    window.activateWindow()

    #Авто-бэкап локальной базы при выходе + аккуратная остановка синхронизации
    def _on_quit():
        try:
            from core import DBManager, _syncer
            DBManager.backup(reason="on_exit")
            _syncer.stop()
        except Exception as _e:
            print(f"[exit] {_e}")
    app.aboutToQuit.connect(_on_quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
