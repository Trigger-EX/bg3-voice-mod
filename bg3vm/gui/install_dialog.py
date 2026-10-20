"""Pop-out progress window for large engine downloads."""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout

from bg3vm.gui.workers import FuncThread


class InstallDialog(QDialog):
    def __init__(self, parent, engine):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("Installing voice engine")
        self.setModal(True)
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        self.title = QLabel(f"<b>{engine.label}</b><br>One-time download ({engine.install_size_hint}). "
                            "Keep this window open; it can take a while on a slow connection.")
        self.title.setWordWrap(True)
        self.stage = QLabel("Starting…")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(400)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        for w in (self.title, self.stage, self.bar, self.log, self.cancel_btn):
            lay.addWidget(w)
        self._cancel_ev = threading.Event()
        self._error: str | None = None
        self._ok = False
        self._last_stage = ""
        self._thread = FuncThread(lambda progress: engine.install(progress, self._cancel_ev))
        self._thread.progress.connect(self._on_progress)
        self._thread.result.connect(self._on_done)
        self._thread.failed.connect(self._on_failed)

    def run(self) -> bool:
        """Show the window, start the download right away, and block until it finishes. True on success."""
        self._thread.start()
        self.exec()
        self._thread.wait()
        if self._error:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.parent(), "Install failed", self._error)
        return self._ok

    def _on_progress(self, frac: float, msg: str):
        self.bar.setValue(int(frac * 1000))
        if msg and msg != self._last_stage and not msg.startswith((" ", "\t")) and len(msg) < 90 and msg[0].isupper():
            self.stage.setText(msg)
            self._last_stage = msg
        self.log.appendPlainText(msg)

    def _on_done(self, _):
        self._ok = True
        self.accept()

    def _on_failed(self, msg: str):
        if "Cancelled" not in msg:
            self._error = msg
        self.reject()

    def _cancel(self):
        self._cancel_ev.set()
        self.cancel_btn.setEnabled(False)
        self.stage.setText("Cancelling…")

    def closeEvent(self, e):  # closing the window counts as cancel; wait for the worker to stop
        if self._thread.isRunning():
            self._cancel()
            e.ignore()
        else:
            super().closeEvent(e)
