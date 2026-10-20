"""Decode .wem via vgmstream-cli (auto-installable), falling back to ffmpeg for plain PCM/RIFF."""
from __future__ import annotations

import io
import shutil
import stat
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from bg3vm.core.config import TOOLS_DIR

VGM_DIR = TOOLS_DIR / "vgmstream"
# Release asset names have changed between vgmstream releases, so try each in turn.
_ASSETS = ["vgmstream-linux-cli.tar.gz", "vgmstream-linux-cli.zip", "vgmstream-linux.zip"]
_BASE = "https://github.com/vgmstream/vgmstream/releases/latest/download/"


def find_vgmstream() -> str | None:
    local = VGM_DIR / "vgmstream-cli"
    if local.is_file():
        return str(local)
    return shutil.which("vgmstream-cli")


def install_vgmstream(progress: Callable[[float, str], None] = lambda f, m: None) -> str:
    """Download the latest Linux vgmstream-cli into the app's tools folder. Returns its path."""
    VGM_DIR.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    for asset in _ASSETS:
        try:
            progress(0.0, f"Downloading {asset}…")
            with urllib.request.urlopen(_BASE + asset, timeout=60) as r:
                total = int(r.headers.get("Content-Length") or 0)
                buf = io.BytesIO()
                while chunk := r.read(1 << 16):
                    buf.write(chunk)
                    if total:
                        progress(min(buf.tell() / total, 0.95), f"Downloading {asset}…")
            buf.seek(0)
            _extract(buf, asset)
            break
        except Exception as e:  # try the next asset name
            last_err = e
    else:
        raise RuntimeError(f"Could not download vgmstream: {last_err}")
    exe = VGM_DIR / "vgmstream-cli"
    if not exe.is_file():
        raise RuntimeError("vgmstream archive did not contain vgmstream-cli")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    # Make sure it actually runs on this machine (libraries, architecture).
    subprocess.run([str(exe), "-h"], capture_output=True, timeout=20)
    progress(1.0, "vgmstream installed")
    return str(exe)


def _extract(buf: io.BytesIO, asset: str) -> None:
    if asset.endswith(".zip"):
        with zipfile.ZipFile(buf) as z:
            for info in z.infolist():
                if not info.is_dir():
                    (VGM_DIR / Path(info.filename).name).write_bytes(z.read(info))
    else:
        with tarfile.open(fileobj=buf, mode="r:gz") as t:
            for m in t.getmembers():
                if m.isfile():
                    f = t.extractfile(m)
                    if f:
                        (VGM_DIR / Path(m.name).name).write_bytes(f.read())


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


def decode_wems(wems: list[Path]) -> dict[Path, str | None]:
    """Decode many .wem files in one vgmstream call; each output lands beside its input as '<name>.wav'.

    Returns {wem: None on success | error text}. If the batch call fails, files are retried one by one so a
    single bad file only fails itself.
    """
    out_for = lambda w: w.with_name(w.name + ".wav")
    tool = find_vgmstream()
    if tool and wems:
        subprocess.run([tool, *map(str, wems)], capture_output=True)  # default output: '<infile>.wav'
    result: dict[Path, str | None] = {}
    for w in wems:
        if out_for(w).exists():
            result[w] = None
            continue
        try:  # missing output: batch failed (or no vgmstream); retry alone to get a real error message
            decode_wem(w, out_for(w))
            result[w] = None
        except subprocess.CalledProcessError as e:
            result[w] = (e.stderr or b"").decode(errors="replace").strip()[-300:] or f"decoder exit {e.returncode}"
        except Exception as e:
            result[w] = str(e)
    return result
