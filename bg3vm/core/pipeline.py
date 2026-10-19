"""The end-to-end stages: index -> extract -> dataset -> train -> convert -> encode -> package -> install."""
from __future__ import annotations

import json
from pathlib import Path

import soundfile as sf

from bg3vm.audio import dataset as ds
from bg3vm.audio.vgmstream import decode_wem
from bg3vm.audio.wem import wav_to_wem
from bg3vm.core.jobs import Context, Stage
from bg3vm.engines import get_engine
from bg3vm.game.lspk import PakReader
from bg3vm.game.steam import GameInstall, find_bg3
from bg3vm.game.voicemeta import index_voice_paks, lines_for_speaker
from bg3vm.mod.install import install_mod
from bg3vm.mod.package import build_mod, BuiltMod


def _game(ctx: Context) -> GameInstall:
    s = ctx.settings
    if s and s.game_dir:
        appdata = Path(s.bg3_appdata) if s.bg3_appdata else None
        return GameInstall(Path(s.game_dir), appdata)
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


def stage_extract(ctx: Context) -> None:
    p = ctx.project
    lines = json.loads((p.dir("index") / "lines.json").read_text())
    readers: dict[str, PakReader] = {}
    for i, ln in enumerate(lines):
        ctx.check()
        r = readers.setdefault(ln["pak"], PakReader(ln["pak"]))
        wem = p.dir("orig_wem") / f"{ln['key']}.wem"
        wem.write_bytes(r.read(ln["entry"]))
        decode_wem(wem, p.dir("orig_wav") / f"{ln['key']}.wav")
        ctx.emit((i + 1) / len(lines), f"Extracting {i + 1}/{len(lines)}")


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
    wavs = sorted(p.dir("orig_wav").glob("*.wav"))
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
        orig = sf.info(str(p.dir("orig_wav") / f"{ln['key']}.wav"))
        data = wav_to_wem(p.dir("conv_wav") / f"{ln['key']}.wav", orig.samplerate, orig.channels)
        (p.dir("new_wem") / f"{ln['key']}.wem").write_bytes(data)
        ctx.emit((i + 1) / len(lines), f"Encoding {i + 1}/{len(lines)}")


def stage_package(ctx: Context) -> None:
    p = ctx.project
    lines = json.loads((p.dir("index") / "lines.json").read_text())
    wems = {ln["entry"]: (p.dir("new_wem") / f"{ln['key']}.wem").read_bytes() for ln in lines}
    mod = build_mod(p.dir("out"), f"{p.name}", wems)
    (p.dir("out") / "mod.json").write_text(json.dumps({**mod.__dict__, "pak": str(mod.pak), "zip": str(mod.zip)}))
    ctx.emit(1.0, f"Built {mod.pak.name}")


def stage_install(ctx: Context) -> None:
    g = _game(ctx)
    if not g.appdata_dir:
        raise RuntimeError("Proton prefix not found; copy the .pak from the project's out/ folder manually.")
    d = json.loads((ctx.project.dir("out") / "mod.json").read_text())
    mod = BuiltMod(Path(d["pak"]), Path(d["zip"]), d["name"], d["folder"], d["uuid"], d["version64"])
    dest = install_mod(g.appdata_dir, mod)
    ctx.emit(1.0, f"Installed to {dest}")


STAGES = [
    Stage("index", "Find voice lines", stage_index),
    Stage("extract", "Extract original audio", stage_extract),
    Stage("dataset", "Prepare your recordings", stage_dataset),
    Stage("train", "Train voice model", stage_train),
    Stage("convert", "Convert lines", stage_convert),
    Stage("encode", "Encode .wem", stage_encode),
    Stage("package", "Build mod package", stage_package),
    Stage("install", "Install into game", stage_install),
]
