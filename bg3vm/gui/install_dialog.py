"""Pop-out window showing the background engine download. Non-modal: the pipeline keeps running behind it."""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout


class InstallWindow(QDialog):
    _progress = Signal(float, str)  # bridges the worker thread's callbacks onto the UI thread

    def __init__(self, parent, installer):
        super().__init__(parent)
        self.installer = installer
        self.setWindowTitle("Downloading voice engine")
        self.setModal(False)
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        parts = "<br>".join(f"<b>{p.label}</b> ({p.install_size_hint})" for p in installer.parts)
        title = QLabel(f"{parts}<br>One-time download. The steps that don't need it keep running; "
                       "the steps that do wait here if the download isn't finished yet.")
        title.setWordWrap(True)
        self.stage = QLabel("Starting…")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(400)
        self.cancel_btn = QPushButton("Cancel download")
        self.cancel_btn.clicked.connect(self._cancel)
        self.hide_btn = QPushButton("Hide window")
        self.hide_btn.clicked.connect(self.hide)
        row = QHBoxLayout()
        row.addWidget(self.cancel_btn)
        row.addStretch(1)
        row.addWidget(self.hide_btn)
        for w in (title, self.stage, self.bar, self.log):
            lay.addWidget(w)
        lay.addLayout(row)
        self._last_stage = ""
        self._progress.connect(self._on_progress)
        installer.add_listener(lambda f, m: self._progress.emit(f, m))
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._check_done)
        self._poll.start(300)

    def _on_progress(self, frac: float, msg: str):
        self.bar.setValue(int(frac * 1000))
        if msg and msg != self._last_stage and len(msg) < 90 and msg[0].isupper() and not msg.startswith("Using"):
            self.stage.setText(msg)
            self._last_stage = msg
        self.log.appendPlainText(msg)

    def _check_done(self):
        if not self.installer.done.is_set():
            return
        self._poll.stop()
        self.cancel_btn.setEnabled(False)
        if self.installer.ok:
            self.stage.setText("Voice engine installed.")
            QTimer.singleShot(1500, self.close)
        else:
            self.stage.setText(f"Failed: {self.installer.error}")
            self.show()  # make sure a failure is seen

    def _cancel(self):
        self.installer.cancel.set()
        self.cancel_btn.setEnabled(False)
        self.stage.setText("Cancelling…")

    def closeEvent(self, e):
        if self.installer.running:  # closing the window must not silently kill a multi-GB download
            e.ignore()
            self.hide()
        else:
            super().closeEvent(e)
