"""Runs pipeline stages on a worker thread and reports progress through Qt signals."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QThread, Signal

from bg3vm.core.jobs import Cancelled, Context, run_stages
from bg3vm.core.pipeline import STAGES


class _Worker(QThread):
    progress = Signal(float, str)
    stage = Signal(int, int, str)
    failed = Signal(str)
    finished_ok = Signal()
    cancelled = Signal()

    def __init__(self, project, settings, force, cancel):
        super().__init__()
        self.project, self.settings, self.force, self._cancel = project, settings, force, cancel

    def run(self):
        ctx = Context(self.project, lambda f, m: self.progress.emit(f, m), self._cancel, self.settings)
        try:
            run_stages(STAGES, ctx, self.force, lambda i, n, label: self.stage.emit(i, n, label))
            self.finished_ok.emit()
        except Cancelled:
            self.cancelled.emit()
        except Exception as e:  # surfaced to the UI
            logging.getLogger("bg3vm").exception("pipeline failed")
            self.failed.emit(f"{type(e).__name__}: {e}")


class JobRunner(QObject):
    progress = Signal(float, str)
    stage = Signal(int, int, str)
    failed = Signal(str)
    done = Signal()
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self._worker: _Worker | None = None
        self._cancel = threading.Event()

    @property
    def running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def start(self, project, settings, force=None):
        if self.running:
            return
        self._cancel.clear()
        w = _Worker(project, settings, force or set(), self._cancel)
        w.progress.connect(self.progress)
        w.stage.connect(self.stage)
        w.failed.connect(self.failed)
        w.finished_ok.connect(self.done)
        w.cancelled.connect(self.cancelled)
        self._worker = w
        w.start()

    def cancel(self):
        self._cancel.set()
