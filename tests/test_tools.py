import numpy as np
import pytest

from bg3vm import bootstrap
from bg3vm.audio import vgmstream
from bg3vm.audio.wem import pcm_to_wem


def test_bootstrap_missing_detects_absent_modules():
    assert bootstrap.missing(lambda m: m != "PySide6") == ["PySide6-Essentials>=6.6"]
    assert bootstrap.missing(lambda m: True) == []


def test_vgmstream_install_and_decode(tmp_path, monkeypatch):
    monkeypatch.setattr(vgmstream, "VGM_DIR", tmp_path / "vgm")
    try:
        exe = vgmstream.install_vgmstream()
    except RuntimeError as e:
        pytest.skip(f"no network: {e}")
    wem = tmp_path / "a.wem"
    wem.write_bytes(pcm_to_wem(np.sin(np.arange(24000) / 10).astype("float32") * 0.3, 24000))
    wav = tmp_path / "a.wav"
    vgmstream.decode_wem(wem, wav)
    assert wav.stat().st_size > 1000
