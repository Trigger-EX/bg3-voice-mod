"""Locate Baldur's Gate 3 and its Proton prefix on Linux (native and Flatpak Steam)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

APP_ID = "1086940"
GAME_DIRNAME = "Baldurs Gate 3"
APPDATA_REL = Path("pfx/drive_c/users/steamuser/AppData/Local/Larian Studios/Baldur's Gate 3")

STEAM_ROOTS = [
    ".local/share/Steam",
    ".steam/steam",
    ".steam/root",
    ".var/app/com.valvesoftware.Steam/.local/share/Steam",
]

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text: str) -> dict:
    """Minimal Valve KeyValues parser (quoted strings and braces)."""
    tokens = [m.group(1) if m.group(1) is not None else m.group(2) for m in _TOKEN.finditer(text)]
    pos = 0

    def block() -> dict:
        nonlocal pos
        out: dict = {}
        while pos < len(tokens):
            tok = tokens[pos]
            pos += 1
            if tok == "}":
                return out
            key = tok
            nxt = tokens[pos]
            pos += 1
            if nxt == "{":
                out[key] = block()
            else:
                out[key] = nxt.replace("\\\\", "\\")
        return out

    return block()


@dataclass
class GameInstall:
    game_dir: Path
    appdata_dir: Path | None  # Proton prefix 'Larian Studios/Baldur's Gate 3'

    @property
    def mods_dir(self) -> Path | None:
        return self.appdata_dir / "Mods" if self.appdata_dir else None

    @property
    def data_dir(self) -> Path:
        return self.game_dir / "Data"

    def voice_paks(self) -> list[Path]:
        found: list[Path] = []
        for sub in ("Localization/English", "Localization"):
            d = self.data_dir / sub
            if d.is_dir():
                found += sorted(d.glob("Voice*.pak"))
        return found


def steam_libraries(home: Path) -> list[Path]:
    libs: list[Path] = []
    for rel in STEAM_ROOTS:
        root = home / rel
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if not vdf.is_file():
            continue
        libs.append(root)
        data = parse_vdf(vdf.read_text(errors="replace")).get("libraryfolders", {})
        for entry in data.values():
            if isinstance(entry, dict) and "path" in entry:
                libs.append(Path(entry["path"]))
    seen, out = set(), []
    for lib in libs:
        key = str(lib.resolve()) if lib.exists() else str(lib)
        if key not in seen:
            seen.add(key)
            out.append(lib)
    return out


def find_bg3(home: Path | None = None) -> GameInstall | None:
    home = home or Path.home()
    for lib in steam_libraries(home):
        game = lib / "steamapps" / "common" / GAME_DIRNAME
        if game.is_dir():
            prefix = lib / "steamapps" / "compatdata" / APP_ID / APPDATA_REL
            return GameInstall(game, prefix if prefix.parent.exists() else None)
    return None
