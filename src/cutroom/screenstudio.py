# screenstudio input/output adapter: reads mic sessions and input events from a
# .screenstudio package and writes cuts by rewriting project.json slices in a
# clone. no re-encoding, media untouched, originals never modified.

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .core import Range, new_id, subtract_cuts
from .media import versioned_output

# input events that count as on-screen action. mouse moves are excluded: the
# cursor drifts constantly, so protecting moves would protect every pause.
ACTION_EVENTS = {"mouseDown", "keyDown"}


def is_screenstudio(path: Path) -> bool:
    return path.suffix == ".screenstudio" or (path / "project.json").exists()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_package(src: Path) -> str:
    if not (src / "project.json").exists():
        sys.exit(f"not a .screenstudio package: {src}")
    meta = _read_json(src / "meta.json")
    return meta["json"].get("version", "unknown")


def _mic_recorder(src: Path) -> dict:
    recording_meta = _read_json(src / "recording" / "metadata.json")
    mic = next(
        (r for r in recording_meta["recorders"] if r["id"].endswith("microphone")), None
    )
    if mic is None:
        sys.exit("no microphone channel in this recording")
    return mic


def _audio_sessions(src: Path, recorder: dict, what: str) -> list[dict]:
    sessions = []
    for i, session in enumerate(recorder["sessions"]):
        name = session.get("outputFilename") or f"{recorder['id']}-{i}.m4a"
        path = src / "recording" / name
        if not path.exists():
            sys.exit(f"missing {what} session file: {path}")
        sessions.append({
            "path": path,
            "durationMs": session["durationMs"],
            "clockStartMs": session.get("processTimeStartMs"),
            "clockEndMs": session.get("processTimeEndMs"),
        })
    return sessions


def mic_sessions(src: Path) -> list[dict]:
    # a recording can have multiple sessions (pause/resume); screen studio
    # concatenates them on one source timeline.
    return _audio_sessions(src, _mic_recorder(src), "mic")


def system_audio_sessions(src: Path) -> list[dict]:
    # the computer's own sound (a video playing, an app), one session per mic
    # session, laid out on the mic's timeline. [] when it was not recorded
    recording_meta = _read_json(src / "recording" / "metadata.json")
    recorder = next((r for r in recording_meta["recorders"] if r.get("type") == "systemAudio"), None)
    if recorder is None:
        return []
    sessions, mics = _audio_sessions(src, recorder, "system audio"), mic_sessions(src)
    if len(sessions) != len(mics):
        sys.exit(f"system audio has {len(sessions)} sessions, the mic {len(mics)}")
    return [{**s, "durationMs": m["durationMs"]} for s, m in zip(sessions, mics)]


def action_times(src: Path, sessions: list[dict]) -> list[float]:
    # clicks and keystrokes on the concatenated mic timeline (ms). events carry
    # processTimeMs on the same clock as each mic session's start/end, so an
    # event maps to whichever session was recording when it happened.
    if any(s["clockStartMs"] is None for s in sessions):
        return []
    offsets, acc = [], 0.0
    for s in sessions:
        offsets.append(acc)
        acc += s["durationMs"]
    times = []
    for pattern in ("mouseclicks-*.json", "keystrokes-*.json"):
        for path in sorted((src / "recording").glob(pattern)):
            for event in _read_json(path):
                if event.get("type") not in ACTION_EVENTS or "processTimeMs" not in event:
                    continue
                t = event["processTimeMs"]
                for offset, s in zip(offsets, sessions):
                    if s["clockStartMs"] <= t <= s["clockEndMs"]:
                        times.append(offset + min(t - s["clockStartMs"], s["durationMs"]))
                        break
    return sorted(times)


def _clone(src: Path, dst: Path) -> None:
    # apfs copy-on-write on macos (instant, no extra disk), plain copy elsewhere
    if sys.platform == "darwin":
        if subprocess.run(["cp", "-c", "-R", str(src), str(dst)]).returncode == 0:
            return
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, symlinks=True)


def write_cut_package(
    src: Path, cuts: list[Range], output: Path | None, default_suffix: str = "-clean"
) -> Path:
    # clone the package and rewrite only scenes[].slices
    base = output or src.with_name(src.stem + default_suffix + ".screenstudio")
    dst = versioned_output(base, src)
    _clone(src, dst)

    wrapper = _read_json(dst / "project.json")
    project = wrapper["json"]
    before_ms = after_ms = 0
    for scene in project["scenes"]:
        if scene.get("type") != "recording":
            continue
        before_ms += sum(x["sourceEndMs"] - x["sourceStartMs"] for x in scene["slices"])
        scene["slices"] = subtract_cuts(scene["slices"], cuts)
        after_ms += sum(x["sourceEndMs"] - x["sourceStartMs"] for x in scene["slices"])
        print(f"scene {scene['id']}: {len(scene['slices'])} slices after cutting")

    (dst / "project.json").write_text(json.dumps(wrapper), encoding="utf-8")
    saved = (before_ms - after_ms) / 1000
    print(f"\noutput duration: {before_ms / 1000:.1f}s -> {after_ms / 1000:.1f}s (saved {saved:.1f}s)")
    print(f"wrote: {dst}")
    return dst


