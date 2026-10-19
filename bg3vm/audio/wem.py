"""Write Wwise-style PCM RIFF .wem files (WAVE_FORMAT_EXTENSIBLE, 16-bit)."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import soundfile as sf

_PCM_GUID = bytes.fromhex("0100000000001000800000aa00389b71")
_MASKS = {1: 0x4, 2: 0x3}


def pcm_to_wem(samples: np.ndarray, rate: int) -> bytes:
    """samples: float [-1,1] shaped (n,) or (n, ch)."""
    arr = np.atleast_2d(samples.T).T if samples.ndim == 1 else samples
    ch = arr.shape[1]
    pcm = (np.clip(arr, -1, 1) * 32767).astype("<i2").tobytes()
    fmt = struct.pack(
        "<HHIIHHHHI16s", 0xFFFE, ch, rate, rate * ch * 2, ch * 2, 16, 22, 16,
        _MASKS.get(ch, 0), _PCM_GUID,
    )
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(pcm)) + pcm
    return b"RIFF" + struct.pack("<I", len(body)) + body


def wav_to_wem(wav_path: str | Path, rate: int | None = None, channels: int | None = None) -> bytes:
    data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    if channels and data.shape[1] != channels:
        data = data.mean(axis=1, keepdims=True).repeat(channels, axis=1)
    if rate and rate != sr:
        n = int(round(len(data) * rate / sr))
        x = np.linspace(0, len(data) - 1, n)
        data = np.stack([np.interp(x, np.arange(len(data)), data[:, c]) for c in range(data.shape[1])], 1)
        sr = rate
    return pcm_to_wem(data, sr)
