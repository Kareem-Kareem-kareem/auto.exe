import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from ui import ResenderWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RESENDER")
    app.setStyle("Fusion")

    window = ResenderWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
