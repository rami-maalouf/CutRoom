# the project file: the one place iteration state lives. next to a single
# source it is <name>.cutroom.json; for a folder of clips it is
# <folder>/cutroom/cutroom.json. people and agents edit it; every cutroom
# command reads it, so a decision made once is never lost between runs.
#
#   edits.cuts   extra cuts, e.g. retakes the detector missed     (shown as M1, M2, ...)
#   edits.keeps  ranges that are never cut (rejects a proposed cut)
#   selects      folders: the vlog, an ordered list of moments     (V1, V2, ...)
#   shorts       short-form candidates                             (S1, S2, ...)
#   pickups      talking heads to record: a line to camera (or a voiceover)
#                that explains what the footage cannot          (P1, P2, ...)
#   inclusions   folders: every moment worth judging in the footage, each
#                "in" or "out" of the vlog with the reason why  (I1, I2, ...)
#   style        "talking-head", "explainer", "reaction" or "vlog" (default: vlog for a folder)
#   ignore       folders: patterns for files that are not footage, e.g.
#                "*-bad-quality.mp4" (matched against the path inside the folder)
#
# selects and shorts may carry "beat", "role" and "intent" (from the story) and
# "raw": true, which plays the moment as it happened: no silence or retake
# cuts inside it, only its edges and manual cuts.
#
# a select may carry "speed": 4 to play its moment faster (a sped-up stretch:
# the walk between scenes, small talk worth seeing but not hearing in full).
# the review page plays it at that speed with its sound sped up too, the
# read-through counts its play length, and the fcpxml retimes the clip.
#
# a select may carry "markers": [{"at": s, "text": "..."}], notes for the
# person finishing the edit (a name to put on screen, a sound to fix). "at" is
# seconds in the select's clip, inside the select; the fcpxml puts a marker there.
#
# shorts may also carry what the review page sorts and groups them by:
# "theme" (text), "rank" (1 = review first), "score" (0-10, overall quality),
# "scores" ({"hook": 8, "standalone": 9, ...}, each 0-10) and "tags" (["v04"]).
#
# a short may also carry its "copy": the text that goes on the finished short
# (rendered by the shorts-text skill), {"status": "proposed" | "approved",
# "texts": [...]}. each text is {"kind": "headline" | "cta", "text": "...",
# "at": "..."}: a headline shows from the start; a call to action starts on the
# words in "at" (said inside the short), or on "last sentence". optional:
# "hold" (seconds), "until": "end", "end" (seconds), "top" (px). a "\n" in the
# text is a line break. the agent proposes, the person approves on the review page.
#
# a range is {"clip": "<path inside the folder>", "start": s, "end": s} with
# seconds inside that clip; for a single source "clip" is left out (and the
# short list form [start, end, note] still works). anchoring times to clips
# means adding a file to the folder never moves an existing decision.
# a pickup is footage that does not exist yet: {"id": "P1", "after": "V12",
# "kind": "talking-head" | "voiceover", "seconds": 20, "purpose": "...",
# "points": ["..."], "draft": "..."}. "after" places it after a select ("start"
# opens the video); without it the pickup is a suggestion not placed yet.
# "near": {"clip": ..., "time": s} marks where in the raw footage it belongs
# (no "clip" for a single source), so a suggestion shows before any selects.
# once recorded, the new file becomes a select and the pickup is removed.
# an inclusion is an editor's verdict on one moment: {"id": "I1", "clip": ...,
# "start": s, "end": s, "verdict": "in" | "out", "why": "...", "title": "...",
# "chapter": "...", "beat": "..."}. it does not play anything: the selects do.
# it makes the choice visible, so a moment left out can be brought back.
# cutroom only stores, shows and exports selects, shorts and pickups; choosing
# them is an editorial judgment made by an agent or a person.

import json
import re
import sys
from pathlib import Path

from .core import Range
from .screenstudio import is_screenstudio

VERSION = 2
# the kind of video: decides the defaults (see STYLE_DEFAULTS in cli.py) and
# which instructions the agent follows (skills/cutroom/references/<style>.md)
STYLES = ("talking-head", "explainer", "reaction", "vlog")
# free text on selects and shorts: shown on the review page and in the read-through
TEXT_FIELDS = ("chapter", "beat", "role", "intent", "title", "why", "theme")
PICKUP_KINDS = ("talking-head", "voiceover")
COPY_KINDS = ("headline", "cta")
COPY_STATUS = ("proposed", "approved")
COPY_KEYS = {"kind", "text", "at", "hold", "until", "end", "top"}
VERDICTS = ("in", "out")
MAX_SPEED = 20


