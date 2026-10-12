# cutroom command line.
#
#   cutroom project <recording.screenstudio>   cut a screen studio project (no re-encode)
#   cutroom video <file.mp4>                   cut any video file (mp4 render or fcpxml)
#   cutroom review <source>                    review page: plays the cut without rendering
#   cutroom export <source> S1 [S2 ...]        export short candidates from the clean cut
#   cutroom import <video> <timeline.fcpxml>   bring edits made in final cut back
#   cutroom transcribe <media>...              word-level transcript cache only
#
# every command reads <name>.cutroom.json next to the source (edits and short
# candidates), so decisions persist between runs. retake cuts are approved one
# by one in a terminal; without a terminal or with --yes everything proposed is
# approved, so agents should --dry-run or review first. outputs never overwrite
# anything: <name>-clean.* or <name>-S1.* next to the source, versioned.

import argparse
import sys
import webbrowser
from pathlib import Path

from . import __version__, project
from .core import invert_cuts, merge_ranges, resolve_pacing
from .fcpxml import read_keeps, write_fcpxml
from .media import probe_video, render, require_ffmpeg, versioned_output
from .pipeline import Plan, plan_cuts, write_report
from .review import write_review
from .screenstudio import action_times, check_package, edited_ranges, mic_sessions, write_cut_package
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
                    help="extra cut range in seconds for this run (persistent: edits.cuts in the project file)")
    ap.add_argument("--keep", action="append", default=[], metavar="START-END",
                    help="range never cut in this run (persistent: edits.keeps in the project file)")
    ap.add_argument("--no-retakes", action="store_true",
                    help="skip retake detection (and transcription): silences only")
    ap.add_argument("--no-silences", action="store_true", help="skip silence cutting: retakes only")
    ap.add_argument("--review-silences", action="store_true",
                    help="approve silence cuts one by one instead of as a batch")
    ap.add_argument("--no-protect-actions", action="store_true",
                    help="screen studio: let silence cuts remove pauses that contain clicks or keystrokes")
    ap.add_argument("--action-before", type=float, default=0.5,
                    help="screen studio: seconds kept on screen before a click or keystroke")
    ap.add_argument("--action-after", type=float, default=1.0,
                    help="screen studio: seconds kept on screen after a click or keystroke")
    ap.add_argument("--backend", choices=["mlx", "faster-whisper"], default=None,
                    help="transcription backend (default: mlx on apple silicon, else faster-whisper)")
    ap.add_argument("--yes", action="store_true", help="approve all cuts without asking")


def is_screenstudio(path: Path) -> bool:
    return path.suffix == ".screenstudio" or (path / "project.json").exists()


def open_source(path: Path, args) -> tuple[str, Path, list[dict], list[float]]:
    # (kind, resolved source, sessions, on-screen action times)
    src = path.resolve()
    if is_screenstudio(src):
        print(f"screen studio project version: {check_package(src)}")
        sessions = mic_sessions(src)
        total_s = sum(s["durationMs"] for s in sessions) / 1000
        print(f"mic sessions: {len(sessions)}, total {total_s:.1f}s")
        actions = [] if args.no_protect_actions else action_times(src, sessions)
        return "screenstudio", src, sessions, actions
    if not src.is_file():
        sys.exit(f"not a video file or .screenstudio project: {src}")
    duration_ms, has_audio = probe_video(src)
    if not has_audio:
        sys.exit("video has no audio track - nothing to analyze")
    print(f"video: {src.name}, {duration_ms / 1000:.1f}s")
    return "video", src, [{"path": src, "durationMs": duration_ms}], []


