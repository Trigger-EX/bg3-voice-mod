import json
import sys
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf

from bg3vm.audio.wem import pcm_to_wem
from bg3vm.audio.dataset import split_on_silence, qc_report
from bg3vm.core.jobs import Context, run_stages
from bg3vm.core.project import Project
from bg3vm.core import audiocache, pipeline
from bg3vm.game.loca import build_loca, parse_loca
from bg3vm.game.lspk import PakReader, write_pak
from bg3vm.game.steam import find_bg3, parse_vdf
from bg3vm.mod.meta import pack_version64
from bg3vm.mod.package import build_mod
from bg3vm.mod.install import install_mod
import threading


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(audiocache, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(pipeline, "PROJECTS_DIR", tmp_path / "legacy_projects")
    from bg3vm.core import voices
    monkeypatch.setattr(voices, "VOICES_DIR", tmp_path / "voices")
    monkeypatch.setattr(voices, "PROJECTS_DIR", tmp_path / "proj_none")


def test_pak_roundtrip(tmp_path):
    files = {"a/b.wem": b"x" * 1000, "Mods/M/meta.lsx": b"<save/>"}
    write_pak(tmp_path / "t.pak", files)
    r = PakReader(tmp_path / "t.pak")
    assert set(r.names()) == set(files)
    assert all(r.read(k) == v for k, v in files.items())


def test_loca_roundtrip():
    d = {"h1": "Hello", "h2": "Wörld"}
    assert parse_loca(build_loca(d)) == d


def test_version64():
    assert pack_version64(1, 0, 0, 0) == 36028797018963968


def test_wem_header():
    w = pcm_to_wem(np.zeros(100, dtype="float32"), 24000)
    assert w[:4] == b"RIFF" and w[8:12] == b"WAVE"


def test_vdf_and_steam(tmp_path):
    lib = tmp_path / ".local/share/Steam"
    (lib / "steamapps/common/Baldurs Gate 3").mkdir(parents=True)
    (lib / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders" { "0" { "path" "%s" } }' % lib)
    assert parse_vdf('"a" { "b" "c" }') == {"a": {"b": "c"}}
    g = find_bg3(tmp_path)
    assert g and g.game_dir.name == "Baldurs Gate 3"


def test_split_and_qc():
    sr = 40000
    t = np.arange(sr * 3) / sr
    tone = 0.5 * np.sin(2 * np.pi * 200 * t).astype("float32")
    x = np.concatenate([tone, np.zeros(sr), tone])
    clips = split_on_silence(x, sr)
    assert len(clips) == 2
    assert qc_report(clips, sr).clips == 2


def test_install(tmp_path):
    mod = build_mod(tmp_path / "out", "Test Mod", {"v1.wem": b"abc"})
    app = tmp_path / "app"
    install_mod(app, mod)
    install_mod(app, mod)  # idempotent
    ms = (app / "PlayerProfiles/Public/modsettings.lsx").read_text()
    assert ms.count(mod.uuid) == 1


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_full_pipeline_fake_engine(tmp_path, monkeypatch):
    # fake game: Voice.pak with two wem lines (PCM wem is decodable by ffmpeg)
    game = tmp_path / "game"
    voice = game / "Data/Localization/English"
    voice.mkdir(parents=True)
    SPK = "c7c13742bacd460a8f65f864fe41f255"
    wems = {f"Mods/Gustav/Localization/English/Soundbanks/v{SPK}_h{i}abcdef01g1.wem": pcm_to_wem(np.random.uniform(-.3, .3, 24000).astype("float32"), 24000) for i in range(2)}
    write_pak(voice / "Voice.pak", wems)
    appdata = tmp_path / "appdata"
    # user recordings
    t = np.arange(40000 * 12) / 40000
    sf.write(str(tmp_path / "me.wav"), (0.4 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 0.2 * t) > -0.3)).astype("float32"), 40000)

    class S: game_dir = str(game); bg3_appdata = str(appdata)
    p = Project.create("t", base=tmp_path / "proj", engine="fake", speaker="Astarion",
                       voice_inputs=[str(tmp_path / "me.wav")])
    msgs = []
    run_stages(pipeline.STAGES, Context(p, lambda f, m: msgs.append(m), threading.Event(), S()))
    assert list((appdata / "Mods").glob("*.pak"))
    assert (p.root / "state/install.done").exists()


