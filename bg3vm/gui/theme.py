from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#c9a227"

QSS = f"""
* {{ font-size: 14px; }}
QMainWindow, QWidget#page {{ background: #14141a; }}
QListWidget#nav {{ background: #0f0f14; border: none; padding: 12px 8px; outline: 0; min-width: 190px; }}
QListWidget#nav::item {{ padding: 12px 14px; border-radius: 8px; color: #a0a0b0; margin: 2px 0; }}
QListWidget#nav::item:selected {{ background: #23232e; color: {ACCENT}; }}
QListWidget#nav::item:hover {{ background: #1b1b24; }}
QFrame#card {{ background: #1c1c25; border: 1px solid #2a2a38; border-radius: 12px; }}
QLabel#h1 {{ font-size: 24px; font-weight: 600; color: #f0f0f5; }}
QLabel#muted {{ color: #8a8a9a; }}
QPushButton {{ background: #2a2a38; border: none; border-radius: 8px; padding: 9px 16px; color: #e8e8f0; }}
QPushButton:hover {{ background: #34344a; }}
QPushButton#primary {{ background: {ACCENT}; color: #14141a; font-weight: 600; padding: 12px 24px; font-size: 15px; }}
QPushButton#primary:hover {{ background: #ddb633; }}
QPushButton:disabled {{ background: #22222c; color: #5a5a68; }}
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QListWidget {{
  background: #12121a; border: 1px solid #2a2a38; border-radius: 8px; padding: 7px; color: #e8e8f0; }}
QProgressBar {{ background: #12121a; border: none; border-radius: 6px; height: 12px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}
QLabel#drop {{ border: 2px dashed #3a3a50; border-radius: 12px; color: #8a8a9a; padding: 28px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, col in [
        (QPalette.Window, "#14141a"), (QPalette.WindowText, "#e8e8f0"), (QPalette.Base, "#12121a"),
        (QPalette.Text, "#e8e8f0"), (QPalette.Button, "#2a2a38"), (QPalette.ButtonText, "#e8e8f0"),
        (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, "#14141a"),
    ]:
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
