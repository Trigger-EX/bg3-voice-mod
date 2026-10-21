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


def test_auto_transpose_from_pitch(tmp_path):
    import soundfile as sf
    from bg3vm.audio.pitch import auto_transpose

    def tone(f, name):
        t = np.arange(40000 * 4) / 40000
        x = sum(np.sin(2 * np.pi * f * k * t) / k for k in range(1, 6)).astype("float32") * 0.2
        sf.write(str(tmp_path / name), x, 40000)
        return tmp_path / name

    low, high = tone(110, "low.wav"), tone(220, "high.wav")
    assert auto_transpose([low], [high]) == 12
    assert auto_transpose([high], [low]) == -12
    assert auto_transpose([low], [low]) == 0


def test_wem_exact_length(tmp_path):
    import soundfile as sf
    from bg3vm.audio.wem import wav_to_wem

    sf.write(str(tmp_path / "a.wav"), np.zeros(1000, dtype="float32"), 24000)
    wem = wav_to_wem(tmp_path / "a.wav", 24000, 1, frames=1500)
    assert len(wem) == 12 + 8 + 40 + 8 + 1500 * 2  # RIFF/WAVE + fmt chunk + data chunk header + samples


def test_batch_size_by_vram():
    from bg3vm.engines.rvc_applio import batch_size_for
    assert batch_size_for({"kind": "cpu", "vram_mb": None}) == 4
    assert batch_size_for({"kind": "cuda", "vram_mb": 8000}) == 8
    assert batch_size_for({"kind": "cuda", "vram_mb": 24000}) == 12


def test_setup_run_kills_silent_tool_and_cancels_promptly():
    import sys, threading, time
    from bg3vm.core.jobs import Cancelled
    from bg3vm.engines import applio_setup as su

    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    t0 = time.monotonic()
    try:
        su._run(sleeper, lambda f, m: None, "sleeper", None, silence_timeout=2)
        raise AssertionError("expected a timeout")
    except RuntimeError as e:
        assert "no output for 2s" in str(e)
    assert time.monotonic() - t0 < 10

    ev = threading.Event()
    threading.Timer(0.5, ev.set).start()  # cancel while the tool is completely silent
    t0 = time.monotonic()
    try:
        su._run(sleeper, lambda f, m: None, "sleeper", ev)
        raise AssertionError("expected cancel")
    except Cancelled:
        pass
    assert time.monotonic() - t0 < 10


def test_run_streams_output_and_reports_failure():
    import sys
    from bg3vm.engines import applio_setup as su
    seen = []
    su._run([sys.executable, "-c", "print('hello'); print('world')"], lambda f, m: seen.append(m), "echo", None)
    assert "hello" in seen
    try:
        su._run([sys.executable, "-c", "print('boom'); raise SystemExit(3)"], lambda f, m: None, "bad", None)
        raise AssertionError("expected failure")
    except RuntimeError as e:
        assert "exit 3" in str(e) and "boom" in str(e)
