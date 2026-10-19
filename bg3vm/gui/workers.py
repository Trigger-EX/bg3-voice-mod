from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Signal


class FuncThread(QThread):
    """Run ``fn(progress)`` off the UI thread; progress(fraction, message)."""

    progress = Signal(float, str)
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.result.emit(self._fn(lambda f, m: self.progress.emit(f, m)))
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
