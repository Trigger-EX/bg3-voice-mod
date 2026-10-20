"""Runs INSIDE the Applio/RVC virtualenv (it has torch). Re-speaks text as American English with Kokoro.

Usage: python tts_worker.py jobs.json
jobs.json: {"voice": "am_michael", "speed": 1.0, "jobs": [{"key": ..., "text": ..., "out": ".../x.wav"}]}
Prints one status line per job: 'OK i/N key' or 'FAIL i/N key reason'. Existing outputs are skipped.
"""
import ctypes.util
import glob
import json
import os
import sys


def point_espeak_at_system_install() -> None:
    """The espeak copy bundled with espeakng-loader can have baked-in paths; prefer the system one."""
    lib = ctypes.util.find_library("espeak-ng")
    libs = glob.glob("/usr/lib*/**/libespeak-ng.so*", recursive=True) + glob.glob("/usr/lib/libespeak-ng.so*")
    data = next((d for d in glob.glob("/usr/lib*/**/espeak-ng-data", recursive=True) + ["/usr/share/espeak-ng-data"]
                 if os.path.isfile(os.path.join(d, "phontab"))), None)
    if not (libs and data):
        return
    import espeakng_loader
    path = next((p for p in libs if p.endswith(".so.1")), libs[0])
    espeakng_loader.get_library_path = lambda: path
    espeakng_loader.get_data_path = lambda: data


def main(jobs_file: str) -> int:
    spec = json.load(open(jobs_file, encoding="utf-8"))
    point_espeak_at_system_install()
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
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
