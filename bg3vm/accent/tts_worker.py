"""Runs INSIDE the Applio/RVC virtualenv (it has torch). Re-speaks text as American English with Kokoro.

Usage: python tts_worker.py jobs.json
jobs.json: {"voice": "am_michael", "speed": 1.0, "jobs": [{"key": ..., "text": ..., "out": ".../x.wav"}]}
Prints one status line per job: 'OK i/N key' or 'FAIL i/N key reason'. Existing outputs are skipped.
"""
import json
import os
import sys
import time

# Plain HTTP downloads: the newer chunked/Xet transfer path can stall silently on some networks.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")


def step(msg: str) -> None:
    print(f"STEP {time.strftime('%H:%M:%S')} {msg}", flush=True)


def point_espeak_at_system_install() -> None:
    """The espeak copy bundled with espeakng-loader can have baked-in paths; prefer the system one.

    Only a handful of fixed directories are checked (no recursive globbing: that can crawl symlink loops).
    """
    lib_dirs = ["/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib64", "/usr/lib", "/usr/local/lib"]
    lib = next((os.path.join(d, n) for d in lib_dirs for n in ("libespeak-ng.so.1", "libespeak-ng.so")
                if os.path.exists(os.path.join(d, n))), None)
    data = next((d for d in [os.path.join(d, "espeak-ng-data") for d in lib_dirs] + ["/usr/share/espeak-ng-data"]
                 if os.path.isfile(os.path.join(d, "phontab"))), None)
    if not (lib and data):
        step("system espeak-ng not found; using the bundled copy")
        return
    import espeakng_loader
    espeakng_loader.get_library_path = lambda: lib
    espeakng_loader.get_data_path = lambda: data
    step(f"using system espeak-ng ({lib})")


def main(jobs_file: str) -> int:
    spec = json.load(open(jobs_file, encoding="utf-8"))
    point_espeak_at_system_install()
    step("importing speech libraries")
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    step("loading the speech model (downloads ~330 MB the first time)")
    pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    step("speech model ready")
    jobs = spec["jobs"]
    for i, job in enumerate(jobs, 1):
        if os.path.exists(job["out"]):
            print(f"OK {i}/{len(jobs)} {job['key']}", flush=True)
            continue
        try:
            chunks = [np.asarray(a.numpy() if hasattr(a, "numpy") else a)
                      for _, _, a in pipe(job["text"], voice=spec["voice"], speed=spec.get("speed", 1.0))]
            if not chunks:
                raise RuntimeError("no audio produced")
            os.makedirs(os.path.dirname(job["out"]), exist_ok=True)
            tmp = job["out"] + ".part.wav"
            sf.write(tmp, np.concatenate(chunks), 24000)
            os.replace(tmp, job["out"])
            print(f"OK {i}/{len(jobs)} {job['key']}", flush=True)
        except Exception as e:  # one bad line must not stop the batch
            print(f"FAIL {i}/{len(jobs)} {job['key']} {type(e).__name__}: {e}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
