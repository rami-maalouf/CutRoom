# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-whisper"]
# ///
# full pipeline for a .screenstudio project in one pass: retake cuts + silence
# cuts + wordless-fragment cleanup, with a single transcription. this is the
# screen studio twin of cut_video.py - both are thin adapters over core.py.
#
# usage: uv run cut_project.py <path/to/project.screenstudio> [--yes] [--dry-run]
# retake cuts are approved one by one (removed vs kept text); silence cuts are
# approved as a batch (use --review-silences for one-by-one).
# writes <name>-clean.screenstudio next to the original; never overwrites.

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import (  # noqa: E402
    cleanup_cuts,
    collect_silences,
    drop_hallucinated_words,
    find_retake_cuts,
    merge_ranges,
    review_cuts,
    resolve_pacing,
    silence_cuts,
    transcribe_sessions,
    words_to_sentences,
)
from screenstudio import check_package, mic_sessions, write_cut_package  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--pacing", choices=["tight", "balanced", "relaxed"], default="balanced",
                    help="how rigorous silence cutting is: tight cuts hard, relaxed embraces pauses")
    ap.add_argument("--noise", type=float, default=-35.0, help="silence threshold in dB")
    ap.add_argument("--min-silence", type=float, default=None, help="min silence duration in seconds")
    ap.add_argument("--pad", type=float, default=None, help="padding kept on each side of speech, seconds")
    ap.add_argument("--window", type=float, default=60.0,
                    help="max seconds between a bad take and its redo")
    ap.add_argument("--threshold", type=float, default=0.75,
                    help="opening-words similarity 0..1 to count as a retake")
    ap.add_argument("--pre-roll", type=float, default=0.1,
                    help="seconds kept before the final take's first word")
    ap.add_argument("--min-keep", type=float, default=None,
                    help="wordless kept fragments shorter than this (seconds) are absorbed into cuts")
    ap.add_argument("--no-retakes", action="store_true", help="skip retake detection")
    ap.add_argument("--no-silences", action="store_true", help="skip silence cutting")
    ap.add_argument("--review-silences", action="store_true",
                    help="approve silence cuts one by one instead of as a batch")
    ap.add_argument("--yes", action="store_true", help="approve all cuts without asking")
    ap.add_argument("--dry-run", action="store_true", help="detect and review only, write nothing")
    ap.add_argument("--output", type=Path, default=None, help="output package path")
    args = ap.parse_args()
    resolve_pacing(args)

    src = args.project.resolve()
    print(f"screen studio project version: {check_package(src)}")

    sessions = mic_sessions(src)
    total_ms = sum(s["durationMs"] for s in sessions)
    print(f"mic sessions: {len(sessions)}, total {total_ms / 1000:.1f}s")

    silences = collect_silences(sessions, args.noise, args.min_silence)
    approved_ranges: list[tuple[float, float]] = []
    words: list[dict] | None = None
    interactive = sys.stdin.isatty() and not args.yes

    # retake cuts: reviewed one by one, they carry semantic content
    if not args.no_retakes:
        words = transcribe_sessions(sessions, src.with_suffix(".transcript.json"))
        words, dropped = drop_hallucinated_words(words, silences)
        if dropped:
            print(f"dropped {len(dropped)} hallucinated words (inside silence)")
        sentences = words_to_sentences(words)
        print(f"transcript sentences: {len(sentences)}")
        retakes = find_retake_cuts(sentences, args.window, args.threshold, args.pre_roll * 1000)
        print(f"proposed retake cuts: {len(retakes)}")
        approved = review_cuts(retakes, args.yes) if retakes else []
        approved_ranges += [(c["startMs"], c["endMs"]) for c in approved]

    # silence cuts: batch approval by default (there are usually hundreds)
    if not args.no_silences:
        cuts = silence_cuts(silences, args.pad * 1000)
        total_cut_s = sum(e - s for s, e in cuts) / 1000
        print(f"\nproposed silence cuts: {len(cuts)}, total {total_cut_s:.1f}s")
        if args.review_silences:
            reviewed = review_cuts(
                [{"startMs": s, "endMs": e, "reason": "silence"} for s, e in cuts], args.yes
            )
            approved_ranges += [(c["startMs"], c["endMs"]) for c in reviewed]
        else:
            take_all = True
            if interactive:
                take_all = input("  approve all silence cuts? [Y/n] ").strip().lower() not in ("n", "no")
            if take_all:
                approved_ranges += cuts
            else:
                print("  silence cuts skipped (use --review-silences for one-by-one)")

    if not approved_ranges:
        print("no cuts approved - nothing to do")
        return

    # cleanup layer: absorb tiny wordless fragments left between approved cuts
    final_cuts, absorbed = cleanup_cuts(
        merge_ranges(approved_ranges), total_ms, words, args.min_keep * 1000
    )
    if absorbed:
        gone = sum(e - s for s, e in absorbed) / 1000
        print(f"cleanup: absorbed {len(absorbed)} wordless fragments ({gone:.1f}s)")
        for s, e in absorbed:
            print(f"  absorbed {s / 1000:8.2f}s -> {e / 1000:8.2f}s  ({(e - s) / 1000:.2f}s)")

    if args.dry_run:
        cut_s = sum(e - s for s, e in final_cuts) / 1000
        print(f"\ndry run - would cut {cut_s:.1f}s of {total_ms / 1000:.1f}s, nothing written")
        return

    write_cut_package(src, final_cuts, args.output, "-clean")


if __name__ == "__main__":
    main()