def speed(item: dict) -> float:
    # how fast a select plays: 1 unless it says otherwise
    return float(item.get("speed", 1))


def project_path(src: Path) -> Path:
    # a folder of clips keeps it inside; a video or a screen studio package (also
    # a folder) keeps it next to itself, so the package stays screen studio's own
    if src.is_dir() and not is_screenstudio(src):
        return src / "cutroom" / "cutroom.json"
    return src.with_suffix(".cutroom.json")


def load(src: Path, clips: set[str] | None = None, new_selects: bool = False) -> dict:
    # clips: the folder's clip paths (None for a single source). new_selects:
    # the caller replaces every select, so the old ones are dropped unchecked
    path = project_path(src)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if data.get("v", VERSION) not in (1, VERSION):
        sys.exit(f"{path.name}: unsupported project file version {data.get('v')}")
    data["v"] = VERSION
    data.setdefault("edits", {})
    data["edits"].setdefault("cuts", [])
    data["edits"].setdefault("keeps", [])
    # a folder of clips is a vlog; a single recording (or screen studio project) a talking head
    data.setdefault("style", "vlog" if clips is not None else "talking-head")
    data.setdefault("selects", [])
    data.setdefault("shorts", [])
    data.setdefault("pickups", [])
    data.setdefault("inclusions", [])
    if new_selects:
        data["selects"] = []
        # select ids are renumbered: a placed pickup has to be placed again
        unplaced = [p["id"] for p in data["pickups"] if p.get("after") not in (None, "start")]
        for p in data["pickups"]:
            if p["id"] in unplaced:
                p.pop("after")
        if unplaced:
            print(f"pickups {', '.join(unplaced)} are no longer placed: set their \"after\" again")
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


def check_ignore(ignore, path: Path) -> list[str]:
    if not (isinstance(ignore, list) and all(isinstance(p, str) for p in ignore)):
        sys.exit(f"{path.name}: ignore must be a list of patterns like [\"*-bad-quality.mp4\"], got {ignore!r}")
    return ignore


