"""Project folder + manifest."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import PROJECTS_DIR


@dataclass
class Project:
    name: str
    root: Path
    speaker: str = ""
    speaker_map: str = ""  # path to speakers.json
    voice_inputs: list[str] = field(default_factory=list)
    engine: str = "fake"
    preset: str = "good"
    transpose: int = 0
    max_lines: int = 0  # 0 = all

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
        return cls(**data)

    @classmethod
    def create(cls, name: str, base: Path | None = None, **kw) -> "Project":
        p = cls(name=name, root=(base or PROJECTS_DIR) / name, **kw)
        p.save()
        return p
