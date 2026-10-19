"""Voice engine interface. Engines train on a prepared dataset and convert audio files."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

Progress = Callable[[float, str], None]  # fraction 0..1, message


class VoiceEngine(ABC):
    name = "base"
    label = "Base"

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(ready, reason-if-not)."""

    @abstractmethod
    def train(self, dataset_dir: Path, model_dir: Path, preset: str, progress: Progress) -> None: ...

    @abstractmethod
    def convert(self, model_dir: Path, src_wav: Path, dst_wav: Path, transpose: int = 0) -> None: ...
