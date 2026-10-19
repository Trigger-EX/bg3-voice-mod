"""Resumable stage runner: each stage drops a '.done' marker and is skipped next time."""
from __future__ import annotations

import json
import logging
import shutil
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
    # Fingerprint of the project settings this stage depends on; a change invalidates it and all later stages.
    key: Callable[[Project], object] | None = None
    # Project subfolders (and files) wiped before this stage re-runs because it was invalidated.
    outputs: tuple[str, ...] = ()
    always: bool = False  # cheap and idempotent: run every time
    deps: tuple[str, ...] = ()  # stages whose re-run invalidates this one


class Context:
    def __init__(self, project: Project, emit: Emit, cancel: threading.Event, settings=None):
        self.project, self.emit, self.cancel, self.settings = project, emit, cancel, settings

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()


def _wipe(project: Project, names: tuple[str, ...]) -> None:
    for n in names:
        path = project.root / n
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()


def run_stages(stages: list[Stage], ctx: Context, force: set[str] | None = None,
               on_stage: Callable[[int, int, str], None] | None = None) -> None:
    force = force or set()
    reran: set[str] = set()
    for i, st in enumerate(stages):
        ctx.check()
        marker = ctx.project.dir("state") / f"{st.name}.done"
        fp = json.dumps(st.key(ctx.project), sort_keys=True, default=str) if st.key else ""
        had_marker = marker.exists()
        fresh = had_marker and marker.read_text() == fp and not st.always
        if fresh and not (reran & set(st.deps)) and st.name not in force:
            ctx.emit(1.0, f"{st.label}: already done")
            continue
        if had_marker and not st.always:
            log.info("stage %s: invalidated (settings changed or upstream re-ran); clearing old output", st.name)
            _wipe(ctx.project, st.outputs)
        marker.unlink(missing_ok=True)
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
        marker.write_text(fp)
        reran.add(st.name)