def make_plan(path: Path, args) -> tuple[str, Path, list[dict], Plan, dict]:
    kind, src, sessions, actions = open_source(path, args)
    data = project.load(src)
    edits = {"cuts": project.edit_ranges(data, "cuts"), "keeps": project.edit_ranges(data, "keeps")}
    if edits["cuts"] or edits["keeps"] or data["shorts"]:
        print(f"project file: {project.project_path(src).name} ({len(edits['cuts'])} cuts, "
              f"{len(edits['keeps'])} keeps, {len(data['shorts'])} shorts)")
    plan = plan_cuts(sessions, args, src.with_suffix(".transcript.json"), actions, edits)
    if kind == "screenstudio":
        # respect the edit already made in screen studio: what it hides counts as cut
        shown = edited_ranges(src)
        hidden = invert_cuts(shown, plan.total_ms)
        if hidden:
            plan.final_cuts = merge_ranges(plan.final_cuts + hidden)
            plan.decisions = [d for d in plan.decisions
                              if any(e > d["startMs"] and s < d["endMs"] for s, e in shown)]
            print(f"screen studio edit: {sum(e - s for s, e in shown) / 1000:.1f}s of "
                  f"{plan.total_ms / 1000:.1f}s shown before cutroom")
    if getattr(args, "report", None):
        write_report(plan, args.report, src)
    return kind, src, sessions, plan, data


def summarize(plan: Plan) -> None:
    print(f"\nfinal: {len(plan.keeps)} kept segments, {plan.total_ms / 1000:.1f}s -> "
          f"{plan.kept_ms / 1000:.1f}s (saved {(plan.total_ms - plan.kept_ms) / 1000:.1f}s)")


def run_project(args) -> None:
    kind, src, _sessions, plan, _data = make_plan(args.project, args)
    if kind != "screenstudio":
        sys.exit(f"{src.name} is not a .screenstudio project - use: cutroom video")
    if not plan.final_cuts:
        print("no cuts approved - nothing to do")
        return
    summarize(plan)
    if args.dry_run:
        print("dry run - nothing written")
        return
    write_cut_package(src, plan.final_cuts, args.output)


def run_video(args) -> None:
    kind, src, _sessions, plan, _data = make_plan(args.video, args)
    if kind != "video":
        sys.exit(f"{src.name} is a screen studio project - use: cutroom project")
    if not plan.final_cuts:
        print("no cuts approved - nothing to do")
        return
    summarize(plan)
    if args.dry_run:
        print("dry run - nothing written")
        return
    if args.export == "fcpxml":
        dst = versioned_output(args.output or src.with_name(f"{src.stem}-clean.fcpxml"), src)
        markers = [(d["endMs"], f"{d['id']} {d['reason']} cut, kept: {(d.get('kept') or '')[:80]}")
                   for d in plan.cut_decisions]
        write_fcpxml(src, plan.keeps, dst, plan.total_ms, markers)
        return
    dst = versioned_output(args.output or src.with_name(f"{src.stem}-clean{src.suffix}"), src)
    render(src, plan.keeps, dst)
    print(f"wrote: {dst}")


def run_review(args) -> None:
    args.yes = True  # reviewing never writes media, so nothing needs approving
    kind, src, sessions, plan, data = make_plan(args.source, args)
    summarize(plan)
    dst = args.output or src.with_suffix(".review.html")
    write_review(plan, src, sessions, kind, data["shorts"], dst)
    if args.open:
        webbrowser.open(dst.resolve().as_uri())


def run_export(args) -> None:
    args.yes = True
    kind, src, _sessions, plan, data = make_plan(args.source, args)
    for sid in args.ids:
        short = project.find_short(data, sid)
        s0, s1 = project.short_range(short)
        keeps = [(max(s, s0), min(e, s1)) for s, e in plan.keeps if min(e, s1) - max(s, s0) > 50]
        if not keeps:
            print(f"{short['id']}: nothing of the clean cut falls inside {s0 / 1000:.1f}-{s1 / 1000:.1f}s")
            continue
        clean_s = sum(e - s for s, e in keeps) / 1000
        print(f"\n{short['id']} {short.get('title', '')}: {len(keeps)} segments, {clean_s:.1f}s")
        tag = f"-{short['id']}"
        if kind == "screenstudio":
            write_cut_package(src, invert_cuts(keeps, plan.total_ms), None, tag)
        elif args.format == "mp4":
            dst = versioned_output(src.with_name(f"{src.stem}{tag}.mp4"), src)
            render(src, keeps, dst)
            print(f"wrote: {dst}")
        else:
            dst = versioned_output(src.with_name(f"{src.stem}{tag}.fcpxml"), src)
            write_fcpxml(src, keeps, dst, plan.total_ms,
                         project_name=f"{src.stem} {short['id']} {short.get('title', '')}".strip())


