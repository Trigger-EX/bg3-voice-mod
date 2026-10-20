"""Decoded original game audio, cached across projects (and used for sample previews)."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from bg3vm.audio.vgmstream import decode_wem
from bg3vm.core.config import CACHE_DIR
from bg3vm.game.lspk import PakReader


def cache_dir(pak: str) -> Path:
    """Per pak build (name, size, mtime), so a game update never serves stale audio."""
    st = os.stat(pak)
    return CACHE_DIR / "orig_wav" / f"{Path(pak).stem}-{st.st_size}-{int(st.st_mtime)}"


def cached_path(pak: str, key: str) -> Path:
    return cache_dir(pak) / f"{key}.wav"


def decode_to_cache(pak: str, entry: str, key: str, reader: PakReader | None = None,
                    tmp_root: Path | None = None) -> Path:
    wav = cached_path(pak, key)
    if wav.exists():
        return wav
    wav.parent.mkdir(parents=True, exist_ok=True)
    reader = reader or PakReader(pak)
    with tempfile.TemporaryDirectory(dir=tmp_root) as td:
        wem, part = Path(td) / f"{key}.wem", Path(td) / f"{key}.wav"
        wem.write_bytes(reader.read(entry))
        decode_wem(wem, part)
        shutil.move(str(part), str(wav) + ".tmp")  # never leave a half-written cache file
    os.replace(str(wav) + ".tmp", wav)
    return wav
