"""Fit a re-spoken (TTS) line onto the original line's timing, so lip-sync and length stay valid."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf


def speech_bounds(x: np.ndarray, sr: int, floor_db: float = -40.0) -> tuple[int, int]:
    """First and last samples with speech-level energy (mono float)."""
    hop = max(1, int(0.01 * sr))
    n = len(x) // hop
    if n == 0:
        return 0, len(x)
    rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9
    voiced = np.nonzero(20 * np.log10(rms / rms.max()) > floor_db)[0]
    if len(voiced) == 0:
        return 0, len(x)
    return int(voiced[0] * hop), int(min((voiced[-1] + 1) * hop, len(x)))


def _atempo(src: Path, dst: Path, factor: float) -> None:
    """Pitch-preserving time stretch: factor > 1 is faster/shorter."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter:a", f"atempo={factor:.5f}",
                    str(dst)], check=True, capture_output=True, timeout=120)


def fit_to_original(orig_wav: Path, tts_wav: Path, out_wav: Path, min_factor=0.6, max_factor=1.8) -> float:
    """Write out_wav: the TTS speech stretched to span the same stretch of time as the original's speech,
    placed at the same offset, padded/trimmed to the original's exact length at its sample rate.
    Returns the stretch factor applied."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required (sudo apt install ffmpeg)")
    o, osr = sf.read(str(orig_wav), dtype="float32", always_2d=True)
    o_mono = o.mean(axis=1)
    o_start, o_end = speech_bounds(o_mono, osr)
    t, tsr = sf.read(str(tts_wav), dtype="float32", always_2d=True)
    t = t.mean(axis=1)
    t_start, t_end = speech_bounds(t, tsr)
    t_speech = t[t_start:t_end]
    target = max((o_end - o_start) / osr, 0.2)  # seconds of original speech
    factor = min(max((len(t_speech) / tsr) / target, min_factor), max_factor)
    with tempfile.TemporaryDirectory() as td:
        a, b = Path(td) / "a.wav", Path(td) / "b.wav"
        sf.write(str(a), t_speech, tsr)
        _atempo(a, b, factor)
        s, ssr = sf.read(str(b), dtype="float32")
    if ssr != osr:  # linear resample is plenty for speech that RVC re-synthesises anyway
        s = np.interp(np.linspace(0, len(s) - 1, int(round(len(s) * osr / ssr))), np.arange(len(s)), s)
    out = np.zeros(len(o_mono), dtype="float32")
    seg = s[: max(len(out) - o_start, 0)]
    out[o_start : o_start + len(seg)] = seg
    sf.write(str(out_wav), out, osr)
    return factor
