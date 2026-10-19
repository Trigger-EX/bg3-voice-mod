"""Resumable stage runner: each stage drops a '.done' marker and is skipped next time."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from .project import Project

log = logging.getLogger("bg3vm.jobs")
Emit = Callable[[float, str], None]


class Cancelled(Exception):
    pass


class Skip(Exception):
    """Raised by a stage that finished without doing its job (not an error; no .done marker)."""


@dataclass
class Stage:
    name: str
    label: str
    run: Callable[["Context"], None]


class Context:
    def __init__(self, project: Project, emit: Emit, cancel: threading.Event, settings=None):
        self.project, self.emit, self.cancel, self.settings = project, emit, cancel, settings

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()


def run_stages(stages: list[Stage], ctx: Context, force: set[str] | None = None,
               on_stage: Callable[[int, int, str], None] | None = None) -> None:
    force = force or set()
    for i, st in enumerate(stages):
        ctx.check()
        marker = ctx.project.dir("state") / f"{st.name}.done"
        if marker.exists() and st.name not in force:
            ctx.emit(1.0, f"{st.label}: already done")
            continue
        if on_stage:
            on_stage(i, len(stages), st.label)
        log.info("stage %s: start", st.name)
        try:
            st.run(ctx)
        except Cancelled:
            log.info("stage %s: cancelled", st.name)
            raise
        except Skip:
            log.info("stage %s: skipped", st.name)
            continue
        except Exception:
            log.exception("stage %s: failed", st.name)
            raise
        log.info("stage %s: done", st.name)
        marker.touch()
