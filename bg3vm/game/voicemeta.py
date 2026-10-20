"""Index of voice lines in the game's Voice paks, grouped by speaker.

Voice files are named ``v<speaker-uuid-without-hyphens>_h<text-handle>.wem`` (see BG3 Modding
Community Wiki, "Localization Voicelines"), so the speaker comes straight from the filename and
the ``h...`` part is also the line's key in English.loca. No LSF parsing is needed.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .lspk import PakReader

SPEAKER_RE = re.compile(r"^v([0-9a-fA-F]{32})_(h[0-9a-zA-Z]+)$")

# Speaker prefixes published on the BG3 Modding Community Wiki (without the leading 'v').
# The Tav numbering has been observed NOT to match the in-game voice numbers: audition before trusting it.
KNOWN_SPEAKERS = {
    "c7c13742bacd460a8f65f864fe41f255": "Astarion",
    "ad9af97d75da406aae137071c563f604": "Gale",
    "7628bc0e52b842a7856a13a6fd413323": "Halsin",
    "91b6b2007d004d628dc999e8339dfa1a": "Jaheira",
    "58a6933340bf83581d17fff240d7fb12": "Lae'zel",
    "2c76687d93a2477b8b188a14b549304c": "Karlach",
    "0de603c542e248119dadf652de080eba": "Minsc",
    "257213130c15493581769f134385451b": "Minthara",
    "3ed74f063c6042dc83f6f034cb47c679": "Shadowheart",
    "c774d7644a1748dcb47032ace9ce447d": "Wyll",
    "24247531c4324f0f8f356c90c4844aa8": "Tav voice (wiki #1, unverified)",
    "2d206fda0d4f457fb4ea0fc18866f5dd": "Tav voice (wiki #2, unverified)",
    "3347e417d7ad4088bdd6d5565efcd815": "Tav voice 4 (female; wiki lists it as #3)",
    "4df6dba085744704a9fba500da38e1e1": "Tav voice 3 (male; wiki lists it as #4)",
    "869248f0468a474782d7e8efc3bbcacf": "Tav voice (wiki #5, unverified)",
    "b9b26a44943b44279890d81c7e81a75b": "Tav voice (wiki #6, unverified)",
    "f5b335b29cd94b38a4c1458b846ab499": "Tav voice (wiki #7, unverified)",
    "fb6b53538d1445079222ceaec990fce9": "Tav voice (wiki #8, unverified)",
}


@dataclass
class VoiceLine:
    key: str  # file stem, e.g. 'v<uuid>_h<handle>'
    pak: str
    entry: str  # path inside the pak
    speaker: str  # 32-hex id, lowercase
    handle: str  # loca key
    size: int = 0  # bytes in the pak; a rough proxy for line length


@dataclass
class Speaker:
    id: str
    name: str
    lines: int


def speaker_name(speaker_id: str) -> str:
    return KNOWN_SPEAKERS.get(speaker_id.lower(), f"Unknown {speaker_id[:8]}")


def index_voice_paks(paks: list[Path]) -> list[VoiceLine]:
    out: list[VoiceLine] = []
    for p in paks:
        reader = PakReader(p)
        for name in reader.names():
            if not name.lower().endswith(".wem"):
                continue
            stem = name.rsplit("/", 1)[-1][:-4]
            m = SPEAKER_RE.match(stem)
            if m:
                out.append(VoiceLine(stem, str(p), name, m.group(1).lower(), m.group(2), reader.entries[name].size))
    return out


def list_speakers(lines: list[VoiceLine]) -> list[Speaker]:
    counts = Counter(l.speaker for l in lines)
    return sorted((Speaker(i, speaker_name(i), n) for i, n in counts.items()),
                  key=lambda s: (s.name.startswith("Unknown"), -s.lines))


def lines_for_speaker(lines: list[VoiceLine], speaker: str) -> list[VoiceLine]:
    """``speaker`` may be a known name (case-insensitive), a 32-hex id, or with a leading 'v'."""
    want = speaker.strip().lower()
    ids = {i for i, n in KNOWN_SPEAKERS.items() if n.lower() == want}
    ids.add(want[1:] if len(want) == 33 and want[0] == "v" else want)
    return [l for l in lines if l.speaker in ids]


def sample_lines(lines: list[VoiceLine], n: int = 8) -> list[VoiceLine]:
    """A few mid-length lines (skipping one-word barks and long monologues) to audition a speaker."""
    ordered = sorted(lines, key=lambda l: l.size)
    if len(ordered) <= n:
        return ordered
    lo, hi = int(len(ordered) * 0.35), int(len(ordered) * 0.85)
    step = max(1, (hi - lo) // n)
    return ordered[lo:hi:step][:n]
