# the read-through: the cut as a script, in play order, with only the words
# that survive. reading it is how a reviewer (agent or person) finds story
# problems without watching: a payoff with no setup, two moments that do not
# connect, an intro that does not hook. " / " marks a cut inside a moment.

from pathlib import Path

from .core import words_to_sentences


def _clock(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{s:04.1f}"


def _spoken(words: list[dict], segments: list[tuple]) -> str:
    parts = []
    for s, e, *_ in segments:
        text = " ".join(w["word"] for w in words if s <= w["startMs"] < e)
        if text:
            parts.append(text)
    return " / ".join(parts) or "(no speech)"


def build_script(job) -> str:
    plan, words = job.plan, job.plan.words or []
    total = sum(r[1] - r[0] for r in job.program) / 1000
    out = [f"# {job.stem}: read-through", "",
           f"{job.data['style']}  ·  {_clock(total)} long  ·  {len(job.data['selects'])} selects  ·  "
           f"{len(job.chapters)} chapters", ""]
    if not job.data["selects"]:
        # a talking head (or a folder without selects): the clean cut, one line per
        # sentence at its time in the cut; " / " marks a cut inside a sentence
        at = 0.0
        for s, e, *_ in job.program:
            piece = [w for w in words if s <= w["startMs"] < e]
            for sent in words_to_sentences(piece):
                out.append(f"[{_clock(at + (sent['startMs'] - s) / 1000)}] {sent['text']}")
            at += (e - s) / 1000
        return "\n".join(out) + "\n"

    by_id: dict[str, list[tuple]] = {}
    for seg in job.program:
        by_id.setdefault(seg[2], []).append(seg)
    at, chapter = 0.0, None
    for item in job.data["selects"]:
        segs = by_id.get(item["id"], [])
        length = sum(e - s for s, e, _ in segs) / 1000
        if item.get("chapter") and item["chapter"] != chapter:
            chapter = item["chapter"]
            out += ["", f"## {chapter}", ""]
        tags = [t for t in (item.get("beat"), item.get("role"), "raw" if item.get("raw") else None) if t]
        out.append(f"### {item['id']}  [{_clock(at)}, {length:.1f}s]" + (f"  {' · '.join(tags)}" if tags else ""))
        if item.get("intent"):
            out.append(f"intent: {item['intent']}")
        source = f"{item['clip']} {_clock(item['start'])}-{_clock(item['end'])}" if "clip" in item \
            else f"{_clock(item['start'])}-{_clock(item['end'])}"
        out.append(f"source: {source}" + ("" if segs else "  (NOTHING LEFT AFTER CUTS)"))
        out.append(f"> {_spoken(words, segs)}" if segs else "> (empty)")
        out.append("")
        at += length
    return "\n".join(out) + "\n"


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

