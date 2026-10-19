import sys

from PySide6.QtWidgets import QApplication

from bg3vm.gui.main_window import MainWindow
from bg3vm.gui.theme import apply_theme


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("BG3 Voice Forge")
    apply_theme(app)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
