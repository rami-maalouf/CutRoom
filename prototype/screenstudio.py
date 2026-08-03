# screenstudio input/output adapter: reads mic sessions from a .screenstudio
# package and writes cuts by rewriting project.json slices in a clone.
# no re-encoding, media untouched, originals never modified.

import json
import subprocess
import sys
from pathlib import Path

from core import subtract_cuts, versioned_output


def check_package(src: Path) -> str:
    if not (src / "project.json").exists():
        sys.exit(f"not a .screenstudio package: {src}")
    meta = json.loads((src / "meta.json").read_text())
    return meta["json"].get("version", "unknown")


def mic_sessions(src: Path) -> list[dict]:
    # a recording can have multiple sessions (pause/resume); screen studio
    # concatenates them on one source timeline.
    recording_meta = json.loads((src / "recording" / "metadata.json").read_text())
    mic = next(
        (r for r in recording_meta["recorders"] if r["id"].endswith("microphone")), None
    )
    if mic is None:
        sys.exit("no microphone channel in this recording")
    sessions = []
    for i, session in enumerate(mic["sessions"]):
        path = src / "recording" / f"{mic['id']}-{i}.m4a"
        if not path.exists():
            sys.exit(f"missing mic session file: {path}")
        sessions.append({"path": path, "durationMs": session["durationMs"]})
    return sessions


def write_cut_package(
    src: Path, cuts: list[tuple[float, float]], output: Path | None, default_suffix: str
) -> Path:
    # clone the package (apfs copy-on-write) and rewrite only scenes[].slices
    base = output or src.with_name(src.stem + default_suffix + ".screenstudio")
    dst = versioned_output(base, src)
    subprocess.run(["cp", "-c", "-R", str(src), str(dst)], check=True)

    wrapper = json.loads((dst / "project.json").read_text())
    project = wrapper["json"]
    before_ms = after_ms = 0
    for scene in project["scenes"]:
        if scene.get("type") != "recording":
            continue
        before_ms += sum(x["sourceEndMs"] - x["sourceStartMs"] for x in scene["slices"])
        scene["slices"] = subtract_cuts(scene["slices"], cuts)
        after_ms += sum(x["sourceEndMs"] - x["sourceStartMs"] for x in scene["slices"])
        print(f"scene {scene['id']}: {len(scene['slices'])} slices after cutting")

    (dst / "project.json").write_text(json.dumps(wrapper))
    saved = (before_ms - after_ms) / 1000
    print(f"\noutput duration: {before_ms / 1000:.1f}s -> {after_ms / 1000:.1f}s (saved {saved:.1f}s)")
    print(f"wrote: {dst}")
    return dst
