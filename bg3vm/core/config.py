"""Paths and persistent settings (XDG-aware)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "bg3vm"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "bg3vm"
TOOLS_DIR = DATA_DIR / "tools"
PROJECTS_DIR = DATA_DIR / "projects"
CACHE_DIR = DATA_DIR / "cache"  # shared across projects: decoded original game audio


@dataclass
class Settings:
    game_dir: str = ""
    bg3_appdata: str = ""
    engine: str = "rvc"
    last_project: str = ""
    extra: dict = field(default_factory=dict)
    version: int = 2  # v1 defaulted the engine to the test engine

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or CONFIG_DIR / "settings.json"
        try:
            data = json.loads(path.read_text())
            st = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            if data.get("version", 1) < 2:
                st.engine, st.version = "rvc", 2
            return st
        except (OSError, ValueError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_DIR / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
