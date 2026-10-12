# the per-recording project file, <name>.cutroom.json next to the source: the
# one place iteration state lives. people and agents edit it; every cutroom
# command reads it, so a decision made once is never lost between runs.
#
#   edits.cuts   [[start, end, note], ...]  extra cuts, e.g. retakes the detector missed
#   edits.keeps  [[start, end, note], ...]  ranges that are never cut (rejects a proposed cut)
#   shorts       [{"id": "S1", "start", "end", "title", "why"}, ...]  short-form candidates
#
# times are seconds on the source timeline. cutroom only stores, shows and
# exports shorts; choosing them is an editorial judgment made by an agent or a person.

import json
import re
import sys
from pathlib import Path

from .core import Range

VERSION = 1


def project_path(src: Path) -> Path:
    return src.with_suffix(".cutroom.json")


def load(src: Path) -> dict:
    path = project_path(src)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if data.get("v", VERSION) != VERSION:
        sys.exit(f"{path.name}: unsupported project file version {data.get('v')}")
    data.setdefault("v", VERSION)
    data.setdefault("edits", {})
    data["edits"].setdefault("cuts", [])
    data["edits"].setdefault("keeps", [])
    data.setdefault("shorts", [])
    validate(data, path)
    return data


def save(src: Path, data: dict) -> Path:
    path = project_path(src)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def validate(data: dict, path: Path) -> None:
    for key in ("cuts", "keeps"):
        for item in data["edits"][key]:
            if not (isinstance(item, list) and len(item) >= 2 and 0 <= item[0] < item[1]):
                sys.exit(f"{path.name}: edits.{key} entries must be [start, end, note?] "
                         f"with start < end, got {item!r}")
    ids = set()
    for short in data["shorts"]:
        sid = short.get("id", "")
        if not re.fullmatch(r"S\d+", sid) or sid in ids:
            sys.exit(f"{path.name}: every short needs a unique id like S1, got {sid!r}")
        if not 0 <= short.get("start", -1) < short.get("end", -1):
            sys.exit(f"{path.name}: short {sid} needs start < end (seconds)")
        ids.add(sid)


def edit_ranges(data: dict, key: str) -> list[tuple[float, float, str]]:
    # (start_ms, end_ms, note)
    return [(s * 1000, e * 1000, rest[0] if rest else "") for s, e, *rest in data["edits"][key]]


def find_short(data: dict, sid: str) -> dict:
    for short in data["shorts"]:
        if short["id"].lower() == sid.lower():
            return short
    known = ", ".join(s["id"] for s in data["shorts"]) or "none"
    sys.exit(f"no short {sid!r} in the project file (known: {known})")


def short_range(short: dict) -> Range:
    return short["start"] * 1000, short["end"] * 1000
