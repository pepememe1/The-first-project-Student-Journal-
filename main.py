import sys
from PySide6.QtWidgets import QApplication
from GUI import MainAppWindow 

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    window = MainAppWindow()
    window.show()
    
    # Принудительно выводим на передний план
    window.raise_()
    window.activateWindow()
    
    print("✅ Окно успешно создано и должно быть на экране.")
    sys.exit(app.exec())