def test_speaker_parsing():
    from bg3vm.game.voicemeta import SPEAKER_RE, lines_for_speaker, VoiceLine, list_speakers
    stem = "v2c76687d93a2477b8b188a14b549304c_h109f706dg36cfg4089ga269gbe33b34cc981"
    m = SPEAKER_RE.match(stem)
    assert m and m.group(2).startswith("h109f706d")
    lines = [VoiceLine(stem, "p", "e", m.group(1), m.group(2))]
    assert lines_for_speaker(lines, "karlach") and lines_for_speaker(lines, "v" + m.group(1))
    assert list_speakers(lines)[0].name == "Karlach"


def test_appdata_found_in_other_library(tmp_path):
    from bg3vm.game.steam import GameInstall
    default = tmp_path / ".local/share/Steam"
    (default / "steamapps/compatdata/1086940/pfx").mkdir(parents=True)
    ext = tmp_path / "media/EVO1/SteamLibrary"
    (ext / "steamapps/common/Baldurs Gate 3/bin").mkdir(parents=True)
    (ext / "steamapps/common/Baldurs Gate 3/bin/bg3.exe").write_text("")  # Windows build -> Proton prefix
    (default / "steamapps/libraryfolders.vdf").write_text('"libraryfolders" { "0" { "path" "%s" } "1" { "path" "%s" } }' % (default, ext))
    g = GameInstall.from_game_dir(ext / "steamapps/common/Baldurs Gate 3", home=tmp_path)
    assert g.appdata_dir and "compatdata/1086940" in str(g.appdata_dir)
    assert GameInstall.from_game_dir(tmp_path / "nowhere/x/y", home=tmp_path / "empty").appdata_dir is None


