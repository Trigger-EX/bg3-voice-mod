"""Decode .wem via vgmstream-cli, falling back to ffmpeg for plain PCM/RIFF."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from bg3vm.core.config import TOOLS_DIR


def find_vgmstream() -> str | None:
    local = TOOLS_DIR / "vgmstream" / "vgmstream-cli"
    if local.is_file():
        return str(local)
    return shutil.which("vgmstream-cli")


def decode_wem(wem: Path, wav: Path) -> None:
    wav.parent.mkdir(parents=True, exist_ok=True)
    tool = find_vgmstream()
    if tool:
        cmd = [tool, "-o", str(wav), str(wem)]
    elif shutil.which("ffmpeg"):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wem), str(wav)]
    else:
        raise RuntimeError("vgmstream-cli (or ffmpeg) is required to decode .wem files")
    subprocess.run(cmd, check=True, capture_output=True)
