# cutroom command line: one entry point, three subcommands.
#
#   cutroom project <recording.screenstudio>   cut a screen studio project (no re-encode)
#   cutroom video <file.mp4>                   cut any video file (mp4 render or fcpxml)
#   cutroom transcribe <media>...              word-level transcript cache only
#
# retake cuts are approved one by one (removed vs kept text); silence cuts are
# approved as a batch (--review-silences for one-by-one). without a terminal or
# with --yes everything proposed is approved, so agents should --dry-run first.
# outputs never overwrite anything: <name>-clean.* next to the source, versioned.

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import resolve_pacing
from .fcpxml import write_fcpxml
from .media import probe_video, render, require_ffmpeg, versioned_output
from .pipeline import plan_cuts, write_report
from .screenstudio import action_times, check_package, mic_sessions, write_cut_package
from .transcribe import transcribe_sessions


def add_cut_options(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--pacing", choices=["tight", "balanced", "relaxed"], default="balanced",
                    help="how rigorous silence cutting is: tight cuts hard, relaxed embraces pauses")
    ap.add_argument("--noise", type=float, default=-35.0, help="silence threshold in dB")
    ap.add_argument("--min-silence", type=float, default=None, help="min silence duration in seconds")
    ap.add_argument("--trail", type=float, default=None,
                    help="silence kept after speech ends at a cut, seconds")
    ap.add_argument("--lead", type=float, default=None,
                    help="silence kept before speech resumes at a cut, seconds")
    ap.add_argument("--window", type=float, default=60.0,
                    help="max seconds between a bad take and its redo")
    ap.add_argument("--threshold", type=float, default=0.75,
                    help="opening-words similarity 0..1 to count as a retake")
    ap.add_argument("--pre-roll", type=float, default=0.1,
                    help="seconds kept before the final take's first word")
    ap.add_argument("--min-keep", type=float, default=None,
                    help="wordless kept fragments shorter than this (seconds) are absorbed into cuts")
    ap.add_argument("--cut", action="append", default=[], metavar="START-END",
                    help="manual cut range in seconds (e.g. 43.45-86.8), repeatable")
    ap.add_argument("--no-retakes", action="store_true",
                    help="skip retake detection (and transcription): silences only")
    ap.add_argument("--no-silences", action="store_true", help="skip silence cutting: retakes only")
    ap.add_argument("--review-silences", action="store_true",
                    help="approve silence cuts one by one instead of as a batch")
    ap.add_argument("--backend", choices=["mlx", "faster-whisper"], default=None,
                    help="transcription backend (default: mlx on apple silicon, else faster-whisper)")
    ap.add_argument("--report", type=Path, default=None,
                    help="write a json report (sentences, cuts, keeps) to this path")
    ap.add_argument("--yes", action="store_true", help="approve all cuts without asking")
    ap.add_argument("--dry-run", action="store_true", help="detect and review only, write no media")


def run_project(args) -> None:
    src = args.project.resolve()
    print(f"screen studio project version: {check_package(src)}")
    sessions = mic_sessions(src)
    total_ms = sum(s["durationMs"] for s in sessions)
    print(f"mic sessions: {len(sessions)}, total {total_ms / 1000:.1f}s")

    actions = [] if args.no_protect_actions else action_times(src, sessions)
    plan = plan_cuts(sessions, args, src.with_suffix(".transcript.json"), actions)
    if args.report:
        write_report(plan, args.report, src)
    if not plan.final_cuts:
        print("no cuts approved - nothing to do")
        return
    if args.dry_run:
        print(f"\ndry run - would cut {(total_ms - plan.kept_ms) / 1000:.1f}s "
              f"of {total_ms / 1000:.1f}s, nothing written")
        return
    write_cut_package(src, plan.final_cuts, args.output)


def run_video(args) -> None:
    src = args.video.resolve()
    if not src.is_file():
        sys.exit(f"not a video file: {src}")
    duration_ms, has_audio = probe_video(src)
    if not has_audio:
        sys.exit("video has no audio track - nothing to analyze")
    print(f"video: {src.name}, {duration_ms / 1000:.1f}s")
    sessions = [{"path": src, "durationMs": duration_ms}]

    plan = plan_cuts(sessions, args, src.with_suffix(".transcript.json"))
    if args.report:
        write_report(plan, args.report, src)
    if not plan.final_cuts:
        print("no cuts approved - nothing to do")
        return
    keeps = plan.keeps
    print(f"\nfinal: {len(keeps)} kept segments, "
          f"{duration_ms / 1000:.1f}s -> {plan.kept_ms / 1000:.1f}s "
          f"(saved {(duration_ms - plan.kept_ms) / 1000:.1f}s)")
    if args.dry_run:
        print("dry run - nothing written")
        return

    if args.export == "fcpxml":
        dst = versioned_output(args.output or src.with_name(f"{src.stem}-clean.fcpxml"), src)
        markers = [
            (c["endMs"], f"{c['reason']} cut, kept: {(c.get('kept') or '')[:80]}")
            for c in plan.retakes
        ]
        write_fcpxml(src, keeps, dst, duration_ms, markers)
        return
    dst = versioned_output(args.output or src.with_name(f"{src.stem}-clean{src.suffix}"), src)
    render(src, keeps, dst)
    print(f"wrote: {dst}")


def run_transcribe(args) -> None:
    for media in args.media:
        src = media.resolve()
        if not src.is_file():
            sys.exit(f"not a file: {src}")
        duration_ms, has_audio = probe_video(src)
        if not has_audio:
            sys.exit(f"{src.name} has no audio track")
        words = transcribe_sessions(
            [{"path": src, "durationMs": duration_ms}], src.with_suffix(".transcript.json"), args.backend)
        print(f"{src.name}: {len(words)} words")


def main(argv: list[str] | None = None) -> None:
    # never crash on a transcript word the console encoding can't print
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    ap = argparse.ArgumentParser(prog="cutroom", description="cut silences and retakes from talking recordings")
    ap.add_argument("--version", action="version", version=f"cutroom {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    project = sub.add_parser("project", help="cut a .screenstudio project (rewrites slices, no re-encode)")
    project.add_argument("project", type=Path)
    add_cut_options(project)
    project.add_argument("--no-protect-actions", action="store_true",
                         help="let silence cuts remove pauses that contain clicks or keystrokes")
    project.add_argument("--action-before", type=float, default=0.5,
                         help="seconds kept on screen before a click or keystroke")
    project.add_argument("--action-after", type=float, default=1.0,
                         help="seconds kept on screen after a click or keystroke")
    project.add_argument("--output", type=Path, default=None, help="output package path")
    project.set_defaults(run=run_project)

    video = sub.add_parser("video", help="cut a video file (renders mp4 or writes fcpxml)")
    video.add_argument("video", type=Path)
    add_cut_options(video)
    video.add_argument("--export", choices=["mp4", "fcpxml"], default="mp4",
                       help="mp4 renders the cut video; fcpxml writes a final cut pro "
                            "timeline referencing the original media (no re-encode)")
    video.add_argument("--output", type=Path, default=None, help="output path")
    video.set_defaults(run=run_video)

    transcribe = sub.add_parser("transcribe", help="write <media>.transcript.json word timings")
    transcribe.add_argument("media", type=Path, nargs="+")
    transcribe.add_argument("--backend", choices=["mlx", "faster-whisper"], default=None)
    transcribe.set_defaults(run=run_transcribe)

    args = ap.parse_args(argv)
    if hasattr(args, "pacing"):
        resolve_pacing(args)
    require_ffmpeg()
    args.run(args)


if __name__ == "__main__":
    main()
