# cutroom command line.
#
#   cutroom project <recording.screenstudio>   cut a screen studio project (no re-encode)
#   cutroom video <file.mp4>                   cut any video file (mp4 render or fcpxml)
#   cutroom digest <folder>                    transcribe a folder of clips, write agent digest shards
#   cutroom candidates <folder>                check agents' candidates, turn them into selects
#   cutroom review <source>                    review page: plays the cut without rendering
#   cutroom export <source> vlog|S1|V1 ...     export the vlog, shorts or selects from the clean cut
#   cutroom import <video> <timeline.fcpxml>   bring edits made in final cut back
#   cutroom transcribe <media>...              word-level transcript cache only
#
# every command reads <name>.cutroom.json next to the source (edits and short
# candidates), so decisions persist between runs. retake cuts are approved one
# by one in a terminal; without a terminal or with --yes everything proposed is
# approved, so agents should --dry-run or review first. outputs never overwrite
# anything: <name>-clean.* or <name>-S1.* next to the source, versioned.

import argparse
import json
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, folder, project
from .core import Range, clean_segments, drop_hallucinated_words, invert_cuts, merge_ranges, resolve_pacing, snap_range
from .fcpxml import read_keeps, write_fcpxml, write_timeline
from .media import collect_silences, probe_video, render, require_ffmpeg, versioned_output
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


@dataclass
class Job:
    kind: str                        # "video", "screenstudio" or "folder"
    src: Path
    sessions: list[dict]
    plan: Plan
    data: dict                       # the project file
    offsets: dict[str, float] | None  # folder: clip -> start on the timeline (ms)
    program: list[tuple] = field(default_factory=list)   # (start_ms, end_ms, select id)
    chapters: dict[int, str] = field(default_factory=dict)

    @property
    def exports(self) -> Path:
        # where exports go: next to a single source, inside cutroom/ for a folder
        return folder.workdir(self.src) / "exports" if self.kind == "folder" else self.src.parent

    @property
    def stem(self) -> str:
        return self.src.name if self.kind == "folder" else self.src.stem

    def clean(self, ranges: list[Range]) -> list[Range]:
        # snap chosen ranges to words, never past the edges of their own clip,
        # then keep only their clean parts
        if self.plan.words:
            bounds, acc = [], 0.0
            for sess in self.sessions:
                bounds.append((acc, acc + sess["durationMs"]))
                acc += sess["durationMs"]
            snapped = []
            for s, e in ranges:
                b0, b1 = next(((a, b) for a, b in bounds if a <= s < b), (0.0, acc))
                a, b = snap_range(self.plan.words, s, e)
                snapped.append((max(a, b0), min(b, b1)))
            ranges = snapped
        return clean_segments(self.plan.keeps, ranges)

    def item_segments(self, item: dict) -> list[Range]:
        return self.clean(project.segments(item, self.offsets))

    def media_segments(self, ranges: list[tuple]) -> list[tuple]:
        # timeline ranges -> (file, start_ms, end_ms, label), split at clip joins
        out, acc = [], 0.0
        bounds = []
        for sess in self.sessions:
            bounds.append((acc, acc + sess["durationMs"], sess["path"]))
            acc += sess["durationMs"]
        for r in ranges:
            s, e = r[0], r[1]
            for b0, b1, path in bounds:
                a, b = max(s, b0), min(e, b1)
                if b - a > 1:
                    label = f"{r[2]} " if len(r) > 2 and r[2] else ""
                    out.append((path, a - b0, b - b0, f"{label}{path.stem} {(a - b0) / 1000:.1f}s"))
        return out


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
    if src.is_dir():
        sessions = folder.sessions(src)
        if not sessions:
            sys.exit(f"no video files in {src}")
        total_s = sum(s["durationMs"] for s in sessions) / 1000
        print(f"folder: {len(sessions)} clips, {total_s / 3600:.2f} h")
        return "folder", src, sessions, []
    if not src.is_file():
        sys.exit(f"not a video file, folder or .screenstudio project: {src}")
    duration_ms, has_audio = probe_video(src)
    if not has_audio:
        sys.exit("video has no audio track - nothing to analyze")
    print(f"video: {src.name}, {duration_ms / 1000:.1f}s")
    return "video", src, [{"path": src, "durationMs": duration_ms}], []


