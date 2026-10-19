"""Make sure the GUI's dependencies exist; otherwise build an app-local venv and re-launch in it.

Deliberately imports nothing outside the standard library, so it works before PySide6 is installed.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REQUIRED = {"PySide6": "PySide6-Essentials>=6.6", "numpy": "numpy", "soundfile": "soundfile",
            "lz4": "lz4", "zstandard": "zstandard"}
_FLAG = "BG3VM_IN_VENV"


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "bg3vm"


def venv_dir() -> Path:
    return data_dir() / "venv"


def venv_python() -> Path:
    return venv_dir() / "bin" / "python"


def missing(python_has=lambda m: importlib.util.find_spec(m) is not None) -> list[str]:
    return [pkg for mod, pkg in REQUIRED.items() if not python_has(mod)]


def _say(msg: str) -> None:
    print(f"[bg3vm] {msg}", flush=True)


def _notify(msg: str) -> None:
    """Best effort desktop notification so double-click launches show something."""
    for cmd in (["notify-send", "BG3 Voice Forge", msg],):
        try:
            subprocess.run(cmd, check=False, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass


def create_venv() -> None:
    d = venv_dir()
    if not venv_python().exists():
        _say(f"Creating app environment in {d} …")
        r = subprocess.run([sys.executable, "-m", "venv", str(d)])
        if r.returncode != 0:
            raise SystemExit(
                "Could not create a virtual environment. On Linux Mint run:\n"
                "  sudo apt install python3-venv python3-pip")
    py = str(venv_python())
    _say("Installing PySide6 (Essentials) and dependencies (one-time, ~150 MB) …")
    subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip"], check=False)
    r = subprocess.run([py, "-m", "pip", "install", *REQUIRED.values()])
    if r.returncode != 0:
        raise SystemExit("pip failed to install the dependencies; check your internet connection.")


def ensure_environment() -> None:
    """Return normally if this interpreter can run the GUI; otherwise set up the venv and re-exec."""
    if not missing():
        return
    if os.environ.get(_FLAG):
        raise SystemExit(f"Missing packages even inside the app environment: {', '.join(missing())}")
    _say(f"Missing: {', '.join(missing())}")
    _notify("Setting up BG3 Voice Forge (first run)…")
    # The venv might exist already but be incomplete; (re)install is idempotent.
    create_venv()
    env = dict(os.environ, **{_FLAG: "1"})
    root = str(Path(__file__).resolve().parent.parent)
    env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
    os.execve(str(venv_python()), [str(venv_python()), "-m", "bg3vm", *sys.argv[1:]], env)
