"""Install Applio (RVC) into the app's tools folder: source, Python 3.12 venv, PyTorch, base models."""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import zipfile
from pathlib import Path

from bg3vm.core.config import TOOLS_DIR

log = logging.getLogger("bg3vm.applio")

APPLIO_DIR = TOOLS_DIR / "applio"
VENV_DIR = TOOLS_DIR / "applio-venv"
UV_VENV_DIR = TOOLS_DIR / "uv-venv"
CONFIG_DIR = TOOLS_DIR / "applio-config"
GIT_URL = "https://github.com/IAHispano/Applio.git"
ZIP_URL = "https://github.com/IAHispano/Applio/archive/refs/heads/main.zip"
MARKER = APPLIO_DIR / ".bg3vm-installed"
TORCH_INDEX = {
    "cuda": "https://download.pytorch.org/whl/cu128",
    "rocm": "https://download.pytorch.org/whl/rocm6.4",
    "cpu": "https://download.pytorch.org/whl/cpu",
}


def venv_python() -> Path:
    return VENV_DIR / "bin" / "python"


def is_installed() -> bool:
    return MARKER.exists() and venv_python().exists() and (APPLIO_DIR / "core.py").exists()


def detect_hardware() -> dict:
    """{'kind': 'cuda'|'rocm'|'cpu', 'vram_mb': int|None}"""
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=15, check=True).stdout
            return {"kind": "cuda", "vram_mb": int(float(out.splitlines()[0]))}
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            pass
    if shutil.which("rocminfo") or Path("/dev/kfd").exists():
        return {"kind": "rocm", "vram_mb": None}
    return {"kind": "cpu", "vram_mb": None}


def _run(cmd: list[str], progress, label: str, cancel: threading.Event | None, env=None, cwd=None) -> None:
    log.info("run: %s", " ".join(map(str, cmd)))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                            env=env, cwd=cwd, start_new_session=True)
    tail: list[str] = []
    for line in proc.stdout:  # type: ignore[union-attr]
        line = line.rstrip()
        tail = (tail + [line])[-30:]
        log.debug(line)
        if cancel is not None and cancel.is_set():
            os.killpg(proc.pid, 15)
            from bg3vm.core.jobs import Cancelled
            raise Cancelled()
    if proc.wait() != 0:
        raise RuntimeError(f"{label} failed (exit {proc.returncode}):\n" + "\n".join(tail))


def _download_source(progress, cancel=None) -> None:
    """Shallow git clone when git exists (smaller, records the commit); otherwise the GitHub zip."""
    progress(0.02, "Downloading Applio…")
    shutil.rmtree(APPLIO_DIR, ignore_errors=True)
    if shutil.which("git"):
        try:
            _run(["git", "clone", "--depth", "1", GIT_URL, str(APPLIO_DIR)], progress, "git clone", cancel)
            return
        except RuntimeError:
            log.warning("git clone failed; falling back to zip download", exc_info=True)
            shutil.rmtree(APPLIO_DIR, ignore_errors=True)
    with urllib.request.urlopen(ZIP_URL, timeout=120) as r:
        data = r.read()
    tmp = TOOLS_DIR / "applio.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(tmp)
    shutil.move(str(next(tmp.iterdir())), str(APPLIO_DIR))
    shutil.rmtree(tmp, ignore_errors=True)


def _ensure_uv(progress, cancel) -> str:
    uv = shutil.which("uv")
    if uv:
        return uv
    exe = UV_VENV_DIR / "bin" / "uv"
    if not exe.exists():
        progress(0.08, "Installing uv (Python manager)…")
        subprocess.run([sys.executable, "-m", "venv", str(UV_VENV_DIR)], check=True)
        _run([str(UV_VENV_DIR / "bin" / "pip"), "install", "uv"], progress, "uv install", cancel)
    return str(exe)


def install(progress, cancel: threading.Event | None = None) -> None:
    """Idempotent. Large download: PyTorch plus Applio's base models (several GB)."""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    hw = detect_hardware()
    progress(0.0, f"Setting up the RVC engine ({hw['kind'].upper()} detected)…")
    if not (APPLIO_DIR / "core.py").exists():
        _download_source(progress, cancel)
    uv = _ensure_uv(progress, cancel)
    env = dict(os.environ, UV_HTTP_TIMEOUT="600")
    if not venv_python().exists():
        progress(0.12, "Creating Python 3.12 environment…")
        _run([uv, "venv", str(VENV_DIR), "--python", os.environ.get("BG3VM_APPLIO_PYTHON", "3.12")], progress, "venv", cancel, env)
    req = APPLIO_DIR / "requirements-engine.txt"
    if not req.exists():
        req = APPLIO_DIR / "requirements.txt"
    attempts = [hw["kind"], "cpu"] if hw["kind"] != "cpu" else ["cpu"]
    for i, kind in enumerate(attempts):
        progress(0.2, f"Installing PyTorch and dependencies ({kind}) — this takes a while…")
        try:
            _run([uv, "pip", "install", "--python", str(venv_python()), "-r", str(req),
                  "--extra-index-url", TORCH_INDEX[kind], "--index-strategy", "unsafe-best-match"],
                 progress, "dependency install", cancel, env)
            _run([uv, "pip", "install", "--python", str(venv_python()), "python-ffmpeg"],
                 progress, "python-ffmpeg install", cancel, env)
            break
        except RuntimeError:
            if i == len(attempts) - 1:
                raise
            log.warning("install with %s wheels failed; falling back to CPU", kind)
    progress(0.8, "Downloading base voice models (pretrained, pitch, embedder)…")
    _run([str(venv_python()), "core.py", "prerequisites", "--no-exe"], progress, "model download", cancel,
         dict(env, APPLIO_CONFIG_DIR=str(CONFIG_DIR)), cwd=str(APPLIO_DIR))
    MARKER.write_text("ok")
    progress(1.0, "RVC engine installed")