def edited_ranges(src: Path) -> list[Range]:
    # source ranges (ms) the project already shows: the union of its recording
    # slices. anything outside was cut by hand in screen studio before cutroom ran.
    from .core import merge_ranges

    project = _read_json(src / "project.json")["json"]
    return merge_ranges([(s["sourceStartMs"], s["sourceEndMs"])
                         for scene in project["scenes"] if scene.get("type") == "recording"
                         for s in scene["slices"]])


# ---------- joining recordings ----------
# screen studio keeps a paused and resumed recording as sessions, one set of
# files per session (channel-1-display-0.m3u8, channel-1-display-1.m3u8, ...),
# and plays them one after another on one timeline. a later recording made in
# the same setup joins a project the same way: its files become the next
# sessions (renamed, not re-encoded), and its slices and zooms move to where
# its sessions start on the timeline.

# per-session fields that name a file inside recording/
SESSION_FILES = ("outputFilename", "keyStrokesFilename", "mouseClicksFilename", "mouseMovesFilename")
# per-session fields that have to match for the sessions to play as one recording
SESSION_SETUP = ("bounds", "recordingScale", "videoSize", "displayRefreshRate", "deviceFrameRate")
# scene lists whose items sit on the source timeline
TIMED_LISTS = ("slices", "zooms", "layouts", "masks", "voiceOvers")
CLOCK_FIELDS = ("processTimeStartMs", "processTimeEndMs")


def _session_name(name: str, n: int) -> str:
    # channel-1-display-0.m3u8 -> channel-1-display-<n>.m3u8, keystrokes-0.json -> keystrokes-<n>.json
    stem, dot, ext = name.partition(".")
    if not re.search(r"-\d+$", stem):
        sys.exit(f"cannot renumber session file {name}")
    return re.sub(r"-\d+$", f"-{n}", stem) + dot + ext


def _check_setup(first: dict, meta: dict, name: str) -> None:
    def channels(m):
        return sorted((r["id"], r.get("type")) for r in m["recorders"])

    if channels(first) != channels(meta):
        sys.exit(f"{name} was recorded with other channels than the first project: "
                 f"{channels(meta)} vs {channels(first)}")
    for r0 in first["recorders"]:
        r = next(x for x in meta["recorders"] if x["id"] == r0["id"])
        for key in SESSION_SETUP:
            seen = {json.dumps(s.get(key), sort_keys=True) for s in r0.get("sessions", []) + r.get("sessions", [])}
            if len(seen) > 1:
                sys.exit(f"{name}: {r0['id']} {key} differs from the first project ({', '.join(sorted(seen))})")


