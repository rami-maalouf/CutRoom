# the read-through: the cut as a script, in play order, with only the words
# that survive. reading it is how a reviewer (agent or person) finds story
# problems without watching: a payoff with no setup, two moments that do not
# connect, an intro that does not hook. " / " marks a cut inside a moment.
# talking heads still to record (pickups) appear where they will play, and the
# moments judged out of the vlog (inclusions) are listed at the end. in a
# reaction the video being watched speaks too: its lines are marked "video:".

from pathlib import Path

from . import project
from .core import played_words, words_to_sentences


def _clock(seconds: float) -> str:
    # round to tenths first, so 599.97 s reads 10:00.0 and not 9:60.0
    m, s = divmod(round(max(0.0, seconds) * 10), 600)
    return f"{m}:{s / 10:04.1f}"


def _spoken(words: list[dict], starts: list[float], segments: list[tuple],
            heard: list[dict] = (), heard_starts: list[float] = ()) -> str:
    # with a second voice (a reaction's video), each change of voice is marked
    parts = []
    for s, e, *_ in segments:
        said = [(words[i]["startMs"], "me:", words[i]["word"]) for i in played_words(words, starts, s, e)]
        said += [(heard[i]["startMs"], "video:", heard[i]["word"])
                 for i in played_words(heard, heard_starts, s, e)]
        text, voice = [], None
        for _, who, word in sorted(said):
            if heard and who != voice:
                text.append(who)
                voice = who
            text.append(word)
        if text:
            parts.append(" ".join(text))
    return " / ".join(parts) or "(no speech)"


def _pickup(p: dict) -> list[str]:
    kind = "voiceover" if p.get("kind") == "voiceover" else "talking head"
    lines = [f"### {p['id']}  {kind} to record  ·  about {p.get('seconds', 20)} s", f"purpose: {p['purpose']}"]
    if p.get("near") and not p.get("after"):
        near = p["near"]
        lines.append(f"near: {(near['clip'] + ' ') if 'clip' in near else ''}{_clock(near['time'])}")
    lines += [f"- {point}" for point in p.get("points", [])]
    if p.get("draft"):
        lines.append(f"draft (say it your way): {p['draft']}")
    return lines + [""]


def build_script(job) -> str:
    words = job.plan.words or []
    starts = [w["startMs"] for w in words]
    heard = job.plan.heard_words
    heard_starts = [w["startMs"] for w in heard]
    total = job.play_ms(job.program) / 1000
    pickups = job.data["pickups"]
    after = project.pickups_after(job.data)
    placed = [p for p in pickups if p.get("after") and (p["after"] == "start" or job.data["selects"])]
    record = (f"  ·  + {_clock(sum(p.get('seconds', 20) for p in placed))} to record "
              f"({len(placed)} talking heads)" if placed else "")
    out = [f"# {job.stem}: read-through", "",
           f"{job.data['style']}  ·  {_clock(total)} long{record}  ·  {len(job.data['selects'])} selects  ·  "
           f"{len(job.chapters)} chapters", ""]
    for p in after.get("start", []):
        out += _pickup(p)
    unplaced = [p for p in pickups if p not in placed]
    tail = ["", "## To record, not placed yet", ""] + [x for p in unplaced for x in _pickup(p)] if unplaced else []
    if not job.data["selects"]:
        # a talking head (or a folder without selects): the clean cut, one line per
        # sentence at its time in the cut; " / " marks a cut inside a sentence
        at = 0.0
        for s, e, *_ in job.program:
            lines = []
            for label, ws, st in (("", words, starts), ("video: ", heard, heard_starts)):
                piece = [ws[i] for i in played_words(ws, st, s, e)]
                lines += [(sent["startMs"], label, sent["text"]) for sent in words_to_sentences(piece)]
            for start, label, text in sorted(lines, key=lambda x: x[0]):
                # a word whisper started inside the cut before it plays from the cut on
                out.append(f"[{_clock(at + (max(start, s) - s) / 1000)}] {label}{text}")
            at += (e - s) / 1000
        return "\n".join(out + tail) + "\n"

    by_id: dict[str, list[tuple]] = {}
    for seg in job.program:
        by_id.setdefault(seg[2], []).append(seg)
    at, chapter = 0.0, None
    for item in job.data["selects"]:
        segs = by_id.get(item["id"], [])
        length = job.play_ms(segs) / 1000
        if item.get("chapter") and item["chapter"] != chapter:
            chapter = item["chapter"]
            out += ["", f"## {chapter}", ""]
        speed = project.speed(item)
        tags = [t for t in (item.get("beat"), item.get("role"), "raw" if item.get("raw") else None,
                            f"{speed:g}x" if speed != 1 else None) if t]
        out.append(f"### {item['id']}  [{_clock(at)}, {length:.1f}s]" + (f"  {' · '.join(tags)}" if tags else ""))
        if item.get("intent"):
            out.append(f"intent: {item['intent']}")
        source = f"{item['clip']} {_clock(item['start'])}-{_clock(item['end'])}" if "clip" in item \
            else f"{_clock(item['start'])}-{_clock(item['end'])}"
        out.append(f"source: {source}" + ("" if segs else "  (NOTHING LEFT AFTER CUTS)"))
        out.append(f"> {_spoken(words, starts, segs, heard, heard_starts)}" if segs else "> (empty)")
        out.append("")
        at += length
        for p in after.get(item["id"], []):
            out += _pickup(p)
    return "\n".join(out + _left_out(job) + tail) + "\n"


def _left_out(job) -> list[str]:
    # the moments judged out, with the reason: read them with the cut, and bring
    # back any that the story misses
    out = [m for m in job.data.get("inclusions", []) if m["verdict"] == "out"]
    if not out:
        return []
    lines = ["", f"## Left out ({len(out)} of {len(job.data['inclusions'])} judged moments)", ""]
    for m in out:
        where = f"{m['clip']} {_clock(m['start'])}-{_clock(m['end'])}"
        lines.append(f"- {m['id']}  {m.get('title') or where}  ({where}): {m['why']}")
    return lines


def script_path(job) -> Path:
    if job.kind == "folder":
        return job.src / "cutroom" / "script.md"
    return job.src.with_suffix(".script.md")


def story_path(job) -> Path:
    # the agent's story outline (written before selection), if there is one
    if job.kind == "folder":
        return job.src / "cutroom" / "story.md"
    return job.src.with_suffix(".story.md")


def story_text(job) -> str:
    path = story_path(job)
    return path.read_text(encoding="utf-8") if path.exists() else ""

