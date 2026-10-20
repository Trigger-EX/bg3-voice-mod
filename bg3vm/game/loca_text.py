"""English line text from the game's .loca files, keyed by the voice file's text handle."""
from __future__ import annotations

import html
import re
from pathlib import Path

from .loca import parse_loca
from .lspk import PakReader

_TAGS = re.compile(r"<[^>]*>|\{[^}]*\}|\[[^\]]*\]")


def clean_text(raw: str) -> str:
    """Plain speakable text: no markup, placeholders or stage directions."""
    t = html.unescape(_TAGS.sub(" ", raw))
    t = t.replace("…", "...").replace("—", ", ").replace("–", ", ")
    return re.sub(r"\s+", " ", t).strip()


def speakable(text: str, min_words: int = 2) -> bool:
    """Grunts, single interjections and empty lines are kept as the original audio."""
    words = re.findall(r"[A-Za-z']+", text)
    return len(words) >= min_words


def find_loca_paks(data_dir: Path) -> list[Path]:
    cands = sorted((data_dir / "Localization").rglob("*.pak")) if (data_dir / "Localization").is_dir() else []
    english = [p for p in cands if "English" in p.parts or p.stem.lower() == "english"]
    return [p for p in (english or cands) if not p.name.startswith("Voice")]


def load_texts(data_dir: Path, handles: set[str]) -> dict[str, str]:
    """handle -> cleaned text, for the requested handles only."""
    found: dict[str, str] = {}
    for pak in find_loca_paks(data_dir):
        reader = PakReader(pak)
        for name in reader.names():
            if name.lower().endswith(".loca"):
                for key, text in parse_loca(reader.read(name)).items():
                    if key in handles and key not in found:
                        found[key] = clean_text(text)
        if len(found) == len(handles):
            break
    return found