def test_install_skipped_without_prefix(tmp_path, monkeypatch):
    import bg3vm.core.pipeline as pl
    monkeypatch.setattr(pl.GameInstall, "from_game_dir", classmethod(lambda cls, g, o=None, home=None: cls(g, None)))
    mod = build_mod(tmp_path / "proj/out", "m", {"a.wem": b"x"})
    p = Project.create("p", base=tmp_path / "proj2")
    (p.dir("out") / "mod.json").write_text(json.dumps({**mod.__dict__, "pak": str(mod.pak), "zip": str(mod.zip)}))
    class S: game_dir = str(tmp_path); bg3_appdata = ""
    msgs = []
    run_stages([pl.STAGES[-1]], Context(p, lambda f, m: msgs.append(m), threading.Event(), S()))
    assert not (p.root / "state/install.done").exists()
    assert "not installed" in msgs[-1]


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_changing_inputs_invalidates_old_work(tmp_path):
    A, B = "c7c13742bacd460a8f65f864fe41f255", "ad9af97d75da406aae137071c563f604"  # Astarion, Gale
    voice = tmp_path / "game/Data/Localization/English"
    voice.mkdir(parents=True)
    w = pcm_to_wem(np.random.uniform(-.3, .3, 24000).astype("float32"), 24000)
    write_pak(voice / "Voice.pak", {f"Mods/G/v{s}_h{i}g1.wem": w for s in (A, B) for i in range(2)})
    t = np.arange(40000 * 12) / 40000
    sf.write(str(tmp_path / "me.wav"), (0.4 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 0.2 * t) > -0.3)).astype("float32"), 40000)

    class S: game_dir = str(tmp_path / "game"); bg3_appdata = str(tmp_path / "ad")
    p = Project.create("t", base=tmp_path / "proj", engine="fake", speaker="Astarion", voice_inputs=[str(tmp_path / "me.wav")])
    ctx = Context(p, lambda f, m: None, threading.Event(), S())
    run_stages(pipeline.STAGES, ctx)
    first = {Path(l["wav"]).name for l in json.loads((p.root / "index/lines.json").read_text())}
    assert len(first) == 2 and all(A in n for n in first)
    # unchanged settings: nothing re-runs (dataset marker stays, clips untouched)
    clip = next((p.root / "dataset").glob("*.wav")); mtime = clip.stat().st_mtime_ns
    run_stages(pipeline.STAGES, ctx)
    assert clip.stat().st_mtime_ns == mtime
    # new character: old audio is wiped, downstream redone, dataset (independent of speaker) kept
    p.speaker = "Gale"
    run_stages(pipeline.STAGES, ctx)
    assert clip.stat().st_mtime_ns == mtime  # recordings/training don't depend on the character
    second = {Path(l["wav"]).name for l in json.loads((p.root / "index/lines.json").read_text())}
    assert len(second) == 2 and all(B in n for n in second)
    assert {x.name for x in (p.root / "new_wem").glob("*.wem")} == {n.replace(".wav", ".wem") for n in second}


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_extraction_shared_between_projects(tmp_path, monkeypatch):
    SPK = "c7c13742bacd460a8f65f864fe41f255"
    voice = tmp_path / "game/Data/Localization/English"
    voice.mkdir(parents=True)
    w = pcm_to_wem(np.random.uniform(-.3, .3, 24000).astype("float32"), 24000)
    write_pak(voice / "Voice.pak", {f"Mods/G/v{SPK}_h{i}g1.wem": w for i in range(3)})

    class S: game_dir = str(tmp_path / "game"); bg3_appdata = ""
    decoded = []
    real = audiocache.decode_many_to_cache
    monkeypatch.setattr(audiocache, "decode_many_to_cache",
                        lambda items, *a, **k: (decoded.extend(items), real(items, *a, **k))[1])

    def extract_only(name):
        p = Project.create(name, base=tmp_path / "proj", engine="fake", speaker="Astarion")
        run_stages(pipeline.STAGES[:2], Context(p, lambda f, m: None, threading.Event(), S()))
        return p

    extract_only("one")
    assert len(decoded) == 3
    p2 = extract_only("two")  # new project: everything comes from the shared cache
    assert len(decoded) == 3
    assert all(Path(l["wav"]).exists() for l in json.loads((p2.root / "index/lines.json").read_text()))


def test_legacy_project_audio_is_imported(tmp_path):
    old = tmp_path / "legacy_projects/old/orig_wav"
    old.mkdir(parents=True)
    (old / "vX_h1.wav").write_bytes(b"RIFFfake")
    got = pipeline._legacy_wavs()
    assert "vX_h1" in got
    dst = tmp_path / "c.wav"
    pipeline._link_or_copy(got["vX_h1"], dst)
    assert dst.read_bytes() == b"RIFFfake"


def test_sample_lines_prefers_mid_length():
    from bg3vm.game.voicemeta import VoiceLine, sample_lines
    lines = [VoiceLine(f"k{i}", "p", "e", "s", "h", size=i * 100) for i in range(1, 101)]
    picks = sample_lines(lines)
    assert len(picks) == 8 and all(3500 <= l.size <= 8500 for l in picks)
    assert len(sample_lines(lines[:3])) == 3


