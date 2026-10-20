"""Locate Baldur's Gate 3 and its Proton prefix on Linux (native and Flatpak Steam)."""
from __future__ import annotations

import os
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
    appdata_dir: Path | None  # user folder holding Mods/ and PlayerProfiles/ (Proton prefix or native)

    @classmethod
    def from_game_dir(cls, game_dir: Path, appdata_override: Path | None = None,
                      home: Path | None = None) -> "GameInstall":
        """Build from a (possibly user-chosen) game folder; locate the Proton prefix automatically."""
        game_dir = Path(game_dir)
        return cls(game_dir, appdata_override or find_appdata(game_dir, home))

    @property
    def native(self) -> bool:
        """True for the native Linux build: the Windows build ships bin/bg3.exe."""
        return self.game_dir.is_dir() and not (self.game_dir / "bin" / "bg3.exe").exists()

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
        if not found and self.data_dir.is_dir():  # layout differs (e.g. native build): search the Data tree
            every = sorted(self.data_dir.rglob("Voice*.pak"))
            found = [p for p in every if "English" in p.parts] or every
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


LARIAN_DIRNAMES = ("Baldur's Gate 3", "Baldurs Gate 3", "Baldur’s Gate 3")


def _has_user_data(d: Path) -> bool:
    return (d / "PlayerProfiles").is_dir() or (d / "Mods").is_dir()


def _native_candidates(home: Path) -> list[Path]:
    """Folders where a native Linux Larian game may keep its user data (XDG data/config, Documents)."""
    out: list[Path] = []
    for base in (home / ".local/share", home / ".config", home / "Documents"):
        lar = base / "Larian Studios"
        if lar.is_dir():
            out += [lar / n for n in LARIAN_DIRNAMES if (lar / n).is_dir()]
            out += [d for d in lar.iterdir() if d.is_dir() and "baldur" in d.name.lower() and d not in out]
    return out


def _proton_candidates(game_dir: Path, home: Path) -> list[Path]:
    steamapps = [game_dir.parent.parent] + [lib / "steamapps" for lib in steam_libraries(home)]
    return [sa / "compatdata" / APP_ID / APPDATA_REL for sa in steamapps
            if (sa / "compatdata" / APP_ID / "pfx").is_dir()]


def _freshness(d: Path) -> float:
    ms = d / "PlayerProfiles" / "Public" / "modsettings.lsx"
    return ms.stat().st_mtime if ms.exists() else 0.0


def find_appdata(game_dir: Path, home: Path | None = None) -> Path | None:
    """Locate the user folder the game actually reads mods from.

    Only folders that exist (and hold game data) are returned: for the native Linux build there is no
    verified default location, so installing into a guessed folder would silently not load.
    The Proton prefix counts even if the game has not run yet (its Larian folder is created on install).
    """
    home = home or Path.home()
    native = not (game_dir / "bin" / "bg3.exe").exists() and game_dir.is_dir()
    with_data = [d for d in _native_candidates(home) if _has_user_data(d)]
    with_data.sort(key=_freshness, reverse=True)  # the one the game wrote to most recently wins
    proton = _proton_candidates(game_dir, home)
    order = (with_data + proton) if native else (proton + with_data)
    return order[0] if order else None


def search_appdata(home: Path | None = None, max_depth: int = 7) -> list[Path]:
    """Slow path: look for modsettings.lsx under the usual user directories; newest first."""
    home = home or Path.home()
    hits: dict[Path, float] = {}
    for base in (home / ".local/share", home / ".config", home / "Documents", home / ".steam", home / ".var"):
        if not base.is_dir():
            continue
        root_depth = len(base.parts)
        for dirpath, dirnames, filenames in os.walk(base):
            depth = len(Path(dirpath).parts) - root_depth
            if depth >= max_depth:
                dirnames[:] = []
            if "modsettings.lsx" in filenames:
                p = Path(dirpath)
                if p.name == "Public" and p.parent.name == "PlayerProfiles":
                    hits[p.parent.parent] = (p / "modsettings.lsx").stat().st_mtime
    return sorted(hits, key=hits.get, reverse=True)


def find_bg3(home: Path | None = None) -> GameInstall | None:
    home = home or Path.home()
    for lib in steam_libraries(home):
        game = lib / "steamapps" / "common" / GAME_DIRNAME
        if game.is_dir():
            return GameInstall.from_game_dir(game, home=home)
    return None
