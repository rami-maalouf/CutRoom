# cut silences from a .screenstudio project by rewriting project.json slices.
# usage: uv run cut_silences.py <path/to/project.screenstudio> [--noise -35] [--min-silence 0.6] [--pad 0.15]
# thin adapter: detection lives in core.py, package i/o in screenstudio.py.

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import cleanup_cuts, collect_silences, resolve_pacing, silence_cuts  # noqa: E402
from screenstudio import check_package, mic_sessions, write_cut_package  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--pacing", choices=["tight", "balanced", "relaxed"], default="balanced",
                    help="how rigorous silence cutting is: tight cuts hard, relaxed embraces pauses")
    ap.add_argument("--noise", type=float, default=-35.0, help="silence threshold in dB")
    ap.add_argument("--min-silence", type=float, default=None, help="min silence duration in seconds")
    ap.add_argument("--pad", type=float, default=None, help="padding kept on each side of speech, seconds")
    ap.add_argument("--output", type=Path, default=None, help="output package path")
    args = ap.parse_args()
    resolve_pacing(args)

    src = args.project.resolve()
    print(f"screen studio project version: {check_package(src)}")

    sessions = mic_sessions(src)
    total_s = sum(s["durationMs"] for s in sessions) / 1000
    print(f"mic sessions: {len(sessions)}, total {total_s:.1f}s")

    silences = collect_silences(sessions, args.noise, args.min_silence)
    print(f"raw silences detected: {len(silences)}")

    cuts = silence_cuts(silences, args.pad * 1000)
    print(f"cuts after padding: {len(cuts)}")

    # no transcript here, so only ultra-short fragments are absorbed;
    # cut_project.py has word timings and cleans up more thoroughly
    cuts, absorbed = cleanup_cuts(cuts, total_s * 1000, words=None)
    if absorbed:
        print(f"cleanup: absorbed {len(absorbed)} tiny fragments")
    for s, e in cuts:
        print(f"  cut {s / 1000:8.2f}s -> {e / 1000:8.2f}s  ({(e - s) / 1000:.2f}s)")

    write_cut_package(src, cuts, args.output, "-cleaned")


if __name__ == "__main__":
    main()
