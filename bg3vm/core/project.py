"""Project folder + manifest."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import PROJECTS_DIR


@dataclass
class Project:
    name: str
    root: Path
    speaker: str = ""  # known name or 32-hex speaker id
    voice_inputs: list[str] = field(default_factory=list)
    engine: str = "rvc"
    preset: str = "good"
    transpose: int = 0
    auto_pitch: bool = True  # estimate the semitone shift from your voice vs. the original line
    max_lines: int = 0  # 0 = all
    mod_uuid: str = field(default_factory=lambda: str(uuid.uuid4()))

    def dir(self, *parts: str) -> Path:
        d = self.root.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["root"] = str(self.root)
        (self.root / "project.json").write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, root: Path) -> "Project":
        data = json.loads((Path(root) / "project.json").read_text())
        data["root"] = Path(data["root"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def create(cls, name: str, base: Path | None = None, **kw) -> "Project":
        p = cls(name=name, root=(base or PROJECTS_DIR) / name, **kw)
        p.save()
        return p
