"""Tiny external-player wrapper (QtMultimedia lives in PySide6-Addons, which we don't install)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_PLAYERS = [
    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
    ["paplay"],
    ["pw-play"],
    ["aplay", "-q"],
    ["play", "-q"],  # sox
]


def find_player() -> list[str] | None:
    return next((c for c in _PLAYERS if shutil.which(c[0])), None)


class Player:
    def __init__(self):
        self._proc: subprocess.Popen | None = None

    @property
    def playing(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def play(self, path: Path) -> None:
        cmd = find_player()
        if not cmd:
            raise RuntimeError("No audio player found. Install one: sudo apt install ffmpeg")
        self.stop()
        self._proc = subprocess.Popen([*cmd, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self) -> None:
        if self.playing:
            self._proc.terminate()
        self._proc = None
