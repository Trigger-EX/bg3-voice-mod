"""File logging + crash capture. Logs live in ~/.local/share/bg3vm/logs/."""
from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import sys
import threading

from .config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "bg3vm.log"
CRASH_FILE = LOG_DIR / "crash.log"
_crash_fh = None  # must stay open for faulthandler


def setup_logging() -> logging.Logger:
    global _crash_fh
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("bg3vm")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)
    fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    log.addHandler(fh)
    log.addHandler(logging.StreamHandler(sys.stderr))

    # Hard crashes (segfault, abort) and hangs: Python + native thread stacks go to crash.log.
    _crash_fh = open(CRASH_FILE, "a", buffering=1)
    _crash_fh.write(f"\n--- session start ---\n")
    faulthandler.enable(file=_crash_fh, all_threads=True)

    def excepthook(t, v, tb):
        log.critical("Uncaught exception", exc_info=(t, v, tb))

    def thread_hook(args):
        log.critical("Uncaught exception in thread %s", args.thread.name if args.thread else "?",
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    log.info("bg3vm started (python %s)", sys.version.split()[0])
    return log
