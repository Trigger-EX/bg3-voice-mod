"""Decoded original game audio, cached across projects (and used for sample previews)."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from bg3vm.audio.vgmstream import decode_wem, decode_wems
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


def decode_many_to_cache(items: list[tuple[str, str, str]], progress: Callable[[int, int], None],
                         cancel: threading.Event | None = None, tmp_root: Path | None = None,
                         workers: int | None = None, chunk: int = 24) -> list[tuple[str, str]]:
    """Decode (pak, entry, key) items into the cache using all CPU cores, several files per decoder call.

    Returns [(key, error)] for items that failed. progress(done, total) is called from the calling thread.
    """
    from bg3vm.core.jobs import Cancelled

    readers: dict[str, PakReader] = {}
    for pak, _, _ in items:
        readers.setdefault(pak, PakReader(pak))  # reads open the file per call, so sharing is thread-safe
    for d in {cache_dir(pak) for pak, _, _ in items}:
        d.mkdir(parents=True, exist_ok=True)
    failures: list[tuple[str, str]] = []

    def work(batch):
        bad: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory(dir=tmp_root) as td:
            wems = []
            for pak, entry, key in batch:
                w = Path(td) / f"{key}.wem"
                w.write_bytes(readers[pak].read(entry))
                wems.append(w)
            results = decode_wems(wems)
            for (pak, _, key), w in zip(batch, wems):
                if results[w] is not None:
                    bad.append((key, results[w]))
                    continue
                dst = cached_path(pak, key)
                shutil.move(str(w) + ".wav", str(dst) + ".tmp")
                os.replace(str(dst) + ".tmp", dst)
        return bad

    batches = [items[i : i + chunk] for i in range(0, len(items), chunk)]
    done = 0
    with ThreadPoolExecutor(max_workers=workers or os.cpu_count() or 2) as ex:
        pending = {ex.submit(work, b): len(b) for b in batches}
        try:
            while pending:
                finished, _ = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                for f in finished:
                    done += pending.pop(f)
                    failures += f.result()
                    progress(done, len(items))
        except BaseException:
            for f in pending:
                f.cancel()
            raise
    return failures