def test_native_linux_user_data_detection(tmp_path):
    from bg3vm.game.steam import GameInstall, search_appdata
    lib = tmp_path / ".local/share/Steam"
    game = lib / "steamapps/common/Baldurs Gate 3"
    (game / "Data").mkdir(parents=True)  # no bin/bg3.exe -> native build
    (lib / "steamapps/libraryfolders.vdf").write_text('"libraryfolders" { "0" { "path" "%s" } }' % lib)
    assert GameInstall(game, None).native
    default = tmp_path / ".local/share/Larian Studios/Baldur's Gate 3"
    assert GameInstall.from_game_dir(game, home=tmp_path).appdata_dir == default  # confirmed native location
    (lib / "steamapps/compatdata/1086940/pfx").mkdir(parents=True)  # leftover prefix must not win
    assert GameInstall.from_game_dir(game, home=tmp_path).appdata_dir == default
    data = tmp_path / ".local/share/Larian Studios/Baldur's Gate 3"
    (data / "PlayerProfiles/Public").mkdir(parents=True)
    (data / "PlayerProfiles/Public/modsettings.lsx").write_text("<save/>")
    assert GameInstall.from_game_dir(game, home=tmp_path).appdata_dir == data
    assert search_appdata(tmp_path) == [data]
    # a Windows build (bin/bg3.exe) prefers the Proton prefix when both exist
    (game / "bin").mkdir()
    (game / "bin/bg3.exe").write_text("")
    assert "compatdata" in str(GameInstall.from_game_dir(game, home=tmp_path).appdata_dir)
    assert not GameInstall(game, None).native


def test_voice_paks_found_in_unusual_layout(tmp_path):
    from bg3vm.game.steam import GameInstall
    d = tmp_path / "Data/Odd/English/Sub"
    d.mkdir(parents=True)
    (d / "Voice.pak").write_bytes(b"x")
    assert [p.name for p in GameInstall(tmp_path, None).voice_paks()] == ["Voice.pak"]


def test_parallel_decode_isolates_bad_files(tmp_path, monkeypatch):
    monkeypatch.setattr(audiocache, "CACHE_DIR", tmp_path / "cache")
    good = pcm_to_wem(np.random.uniform(-.3, .3, 8000).astype("float32"), 24000)
    write_pak(tmp_path / "V.pak", {f"v{i}.wem": (b"garbage" if i == 5 else good) for i in range(60)})
    items = [(str(tmp_path / "V.pak"), f"v{i}.wem", f"k{i}") for i in range(60)]
    seen = []
    bad = audiocache.decode_many_to_cache(items, lambda d, n: seen.append(d), None, tmp_path, workers=4, chunk=7)
    assert [k for k, _ in bad] == ["k5"]
    assert seen[-1] == 60
    assert all(audiocache.cached_path(str(tmp_path / "V.pak"), f"k{i}").exists() for i in range(60) if i != 5)


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_engine_downloads_in_background_and_training_waits(tmp_path):
    import time
    from bg3vm.core.background import BackgroundInstall
    from bg3vm.engines import ENGINES
    from bg3vm.engines.fake import FakeEngine

    events = []

    class SlowInstallEngine(FakeEngine):
        name, install_size_hint = "slow", "1 GB"
        ready = False

        def available(self):
            return (SlowInstallEngine.ready, "not installed")

        def install(self, progress, cancel=None):
            events.append(("install_start", time.monotonic()))
            for i in range(10):
                progress(i / 10, f"step {i}")
                time.sleep(0.15)
            SlowInstallEngine.ready = True
            events.append(("install_done", time.monotonic()))

        def train(self, *a, **k):
            events.append(("train", time.monotonic()))
            return super().train(*a, **k)

    ENGINES["slow"] = SlowInstallEngine
    try:
        SPK = "c7c13742bacd460a8f65f864fe41f255"
        voice = tmp_path / "game/Data/Localization/English"
        voice.mkdir(parents=True)
        w = pcm_to_wem(np.random.uniform(-.3, .3, 24000).astype("float32"), 24000)
        write_pak(voice / "Voice.pak", {f"Mods/G/v{SPK}_h{i}g1.wem": w for i in range(2)})
        t = np.arange(40000 * 12) / 40000
        sf.write(str(tmp_path / "me.wav"), (0.4 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 0.2 * t) > -0.3)).astype("float32"), 40000)

        class S: game_dir = str(tmp_path / "game"); bg3_appdata = str(tmp_path / "ad")
        p = Project.create("t", base=tmp_path / "proj", engine="slow", speaker="Astarion", voice_inputs=[str(tmp_path / "me.wav")])
        inst = BackgroundInstall(SlowInstallEngine())
        inst.start()
        stage_done = {}
        orig_run = {s.name: s.run for s in pipeline.STAGES}
        stages = [pipeline.Stage(s.name, s.label, (lambda ctx, n=s.name: (orig_run[n](ctx), stage_done.__setitem__(n, time.monotonic()))),
                                 s.key, s.outputs, s.always, s.deps) for s in pipeline.STAGES]
        run_stages(stages, Context(p, lambda f, m: None, threading.Event(), S(), inst))
        times = dict(events)
        assert stage_done["dataset"] < times["install_done"]   # recordings were prepared during the download
        assert times["train"] >= times["install_done"]         # training waited for it
        assert inst.ok
    finally:
        ENGINES.pop("slow", None)


