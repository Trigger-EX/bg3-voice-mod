"""Run a large engine install in the background while early pipeline stages keep going."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from .jobs import Cancelled

log = logging.getLogger("bg3vm.background")


class BackgroundInstall:
    def __init__(self, engine, *more):
        """engine: the main installable (has .label, .install_size_hint, .install(), .available()).
        more: further installables that run after it (e.g. the accent speech model)."""
        self.engine = engine
        self.parts = [engine, *more]
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.error: str | None = None
        self.last: tuple[float, str] = (0.0, "Starting…")
        self._listeners: list[Callable[[float, str], None]] = []
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and not self.done.is_set()

    @property
    def ok(self) -> bool:
        return self.done.is_set() and self.error is None

    def add_listener(self, fn: Callable[[float, str], None]) -> None:
        self._listeners.append(fn)

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="engine-install", daemon=True)
        self._thread.start()

    def _progress(self, frac: float, msg: str) -> None:
        self.last = (frac, msg)
        for fn in list(self._listeners):
            fn(frac, msg)

    def _run(self) -> None:
        try:
            n = len(self.parts)
            for i, part in enumerate(self.parts):
                if part.available()[0]:
                    continue
                part.install(lambda f, m, i=i: self._progress((i + f) / n, m), self.cancel)
                ok, why = part.available()
                if not ok:
                    self.error = f"{part.label}: install finished but it is still unavailable: {why}"
                    break
        except Cancelled:
            self.error = "download was cancelled"
        except Exception as e:
            log.exception("background install failed")
            self.error = f"{type(e).__name__}: {e}"
        finally:
            self.done.set()
            self._progress(1.0 if self.error is None else self.last[0], "Voice engine ready" if self.error is None
                           else f"Install failed: {self.error}")

    def wait(self, cancel: threading.Event, emit: Callable[[float, str], None] | None = None,
             poll: float = 0.5) -> None:
        """Block the calling pipeline thread until the install finishes. Raises if it failed."""
        ticks = 0
        while not self.done.wait(poll):
            if cancel.is_set():
                raise Cancelled()
            ticks += 1
            if emit and ticks % max(1, int(2 / poll)) == 1:  # a heartbeat every ~2 s, not every poll
                emit(self.last[0], f"Waiting for the download… {int(self.last[0] * 100)}%")
        if self.error:
            raise RuntimeError(f"Voice engine install failed: {self.error}")