def run_import(args) -> None:
    src = args.video.resolve()
    if is_screenstudio(src):
        sys.exit("fcpxml read-back works for video files; screen studio projects are edited in screen studio")
    if not src.is_file():
        sys.exit(f"not a video file: {src}")
    total_ms, _ = probe_video(src)
    keeps = read_keeps(args.timeline.resolve(), src)
    data = project.load(src)
    note = f"from {args.timeline.name}"
    before = len(data["edits"]["cuts"]) + len(data["edits"]["keeps"])
    sec = lambda r: [round(r[0] / 1000, 3), round(r[1] / 1000, 3), note]  # noqa: E731
    data["edits"] = {"cuts": [sec(r) for r in invert_cuts(keeps, total_ms)],
                     "keeps": [sec(r) for r in keeps]}
    path = project.save(src, data)
    kept_s = sum(e - s for s, e in keeps) / 1000
    print(f"{args.timeline.name}: {len(keeps)} clips, {kept_s:.1f}s of {total_ms / 1000:.1f}s")
    print(f"wrote {path.name}: the final cut pro timeline is now the edit "
          f"(replaced {before} earlier edits; short candidates kept)")


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

    p = sub.add_parser("project", help="cut a .screenstudio project (rewrites slices, no re-encode)")
    p.add_argument("project", type=Path)
    add_cut_options(p)
    p.add_argument("--report", type=Path, default=None, help="write a json report to this path")
    p.add_argument("--dry-run", action="store_true", help="decide and print, write nothing")
    p.add_argument("--output", type=Path, default=None, help="output package path")
    p.set_defaults(run=run_project)

    p = sub.add_parser("video", help="cut a video file (renders mp4 or writes fcpxml)")
    p.add_argument("video", type=Path)
    add_cut_options(p)
    p.add_argument("--report", type=Path, default=None, help="write a json report to this path")
    p.add_argument("--dry-run", action="store_true", help="decide and print, write nothing")
    p.add_argument("--export", choices=["mp4", "fcpxml"], default="mp4",
                   help="mp4 renders the cut video; fcpxml writes a final cut pro "
                        "timeline referencing the original media (no re-encode)")
    p.add_argument("--output", type=Path, default=None, help="output path")
    p.set_defaults(run=run_video)

    p = sub.add_parser("review", help="write a review page that plays the cut without rendering")
    p.add_argument("source", type=Path)
    add_cut_options(p)
    p.add_argument("--report", type=Path, default=None, help="also write the json report")
    p.add_argument("--output", type=Path, default=None, help="page path (default <name>.review.html)")
    p.add_argument("--open", action="store_true", help="open the page in the default browser")
    p.set_defaults(run=run_review)

    p = sub.add_parser("export", help="export short candidates (S1, S2, ...) from the clean cut")
    p.add_argument("source", type=Path)
    p.add_argument("ids", nargs="+", metavar="ID")
    add_cut_options(p)
    p.add_argument("--format", choices=["fcpxml", "mp4"], default="fcpxml",
                   help="video sources: fcpxml (no re-encode) or a rendered mp4; "
                        "screen studio sources always export a project")
    p.set_defaults(run=run_export)

    p = sub.add_parser("import", help="make a final cut pro timeline (exported xml) the edit")
    p.add_argument("video", type=Path)
    p.add_argument("timeline", type=Path, help="fcpxml exported from final cut pro (file > export xml)")
    p.set_defaults(run=run_import)

    p = sub.add_parser("transcribe", help="write <media>.transcript.json word timings")
    p.add_argument("media", type=Path, nargs="+")
    p.add_argument("--backend", choices=["mlx", "faster-whisper"], default=None)
    p.set_defaults(run=run_transcribe)

    args = ap.parse_args(argv)
    if hasattr(args, "pacing"):
        resolve_pacing(args)
    require_ffmpeg()
    args.run(args)


if __name__ == "__main__":
    main()