def validate(data: dict, path: Path, clips: set[str] | None) -> None:
    def check_range(r: dict, where: str) -> None:
        if not (isinstance(r.get("start"), (int, float)) and isinstance(r.get("end"), (int, float))
                and 0 <= r["start"] < r["end"]):
            sys.exit(f"{path.name}: {where} needs numeric start < end (seconds), got {r!r}")
        if clips is not None:
            if "clip" not in r:
                sys.exit(f"{path.name}: {where} needs a \"clip\" (a path inside the folder)")
            if r["clip"] not in clips:
                sys.exit(f"{path.name}: {where} names clip {r['clip']!r}, which is not in the folder (or is ignored)")
        elif "clip" in r:
            sys.exit(f"{path.name}: {where} names a clip, but the source is a single file")

    check_ignore(data.get("ignore", []), path)
    if data.get("style") not in STYLES:
        sys.exit(f"{path.name}: style must be one of {', '.join(STYLES)}, got {data.get('style')!r}")
    for item in data["selects"]:
        value = item.get("speed", 1)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= MAX_SPEED:
            sys.exit(f"{path.name}: {item.get('id')} \"speed\" must be a number above 0 and at most {MAX_SPEED}, got {value!r}")
    for item in data["selects"]:
        marks = item.get("markers", [])
        if not isinstance(marks, list) or not all(
                isinstance(m, dict) and isinstance(m.get("text"), str) and m["text"]
                and isinstance(m.get("at"), (int, float)) and not isinstance(m["at"], bool)
                and item.get("start", 0) <= m["at"] <= item.get("end", 0) for m in marks):
            sys.exit(f"{path.name}: {item.get('id')} \"markers\" must be a list of "
                     f"{{\"at\": seconds inside the select, \"text\": \"...\"}}")
    for item in data["shorts"]:
        if "speed" in item:
            sys.exit(f"{path.name}: {item.get('id')} \"speed\" is for selects only")
    for item in data["selects"] + data["shorts"]:
        if "raw" in item and not isinstance(item["raw"], bool):
            sys.exit(f"{path.name}: {item.get('id')} \"raw\" must be true or false")
        for key in TEXT_FIELDS:
            if key in item and not isinstance(item[key], str):
                sys.exit(f"{path.name}: {item.get('id')} \"{key}\" must be text, got {item[key]!r}")
    for item in data["shorts"]:
        check_short_review(item, path)
        if "copy" in item:
            check_short_copy(item, path)
    for key in ("cuts", "keeps"):
        for item in data["edits"][key]:
            if isinstance(item, list) and len(item) < 2:
                sys.exit(f"{path.name}: edits.{key} entries must be [start, end, note?], got {item!r}")
            check_range(_as_range(item), f"edits.{key} entry")
    select_ids = {item.get("id") for item in data["selects"]}
    ids = set()
    for item in data["pickups"]:
        iid = item.get("id", "")
        if not re.fullmatch(r"P\d+", iid) or iid in ids:
            sys.exit(f"{path.name}: every entry in pickups needs a unique id like P1, got {iid!r}")
        ids.add(iid)
        if not isinstance(item.get("purpose"), str) or not item["purpose"]:
            sys.exit(f"{path.name}: {iid} needs a \"purpose\": what the talking head explains")
        if item.get("kind", "talking-head") not in PICKUP_KINDS:
            sys.exit(f"{path.name}: {iid} \"kind\" must be one of {', '.join(PICKUP_KINDS)}")
        if "after" in item and item["after"] != "start" and item["after"] not in select_ids:
            sys.exit(f"{path.name}: {iid} goes after {item['after']!r}, which is not a select (or \"start\")")
        if "near" in item:
            near = item["near"]
            if not (isinstance(near, dict) and isinstance(near.get("time"), (int, float)) and near["time"] >= 0):
                sys.exit(f"{path.name}: {iid} \"near\" must be {{\"clip\": ..., \"time\": seconds}}, got {near!r}")
            if clips is not None and near.get("clip") not in clips:
                sys.exit(f"{path.name}: {iid} \"near\" names clip {near.get('clip')!r}, which is not in the folder")
            if clips is None and "clip" in near:
                sys.exit(f"{path.name}: {iid} \"near\" names a clip, but the source is a single file")
        seconds = item.get("seconds", 20)
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            sys.exit(f"{path.name}: {iid} \"seconds\" must be a positive number, got {seconds!r}")
        points = item.get("points", [])
        if not (isinstance(points, list) and all(isinstance(x, str) for x in points)):
            sys.exit(f"{path.name}: {iid} \"points\" must be a list of text")
        for key in TEXT_FIELDS + ("draft",):
            if key in item and not isinstance(item[key], str):
                sys.exit(f"{path.name}: {iid} \"{key}\" must be text, got {item[key]!r}")
    ids = set()
    for item in data["inclusions"]:
        iid = item.get("id", "")
        if not re.fullmatch(r"I\d+", iid) or iid in ids:
            sys.exit(f"{path.name}: every entry in inclusions needs a unique id like I1, got {iid!r}")
        ids.add(iid)
        check_range(item, f"inclusions {iid}")
        if item.get("verdict") not in VERDICTS:
            sys.exit(f"{path.name}: {iid} \"verdict\" must be \"in\" or \"out\", got {item.get('verdict')!r}")
        if not isinstance(item.get("why"), str) or not item["why"]:
            sys.exit(f"{path.name}: {iid} needs a \"why\": the reason it is in or out")
        for key in TEXT_FIELDS:
            if key in item and not isinstance(item[key], str):
                sys.exit(f"{path.name}: {iid} \"{key}\" must be text, got {item[key]!r}")
    for key, prefix in (("selects", "V"), ("shorts", "S")):
        ids = set()
        for item in data[key]:
            iid = item.get("id", "")
            if not re.fullmatch(prefix + r"\d+", iid) or iid in ids:
                sys.exit(f"{path.name}: every entry in {key} needs a unique id like {prefix}1, got {iid!r}")
            ids.add(iid)
            for seg in item.get("segments") or [item]:
                check_range(seg, f"{key} {iid}")


