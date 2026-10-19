"""Voice engine interface. Engines train on a prepared dataset and convert audio files."""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

Progress = Callable[[float, str], None]  # fraction 0..1, message


class VoiceEngine(ABC):
    name = "base"
    label = "Base"
    install_size_hint = ""  # shown to the user before a large download

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(ready, reason-if-not)."""

    def install(self, progress: Progress, cancel: threading.Event | None = None) -> None:
        """Download/set up whatever the engine needs. No-op for engines that need nothing."""

    @abstractmethod
    def train(self, dataset_dir: Path, model_dir: Path, preset: str, progress: Progress,
              cancel: threading.Event | None = None) -> None: ...

    @abstractmethod
    def convert(self, model_dir: Path, src_wav: Path, dst_wav: Path, transpose: int = 0) -> None: ...

    def convert_batch(self, model_dir: Path, pairs: list[tuple[Path, Path]], transpose: int,
                      progress: Progress, cancel: threading.Event | None = None) -> None:
        """Convert many files; engines with expensive start-up override this."""
        for i, (src, dst) in enumerate(pairs):
            if cancel is not None and cancel.is_set():
                from bg3vm.core.jobs import Cancelled
                raise Cancelled()
            self.convert(model_dir, src, dst, transpose)
            progress((i + 1) / len(pairs), f"Converting {i + 1}/{len(pairs)}")