def make_plan(path: Path, args) -> Job:
    kind, src, sessions, actions = open_source(path, args)
    offsets = folder.offsets(sessions) if kind == "folder" else None
    data = project.load(src, set(offsets) if offsets is not None else None)
    edits = {"cuts": project.edit_ranges(data, "cuts", offsets),
             "keeps": project.edit_ranges(data, "keeps", offsets)}
    if edits["cuts"] or edits["keeps"] or data["selects"] or data["shorts"]:
        print(f"project file: {project.project_path(src).name} ({len(edits['cuts'])} cuts, "
              f"{len(edits['keeps'])} keeps, {len(data['selects'])} selects, {len(data['shorts'])} shorts)")
    cache = None if kind == "folder" else src.with_suffix(".transcript.json")
    scopes = None
    if kind == "folder" and (data["selects"] or data["shorts"]):
        scopes = [r for item in data["selects"] + data["shorts"] for r in project.segments(item, offsets)]
    plan = plan_cuts(sessions, args, cache, actions, edits, scopes)
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
    job = Job(kind, src, sessions, plan, data, offsets)

    # the program: the selects in their order when there are any, else the whole clean cut
    selected = project.selects(data, offsets)
    if selected:
        last = None
        for item in selected:
            parts = job.clean([(item["startMs"], item["endMs"])])
            if parts and item.get("chapter") and item["chapter"] != last:
                job.chapters[len(job.program)] = item["chapter"]
                last = item["chapter"]
            job.program += [(a, b, item["id"]) for a, b in parts]
        # judgment calls worth checking are the ones inside a select (a removed
        # retake is never inside the kept pieces, so test against the selects)
        spans = [(item["startMs"], item["endMs"]) for item in selected]
        plan.decisions = [d for d in plan.decisions
                          if any(e > d["startMs"] and s < d["endMs"] for s, e in spans)]
    else:
        job.program = [(s, e, None) for s, e in plan.keeps]
    if getattr(args, "report", None):
        write_report(plan, args.report, src)
    return job


def summarize(job: Job) -> None:
    plan = job.plan
    if job.data["selects"]:
        kept = sum(e - s for s, e, _ in job.program) / 1000
        print(f"\nprogram: {len(job.data['selects'])} selects, {len(job.program)} segments, "
              f"{kept / 60:.1f} min from {plan.total_ms / 60000:.1f} min of footage")
        return
    print(f"\nfinal: {len(plan.keeps)} kept segments, {plan.total_ms / 1000:.1f}s -> "
          f"{plan.kept_ms / 1000:.1f}s (saved {(plan.total_ms - plan.kept_ms) / 1000:.1f}s)")


def run_project(args) -> None:
    job = make_plan(args.project, args)
    if job.kind != "screenstudio":
        sys.exit(f"{job.src.name} is not a .screenstudio project - use: cutroom video")
    if not job.plan.final_cuts:
        print("no cuts approved - nothing to do")
        return
    summarize(job)
    if args.dry_run:
        print("dry run - nothing written")
        return
    write_cut_package(job.src, job.plan.final_cuts, args.output)


def run_video(args) -> None:
    job = make_plan(args.video, args)
    src, plan = job.src, job.plan
    if job.kind != "video":
        sys.exit(f"{src.name} is not a single video file - use: cutroom project, or cutroom export <folder> vlog")
    if not plan.final_cuts:
        print("no cuts approved - nothing to do")
        return
    summarize(job)
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
    job = make_plan(args.source, args)
    summarize(job)
    if job.kind == "folder":
        dst = args.output or folder.workdir(job.src) / "review.html"
    else:
        dst = args.output or job.src.with_suffix(".review.html")
    write_review(job, dst)
    if args.open:
        webbrowser.open(dst.resolve().as_uri())