def test_wait_raises_when_install_fails_or_is_cancelled():
    from bg3vm.core.background import BackgroundInstall
    from bg3vm.core.jobs import Cancelled
    from bg3vm.engines.fake import FakeEngine

    class Broken(FakeEngine):
        def available(self):
            return False, "not installed"

        def install(self, progress, cancel=None):
            raise RuntimeError("no network")

    b = BackgroundInstall(Broken())
    b.start()
    with pytest.raises(RuntimeError, match="no network"):
        b.wait(threading.Event(), poll=0.05)

    class Hang(FakeEngine):
        def available(self):
            return False, "not installed"

        def install(self, progress, cancel=None):
            threading.Event().wait(2)

    b2 = BackgroundInstall(Hang())
    b2.start()
    stop = threading.Event()
    stop.set()
    with pytest.raises(Cancelled):
        b2.wait(stop, poll=0.05)


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_trained_voice_is_saved_and_reused_for_another_character(tmp_path):
    from bg3vm.core import voices
    A, B = "c7c13742bacd460a8f65f864fe41f255", "ad9af97d75da406aae137071c563f604"
    voice = tmp_path / "game/Data/Localization/English"
    voice.mkdir(parents=True)
    w = pcm_to_wem(np.random.uniform(-.3, .3, 24000).astype("float32"), 24000)
    write_pak(voice / "Voice.pak", {f"Mods/G/v{s}_h{i}g1.wem": w for s in (A, B) for i in range(2)})
    t = np.arange(40000 * 12) / 40000
    sf.write(str(tmp_path / "me.wav"), (0.4 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 0.2 * t) > -0.3)).astype("float32"), 40000)

    class S: game_dir = str(tmp_path / "game"); bg3_appdata = str(tmp_path / "ad")
    one = Project.create("tav_one", base=tmp_path / "proj", engine="fake", speaker="Astarion",
                         voice_inputs=[str(tmp_path / "me.wav")])
    run_stages(pipeline.STAGES, Context(one, lambda f, m: None, threading.Event(), S()))
    saved = voices.list_voices("fake")
    assert [v.name for v in saved] == ["tav_one"] and saved[0].origin == "library"
    assert voices.read_info(saved[0].path).get("f0")

    # a different character, same voice: no recordings, nothing retrained
    two = Project.create("tav_two", base=tmp_path / "proj", engine="fake", speaker="Gale",
                         voice_model=str(saved[0].path))
    run_stages(pipeline.STAGES, Context(two, lambda f, m: None, threading.Event(), S()))
    assert not list((two.root / "dataset").glob("*.wav")) if (two.root / "dataset").exists() else True
    assert (two.root / "model/model.json").exists()
    assert list((tmp_path / "ad/Mods").glob("tav_two.pak"))
    assert {v.name for v in voices.list_voices("fake")} == {"tav_one"}  # reusing doesn't add duplicates


