"""Prepare user recordings for training: convert, normalise, slice on silence, QC."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 40000
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".opus", ".wma", ".aac"}


@dataclass
class QC:
    clips: int
    minutes: float
    clipped_fraction: float
    snr_db: float
    warnings: list[str]


def to_mono_wav(src: Path, dst: Path, sr: int = SR) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required (sudo apt install ffmpeg)")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(sr), str(dst)],
        check=True,
    )


def split_on_silence(x: np.ndarray, sr: int, min_s=2.0, max_s=10.0, top_db=35.0) -> list[np.ndarray]:
    hop = int(sr * 0.02)
    n = len(x) // hop
    if n == 0:
        return []
    frames = x[: n * hop].reshape(n, hop)
    rms = np.sqrt((frames**2).mean(axis=1)) + 1e-9
    db = 20 * np.log10(rms / rms.max())
    voiced = db > -top_db
    clips, start, last_voice = [], None, 0
    for i, v in enumerate(voiced):
        if v and start is None:
            start = i
        if v:
            last_voice = i
        if start is not None:
            gap_end = (not v) and (i - last_voice) >= 15  # 300 ms of silence
            too_long = (i - start) * hop / sr >= max_s
            if gap_end or too_long:
                seg = x[start * hop : (last_voice + 1) * hop]
                if len(seg) / sr >= min_s:
                    clips.append(seg)
                start = None
    if start is not None:
        seg = x[start * hop : (last_voice + 1) * hop]
        if len(seg) / sr >= min_s:
            clips.append(seg)
    return clips


def qc_report(clips: list[np.ndarray], sr: int) -> QC:
    total = sum(len(c) for c in clips) / sr
    allx = np.concatenate(clips) if clips else np.zeros(1)
    clipped = float((np.abs(allx) > 0.999).mean())
    sig = float(np.sqrt((allx**2).mean())) + 1e-9
    floor = float(np.percentile(np.abs(allx), 5)) + 1e-9
    snr = 20 * np.log10(sig / floor)
    warn = []
    if total < 600:
        warn.append(f"Only {total / 60:.1f} min of speech; 10+ minutes gives much better results.")
    if clipped > 0.001:
        warn.append("Audio is clipping; re-record at a lower input level.")
    if snr < 15:
        warn.append("Recordings look noisy; use a quiet room or enable vocal isolation.")
    return QC(len(clips), total / 60, clipped, float(snr), warn)


def prepare_dataset(inputs: list[Path], out_dir: Path, tmp_dir: Path) -> QC:
    files: list[Path] = []
    for p in inputs:
        files += sorted(f for f in p.rglob("*") if f.suffix.lower() in AUDIO_EXT) if p.is_dir() else [p]
    if not files:
        raise ValueError("no audio files found")
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    clips: list[np.ndarray] = []
    for i, f in enumerate(files):
        tmp = tmp_dir / f"{i:04d}.wav"
        to_mono_wav(f, tmp)
        x, _ = sf.read(str(tmp), dtype="float32")
        peak = float(np.abs(x).max()) or 1.0
        clips += split_on_silence(x / peak * 0.9, SR)
    for i, c in enumerate(clips):
        sf.write(str(out_dir / f"clip_{i:05d}.wav"), c, SR)
    qc = qc_report(clips, SR)
    (out_dir.parent / "qc.json").write_text(json.dumps(asdict(qc), indent=2))
    return qc
