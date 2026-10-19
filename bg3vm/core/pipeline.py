"""The end-to-end stages: index -> extract -> dataset -> train -> convert -> encode -> package -> install."""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

import soundfile as sf

from bg3vm.audio import dataset as ds
from bg3vm.audio.vgmstream import decode_wem
from bg3vm.audio.wem import wav_to_wem
from bg3vm.core.config import CACHE_DIR, PROJECTS_DIR
from bg3vm.core.jobs import Context, Skip, Stage
from bg3vm.core.logs import LOG_FILE
from bg3vm.engines import get_engine
from bg3vm.game.lspk import PakReader
from bg3vm.game.steam import GameInstall, find_bg3
from bg3vm.game.voicemeta import index_voice_paks, lines_for_speaker
from bg3vm.mod.install import install_mod
from bg3vm.mod.package import build_mod, BuiltMod

log = logging.getLogger("bg3vm.pipeline")


def _game(ctx: Context) -> GameInstall:
    s = ctx.settings
    if s and s.game_dir:
        return GameInstall.from_game_dir(Path(s.game_dir), Path(s.bg3_appdata) if s.bg3_appdata else None)
    g = find_bg3()
    if not g:
        raise RuntimeError("Baldur's Gate 3 not found; set the game folder in Setup.")
    return g


def stage_index(ctx: Context) -> None:
    p = ctx.project
    paks = _game(ctx).voice_paks()
    if not paks:
        raise RuntimeError("No Voice*.pak found in the game's Localization folder.")
    ctx.emit(0.0, "Indexing voice packs…")
    index = index_voice_paks(paks)
    lines = lines_for_speaker(index, p.speaker)
    if p.max_lines:
        lines = lines[: p.max_lines]
    if not lines:
        raise RuntimeError(f"No voice lines found for {p.speaker!r}.")
    (p.dir("index") / "lines.json").write_text(json.dumps([l.__dict__ for l in lines]))
    ctx.emit(1.0, f"{len(lines)} lines for {p.speaker}")


def _cache_dir(pak: str) -> Path:
    """Decoded audio is cached per pak build (name, size, mtime), so a game update never serves stale audio."""
    st = os.stat(pak)
    return CACHE_DIR / "orig_wav" / f"{Path(pak).stem}-{st.st_size}-{int(st.st_mtime)}"


def _link_or_copy(src: Path, dst: Path) -> None:
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        os.link(src, tmp)
    except OSError:
        shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def _legacy_wavs() -> dict[str, Path]:
    """Audio decoded by earlier versions lives inside each project; reuse it instead of decoding again."""
    return {f.stem: f for d in PROJECTS_DIR.glob("*/orig_wav") for f in d.glob("*.wav")}


def stage_extract(ctx: Context) -> None:
    p = ctx.project
    lines = json.loads((p.dir("index") / "lines.json").read_text())
    readers: dict[str, PakReader] = {}
    legacy: dict[str, Path] | None = None
    failed: list[dict] = []
    reused = 0
    for i, ln in enumerate(lines):
        ctx.check()
        cdir = _cache_dir(ln["pak"])
        cdir.mkdir(parents=True, exist_ok=True)
        wav = cdir / f"{ln['key']}.wav"
        ln["wav"] = str(wav)
        if wav.exists():
            reused += 1
        else:
            try:
                if legacy is None:
                    legacy = _legacy_wavs()
                if ln["key"] in legacy:
                    _link_or_copy(legacy[ln["key"]], wav)
                    reused += 1
                else:
                    r = readers.setdefault(ln["pak"], PakReader(ln["pak"]))
                    with tempfile.TemporaryDirectory(dir=p.dir("tmp")) as td:
                        wem = Path(td) / f"{ln['key']}.wem"
                        part = Path(td) / f"{ln['key']}.wav"
                        wem.write_bytes(r.read(ln["entry"]))
                        decode_wem(wem, part)
                        shutil.move(str(part), str(wav) + ".tmp")  # never leave a half-written cache file
                        os.replace(str(wav) + ".tmp", wav)
            except Exception as e:
                log.warning("extract failed for %s: %s", ln["key"], e, exc_info=True)
                failed.append({"key": ln["key"], "error": str(e)})
                ln["wav"] = ""
        ctx.emit((i + 1) / len(lines), f"Extracting {i + 1}/{len(lines)}")
    (p.dir("index") / "extract_failed.json").write_text(json.dumps(failed, indent=2))
    lines = [l for l in lines if l["wav"]]
    (p.dir("index") / "lines.json").write_text(json.dumps(lines))
    if reused:
        ctx.emit(1.0, f"Reused {reused} previously extracted lines from the shared cache.")
    if failed:
        ctx.emit(1.0, f"{len(failed)} line(s) could not be decoded and were skipped (see log).")
    if len(failed) > (len(lines) + len(failed)) * 0.2:
        raise RuntimeError(f"{len(failed)} lines failed to decode; see {LOG_FILE}")