def _score(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 10


def check_short_review(item: dict, path: Path) -> None:
    # the fields the review page sorts, groups and shows shorts by
    iid = item.get("id")
    rank = item.get("rank", 1)
    if not (isinstance(rank, int) and not isinstance(rank, bool) and rank >= 1):
        sys.exit(f"{path.name}: {iid} \"rank\" must be a whole number from 1 (review first), got {rank!r}")
    if "score" in item and not _score(item["score"]):
        sys.exit(f"{path.name}: {iid} \"score\" must be a number from 0 to 10, got {item['score']!r}")
    scores = item.get("scores", {})
    if not (isinstance(scores, dict) and all(isinstance(k, str) and _score(v) for k, v in scores.items())):
        sys.exit(f"{path.name}: {iid} \"scores\" must look like {{\"hook\": 8, \"payoff\": 7}} (0-10 each), got {scores!r}")
    tags = item.get("tags", [])
    if not (isinstance(tags, list) and all(isinstance(x, str) for x in tags)):
        sys.exit(f"{path.name}: {iid} \"tags\" must be a list of text, got {tags!r}")


def _positive(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def check_short_copy(item: dict, path: Path) -> None:
    # the short's text for the finished video, in the shape of a shorts-text job's "texts"
    iid, copy = item.get("id"), item["copy"]
    shape = '{"status": "proposed", "texts": [{"kind": "headline", "text": "..."}, ...]}'
    if not (isinstance(copy, dict) and isinstance(copy.get("texts"), list) and copy["texts"]):
        sys.exit(f"{path.name}: {iid} \"copy\" must look like {shape}, got {copy!r}")
    if copy.get("status", "proposed") not in COPY_STATUS:
        sys.exit(f"{path.name}: {iid} copy \"status\" must be \"proposed\" or \"approved\", got {copy.get('status')!r}")
    for n, t in enumerate(copy["texts"], 1):
        where = f"{iid} copy text {n}"
        if not isinstance(t, dict):
            sys.exit(f"{path.name}: {where} must be an object like {{\"kind\": \"cta\", \"text\": ..., \"at\": ...}}")
        unknown = sorted(set(t) - COPY_KEYS)
        if unknown:
            sys.exit(f"{path.name}: {where} has unknown keys {unknown} (known: {', '.join(sorted(COPY_KEYS))})")
        if t.get("kind") not in COPY_KINDS:
            sys.exit(f"{path.name}: {where} \"kind\" must be \"headline\" or \"cta\", got {t.get('kind')!r}")
        if not (isinstance(t.get("text"), str) and t["text"].strip()):
            sys.exit(f"{path.name}: {where} needs a \"text\"")
        if t["kind"] == "cta" and not (isinstance(t.get("at"), str) and t["at"].strip()):
            sys.exit(f"{path.name}: {where} needs \"at\": the words it starts on, or \"last sentence\"")
        for key in ("hold", "end"):
            if key in t and not _positive(t[key]):
                sys.exit(f"{path.name}: {where} \"{key}\" must be a positive number of seconds, got {t[key]!r}")
        if "until" in t and t["until"] != "end":
            sys.exit(f"{path.name}: {where} \"until\" can only be \"end\", got {t['until']!r}")
        if "top" in t and not (isinstance(t["top"], int) and not isinstance(t["top"], bool) and t["top"] >= 0):
            sys.exit(f"{path.name}: {where} \"top\" must be a whole number of pixels, got {t['top']!r}")
    if sum(t["kind"] == "headline" for t in copy["texts"]) > 1:
        sys.exit(f"{path.name}: {iid} copy has more than one headline")


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


def pickups_after(data: dict) -> dict[str, list[dict]]:
    # placed pickups by the select they follow ("start": before the first select)
    out: dict[str, list[dict]] = {}
    for p in data["pickups"]:
        if p.get("after"):
            out.setdefault(p["after"], []).append(p)
    return out


def inclusion_selects(data: dict, offsets: dict[str, float] | None = None) -> dict[str, list[str]]:
    # inclusion id -> the selects that play part of it, in play order. a touch
    # at the edges (a select that ends where the next moment starts) does not count
    spans = [(s["id"], *_ms(seg, offsets)) for s in data["selects"] for seg in (s.get("segments") or [s])]
    out = {}
    for item in data["inclusions"]:
        a, b = _ms(item, offsets)
        out[item["id"]] = list(dict.fromkeys(sid for sid, s, e in spans if min(e, b) - max(s, a) > 500))
    return out


def inclusion_problems(data: dict, offsets: dict[str, float] | None = None) -> list[str]:
    # a verdict the selects do not follow: "in" with nothing playing it, or "out" that plays
    played = inclusion_selects(data, offsets)
    problems = []
    for item in data["inclusions"]:
        sids = played[item["id"]]
        if item["verdict"] == "in" and not sids:
            problems.append(f"{item['id']} is in, but no select plays it ({item.get('title', '')})")
        elif item["verdict"] == "out" and sids:
            problems.append(f"{item['id']} is out, but {', '.join(sids)} play part of it ({item.get('title', '')})")
    return problems


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
