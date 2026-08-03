# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-whisper"]
# ///
# cut repeated takes (restarts) from a .screenstudio project. transcribes the mic
# audio locally (mlx whisper), finds later sentences that re-start with the same
# opening words as an earlier one, and cuts the earlier take(s), keeping the last.
#
# usage: uv run cut_retakes.py <path/to/project.screenstudio> [--yes] [--dry-run]
# each proposed cut shows the removed vs kept text and asks for approval.
# thin adapter: detection lives in core.py, package i/o in screenstudio.py.

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import (  # noqa: E402
    collect_silences,
    drop_hallucinated_words,
    find_retake_cuts,
    review_cuts,
    transcribe_sessions,
    words_to_sentences,
)
from screenstudio import check_package, mic_sessions, write_cut_package  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--window", type=float, default=60.0,
                    help="max seconds between a bad take and its redo")
    ap.add_argument("--threshold", type=float, default=0.75,
                    help="opening-words similarity 0..1 to count as a retake")
    ap.add_argument("--pre-roll", type=float, default=0.1,
                    help="seconds kept before the final take's first word")
    ap.add_argument("--yes", action="store_true", help="approve all cuts without asking")
    ap.add_argument("--dry-run", action="store_true", help="detect and review only, write nothing")
    ap.add_argument("--output", type=Path, default=None, help="output package path")
    args = ap.parse_args()

    src = args.project.resolve()
    print(f"screen studio project version: {check_package(src)}")

    sessions = mic_sessions(src)
    words = transcribe_sessions(sessions, src.with_suffix(".transcript.json"))
    silences = collect_silences(sessions)
    words, dropped = drop_hallucinated_words(words, silences)
    if dropped:
        print(f"dropped {len(dropped)} hallucinated words (inside silence): "
              f"{' '.join(w['word'] for w in dropped[:12])}...")
    sentences = words_to_sentences(words)
    print(f"transcript sentences: {len(sentences)}")

    cuts = find_retake_cuts(sentences, args.window, args.threshold, args.pre_roll * 1000)
    if not cuts:
        print("no retakes detected")
        return
    print(f"proposed retake cuts: {len(cuts)}")

    approved = review_cuts(cuts, args.yes)
    total_s = sum(c["endMs"] - c["startMs"] for c in approved) / 1000
    print(f"\napproved {len(approved)}/{len(cuts)} cuts, {total_s:.1f}s to remove")
    if args.dry_run or not approved:
        print("dry run - nothing written" if args.dry_run else "nothing to write")
        return

    cut_ranges = [(c["startMs"], c["endMs"]) for c in approved]
    write_cut_package(src, cut_ranges, args.output, "-retakes")


if __name__ == "__main__":
    main()