def stage_dataset(ctx: Context) -> None:
    p = ctx.project
    qc = ds.prepare_dataset([Path(x) for x in p.voice_inputs], p.dir("dataset"), p.dir("tmp"))
    ctx.emit(1.0, f"{qc.clips} clips, {qc.minutes:.1f} min" + ("".join(f"\n⚠ {w}" for w in qc.warnings)))


def _engine(ctx: Context):
    eng = get_engine(ctx.project.engine)
    ok, why = eng.available()
    if not ok:
        raise RuntimeError(f"Engine {eng.label} unavailable: {why}")
    return eng


def stage_train(ctx: Context) -> None:
    p = ctx.project
    _engine(ctx).train(p.dir("dataset"), p.dir("model"), p.preset, ctx.emit)


def stage_convert(ctx: Context) -> None:
    p = ctx.project
    eng = _engine(ctx)
    lines = json.loads((p.dir("index") / "lines.json").read_text())
    wavs = [Path(ln["wav"]) for ln in lines]
    for i, w in enumerate(wavs):
        ctx.check()
        dst = p.dir("conv_wav") / w.name
        if not dst.exists():
            eng.convert(p.dir("model"), w, dst, p.transpose)
        ctx.emit((i + 1) / len(wavs), f"Converting {i + 1}/{len(wavs)}")


def stage_encode(ctx: Context) -> None:
    p = ctx.project
    lines = json.loads((p.dir("index") / "lines.json").read_text())
    for i, ln in enumerate(lines):
        ctx.check()
        orig = sf.info(ln["wav"])
        data = wav_to_wem(p.dir("conv_wav") / f"{ln['key']}.wav", orig.samplerate, orig.channels)
        (p.dir("new_wem") / f"{ln['key']}.wem").write_bytes(data)
        ctx.emit((i + 1) / len(lines), f"Encoding {i + 1}/{len(lines)}")


def stage_package(ctx: Context) -> None:
    p = ctx.project
    lines = json.loads((p.dir("index") / "lines.json").read_text())
    wems = {ln["entry"]: (p.dir("new_wem") / f"{ln['key']}.wem").read_bytes() for ln in lines}
    mod = build_mod(p.dir("out"), p.name, wems, p.mod_uuid)
    (p.dir("out") / "mod.json").write_text(json.dumps({**mod.__dict__, "pak": str(mod.pak), "zip": str(mod.zip)}))
    ctx.emit(1.0, f"Built {mod.pak.name}")


def stage_install(ctx: Context) -> None:
    g = _game(ctx)
    d = json.loads((ctx.project.dir("out") / "mod.json").read_text())
    mod = BuiltMod(Path(d["pak"]), Path(d["zip"]), d["name"], d["folder"], d["uuid"], d["version64"])
    if not g.appdata_dir:
        ctx.emit(1.0, f"Couldn't find BG3's Proton folder, so the mod was not installed.\n"
                      f"Your mod is ready: {mod.pak}\n"
                      f"Copy it into <BG3 user folder>/Mods, or set that folder in Setup and run again.")
        (ctx.project.dir("state") / "install.done").unlink(missing_ok=True)
        raise Skip()
    dest = install_mod(g.appdata_dir, mod)
    ctx.emit(1.0, f"Installed to {dest}")


def _inputs_fp(p) -> list:
    """Recordings identified by path, size and mtime, so edits to the files also invalidate training."""
    out = []
    for raw in p.voice_inputs:
        base = Path(raw)
        files = [f for f in base.rglob("*") if f.is_file()] if base.is_dir() else [base]
        out += [(str(f), f.stat().st_size, int(f.stat().st_mtime)) for f in sorted(files) if f.exists()]
    return out


STAGES = [
    Stage("index", "Find voice lines", stage_index,
          key=lambda p: [p.speaker.lower(), p.max_lines], outputs=("index",)),
    Stage("extract", "Extract original audio", stage_extract, deps=("index",)),
    Stage("dataset", "Prepare your recordings", stage_dataset,
          key=_inputs_fp, outputs=("dataset", "tmp", "qc.json")),
    Stage("train", "Train voice model", stage_train,
          key=lambda p: [p.engine, p.preset], deps=("dataset",), outputs=("model",)),
    Stage("convert", "Convert lines", stage_convert, key=lambda p: p.transpose,
          deps=("train", "extract"), outputs=("conv_wav",)),
    Stage("encode", "Encode .wem", stage_encode, deps=("convert",), outputs=("new_wem",)),
    Stage("package", "Build mod package", stage_package, key=lambda p: p.name,
          deps=("encode",), outputs=("out",)),
    Stage("install", "Install into game", stage_install, always=True, deps=("package",)),
]