class _Mover:
    # brings one later package's session files into the joined package under
    # their new session numbers. the package is cloned to a scratch folder
    # first (copy-on-write on macos), so each file is a rename, not a copy
    def __init__(self, src: Path, dst: Path, shift_ms: float):
        self.dst, self.shift_ms, self.done = dst / "recording", shift_ms, {}
        self.tmp = dst / ".cutroom-join"
        _clone(src / "recording", self.tmp)

    def _move(self, name: str, new: str) -> None:
        target = self.dst / new
        if target.exists():
            sys.exit(f"{new} already exists in the joined project")
        os.replace(self.tmp / name, target)

    def bring(self, name: str, n: int) -> str:
        if name in self.done:
            return self.done[name]
        new = _session_name(name, n)
        source = self.tmp / name
        if not source.exists():
            sys.exit(f"missing session file: {name}")
        if name.endswith(".m3u8"):
            # an hls playlist names its init segment and media segments, which
            # carry the session number too: channel-1-display-0-0001.m4s
            old_stem, new_stem = name[:-len(".m3u8")], new[:-len(".m3u8")]
            text = source.read_text(encoding="utf-8")
            refs = re.findall(r'URI="([^"]+)"', text) + [
                line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
            for ref in refs:
                if not ref.startswith(old_stem + "-"):
                    sys.exit(f"{name} names {ref}, which is not one of its segments")
                self._move(ref, new_stem + ref[len(old_stem):])
            (self.dst / new).write_text(text.replace(old_stem + "-", new_stem + "-"), encoding="utf-8")
        elif name.endswith(".json") and self.shift_ms:
            # input events: moved onto the joined recording's clock
            events = _read_json(source)
            for event in events:
                if "processTimeMs" in event:
                    event["processTimeMs"] += self.shift_ms
            (self.dst / new).write_text(json.dumps(events), encoding="utf-8")
        else:
            self._move(name, new)
        self.done[name] = new
        return new

    def bring_cursors(self, cursor_info: str, cursor_dir: str) -> None:
        # cursor images are shared by every session: add the ones not there yet
        info_path = self.dst / cursor_info
        known = _read_json(info_path)
        ids = {c["id"] for c in known}
        known += [c for c in _read_json(self.tmp / cursor_info) if c["id"] not in ids]
        info_path.write_text(json.dumps(known), encoding="utf-8")
        for image in (self.tmp / cursor_dir).iterdir():
            if not (self.dst / cursor_dir / image.name).exists():
                os.replace(image, self.dst / cursor_dir / image.name)

    def close(self) -> None:
        shutil.rmtree(self.tmp)


def _markers(pkg: Path) -> list:
    found = []
    for path, read in ((pkg / "recording-markers.json", lambda d: d.get("json", [])),
                       (pkg / "recording" / "screen-studio-recording.json", lambda d: d.get("markers", []))):
        if path.exists():
            found += read(_read_json(path)) or []
    return found


def join_packages(sources: list[Path], output: Path | None) -> Path:
    # one project that plays several recordings in order. they must come from
    # the same setup (channels, display, camera); the first project's look,
    # layout and edits are kept, the others bring their slices and zooms
    if len(sources) < 2:
        sys.exit("join needs at least two .screenstudio projects")
    for src in sources:
        check_package(src)
    first = sources[0]
    metas = [_read_json(src / "recording" / "metadata.json") for src in sources]
    for src, meta in zip(sources[1:], metas[1:]):
        _check_setup(metas[0], meta, src.name)

    dst = versioned_output(output or first.with_name(first.stem + "-joined.screenstudio"), first)
    _clone(first, dst)
    # screen studio's caches and backup describe the first recording alone
    shutil.rmtree(dst / "cache", ignore_errors=True)
    (dst / "project.json.bak").unlink(missing_ok=True)

    meta_names = [n for n in ("metadata.json", "metadata-raw.json") if (dst / "recording" / n).exists()]
    wrapper = _read_json(dst / "project.json")
    scenes = [s for s in wrapper["json"]["scenes"] if s.get("type") == "recording"]
    if len(scenes) != 1:
        sys.exit(f"{first.name} has {len(scenes)} recording scenes; join needs exactly one")
    scene = scenes[0]

    for src in sources[1:]:
        meta = _read_json(dst / "recording" / "metadata.json")
        n0 = len(meta["sessions"])
        offset_ms = sum(s["durationMs"] for s in meta["sessions"])
        src_meta = _read_json(src / "recording" / "metadata.json")
        # every session must sit on one clock in order: input events find their
        # session by it. recordings from one app run already do; others move
        ends = [s.get("processTimeEndMs") for s in meta["sessions"]]
        starts = [s.get("processTimeStartMs") for s in src_meta["sessions"]]
        shift_ms = 0.0
        if None not in ends + starts and min(starts) <= max(ends):
            shift_ms = max(ends) + 1000 - min(starts)
        mover = _Mover(src, dst, shift_ms)
        for meta_name in meta_names:
            joined = _read_json(dst / "recording" / meta_name)
            later = _read_json(src / "recording" / meta_name)
            for r in later["recorders"]:
                into = next(x for x in joined["recorders"] if x["id"] == r["id"])
                for i, session in enumerate(r.get("sessions", [])):
                    session = dict(session)
                    for key in SESSION_FILES:
                        if key in session:
                            session[key] = mover.bring(session[key], n0 + i)
                    for key in CLOCK_FIELDS:
                        if session.get(key) is not None:
                            session[key] += shift_ms
                    into.setdefault("sessions", []).append(session)
            joined["sessions"] += [{**s, **{k: s[k] + shift_ms for k in CLOCK_FIELDS if s.get(k) is not None}}
                                   for s in later["sessions"]]
            (dst / "recording" / meta_name).write_text(json.dumps(joined, indent=1), encoding="utf-8")
        cursor = next((r for r in src_meta["recorders"] if r.get("type") == "cursor"), None)
        if cursor and cursor.get("cursorsInfoFile"):
            mover.bring_cursors(cursor["cursorsInfoFile"], cursor.get("cursorImagesFolder", "cursors"))
        mover.close()

        later_scenes = [s for s in _read_json(src / "project.json")["json"]["scenes"] if s.get("type") == "recording"]
        if len(later_scenes) != 1:
            sys.exit(f"{src.name} has {len(later_scenes)} recording scenes; join needs exactly one")
        for key in TIMED_LISTS:
            for item in later_scenes[0].get(key, []):
                if "sourceStartMs" not in item or "sourceEndMs" not in item:
                    sys.exit(f"{src.name}: a {key} entry has no source times, so it cannot move")
                moved = {**item, "sourceStartMs": item["sourceStartMs"] + offset_ms,
                         "sourceEndMs": item["sourceEndMs"] + offset_ms}
                if "id" in moved:
                    moved["id"] = new_id()
                scene.setdefault(key, []).append(moved)
        if _markers(src):
            print(f"note: the recording markers of {src.name} are not carried over")
        shown = sum(s["durationMs"] for s in src_meta["sessions"]) / 1000
        print(f"joined {src.name}: sessions {n0 + 1}-{n0 + len(src_meta['sessions'])}, "
              f"from {offset_ms / 1000:.1f}s ({shown:.1f}s)"
              + (f", clock moved {shift_ms / 1000:.1f}s" if shift_ms else ""))

    wrapper["json"]["name"] = dst.stem
    (dst / "project.json").write_text(json.dumps(wrapper), encoding="utf-8")
    print(f"wrote: {dst}")
    return dst
