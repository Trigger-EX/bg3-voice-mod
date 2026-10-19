"""RVC voice conversion through Applio's command line (installed by applio_setup).

Training uses ONLY the user's own recordings (the dataset folder). Game audio is only ever fed to the
trained model as conversion input; it is never used for training.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
from collections import deque
from pathlib import Path

from bg3vm.core.jobs import Cancelled

from . import applio_setup as setup
from .base import Progress, VoiceEngine

log = logging.getLogger("bg3vm.rvc")

MODEL_NAME = "bg3voice"
SAMPLE_RATE = "40000"
# total epochs per preset and hardware; CPU gets far fewer so it finishes in hours, not days
EPOCHS = {"cuda": {"fast": 100, "good": 250, "best": 500},
          "rocm": {"fast": 100, "good": 250, "best": 500},
          "cpu": {"fast": 20, "good": 50, "best": 100}}
CHUNK = 100  # files per batch-infer call: progress/cancel granularity vs. model start-up cost


def batch_size_for(hw: dict) -> int:
    vram = hw.get("vram_mb")
    if hw["kind"] == "cpu" or not vram:
        return 4
    return 4 if vram < 6000 else 8 if vram < 10000 else 12


class RvcApplioEngine(VoiceEngine):
    name = "rvc"
    label = "RVC voice cloning (Applio) — trains on your recordings"
    install_size_hint = "about 5–8 GB (PyTorch + base models)"

    # ---- setup
    def available(self):
        if setup.is_installed():
            return True, ""
        return False, "RVC engine not installed yet"

    def install(self, progress, cancel=None):
        setup.install(progress, cancel)

    # ---- process helpers
    def _env(self, model_dir: Path) -> dict:
        return dict(os.environ, PYTHONUNBUFFERED="1", APPLIO_LOGS_DIR=str(model_dir / "logs"),
                    APPLIO_CONFIG_DIR=str(setup.CONFIG_DIR), APPLIO_ROOT=str(setup.APPLIO_DIR))

    def _run(self, model_dir: Path, args: list[str], label: str, cancel, on_line=None) -> None:
        cmd = [str(setup.venv_python()), "core.py", *args]
        log.info("%s: %s", label, " ".join(cmd))
        proc = subprocess.Popen(cmd, cwd=str(setup.APPLIO_DIR), env=self._env(model_dir), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
                                start_new_session=True)
        tail: deque[str] = deque(maxlen=40)
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            tail.append(line)
            log.debug("[%s] %s", label, line)
            if on_line:
                on_line(line)
            if cancel is not None and cancel.is_set():
                try:
                    os.killpg(proc.pid, 15)
                except ProcessLookupError:
                    pass
                proc.wait()
                raise Cancelled()
        if proc.wait() != 0:
            raise RuntimeError(f"RVC {label} failed (exit {proc.returncode}). Last output:\n" + "\n".join(tail))

    # ---- training
    def train(self, dataset_dir, model_dir, preset, progress: Progress, cancel=None):
        model_dir = Path(model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)
        hw = setup.detect_hardware()
        epochs = EPOCHS[hw["kind"]].get(preset, EPOCHS[hw["kind"]]["good"])
        if hw["kind"] == "cpu":
            progress(0.0, "No supported GPU found: training on CPU is slow and lower quality "
                          f"({epochs} epochs). A GPU is strongly recommended.")
        exp = model_dir / "logs" / MODEL_NAME
        features_done = model_dir / "features.done"
        if not features_done.exists():
            progress(0.02, "Preprocessing your recordings…")
            self._run(model_dir, ["preprocess", "--model-name", MODEL_NAME, "--dataset-path", str(dataset_dir),
                                  "--sample-rate", SAMPLE_RATE, "--cpu-cores", str(os.cpu_count() or 2),
                                  "--cut-preprocess", "Skip", "--normalization-mode", "none"],
                      "preprocess", cancel)
            progress(0.06, "Extracting pitch and voice features…")
            self._run(model_dir, ["extract", "--model-name", MODEL_NAME, "--f0-method", "rmvpe",
                                  "--cpu-cores", str(os.cpu_count() or 2),
                                  "--gpu", "0" if hw["kind"] != "cpu" else "-",
                                  "--sample-rate", SAMPLE_RATE, "--embedder-model", "contentvec"],
                      "extract", cancel)
            features_done.write_text("ok")

        pat = re.compile(r"epoch=(\d+)")

        def on_line(line: str):
            m = pat.search(line)
            if m:
                e = int(m.group(1))
                progress(0.1 + 0.88 * min(e / epochs, 1.0), f"Training epoch {e}/{epochs}")

        progress(0.1, f"Training ({epochs} epochs)…")
        self._run(model_dir, ["train", "--model-name", MODEL_NAME, "--sample-rate", SAMPLE_RATE,
                              "--total-epoch", str(epochs), "--save-every-epoch", str(max(1, min(10, epochs // 5))),
                              "--save-only-latest", "--batch-size", str(batch_size_for(hw)),
                              "--gpu", "0" if hw["kind"] != "cpu" else "-1", "--pretrained"],
                  "train", cancel, on_line)
        self._collect(model_dir, exp, cancel)
        progress(1.0, "Training finished")

    def _collect(self, model_dir: Path, exp: Path, cancel) -> None:
        weights = [p for p in exp.glob("*.pth") if not re.match(r"^[GD]_", p.name)]
        if not weights:
            raise RuntimeError(f"Training produced no model file in {exp}")
        best = max(weights, key=lambda p: p.stat().st_mtime)
        index = exp / f"{MODEL_NAME}.index"
        if not index.exists():
            found = sorted(exp.glob("*.index"))
            if not found:
                self._run(model_dir, ["index", "--model-name", MODEL_NAME], "index", cancel)
                found = sorted(exp.glob("*.index"))
            if not found:
                raise RuntimeError(f"No .index file produced in {exp}")
            index = found[-1]
        shutil.copy2(best, model_dir / "model.pth")
        shutil.copy2(index, model_dir / "model.index")
        (model_dir / "meta.json").write_text(json.dumps({"weights": best.name, "sample_rate": int(SAMPLE_RATE)}))

    # ---- conversion
    def _model_args(self, model_dir: Path, transpose: int) -> list[str]:
        return ["--pth-path", str(model_dir / "model.pth"), "--index-path", str(model_dir / "model.index"),
                "--pitch", str(transpose), "--f0-method", "rmvpe", "--export-format", "WAV",
                "--embedder-model", "contentvec"]

    def convert(self, model_dir, src_wav, dst_wav, transpose=0):
        self.convert_batch(Path(model_dir), [(Path(src_wav), Path(dst_wav))], transpose, lambda f, m: None)

    def convert_batch(self, model_dir, pairs, transpose, progress: Progress, cancel=None):
        model_dir = Path(model_dir)
        done = 0
        for i in range(0, len(pairs), CHUNK):
            chunk = pairs[i : i + CHUNK]
            stage_in, stage_out = model_dir / "infer_in", model_dir / "infer_out"
            for d in (stage_in, stage_out):
                shutil.rmtree(d, ignore_errors=True)
                d.mkdir(parents=True)
            for src, dst in chunk:  # staged under the destination's name so outputs map back 1:1
                target = stage_in / f"{dst.stem}.wav"
                try:
                    os.link(src, target)
                except OSError:
                    shutil.copy2(src, target)
            self._run(model_dir, ["batch-infer", "--input-folder", str(stage_in), "--output-folder", str(stage_out),
                                  *self._model_args(model_dir, transpose)], "convert", cancel)
            for _, dst in chunk:
                out = stage_out / f"{dst.stem}_output.wav"
                if not out.exists():
                    raise RuntimeError(f"RVC produced no output for {dst.stem}")
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(out), str(dst))
            done += len(chunk)
            progress(done / len(pairs), f"Converting {done}/{len(pairs)}")
        for d in (model_dir / "infer_in", model_dir / "infer_out"):
            shutil.rmtree(d, ignore_errors=True)