def test_project_models_trained_earlier_are_listed(tmp_path):
    from bg3vm.core import voices
    m = tmp_path / "projects/old/model"
    m.mkdir(parents=True)
    (m / "model.pth").write_bytes(b"x"); (m / "model.index").write_bytes(b"y")
    got = voices.list_voices("rvc", library=tmp_path / "nolib", projects=tmp_path / "projects")
    assert [(v.name, v.origin) for v in got] == [("old", "project")]


STUB_WORKER = '''
import json, sys, os
import numpy as np, soundfile as sf
spec = json.load(open(sys.argv[1]))
for i, j in enumerate(spec["jobs"], 1):
    n = int(24000 * (0.25 + 0.06 * len(j["text"].split())))
    t = np.arange(n) / 24000
    sf.write(j["out"], (0.3 * np.sin(2 * np.pi * 200 * t)).astype("float32"), 24000)
    print(f"OK {i}/{len(spec['jobs'])} {j['key']}", flush=True)
'''


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="needs ffmpeg")
def test_american_accent_stage_respeaks_and_keeps_timing(tmp_path, monkeypatch):
    import soundfile as sf
    from bg3vm.accent.tts import AccentTTS
    from bg3vm.game.loca import build_loca

    SPK = "c7c13742bacd460a8f65f864fe41f255"
    loc = tmp_path / "game/Data/Localization/English"
    loc.mkdir(parents=True)
    # the "original" lines: 1.5 s of tone with 0.2 s silence either side, 48 kHz like the real game files
    t = np.arange(int(48000 * 1.5)) / 48000
    body = (0.3 * np.sin(2 * np.pi * 120 * t)).astype("float32")
    orig = np.concatenate([np.zeros(9600, "float32"), body, np.zeros(9600, "float32")])
    wem = pcm_to_wem(orig, 48000)
    write_pak(loc / "Voice.pak", {f"Mods/G/v{SPK}_h{i}g1.wem": wem for i in range(3)})
    write_pak(loc / "English.pak", {"Localization/English/english.loca": build_loca({
        "h0g1": "I marked the <i>spot</i>, my friend, long ago.", "h1g1": "Hmm.", "h2g1": "[Laughs]"})})
    worker = tmp_path / "stub_worker.py"
    worker.write_text(STUB_WORKER)
    monkeypatch.setattr(pipeline, "AccentTTS", lambda: AccentTTS(worker_cmd=[sys.executable, str(worker)]))

    class S: game_dir = str(tmp_path / "game"); bg3_appdata = str(tmp_path / "ad")
    t2 = np.arange(40000 * 12) / 40000
    sf.write(str(tmp_path / "me.wav"), (0.4 * np.sin(2 * np.pi * 180 * t2) * (np.sin(2 * np.pi * 0.2 * t2) > -0.3)).astype("float32"), 40000)
    p = Project.create("acc", base=tmp_path / "proj", engine="fake", speaker="Astarion", accent="american",
                       voice_inputs=[str(tmp_path / "me.wav")])
    msgs = []
    run_stages(pipeline.STAGES, Context(p, lambda f, m: msgs.append(m), threading.Event(), S()))
    got = sorted(x.name for x in (p.root / "accent_wav").glob("*.wav"))
    assert got == [f"v{SPK}_h0g1.wav"]             # only the line with real words; "Hmm." and "[Laughs]" kept
    fitted, sr = sf.read(str(p.root / "accent_wav" / got[0]))
    assert sr == 48000 and len(fitted) == len(orig)  # exact original length
    start = np.nonzero(np.abs(fitted) > 0.01)[0][0]
    assert abs(start - 9600) < 600                   # speech starts where the original speech started
    assert any("1 lines re-spoken" in m for m in msgs)
    assert len(list((tmp_path / "ad/Mods").glob("acc.pak"))) == 1
