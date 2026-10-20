"""Rough median-F0 estimate, used to pick a voice-conversion transpose automatically."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf


def _frame_f0(frame: np.ndarray, sr: int, fmin=60.0, fmax=400.0) -> float | None:
    frame = frame - frame.mean()
    if np.sqrt((frame**2).mean()) < 0.01:
        return None
    n = len(frame)
    spec = np.fft.rfft(frame * np.hanning(n), 2 * n)
    ac = np.fft.irfft(spec * np.conj(spec))[:n]
    if ac[0] <= 0:
        return None
    lo, hi = int(sr / fmax), min(int(sr / fmin), n - 1)
    if hi <= lo:
        return None
    lag = lo + int(np.argmax(ac[lo:hi]))
    if ac[lag] / ac[0] < 0.4:  # not clearly periodic -> unvoiced
        return None
    return sr / lag


def median_f0(paths: list[Path], max_seconds: float = 120.0) -> float | None:
    vals: list[float] = []
    budget = max_seconds
    for p in paths:
        if budget <= 0:
            break
        x, sr = sf.read(str(p), dtype="float32", always_2d=True)
        x = x.mean(axis=1)[: int(min(budget, 20) * sr)]
        budget -= len(x) / sr
        win, hop = int(0.04 * sr), int(0.02 * sr)
        for s in range(0, len(x) - win, hop):
            f = _frame_f0(x[s : s + win], sr)
            if f:
                vals.append(f)
    return float(np.median(vals)) if len(vals) >= 20 else None


def transpose_for(source_f0: float | None, target_f0: float | None, limit: int = 12) -> int:
    if not source_f0 or not target_f0:
        return 0
    return max(-limit, min(limit, round(12 * math.log2(target_f0 / source_f0))))


def auto_transpose(source_paths: list[Path], target_paths: list[Path], limit: int = 12) -> int:
    """Semitones to shift the *source* (game) voice so its pitch matches the target (your) voice."""
    return transpose_for(median_f0(source_paths), median_f0(target_paths), limit)
