# screenstudio input/output adapter: reads mic sessions and input events from a
# .screenstudio package and writes cuts by rewriting project.json slices in a
# clone. no re-encoding, media untouched, originals never modified.

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .core import Range, subtract_cuts
from .media import versioned_output

# input events that count as on-screen action. mouse moves are excluded: the
# cursor drifts constantly, so protecting moves would protect every pause.
ACTION_EVENTS = {"mouseDown", "keyDown"}


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


def mic_sessions(src: Path) -> list[dict]:
    # a recording can have multiple sessions (pause/resume); screen studio
    # concatenates them on one source timeline.
    mic = _mic_recorder(src)
    sessions = []
    for i, session in enumerate(mic["sessions"]):
        name = session.get("outputFilename") or f"{mic['id']}-{i}.m4a"
        path = src / "recording" / name
        if not path.exists():
            sys.exit(f"missing mic session file: {path}")
        sessions.append({
            "path": path,
            "durationMs": session["durationMs"],
            "clockStartMs": session.get("processTimeStartMs"),
            "clockEndMs": session.get("processTimeEndMs"),
        })
    return sessions


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
