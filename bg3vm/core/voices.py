"""Library of trained voice models: train once, reuse for any character or mod."""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .config import DATA_DIR, PROJECTS_DIR

VOICES_DIR = DATA_DIR / "voices"
_MODEL_FILES = ("model.pth", "model.index", "meta.json", "model.json", "voice.json")


@dataclass
class VoiceModel:
    name: str
    path: Path
    engine: str
    origin: str  # "library" | "project"

    @property
    def label(self) -> str:
        return self.name if self.origin == "library" else f"{self.name} (from project)"


def engine_of(d: Path) -> str | None:
    if (d / "model.pth").exists() and (d / "model.index").exists():
        return "rvc"
    if (d / "model.json").exists():
        return "fake"
    return None


def list_voices(engine: str | None = None, library: Path | None = None,
                projects: Path | None = None) -> list[VoiceModel]:
    library, projects = library or VOICES_DIR, projects or PROJECTS_DIR
    out: list[VoiceModel] = []
    saved = set()
    for d in sorted(library.glob("*")) if library.is_dir() else []:
        if d.is_dir() and (e := engine_of(d)):
            out.append(VoiceModel(d.name, d, e, "library"))
            saved.add(d.name)
    for d in sorted(projects.glob("*/model")) if projects.is_dir() else []:  # trained before the library existed
        name = d.parent.name
        if name not in saved and (e := engine_of(d)):
            out.append(VoiceModel(name, d, e, "project"))
    return [v for v in out if engine in (None, v.engine)]


def read_info(d: Path) -> dict:
    try:
        return json.loads((d / "voice.json").read_text())
    except (OSError, ValueError):
        return {}


def save_voice(name: str, model_dir: Path, f0: float | None, library: Path | None = None) -> Path:
    dest = (library or VOICES_DIR) / name
    dest.mkdir(parents=True, exist_ok=True)
    for f in _MODEL_FILES:
        if (model_dir / f).exists():
            shutil.copy2(model_dir / f, dest / f)
    (dest / "voice.json").write_text(json.dumps({"f0": f0, "saved": time.strftime("%Y-%m-%d %H:%M")}))
    return dest


def use_voice(src: Path, model_dir: Path) -> None:
    """Copy a saved model into a project's model folder. Older project models get their pitch measured now."""
    model_dir.mkdir(parents=True, exist_ok=True)
    for f in _MODEL_FILES:
        if (src / f).exists():
            shutil.copy2(src / f, model_dir / f)
    if not (model_dir / "voice.json").exists() and (src.parent / "dataset").is_dir():
        from bg3vm.audio.pitch import median_f0
        f0 = median_f0(sorted((src.parent / "dataset").glob("*.wav"))[:60])
        (model_dir / "voice.json").write_text(json.dumps({"f0": f0}))
