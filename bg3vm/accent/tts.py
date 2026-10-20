"""American-English re-speaking with Kokoro, run inside the RVC engine's virtualenv (which already has torch)."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import deque
from pathlib import Path

from bg3vm.core.config import TOOLS_DIR
from bg3vm.core.jobs import Cancelled
from bg3vm.engines import applio_setup as setup

log = logging.getLogger("bg3vm.accent")

HF_HOME = TOOLS_DIR / "hf-cache"
MARKER = TOOLS_DIR / "accent-tts.installed"
WORKER = Path(__file__).with_name("tts_worker.py")
SPACY_MODEL = ("https://github.com/explosion/spacy-models/releases/download/"
               "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl")
VOICES = {"male": "am_michael", "female": "af_heart"}
INSTALL_HINT = "about 0.6 GB (speech model + language data)"
ESPEAK_HELP = "The American-accent feature needs espeak-ng. Install it with:  sudo apt install espeak-ng"


def choose_voice(setting: str, source_f0: float | None) -> str:
    if setting in VOICES:
        return VOICES[setting]
    return VOICES["male"] if (source_f0 or 0) and source_f0 < 165 else VOICES["female"]


def espeak_installed() -> bool:
    return shutil.which("espeak-ng") is not None


class AccentTTS:
    label = "American English speech (Kokoro)"
    install_size_hint = INSTALL_HINT
    name = "accent-tts"

    def __init__(self, worker_cmd: list[str] | None = None):
        self._worker_cmd = worker_cmd  # tests substitute a stub worker

    def available(self) -> tuple[bool, str]:
        if self._worker_cmd:
            return True, ""
        if not setup.is_installed():
            return False, "the RVC engine must be installed first"
        if not MARKER.exists():
            return False, "American-accent speech model not installed yet"
        return True, ""

    def install(self, progress, cancel: threading.Event | None = None) -> None:
        if not espeak_installed():
            raise RuntimeError(ESPEAK_HELP)
        if not setup.is_installed():
            raise RuntimeError("Install the RVC engine first")
        uv = setup._ensure_uv(progress, cancel)
        py = str(setup.venv_python())
        env = dict(os.environ, UV_HTTP_TIMEOUT="600", HF_HOME=str(HF_HOME))
        setup._step(progress, 0.1, "Installing the American English speech packages…")
        setup._run([uv, "pip", "install", "--python", py, "kokoro", "espeakng-loader", "soundfile", SPACY_MODEL],
                   progress, "speech package install", cancel, env)
        setup._step(progress, 0.5, "Downloading the speech model…")
        with tempfile.TemporaryDirectory() as td:  # a one-line job makes the worker download and load the model
            jobs = Path(td) / "warmup.json"
            jobs.write_text(json.dumps({"voice": VOICES["male"], "jobs": [
                {"key": "warmup", "text": "Warm up.", "out": str(Path(td) / "w.wav")}]}))
            setup._run([py, str(WORKER), str(jobs)], progress, "speech model download", cancel, env)
        MARKER.write_text("ok")
        progress(1.0, "American English speech installed")

    def synthesize(self, jobs: list[dict], voice: str, progress, cancel: threading.Event | None = None) -> list[tuple[str, str]]:
        """jobs: [{'key','text','out'}]. Returns [(key, reason)] for lines that failed."""
        if not jobs:
            return []
        failed: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "jobs.json"
            spec.write_text(json.dumps({"voice": voice, "jobs": jobs}), encoding="utf-8")
            cmd = self._worker_cmd or [str(setup.venv_python()), str(WORKER)]
            proc = subprocess.Popen([*cmd, str(spec)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    bufsize=1, start_new_session=True,
                                    env=dict(os.environ, PYTHONUNBUFFERED="1", HF_HOME=str(HF_HOME)))
            tail: deque[str] = deque(maxlen=30)
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                tail.append(line)
                if m := re.match(r"(OK|FAIL) (\d+)/(\d+) (\S+)\s*(.*)", line):
                    if m.group(1) == "FAIL":
                        failed.append((m.group(4), m.group(5)))
                    progress(int(m.group(2)) / int(m.group(3)), f"Re-speaking lines {m.group(2)}/{m.group(3)}")
                if cancel is not None and cancel.is_set():
                    try:
                        os.killpg(proc.pid, 15)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                    raise Cancelled()
            if proc.wait() != 0:
                raise RuntimeError("American-accent speech failed. Last output:\n" + "\n".join(tail))
        return failed
