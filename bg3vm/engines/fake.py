"""CPU-only stand-in engine: 'trains' instantly and pitch-shifts by resampling. For testing the pipeline."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from .base import Progress, VoiceEngine


class FakeEngine(VoiceEngine):
    name = "fake"
    label = "Test engine (no training, pitch shift only)"

    def available(self):
        return True, ""

    def train(self, dataset_dir, model_dir, preset, progress: Progress, cancel=None):
        clips = sorted(Path(dataset_dir).glob("*.wav"))
        model_dir.mkdir(parents=True, exist_ok=True)
        for i, _ in enumerate(clips):
            progress((i + 1) / max(len(clips), 1), f"epoch {i + 1}/{len(clips)}")
        (model_dir / "model.json").write_text(json.dumps({"clips": len(clips)}))

    def convert(self, model_dir, src_wav, dst_wav, transpose=0):
        x, sr = sf.read(str(src_wav), dtype="float32", always_2d=True)
        f = 2 ** (transpose / 12)
        n = int(len(x) / f)
        idx = np.linspace(0, len(x) - 1, n)
        y = np.stack([np.interp(idx, np.arange(len(x)), x[:, c]) for c in range(x.shape[1])], 1)
        # keep duration: pad/trim back to original length
        y = np.resize(y, x.shape) if len(y) < len(x) else y[: len(x)]
        Path(dst_wav).parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(dst_wav), y, sr)
