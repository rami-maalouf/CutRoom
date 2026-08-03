# /// script
# requires-python = ">=3.11"
# dependencies = ["mlx-whisper"]
# ///
# cut silences AND repeated takes from a normal video file (mp4/mov/...).
# same detection core as the .screenstudio scripts (core.py) - improvements
# there apply here automatically. the only difference is i/o: audio comes from
# the video's own track, and output is rendered with ffmpeg (frame-accurate,
# re-encoded) since there is no project file to rewrite.
#
# usage: uv run cut_video.py <video.mp4> [--yes] [--dry-run] [--no-retakes] [--no-silences]
# retake cuts are approved one by one (removed vs kept text); silence cuts are
# approved as a batch (use --review-silences for one-by-one).
# writes <name>-clean.mp4 next to the original; never overwrites anything.

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import (  # noqa: E402
    cleanup_cuts,
    collect_silences,
    drop_hallucinated_words,
    find_retake_cuts,
    invert_cuts,
    merge_ranges,
    review_cuts,
    resolve_pacing,
    silence_cuts,
    transcribe_sessions,
    versioned_output,
    words_to_sentences,
)


def probe(video: Path) -> tuple[float, bool]:
    # returns (duration_ms, has_audio)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=codec_type", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    duration_ms = float(data["format"]["duration"]) * 1000
    has_audio = any(s.get("codec_type") == "audio" for s in data["streams"])
    return duration_ms, has_audio


def render(video: Path, keeps: list[tuple[float, float]], dst: Path) -> None:
    # frame-accurate assembly of kept ranges via trim/concat, re-encoded
    parts_v, parts_a, labels = [], [], []
    for i, (s, e) in enumerate(keeps):
        ss, es = s / 1000, e / 1000
        parts_v.append(f"[0:v]trim=start={ss:.3f}:end={es:.3f},setpts=PTS-STARTPTS[v{i}];")
        parts_a.append(f"[0:a]atrim=start={ss:.3f}:end={es:.3f},asetpts=PTS-STARTPTS[a{i}];")
        labels.append(f"[v{i}][a{i}]")
    script = "\n".join(parts_v + parts_a) + \
        f"\n{''.join(labels)}concat=n={len(keeps)}:v=1:a=1[v][a]"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(script)
        script_path = f.name
    print(f"rendering {len(keeps)} segments -> {dst.name} ...")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats",
         "-i", str(video), "-filter_complex_script", script_path,
         "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-c:a", "aac", "-b:a", "192k", str(dst)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
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
    ap.add_argument("--output", type=Path, default=None, help="output video path")
    args = ap.parse_args()
    resolve_pacing(args)

    src = args.video.resolve()
    if not src.is_file():
        sys.exit(f"not a video file: {src}")
    duration_ms, has_audio = probe(src)
    if not has_audio:
        sys.exit("video has no audio track - nothing to analyze")
    print(f"video: {src.name}, {duration_ms / 1000:.1f}s")
    sessions = [{"path": src, "durationMs": duration_ms}]

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
        total_s = sum(e - s for s, e in cuts) / 1000
        print(f"\nproposed silence cuts: {len(cuts)}, total {total_s:.1f}s")
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
        approved_ranges, duration_ms, words, args.min_keep * 1000
    )
    if absorbed:
        gone = sum(e - s for s, e in absorbed) / 1000
        print(f"cleanup: absorbed {len(absorbed)} wordless fragments ({gone:.1f}s)")
        for s, e in absorbed:
            print(f"  absorbed {s / 1000:8.2f}s -> {e / 1000:8.2f}s  ({(e - s) / 1000:.2f}s)")

    keeps = invert_cuts(final_cuts, duration_ms)
    kept_s = sum(e - s for s, e in keeps) / 1000
    print(f"\nfinal: {len(keeps)} kept segments, "
          f"{duration_ms / 1000:.1f}s -> {kept_s:.1f}s "
          f"(saved {duration_ms / 1000 - kept_s:.1f}s)")
    if args.dry_run:
        print("dry run - nothing written")
        return

    dst = versioned_output(args.output or src.with_name(f"{src.stem}-clean{src.suffix}"), src)
    render(src, keeps, dst)
    print(f"wrote: {dst}")


if __name__ == "__main__":
    main()