def run_digest(args) -> None:
    src = args.folder.resolve()
    if not src.is_dir() or is_screenstudio(src):
        sys.exit(f"digest works on a folder of clips: {src}")
    sessions = folder.sessions(src)
    if not sessions:
        sys.exit(f"no video files in {src}")
    print(f"folder: {len(sessions)} clips, {sum(s['durationMs'] for s in sessions) / 3600000:.2f} h")
    with ThreadPoolExecutor(2) as pool:
        silences_job = pool.submit(collect_silences, sessions, -35.0, 0.6)
        words = transcribe_sessions(sessions, None, args.backend)
        words, dropped = drop_hallucinated_words(words, silences_job.result())
    if dropped:
        print(f"dropped {len(dropped)} hallucinated words (inside silence)")
    sheets = {}
    if args.sheets:
        offsets = folder.offsets(sessions)
        speechless = [s for s in sessions if folder.mostly_visual(
            sum(offsets[s["rel"]] <= w["startMs"] < offsets[s["rel"]] + s["durationMs"] for w in words),
            s["durationMs"])]
        out = folder.workdir(src) / "sheets"
        with ThreadPoolExecutor(4) as pool:
            done = pool.map(lambda s: folder.contact_sheet(
                s["path"], out / (s["rel"].replace("/", "__") + ".jpg")), speechless)
            sheets = {s["rel"]: p.relative_to(folder.workdir(src)).as_posix() for s, p in zip(speechless, done)}
        print(f"contact sheets: {len(sheets)} mostly visual clips")
    shards = folder.write_digest(sessions, words, folder.workdir(src) / "digest", args.shards, sheets)
    print(f"digest: {folder.workdir(src) / 'digest' / 'all.md'} and {len(shards)} shards")
    for path in shards:
        print(f"  {path}")


def run_candidates(args) -> None:
    # step 4 helper: check every agent's candidates, show what each score
    # threshold would make, and optionally turn the chosen ones into selects
    src = args.folder.resolve()
    sessions = folder.sessions(src)
    durations = {s["rel"]: s["durationMs"] / 1000 for s in sessions}
    order = {s["rel"]: i for i, s in enumerate(sessions)}
    files = sorted((folder.workdir(src) / "candidates").glob("*.json"))
    if not files:
        sys.exit(f"no candidate files in {folder.workdir(src) / 'candidates'}")
    found, problems = [], []
    for path in files:
        for n, c in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            where = f"{path.name}[{n}]"
            if c.get("clip") not in durations:
                problems.append(f"{where}: unknown clip {c.get('clip')!r}")
            elif not 0 <= c.get("start", -1) < c.get("end", -1) <= durations[c["clip"]] + 0.05:
                problems.append(f"{where}: range {c.get('start')}-{c.get('end')} is outside {c['clip']}")
            else:
                found.append({**c, "end": min(c["end"], durations[c["clip"]]), "file": path.name})
    for p in problems:
        print(f"  skipped {p}")
    found.sort(key=lambda c: (order[c["clip"]], c["start"]))
    print(f"{len(found)} candidates from {len(files)} files ({len(problems)} skipped)\n")
    for score in range(10, 0, -1):
        chosen = [c for c in found if c.get("score", 0) >= score]
        if chosen:
            print(f"  score >= {score:2d}: {len(chosen):3d} moments, {sum(c['end'] - c['start'] for c in chosen) / 60:5.1f} min raw")
    if not args.write_selects:
        print("\nadd --write-selects --min-score N to turn them into selects (replaces the current selects)")
        return
    chosen = [c for c in found if c.get("score", 0) >= args.min_score]
    merged: list[dict] = []
    for c in chosen:  # overlapping or touching moments in one clip become one select
        last = merged[-1] if merged else None
        if last and last["clip"] == c["clip"] and c["start"] <= last["end"] + 0.5:
            last["end"] = max(last["end"], c["end"])
            last["title"] = f"{last['title']} / {c.get('title', '')}".strip(" /")
            continue
        merged.append({"clip": c["clip"], "start": round(c["start"], 2), "end": round(c["end"], 2),
                       "chapter": c.get("chapter", ""), "title": c.get("title", ""),
                       "why": c.get("why", ""), "score": c.get("score")})
    data = project.load(src, set(durations))
    data["selects"] = [{"id": f"V{i}", **m} for i, m in enumerate(merged, 1)]
    path = project.save(src, data)
    print(f"\nwrote {len(merged)} selects (score >= {args.min_score}) to {path}")
    print(f"next: cutroom review {json.dumps(str(src))} --open")


