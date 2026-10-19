"""Resumable stage runner: each stage drops a '.done' marker and is skipped next time."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from .project import Project

Emit = Callable[[float, str], None]


class Cancelled(Exception):
    pass


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
        st.run(ctx)
        marker.touch()
