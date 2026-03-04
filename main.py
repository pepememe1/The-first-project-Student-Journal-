import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from GUI import MainAppWindow


def get_icon() -> QIcon:
    """
    Ищет иконку в папке с программой.
    Порядок приоритета: icon.ico → icon.png → icon.jpg
    Работает и в режиме .py и после сборки PyInstaller в .exe
    """
    # При сборке PyInstaller ресурсы лежат в sys._MEIPASS
    if getattr(sys, "frozen", False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    for name in ("icon.ico", "icon.png", "icon.jpg"):
        path = os.path.join(base_dir, name)
        if os.path.exists(path):
            return QIcon(path)

    return QIcon()  # пустая иконка если файл не найден


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # ── Иконка приложения (панель задач + заголовок окна + .exe)
    icon = get_icon()
    app.setWindowIcon(icon)          # иконка в панели задач Windows

    window = MainAppWindow()
    window.setWindowIcon(icon)       # иконка в заголовке окна
    window.show()

    window.raise_()
    window.activateWindow()

    sys.exit(app.exec())