def run_export(args) -> None:
    args.yes = True
    job = make_plan(args.source, args)
    for iid in args.ids:
        if iid.lower() in ("vlog", "clean"):
            ranges, chapters, name, tag = job.program, job.chapters, f"{job.stem}", "-vlog"
            if not job.data["selects"]:
                tag = "-clean"
        else:
            item = project.find(job.data, iid)
            ranges, chapters = job.item_segments(item), {}
            name, tag = f"{job.stem} {item['id']} {item.get('title', '')}".strip(), f"-{item['id']}"
        if not ranges:
            print(f"{iid}: nothing of the clean cut falls inside it")
            continue
        clean_s = sum(r[1] - r[0] for r in ranges) / 1000
        print(f"\n{name}: {len(ranges)} segments, {clean_s / 60:.1f} min")
        job.exports.mkdir(parents=True, exist_ok=True)
        if job.kind == "screenstudio":
            keeps = merge_ranges([(r[0], r[1]) for r in ranges])
            write_cut_package(job.src, invert_cuts(keeps, job.plan.total_ms), None, tag)
        elif args.format == "mp4":
            if job.kind == "folder":
                sys.exit("mp4 export of a folder is not supported yet - export fcpxml")
            dst = versioned_output(job.exports / f"{job.stem}{tag}.mp4", job.src)
            render(job.src, [(r[0], r[1]) for r in ranges], dst)
            print(f"wrote: {dst}")
        else:
            # folder exports live in cutroom/exports and are regenerated from the
            # project file, so they are replaced; next to your own media nothing is
            path = job.exports / f"{job.stem}{tag}.fcpxml"
            dst = path if job.kind == "folder" else versioned_output(path, job.src)
            # a program range can cross a clip join; chapters go on its first piece
            segments, seg_chapters = [], {}
            for i, r in enumerate(ranges):
                parts = job.media_segments([r])
                if i in chapters and parts:
                    seg_chapters[len(segments)] = chapters[i]
                segments += parts
            write_timeline(segments, dst, name, chapters=seg_chapters)


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

    p = sub.add_parser("review", help="review page: plays the cut (or a folder's vlog) without rendering")
    p.add_argument("source", type=Path)
    add_cut_options(p)
    p.add_argument("--report", type=Path, default=None, help="also write the json report")
    p.add_argument("--output", type=Path, default=None, help="page path (default <name>.review.html, or <folder>/cutroom/review.html)")
    p.add_argument("--open", action="store_true", help="open the page in the default browser")
    p.set_defaults(run=run_review)

    p = sub.add_parser("digest", help="folder: transcribe every clip and write agent-readable digest shards")
    p.add_argument("folder", type=Path)
    p.add_argument("--shards", type=int, default=5, help="split the digest for this many parallel agents")
    p.add_argument("--sheets", action="store_true", help="contact sheets for mostly visual clips")
    p.add_argument("--backend", choices=["mlx", "faster-whisper"], default=None)
    p.set_defaults(run=run_digest)

    p = sub.add_parser("candidates", help="folder: check agent candidates and turn them into selects")
    p.add_argument("folder", type=Path)
    p.add_argument("--min-score", type=int, default=7, help="keep candidates scored at least this")
    p.add_argument("--write-selects", action="store_true", help="replace the selects with the kept candidates")
    p.set_defaults(run=run_candidates)

    p = sub.add_parser("export", help="export the vlog (a folder's selects), shorts (S1 ...) or selects (V1 ...)")
    p.add_argument("source", type=Path)
    p.add_argument("ids", nargs="+", metavar="ID", help="vlog (or clean), S1, V3, ...")
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
