"""Index of voice lines in the game's Voice paks, and speaker -> handle mapping.

Listing wem files per handle works from pak entries alone. Mapping handles to *speakers*
needs VoiceMeta soundbanks (LSF); that parser is not written yet (UNVERIFIED format), so
the speaker map is loaded from a JSON file: {"Astarion": ["h1234...", ...]}.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .lspk import PakReader

_WEM = re.compile(r"(?:^|/)v?([0-9a-fA-F-]{8,})\.wem$")


@dataclass
class VoiceLine:
    key: str  # file stem, e.g. 'v123...'
    pak: str
    entry: str


def index_voice_paks(paks: list[Path]) -> dict[str, VoiceLine]:
    out: dict[str, VoiceLine] = {}
    for p in paks:
        for name in PakReader(p).names():
            if name.lower().endswith(".wem"):
                stem = name.rsplit("/", 1)[-1][:-4]
                out[stem] = VoiceLine(stem, str(p), name)
    return out


def load_speaker_map(path: Path) -> dict[str, list[str]]:
    return json.loads(Path(path).read_text())


def lines_for_speaker(index: dict[str, VoiceLine], speaker_map: dict[str, list[str]], speaker: str) -> list[VoiceLine]:
    wanted = speaker_map.get(speaker, [])
    return [index[k] for k in wanted if k in index]
