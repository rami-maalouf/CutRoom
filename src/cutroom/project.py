# the project file: the one place iteration state lives. next to a single
# source it is <name>.cutroom.json; for a folder of clips it is
# <folder>/cutroom/cutroom.json. people and agents edit it; every cutroom
# command reads it, so a decision made once is never lost between runs.
#
#   edits.cuts   extra cuts, e.g. retakes the detector missed     (shown as M1, M2, ...)
#   edits.keeps  ranges that are never cut (rejects a proposed cut)
#   selects      folders: the vlog, an ordered list of moments     (V1, V2, ...)
#   shorts       short-form candidates                             (S1, S2, ...)
#
# a range is {"clip": "<path inside the folder>", "start": s, "end": s} with
# seconds inside that clip; for a single source "clip" is left out (and the
# short list form [start, end, note] still works). anchoring times to clips
# means adding a file to the folder never moves an existing decision.
# cutroom only stores, shows and exports selects and shorts; choosing them is
# an editorial judgment made by an agent or a person.

import json
import re
import sys
from pathlib import Path

from .core import Range

VERSION = 2


def project_path(src: Path) -> Path:
    if src.is_dir():
        return src / "cutroom" / "cutroom.json"
    return src.with_suffix(".cutroom.json")


def load(src: Path, clips: set[str] | None = None) -> dict:
    # clips: the folder's clip paths (None for a single source)
    path = project_path(src)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if data.get("v", VERSION) not in (1, VERSION):
        sys.exit(f"{path.name}: unsupported project file version {data.get('v')}")
    data["v"] = VERSION
    data.setdefault("edits", {})
    data["edits"].setdefault("cuts", [])
    data["edits"].setdefault("keeps", [])
    data.setdefault("selects", [])
    data.setdefault("shorts", [])
    validate(data, path, clips)
    return data


def save(src: Path, data: dict) -> Path:
    path = project_path(src)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _as_range(item) -> dict:
    # list form [start, end, note?] or {"clip"?, "start", "end", "note"?}
    if isinstance(item, list):
        return {"start": item[0], "end": item[1], "note": item[2] if len(item) > 2 else ""}
    return item


def validate(data: dict, path: Path, clips: set[str] | None) -> None:
    def check_range(r: dict, where: str) -> None:
        if not (isinstance(r.get("start"), (int, float)) and isinstance(r.get("end"), (int, float))
                and 0 <= r["start"] < r["end"]):
            sys.exit(f"{path.name}: {where} needs numeric start < end (seconds), got {r!r}")
        if clips is not None:
            if "clip" not in r:
                sys.exit(f"{path.name}: {where} needs a \"clip\" (a path inside the folder)")
            if r["clip"] not in clips:
                sys.exit(f"{path.name}: {where} names clip {r['clip']!r}, which is not in the folder")
        elif "clip" in r:
            sys.exit(f"{path.name}: {where} names a clip, but the source is a single file")

    for key in ("cuts", "keeps"):
        for item in data["edits"][key]:
            if isinstance(item, list) and len(item) < 2:
                sys.exit(f"{path.name}: edits.{key} entries must be [start, end, note?], got {item!r}")
            check_range(_as_range(item), f"edits.{key} entry")
    for key, prefix in (("selects", "V"), ("shorts", "S")):
        ids = set()
        for item in data[key]:
            iid = item.get("id", "")
            if not re.fullmatch(prefix + r"\d+", iid) or iid in ids:
                sys.exit(f"{path.name}: every entry in {key} needs a unique id like {prefix}1, got {iid!r}")
            ids.add(iid)
            for seg in item.get("segments") or [item]:
                check_range(seg, f"{key} {iid}")


def _ms(r: dict, offsets: dict[str, float] | None) -> Range:
    base = offsets[r["clip"]] if offsets is not None else 0.0
    return base + r["start"] * 1000, base + r["end"] * 1000


def edit_ranges(data: dict, key: str, offsets: dict[str, float] | None = None
                ) -> list[tuple[float, float, str]]:
    # (start_ms, end_ms, note) on the source timeline
    out = []
    for item in data["edits"][key]:
        r = _as_range(item)
        out.append((*_ms(r, offsets), r.get("note", "")))
    return out


def selects(data: dict, offsets: dict[str, float] | None = None) -> list[dict]:
    # ordered selects with timeline ranges: {"id", "startMs", "endMs", "chapter", ...}
    return [{**s, "startMs": _ms(s, offsets)[0], "endMs": _ms(s, offsets)[1]} for s in data["selects"]]


def find(data: dict, iid: str) -> dict:
    for key in ("shorts", "selects"):
        for item in data[key]:
            if item["id"].lower() == iid.lower():
                return item
    known = ", ".join(x["id"] for k in ("selects", "shorts") for x in data[k]) or "none"
    sys.exit(f"no {iid!r} in the project file (known: {known})")


def segments(item: dict, offsets: dict[str, float] | None = None) -> list[Range]:
    # timeline ranges (ms) of a short or select, in its own order
    return [_ms(seg, offsets) for seg in (item.get("segments") or [item])]


# kept for single-source callers
def find_short(data: dict, sid: str) -> dict:
    return find(data, sid)


def short_range(short: dict) -> Range:
    return _ms(short, None)
