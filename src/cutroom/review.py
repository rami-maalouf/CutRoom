# the review page: one self-contained html file. it plays the ORIGINAL media
# and skips the cut ranges, so reviewing costs no render and no new media
# files. every judgment call (R*/M*), select (V*) and short candidate (S*) has
# an id, a play button and a toggle; the toggles build feedback text to paste
# back to the agent, which edits the project file and re-plans in a second.
# for a folder of clips the page shows the vlog: the selects in order, by chapter.

import json
from bisect import bisect_left
from pathlib import Path

import html
import re

from . import project
from .pipeline import plan_data
from .script import story_text


def _secs(r) -> list[float]:
    return [round(r[0] / 1000, 3), round(r[1] / 1000, 3)]


def _clock(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{s:04.1f}"


def _where(item: dict) -> str:
    # human description of where an item comes from
    segs = item.get("segments") or [item]
    first = segs[0]
    clip = f"{first['clip']} " if "clip" in first else ""
    more = f" + {len(segs) - 1} more" if len(segs) > 1 else ""
    return f"{clip}{_clock(first['start'])}-{_clock(first['end'])}{more}"


def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", text)


def markdown(text: str) -> str:
    # just enough markdown for a story outline: headings, lists, tables, paragraphs
    out, table, para = [], [], []

    def flush():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()
        if table:
            rows = [r for r in table if not re.fullmatch(r"\|[\s:|-]+\|?", r)]
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            body = "".join("<tr>" + "".join(f"<{'th' if i == 0 else 'td'}>{_inline(c)}</{'th' if i == 0 else 'td'}>"
                                             for c in row) + "</tr>" for i, row in enumerate(cells))
            out.append(f"<table>{body}</table>")
            table.clear()

    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            if para:
                flush()
            table.append(line)
            continue
        if table:
            flush()
        heading = re.match(r"(#{1,4})\s+(.*)", line)
        bullet = re.match(r"\s*(?:[-*]|\d+\.)\s+(.*)", line)
        if heading:
            flush()
            out.append(f"<h{len(heading.group(1)) + 2}>{_inline(heading.group(2))}</h{len(heading.group(1)) + 2}>")
        elif bullet:
            flush()
            nested = ' class="nested"' if len(line) - len(line.lstrip()) >= 2 else ""
            out.append(f"<li{nested}>{_inline(bullet.group(1))}</li>")
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
    flush()
    return "\n".join(out)


# opening words that lean on something said before the short starts
LEANING = {"and", "but", "so", "because", "which", "also", "then", "or", "yeah", "anyway",
           "it", "this", "that", "these", "those", "they", "he", "she"}


def edge_flags(pieces: list[list]) -> list[str]:
    # what to check at a short's edges (the standalone gate starts here): an
    # opening that leans on what came before, an ending cut off mid-sentence.
    # hints, not verdicts: a transcript without punctuation trips the ending check
    words = [w for piece in pieces for _, w in piece]
    if not words:
        return []
    flags = []
    first, last = words[0], words[-1]
    if re.sub(r"[^\w']", "", first).lower() in LEANING:
        flags.append(f'opens on "{first.strip(",.;:")}"')
    elif first[:1].islower():
        flags.append(f'starts mid-sentence: "{first}"')
    if not last.endswith((".", "?", "!")):
        flags.append(f'ends mid-sentence: "...{last}"')
    return flags


def short_data(job, short: dict, words: list[dict], starts: list[float]) -> dict:
    # the short as the page needs it: the ranges that play, and its words in
    # them, one list per piece (a piece is one segment of the project file)
    keeps = job.item_segments(short)
    pieces = []
    for a, b in project.segments(short, job.offsets):
        piece = []
        for s, e in keeps:
            lo, hi = max(s, a), min(e, b)
            if hi > lo:
                piece += [[round(w["startMs"] / 1000, 2), w["word"].strip()]
                          for w in words[bisect_left(starts, lo):bisect_left(starts, hi)]]
        pieces.append(piece)
    return {**short, "where": _where(short), "keeps": [_secs(r) for r in keeps],
            "seconds": round(sum(e - s for s, e in keeps) / 1000, 2),
            "pieces": pieces, "flags": edge_flags(pieces)}


def review_html(job, media_uri=None, served: bool = False) -> str:
    # media_uri(i, path) gives each file's address: file:// for the page on
    # disk, a url on the local network when `cutroom review --serve` sends it
    media_uri = media_uri or (lambda i, path: path.resolve().as_uri())
    plan = job.plan
    data = plan_data(plan, job.src)
    media, offset = [], 0.0
    for i, s in enumerate(job.sessions):
        media.append({"uri": media_uri(i, s["path"]), "offset": round(offset / 1000, 3),
                      "duration": round(s["durationMs"] / 1000, 3),
                      "name": s.get("rel", s["path"].name)})
        offset += s["durationMs"]
    proj = project.project_path(job.src)
    data.update(
        title=job.stem,
        kind=job.kind,
        media=media,
        projectFile=proj.relative_to(job.src).as_posix() if job.kind == "folder" else proj.name,
        exportCommand=f"cutroom export {json.dumps(str(job.src))}",
    )
    words = plan.words or []
    starts = [w["startMs"] for w in words]
    data["shorts"] = [short_data(job, s, words, starts) for s in job.data["shorts"]]
    data["style"] = job.data["style"]
    data["served"] = served
    data["pickups"] = job.data["pickups"]
    # every page needs the program: pickups and slates are placed on it
    data["program"] = [[*_secs(r), r[2]] for r in job.program]
    data["story"] = markdown(story_text(job))
    if job.kind == "folder":
        words = plan.words or []
        selects, raw = [], []
        for item in job.data["selects"]:
            span = project.segments(item, job.offsets)[0]
            raw.append(span)
            text = " ".join(w["word"] for w in words if span[0] <= w["startMs"] < span[1])
            keeps = [_secs(r) for r in job.item_segments(item)]
            selects.append({"id": item["id"], "chapter": item.get("chapter", ""), "title": item.get("title", ""),
                            "why": item.get("why", ""), "where": _where(item), "text": text, "keeps": keeps,
                            "beat": item.get("beat", ""), "role": item.get("role", ""),
                            "intent": item.get("intent", ""), "raw": bool(item.get("raw"))})
        data.update(
            keeps=[_secs(r) for r in job.program],
            keptSeconds=round(sum(r[1] - r[0] for r in job.program) / 1000, 3),
            chapters={str(i): title for i, title in job.chapters.items()},
            selects=selects,
            sentences=[x for x in data["sentences"]
                       if any(x["end"] * 1000 > a and x["start"] * 1000 < b for a, b in raw)],
            finalCuts=[],
            protectedRanges=[],
        )
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace("__TITLE__", html.escape(job.stem)).replace("__DATA__", payload)


def write_review(job, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(review_html(job), encoding="utf-8")
    print(f"wrote review page: {dst}")
    return dst


def feedback_path(job) -> Path:
    # where the served page's "Send to agent" writes the feedback
    if job.kind == "folder":
        return job.src / "cutroom" / "feedback.md"
    return job.src.with_suffix(".feedback.md")


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ - CutRoom review</title>
<style>
  :root {
    --bg: #f6f6f4; --panel: #ffffff; --ink: #1d1d1f; --muted: #6e6e73; --line: #e3e3e0;
    --keep: #34c759; --keep2: #248a3d; --cut: #c7c7cc; --retake: #ff453a; --manual: #ff9f0a; --rejected: #8e8e93;
    --protect: #0a84ff; --short: #5e5ce6; --accent: #0a84ff; --record: #0fa3a3;
    --button: #ffffff; --hover: #c8c8c4; --on-ink: #ffffff; --raw-ink: #b25000; --record-ink: #0b7a7a;
    color-scheme: light dark;
  }
  /* the page follows the device: dark when the system is dark */
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #141416; --panel: #1e1e21; --ink: #f2f2f4; --muted: #9b9ba1; --line: #333337;
      --keep: #30b350; --keep2: #1f7a35; --cut: #4a4a4e; --short: #8482ff; --record: #2cc4c4;
      --button: #2a2a2e; --hover: #4c4c52; --on-ink: #141416; --raw-ink: #ffb35c; --record-ink: #5fd4d4;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif; }
  header { display: flex; align-items: baseline; gap: 16px; padding: 18px 24px 10px; }
  header h1 { font-size: 18px; font-weight: 600; margin: 0; }
  header .stats { color: var(--muted); }
  main { display: grid; grid-template-columns: minmax(0, 1fr) 400px; gap: 16px; padding: 0 24px; }
  main.reading { grid-template-columns: minmax(0, 1fr) minmax(400px, 46%); }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; }
  .player { padding: 12px; align-self: start; }
  video, .audio-stage { width: 100%; aspect-ratio: 16 / 9; background: #000; border-radius: 8px; display: block; }
  .audio-stage { display: flex; align-items: center; justify-content: center; color: #aaa; text-align: center; padding: 24px; }
  .controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; }
  button { font: inherit; border: 1px solid var(--line); background: var(--button); color: var(--ink);
           border-radius: 8px; padding: 5px 11px; cursor: pointer; }
  button:hover { border-color: var(--hover); }
  button.on { background: var(--ink); color: var(--on-ink); border-color: var(--ink); }
  button.small { padding: 2px 8px; font-size: 12px; }
  .rates { display: inline-flex; }
  .rates button { border-radius: 0; margin-left: -1px; }
  .rates button:first-child { border-radius: 8px 0 0 8px; margin-left: 0; }
  .rates button:last-child { border-radius: 0 8px 8px 0; }
  #stage { position: relative; }
  .flash { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); padding: 10px 18px; font-size: 15px;
           border-radius: 999px; background: rgba(0, 0, 0, .62); color: #fff; font-weight: 600;
           font-variant-numeric: tabular-nums; pointer-events: none; opacity: 0; transition: opacity .35s; }
  .flash.show { opacity: 1; transition: none; }
  .slate { position: absolute; inset: 0; display: none; flex-direction: column; align-items: center; justify-content: center;
           gap: 8px; padding: 24px; border-radius: 8px; background: rgba(12, 14, 16, .9); color: #fff; text-align: center; }
  .slate.show { display: flex; }
  .slate .kind { font-size: 13px; font-weight: 600; color: #5fd4d4; }
  .slate .purpose { font-size: 18px; font-weight: 600; max-width: 82%; }
  .slate .more { font-size: 12px; color: #b9bcc0; }
  .keys { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 16px; color: var(--muted); font-size: 12px; margin-top: 8px; }
  .keys span { display: inline-flex; align-items: center; gap: 3px; }
  .keys span kbd:last-of-type { margin-right: 3px; }
  kbd { font-family: inherit; font-size: 11px; line-height: 16px; min-width: 18px; text-align: center; color: var(--ink); background: var(--button);
        border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 4px; padding: 0 4px; }
  .clock { flex: 1 1 340px; min-width: 0; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
           margin-left: auto; font-variant-numeric: tabular-nums; color: var(--muted); }
  .timeline { position: relative; height: 58px; margin-top: 12px; cursor: pointer; }
  .lane { position: absolute; left: 0; right: 0; border-radius: 4px; }
  .lane.base { top: 0; height: 22px; background: var(--keep); opacity: .85; }
  .lane.marks { top: 26px; height: 8px; }
  .lane.shorts { top: 38px; height: 18px; }
  .seg { position: absolute; top: 0; bottom: 0; }
  .seg.cut { background: var(--cut); }
  .seg.retake { background: var(--retake); }
  .seg.manual { background: var(--manual); }
  .seg.rejected { background: transparent; outline: 1.5px dashed var(--rejected); outline-offset: -1.5px; }
  .seg.protect { background: var(--protect); opacity: .55; }
  .seg.program { color: #fff; font-size: 10px; font-weight: 600; padding-left: 4px; line-height: 22px;
                 overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .seg.record { background: var(--record); border-radius: 2px; }
  .seg.record-id { color: var(--record); font-size: 10px; font-weight: 700; line-height: 1; overflow: visible; }
  .seg.select-line { width: 1px !important; top: auto; height: 5px; background: rgba(255, 255, 255, .85); }
  .chapter { margin: 16px 2px 2px; font-size: 12px; font-weight: 600; color: var(--muted);
             text-transform: none; letter-spacing: .01em; }
  .item.dropped { opacity: .5; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
  .chip { font-size: 11px; padding: 1px 7px; border-radius: 999px; background: var(--bg); color: var(--muted); }
  .chip.raw { background: rgba(255, 159, 10, .14); color: var(--raw-ink); }
  .intent { color: var(--muted); font-style: italic; }
  .item.pickup { border: 1.5px dashed var(--record); background: rgba(15, 163, 163, .05); }
  .item.pickup .id { color: var(--record); }
  .item.pickup ul { margin: 6px 0 0; padding-left: 18px; }
  .item.pickup li { margin: 2px 0; }
  .chip.record { background: rgba(15, 163, 163, .14); color: var(--record-ink); }
  .story { padding: 4px 6px 12px; }
  .story h3, .story h4, .story h5 { margin: 14px 0 6px; font-size: 14px; }
  .story h3 { font-size: 16px; }
  .story p { margin: 6px 0; }
  .story li { margin: 3px 0 3px 18px; }
  .story li.nested { margin-left: 36px; list-style: circle; }
  .story table { border-collapse: collapse; width: 100%; font-size: 12px; margin: 8px 0; }
  .story th, .story td { border: 1px solid var(--line); padding: 4px 6px; vertical-align: top; text-align: left; }
  .story td:first-child, .story td:last-child { white-space: nowrap; }
  .story code { font-size: 12px; background: var(--bg); padding: 0 4px; border-radius: 4px; }
  .seg.short { background: rgba(94, 92, 230, .14); border: 1px solid var(--short); border-radius: 4px;
               color: var(--short); font-size: 10px; font-weight: 600; padding-left: 3px; overflow: hidden; white-space: nowrap; }
  .playhead { position: absolute; top: -3px; height: 64px; width: 2px; background: var(--ink); pointer-events: none; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--muted); font-size: 12px; margin-top: 8px; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
  aside { display: flex; flex-direction: column; min-height: 0; max-height: calc(100vh - 150px); }
  .tabs { display: flex; gap: 4px; padding: 10px 10px 0; }
  .tabs { flex: none; flex-wrap: nowrap; overflow-x: auto; }
  .tabs button { border: none; background: none; color: var(--muted); padding: 6px 7px; white-space: nowrap; font-size: 12.5px; }
  .tabs button.on { background: var(--bg); color: var(--ink); border-radius: 8px; }
  .list { overflow-y: auto; padding: 8px 10px 12px; }
  .item { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; margin-top: 8px; }
  .item .top { display: flex; align-items: baseline; gap: 8px; }
  .id { font-weight: 700; }
  .tag { font-size: 11px; color: var(--muted); }
  .item p { margin: 6px 0 0; }
  .removed { color: var(--muted); text-decoration: line-through; }
  .actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .sentence { display: flex; gap: 10px; padding: 4px 6px; border-radius: 6px; cursor: pointer; }
  .sentence:hover { background: var(--bg); }
  .sentence time { color: var(--muted); font-variant-numeric: tabular-nums; flex: none; width: 46px; }
  .sentence.gone { color: var(--muted); text-decoration: line-through; }
  .empty { color: var(--muted); padding: 16px 4px; }
  footer { margin: 16px 24px 24px; padding: 12px; }
  footer .row { display: flex; align-items: center; gap: 10px; }
  footer textarea { width: 100%; height: 84px; margin-top: 8px; resize: vertical; border: 1px solid var(--line);
                    border-radius: 8px; padding: 8px; font: 12px/1.5 ui-monospace, Menlo, monospace; color: var(--ink); background: var(--bg); }
  /* shorts review: the list on the side sorts, groups and filters; the chosen short
     shows under the player with its words, checks and the decision buttons */
  .short-head { position: sticky; top: -8px; z-index: 2; background: var(--panel); margin: -8px -10px 0; padding: 10px 10px 6px;
                border-bottom: 1px solid var(--line); }
  .short-tools { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .short-tools select, .short-tools input { font: inherit; font-size: 12px; color: var(--ink); background: var(--button);
                                            border: 1px solid var(--line); border-radius: 8px; padding: 4px 7px; }
  .short-tools input[type=search] { flex: 1 1 100%; min-width: 0; }
  .short-tools label { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--muted); cursor: pointer; }
  .short-tools input[type=checkbox] { margin: 0; }
  .themes { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 7px; }
  .theme { --h: 220; display: inline-block; font-size: 11px; line-height: 17px; padding: 0 8px; border-radius: 999px; border: none;
           color: hsl(var(--h) 60% 34%); background: hsl(var(--h) 65% 50% / .13); white-space: nowrap; }
  button.theme { cursor: pointer; }
  button.theme.off { opacity: .38; }
  .tally { font-size: 11px; color: var(--muted); margin-top: 7px; }
  .row-short { display: grid; grid-template-columns: 4px minmax(0, 1fr) auto; gap: 10px; padding: 7px 8px 7px 0;
               border-radius: 8px; cursor: pointer; margin-top: 2px; }
  .row-short:hover { background: var(--bg); }
  .row-short.active { background: var(--bg); box-shadow: inset 0 0 0 1.5px var(--accent); }
  .row-short .bar { border-radius: 2px; background: var(--line); }
  .row-short.pick .bar { background: var(--keep); }
  .row-short.maybe .bar { background: var(--manual); }
  .row-short.reject .bar { background: var(--rejected); }
  .row-short.reject .name { color: var(--muted); text-decoration: line-through; }
  .row-short .name { font-weight: 600; font-size: 13px; line-height: 1.3; overflow: hidden;
                     display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .row-short .meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; margin-top: 3px; font-size: 11px; color: var(--muted); }
  .row-short .num { text-align: right; font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; line-height: 1.5; }
  .row-short .num b { display: block; font-size: 13px; color: var(--ink); }
  .warn { color: var(--raw-ink); }
  .detail { display: none; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--line); }
  body.shorts-tab .detail { display: block; }
  .detail .top { display: flex; align-items: baseline; gap: 8px; }
  .detail h2 { margin: 0; font-size: 17px; line-height: 1.3; }
  .detail .chips { margin-top: 8px; }
  .chip.warn { background: rgba(255, 159, 10, .14); color: var(--raw-ink); }
  .scores { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 8px; font-size: 12px; color: var(--muted); }
  .scores b { color: var(--ink); font-variant-numeric: tabular-nums; }
  .progress { height: 4px; margin-top: 10px; border-radius: 2px; background: var(--line); overflow: hidden; }
  .progress i { display: block; height: 100%; width: 0; background: var(--short); }
  .decide { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; }
  .decide .spacer { flex: 1; }
  .decide button kbd { margin-left: 5px; }
  .decide button.pick.on { background: var(--keep2); border-color: var(--keep2); color: #fff; }
  .decide button.maybe.on { background: var(--manual); border-color: var(--manual); color: #1d1d1f; }
  .decide button.reject.on { background: var(--rejected); border-color: var(--rejected); color: #fff; }
  .decide button.on kbd { background: transparent; color: inherit; border-color: currentColor; }
  .words { margin-top: 12px; font-size: 15px; line-height: 1.65; max-height: 300px; overflow-y: auto; }
  .words .piece + .piece::before { content: "/"; color: var(--muted); margin: 0 8px 0 4px; }
  .words .w { border-radius: 3px; cursor: pointer; }
  .words .w:hover { background: var(--bg); }
  .words .w.now { background: rgba(94, 92, 230, .22); }
  .detail textarea { width: 100%; height: 54px; margin-top: 10px; resize: vertical; border: 1px solid var(--line); border-radius: 8px;
                     padding: 7px 9px; font: inherit; font-size: 13px; color: var(--ink); background: var(--bg); }
  .seg.short.active { background: var(--short); color: #fff; }
  /* the shorts tab keeps the decision in view: a shorter player, no colour legend */
  @media (min-width: 701px) { body.shorts-tab video { width: auto; max-width: 100%; height: min(46vh, 560px); margin: 0 auto; } }
  body.shorts-tab .legend { display: none; }
  body.shorts-tab .timeline { height: 50px; margin-top: 10px; }
  .short-keys, #vertical { display: none !important; }
  body.shorts-tab .short-keys { display: inline-flex !important; }
  body.shorts-tab #vertical { display: inline-block !important; }
  /* a centre crop to 9:16, to see a short framed the way a phone shows it */
  body.shorts-tab #stage.vertical video { aspect-ratio: 9 / 16; width: auto; height: min(52vh, 640px); max-height: none; margin: 0 auto; object-fit: cover; }
  @media (prefers-color-scheme: dark) {
    .theme { color: hsl(var(--h) 75% 76%); background: hsl(var(--h) 55% 50% / .2); }
  }
  @media (max-width: 1000px) { main, main.reading { grid-template-columns: 1fr; } aside { max-height: none; } }
  #send, .summary { display: none; }
  body.served #send { display: inline-block; }
  #send:disabled { opacity: .45; cursor: default; border-color: var(--line); }
  /* phones: everything above is the desktop page; only narrow screens get this.
     the player stays on top while the list scrolls, the feedback bar on the bottom */
  @media (max-width: 700px) {
    header { flex-direction: column; gap: 2px; padding: 12px 14px 10px; }
    header h1 { font-size: 16px; }
    header .stats { font-size: 12px; }
    main, main.reading { padding: 0; gap: 10px; }
    .card { border-radius: 0; border-left: none; border-right: none; }
    .player { position: sticky; top: 0; z-index: 5; padding: 0 0 8px; border-top: none; }
    video, .audio-stage { border-radius: 0; }
    .controls { padding: 0 10px; gap: 6px; margin-top: 8px; }
    .controls button { min-height: 36px; padding: 5px 11px; }
    #back, #ahead { display: none; }
    .clock { flex-basis: 100%; order: 9; text-align: left; font-size: 12px; white-space: normal; overflow-wrap: anywhere; }
    .timeline { height: 44px; margin: 6px 10px 0; }
    .lane.base { height: 18px; }
    .lane.marks { top: 21px; height: 6px; }
    .lane.shorts { top: 29px; height: 15px; }
    .seg.program { line-height: 18px; font-size: 9px; }
    .seg.short { font-size: 9px; }
    .playhead { height: 48px; }
    .legend, .keys { display: none; }
    aside { max-height: none; }
    .tabs { padding: 8px 8px 0; }
    .tabs button { padding: 8px 9px; font-size: 13px; }
    .list { padding: 4px 10px 14px; }
    .item button.small { padding: 7px 12px; font-size: 13px; }
    footer { position: sticky; bottom: 0; z-index: 6; margin: 10px 0 0; border-radius: 0; border-left: none; border-right: none;
             padding: 10px 14px calc(10px + env(safe-area-inset-bottom)); }
    footer textarea, footer #hint, footer .row strong { display: none; }
    footer .summary { display: block; flex: 1; min-width: 0; font-size: 14px; font-weight: 600; }
    footer button { min-height: 38px; white-space: nowrap; }
    /* scrolling to an item keeps it clear of the player and the feedback bar */
    html { scroll-padding-top: var(--player-h, 0px); scroll-padding-bottom: 72px; }
    body.served footer #copy { display: none; }
  }
  /* phones: the player stays pinned on top, so the chosen short keeps only what
     a thumb needs there: its title, progress and the decision buttons */
  @media (max-width: 700px) {
    .detail { margin-top: 8px; padding: 8px 10px 0; }
    .detail h2 { font-size: 15px; }
    .detail .chips, .detail .scores, .detail p, .detail .words, .detail textarea { display: none; }
    .decide { margin-top: 8px; }
    .decide button { min-height: 38px; }
    .decide button kbd { display: none; }
  }
  @media (pointer: coarse) { #stage, button, .timeline { touch-action: manipulation; -webkit-tap-highlight-color: transparent; } }
</style>
</head>
<body>
<header>
  <h1 id="title"></h1>
  <span class="stats" id="stats"></span>
</header>
<main>
  <section class="card player">
    <div id="stage"></div>
    <div class="controls">
      <button id="mode-clean" class="on">Clean cut</button>
      <button id="mode-original">Original</button>
      <button id="toggle" title="Play or pause (Space or K)">Play</button>
      <button id="back" title="Back 5 s (←)">−5s</button>
      <button id="ahead" title="Forward 5 s (→)">+5s</button>
      <span class="rates" id="rates"></span>
      <button id="vertical" title="Preview a 9:16 centre crop (V)">9:16</button>
      <span class="clock" id="clock"></span>
    </div>
    <div class="timeline" id="timeline">
      <div class="lane base" id="lane-base"></div>
      <div class="lane marks" id="lane-marks"></div>
      <div class="lane shorts" id="lane-shorts"></div>
      <div class="playhead" id="playhead"></div>
    </div>
    <div class="legend" id="legend">
      <span><i style="background:var(--keep)"></i>kept</span>
      <span><i style="background:var(--cut)"></i>silence cut</span>
      <span><i style="background:var(--retake)"></i>retake cut</span>
      <span><i style="background:var(--manual)"></i>manual cut</span>
      <span><i style="outline:1.5px dashed var(--rejected)"></i>rejected</span>
      <span><i style="background:var(--protect)"></i>screen action kept</span>
      <span><i style="background:var(--short)"></i>short candidate</span>
    </div>
    <div class="keys"><span><kbd>Space</kbd>play</span><span><kbd>←</kbd><kbd>→</kbd>5 s</span>
      <span><kbd>J</kbd><kbd>L</kbd>10 s</span><span><kbd>&lt;</kbd><kbd>&gt;</kbd>speed</span>
      <span class="short-keys"><kbd>↑</kbd><kbd>↓</kbd>short</span><span class="short-keys"><kbd>P</kbd><kbd>M</kbd><kbd>X</kbd>pick, maybe, reject</span>
      <span class="short-keys"><kbd>R</kbd>replay</span><span class="short-keys"><kbd>N</kbd>note</span><span class="short-keys"><kbd>V</kbd>9:16</span></div>
    <div class="detail" id="detail"></div>
  </section>
  <aside class="card">
    <div class="tabs" id="tabs"></div>
    <div class="list" id="list"></div>
  </aside>
</main>
<footer class="card">
  <div class="row"><strong>Feedback for the agent</strong>
    <span class="tag" id="hint"></span>
    <span class="summary" id="summary"></span>
    <button id="copy" style="margin-left:auto">Copy</button>
    <button id="send" title="Saves the feedback in the project folder for the agent">Send to agent</button></div>
  <textarea id="feedback" readonly></textarea>
</footer>
<script type="application/json" id="data">__DATA__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const $ = (id) => document.getElementById(id);
const fmt = (t) => { t = Math.max(0, t); const m = Math.floor(t / 60), s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`; };
const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, "0")}`;
const hours = (t) => t >= 3600 ? `${(t / 3600).toFixed(1)} h` : fmt(t);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const spans = (r) => r.reduce((n, [s, e]) => n + (e - s), 0);
const FOLDER = D.kind === "folder";

// ---------- media: one element, one or more files on a single source timeline ----------
const isVideo = D.kind !== "screenstudio";
const el = document.createElement(isVideo ? "video" : "audio");
el.preload = "auto";
el.playsInline = true;
const stage = $("stage");
if (isVideo) stage.appendChild(el);
else {
  stage.innerHTML = `<div class="audio-stage">Audio preview of the microphone track.<br>
    Open the -clean.screenstudio project in Screen Studio to see the picture.</div>`;
  stage.appendChild(el);
}
let session = -1, pending = null;
// a play interrupted by the next seek or file is expected, not an error
const play = () => el.play().catch(() => {});
// one pending target, so the latest seek wins while a file is still loading
el.addEventListener("loadedmetadata", () => {
  if (!pending) return;
  const [local, go] = pending;
  pending = null;
  el.playbackRate = rate; el.currentTime = local;
  if (go) play();
});
function load(k, local, go) {
  if (k !== session) {
    session = k; pending = [local, go];
    el.src = D.media[k].uri;
    if (go) play();  // inside the tap that asked for it; the seek follows on loadedmetadata
  } else if (el.readyState < 1) {
    pending = [local, go];
  } else {
    el.currentTime = local;
    if (go) play();
  }
}
function seek(t, go) {
  endSlate();
  // offsets are rounded to the millisecond, so allow that much at file joins
  let k = D.media.findIndex((m) => t < m.offset + m.duration - 0.002);
  if (k < 0) k = D.media.length - 1;
  load(k, Math.max(0, t - D.media[k].offset), go);
}
const now = () => session < 0 ? 0 : D.media[session].offset + el.currentTime;
// one file per session or clip: when a file ends, carry on into the next one
// unless the current playlist range ends here anyway
el.addEventListener("ended", () => {
  if (session >= D.media.length - 1) return;
  const next = D.media[session + 1].offset, r = playlist && playlist[idx];
  if (!playlist || (r && r[1] > next)) load(session + 1, 0, true);
});

// ---------- the axis: source time for one file, program time for a folder's vlog ----------
const AX = FOLDER ? Math.max(spans(D.keeps), 0.001) : D.durationSeconds;
function axisOf(t) {
  if (!FOLDER) return t;
  let acc = 0;
  for (const [s, e] of D.keeps) { if (t >= s - 0.01 && t <= e + 0.01) return acc + Math.min(Math.max(t - s, 0), e - s); acc += e - s; }
  return null;
}
function spanOf(a, b) {
  // a source range -> [x0, x1] on the vlog axis, on the select where most of it
  // plays: the hook can replay a moment that plays again later in the vlog
  const groups = new Map();
  let acc = 0;
  D.program.forEach(([s, e, id]) => {
    const lo = Math.max(a, s), hi = Math.min(b, e);
    if (hi > lo) {
      const g = groups.get(id) || { overlap: 0, x0: Infinity, x1: -Infinity };
      g.overlap += hi - lo; g.x0 = Math.min(g.x0, acc + lo - s); g.x1 = Math.max(g.x1, acc + hi - s);
      groups.set(id, g);
    }
    acc += e - s;
  });
  let best = null;
  groups.forEach((g) => { if (!best || g.overlap > best.overlap) best = g; });
  return best && [best.x0, best.x1];
}
function programAt(x, list = D.keeps) {
  // axis position -> [range index, source time]
  let acc = 0;
  for (let i = 0; i < list.length; i++) {
    const [s, e] = list[i];
    if (x < acc + (e - s)) return [i, s + (x - acc)];
    acc += e - s;
  }
  return [list.length - 1, list[list.length - 1][1]];
}

// ---------- playback: a playlist of source ranges, or the plain original ----------
let playlist = null, idx = 0, mode = "clean";
function playRanges(ranges, label, marks = new Map()) {
  if (!ranges.length) return;
  playlist = ranges; idx = 0; slates = marks;
  if (slateAt(0).length) { seek(ranges[0][0], false); showSlate(slateAt(0)); } else seek(ranges[0][0], true);
  $("clock").dataset.label = label || "";
  $("mode-clean").classList.remove("on"); $("mode-original").classList.remove("on");
}
function setMode(m) {
  mode = m;
  $("mode-clean").classList.toggle("on", m === "clean");
  $("mode-original").classList.toggle("on", m === "original");
  playlist = m === "clean" ? D.keeps : null;
  slates = m === "clean" ? programSlates() : new Map();
  if (m === "clean" && !FOLDER) { idx = Math.max(0, D.keeps.findIndex(([, e]) => e > now())); }
}
function finishPlaylist() { el.pause(); if (playlist !== D.keeps) setMode("clean"); }
function tick() {
  if (slateUntil && performance.now() >= slateUntil) {
    endSlate();
    if (playlist && idx < playlist.length) seek(playlist[idx][0], true); else if (playlist) finishPlaylist();
  }
  // while a file loads its time is not ours yet: never correct the playlist against it
  if (playlist && !el.paused && !el.seeking && !pending) {
    const t = now(), r = playlist[idx];
    if (r && t >= r[1] - 0.02) {
      idx += 1;
      if (slateAt(idx).length) showSlate(slateAt(idx));
      else if (idx >= playlist.length) finishPlaylist();
      else seek(playlist[idx][0], true);
    } else if (r && (t < r[0] - 0.3 || t > r[1] + 0.3)) {
      seek(r[0], true);
    }
  }
  const t = now();
  const inProgram = mode === "clean" && playlist === D.keeps;
  const x = inProgram ? spans(D.keeps.slice(0, idx)) + Math.max(0, t - (D.keeps[idx] || [t])[0]) : axisOf(t);
  $("playhead").style.display = x === null ? "none" : "block";
  if (x !== null) $("playhead").style.left = `${(x / AX) * 100}%`;
  // the file name alone fits the control row; the tooltip has the full path
  const file = FOLDER && session >= 0 ? `${D.media[session].name.split("/").pop()} ${fmt(el.currentTime)}` : `source ${fmt(t)} / ${fmt(D.durationSeconds)}`;
  let clock = file;
  if (inProgram) clock = `${NOVLOG ? "all footage, pauses removed" : FOLDER ? PROGRAM.toLowerCase() : "clean"} ${fmt(x)} / ${fmt(D.keptSeconds)}  ·  ${clock}`;
  else if (playlist && playlist !== D.keeps) clock = `${$("clock").dataset.label}  ·  ${clock}`;
  if ($("clock").textContent !== clock) {
    $("clock").textContent = clock;
    $("clock").title = FOLDER && session >= 0 ? `${clock}\n${D.media[session].name}` : clock;
  }
  $("toggle").textContent = el.paused ? "Play" : "Pause";
  if (tab === "shorts") tickShort();
  requestAnimationFrame(tick);
}

// before selects exist a folder has no vlog yet: the player shows all footage.
// a talking head recorded in several files is a folder too: its selects are an edit
const NOVLOG = FOLDER && !D.selects.length;
const VLOG = D.style === "vlog";
const PROGRAM = !FOLDER ? "Clean cut" : NOVLOG ? "All footage" : VLOG ? "Vlog" : "Edit";
$("mode-clean").textContent = PROGRAM;
$("mode-clean").onclick = () => setMode("clean");
$("mode-original").onclick = () => setMode("original");
$("toggle").onclick = () => {
  if (slateUntil) { endSlate(); return idx < playlist.length ? seek(playlist[idx][0], true) : finishPlaylist(); }
  if (!el.paused) return el.pause();
  if (session < 0 && mode === "clean" && slateAt(0).length) { idx = 0; seek(D.keeps[0][0], false); showSlate(slateAt(0)); }
  else if (session < 0) seek(mode === "clean" ? D.keeps[0][0] : 0, true); else play();
};
$("timeline").onclick = (ev) => {
  const box = $("timeline").getBoundingClientRect();
  const x = ((ev.clientX - box.left) / box.width) * AX;
  if (FOLDER) { const [i, t] = programAt(x); setMode("clean"); idx = i; seek(t, true); }
  else { setMode("original"); seek(x, true); }
};

// ---------- skipping and speed, with youtube's keys ----------
const RATES = [1, 1.5, 2];
let rate = 1, flashTimer = 0;
try { if (RATES.includes(+localStorage.cutroomRate)) rate = +localStorage.cutroomRate; } catch (e) {}
const flashEl = document.createElement("div");
flashEl.className = "flash";
stage.appendChild(flashEl);

// ---------- talking heads to record: a slate where each one will play ----------
const PICKUPS = D.pickups || [];
const AFTER = {};
PICKUPS.forEach((p) => { if (p.after) (AFTER[p.after] = AFTER[p.after] || []).push(p); });
const placed = (p) => p.after === "start" || (p.after && D.selects.some((s) => s.id === p.after));
// a suggestion not placed after a select yet can still point at the raw footage
const nearTime = (p) => {
  if (placed(p) || !p.near) return null;
  const m = p.near.clip ? D.media.find((x) => x.name === p.near.clip) : D.media[0];
  return m ? m.offset + p.near.time : null;
};
const pickupKind = (p) => p.kind === "voiceover" ? "Voiceover to record" : "Talking head to record";
const slateEl = document.createElement("div");
slateEl.className = "slate";
stage.appendChild(slateEl);
const SLATE_SECONDS = 3;
let slateUntil = 0, slates = new Map();
function showSlate(list) {
  el.pause();
  const p = list[0], secs = list.reduce((n, x) => n + (x.seconds || 20), 0);
  slateEl.innerHTML = `<div class="kind">${list.map((x) => x.id).join(" + ")}  ·  ${pickupKind(p)}  ·  about ${secs} s</div>
    <div class="purpose">${esc(p.purpose)}</div>
    ${list.length > 1 ? `<div class="more">and ${list.length - 1} more here</div>` : ""}
    <div class="more">not recorded yet: the cut carries on in ${SLATE_SECONDS} s</div>`;
  slateEl.classList.add("show");
  slateUntil = performance.now() + SLATE_SECONDS * 1000;
}
function endSlate() { slateUntil = 0; slateEl.classList.remove("show"); }
// the pickups still wanted at a playlist position (dropped ones no longer play)
const slateAt = (i) => (slates.get(i) || []).filter((p) => !dropped.has(p.id));
function programSlates() {
  // position i = before range i of the program; program.length = after the last one
  const m = new Map();
  if (NOVLOG) return m;
  if (AFTER.start) m.set(0, AFTER.start);
  D.program.forEach(([, , id], i) => {
    const next = D.program[i + 1];
    if (AFTER[id] && (!next || next[2] !== id)) m.set(i + 1, AFTER[id]);
  });
  return m;
}
function flash(text) {
  flashEl.textContent = text; flashEl.classList.add("show");
  clearTimeout(flashTimer); flashTimer = setTimeout(() => flashEl.classList.remove("show"), 450);
}
function setRate(r, quiet) {
  rate = r; el.defaultPlaybackRate = r; el.playbackRate = r;
  try { localStorage.cutroomRate = r; } catch (e) {}
  document.querySelectorAll("[data-rate]").forEach((b) => b.classList.toggle("on", +b.dataset.rate === r));
  if (!quiet) flash(`${r}x`);
}
function skip(dt) {
  const go = !el.paused;
  flash(dt < 0 ? `−${-dt}s` : `+${dt}s`);
  if (!playlist) return seek(Math.min(Math.max(0, now() + dt), D.durationSeconds - 0.05), go);
  // inside a playlist, skip along what plays: removed ranges never count
  const i = Math.min(idx, playlist.length - 1), [s, e] = playlist[i];
  const x = spans(playlist.slice(0, i)) + Math.min(Math.max(0, now() - s), e - s);
  const [j, t] = programAt(Math.min(Math.max(0, x + dt), spans(playlist) - 0.05), playlist);
  idx = j; seek(t, go);
}
$("rates").innerHTML = RATES.map((r) => `<button data-rate="${r}" title="Speed ${r}x (&lt; &gt;)">${r}x</button>`).join("");
$("rates").onclick = (ev) => { const b = ev.target.closest("[data-rate]"); if (b) setRate(+b.dataset.rate); };
$("back").onclick = () => skip(-5);
$("ahead").onclick = () => skip(5);
setRate(rate, true);
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && ev.target.closest("textarea, input")) return ev.target.blur();
  if (ev.metaKey || ev.ctrlKey || ev.altKey || ev.target.closest("textarea, input, select")) return;
  const k = ev.key.length === 1 ? ev.key.toLowerCase() : ev.key, at = RATES.indexOf(rate);
  const onShorts = tab === "shorts" && SHORTS.length;
  if (onShorts && (k === "ArrowDown" || k === "ArrowUp")) step(k === "ArrowDown" ? 1 : -1);
  else if (onShorts && current && (k === "p" || k === "m" || k === "x")) decide({ p: "pick", m: "maybe", x: "reject" }[k]);
  else if (onShorts && current && (k === "r" || k === "Enter")) playShort(shortById(current));
  else if (onShorts && current && k === "n") $("short-note").focus();
  else if (onShorts && k === "v") $("vertical").click();
  else if (k === " " || k === "k") $("toggle").click();
  else if (k === "ArrowLeft") skip(-5);
  else if (k === "ArrowRight") skip(5);
  else if (k === "j") skip(-10);
  else if (k === "l") skip(10);
  else if (k === "<" || k === ">") setRate(RATES[Math.min(Math.max(0, at + (k === ">" ? 1 : -1)), RATES.length - 1)]);
  else return;
  ev.preventDefault();
  // a focused button would also take the space bar on key up
  if (document.activeElement && document.activeElement.tagName === "BUTTON") document.activeElement.blur();
});

// touch screens: tap the video to play or pause, double tap a side to skip 10 s
if (matchMedia("(pointer: coarse)").matches) {
  let lastTap = 0, tapTimer = 0;
  stage.addEventListener("click", (ev) => {
    const box = stage.getBoundingClientRect(), x = (ev.clientX - box.left) / box.width, t = performance.now();
    clearTimeout(tapTimer);
    if (t - lastTap < 300 && (x < 0.35 || x > 0.65)) {
      skip(x < 0.35 ? -10 : 10);
      lastTap = t;  // keep tapping the same side to skip again
      return;
    }
    lastTap = t;
    tapTimer = setTimeout(() => $("toggle").click(), 300);
  });
}

// ---------- timeline ----------
const rejected = new Set(), dropped = new Set();
let current = null, tab = null;  // the short being reviewed, the open tab
const pct = (x) => `${(x / AX) * 100}%`;
function seg(lane, s, e, cls, text, style) {
  const d = document.createElement("div");
  d.className = `seg ${cls}`; d.style.left = pct(s); d.style.width = `calc(${pct(e - s)} + 1px)`;
  if (style) Object.assign(d.style, style);
  if (text) { d.textContent = text; d.title = text; }
  $(lane).appendChild(d);
}
function drawCuts() {
  $("lane-base").innerHTML = "";
  if (FOLDER) {
    // one block per chapter with its name, a thin line where each select starts,
    // dropped selects greyed out on top
    let acc = 0, start = 0, title = null, n = 0;
    const blocks = [], lines = [], gone = [];
    D.program.forEach(([s, e, id], i) => {
      if (D.chapters[i] !== undefined) {
        if (title !== null || i > 0) blocks.push([start, acc, title ?? ""]);
        start = acc; title = D.chapters[i];
      }
      if (i > 0 && D.program[i - 1][2] !== id) lines.push(acc);
      if (dropped.has(id)) gone.push([acc, acc + (e - s)]);
      acc += e - s;
    });
    blocks.push([start, acc, title ?? ""]);
    blocks.forEach(([a, b, t]) => seg("lane-base", a, b, "program", t, { background: n++ % 2 ? "var(--keep2)" : "var(--keep)" }));
    gone.forEach(([a, b]) => seg("lane-base", a, b, "cut"));
    lines.forEach((x) => seg("lane-base", x, x, "select-line"));
    return;
  }
  D.finalCuts.forEach(([s, e]) => seg("lane-base", s, e, "cut"));
  D.decisions.forEach((d) => seg("lane-base", d.start, d.end,
    d.status === "cut" && !rejected.has(d.id) ? (d.reason === "manual" ? "manual" : "retake") : "rejected"));
}
function drawMarks() {
  $("lane-marks").innerHTML = "";
  if (FOLDER) {
    // a tick where each retake or manual cut was taken out of the vlog
    D.decisions.forEach((d) => {
      let x = null;
      for (const t of [d.end, d.start]) { x = axisOf(t); if (x !== null) break; }
      if (x !== null) seg("lane-marks", x, x + AX / 600, rejected.has(d.id) || d.status !== "cut" ? "rejected" : (d.reason === "manual" ? "manual" : "retake"));
    });
    // a mark where each talking head to record will play
    let acc = 0;
    const ends = {};
    D.program.forEach(([s, e, id]) => { acc += e - s; ends[id] = acc; });
    const footageAxis = (t) => {
      // a time inside a removed pause lands where the footage carries on
      let a = 0;
      for (const [s, e] of D.keeps) { if (t <= e) return a + Math.max(0, t - s); a += e - s; }
      return a;
    };
    PICKUPS.filter((p) => !dropped.has(p.id) && (placed(p) || nearTime(p) !== null)).forEach((p) => {
      const x = placed(p) ? (p.after === "start" ? 0 : ends[p.after]) : footageAxis(nearTime(p));
      // a bar through the chapters where the talking head goes in
      if (x !== undefined) {
        seg("lane-marks", x, x, "record", "", { width: "3px", marginLeft: "-1.5px", top: "-28px", bottom: "-2px" });
        // the label sits right of the bar, or left of it near the end of the timeline
        seg("lane-marks", x, x, "record-id", p.id, { width: "auto", marginLeft: x > AX * 0.96 ? "-18px" : "3px", top: "-1px", bottom: "auto" });
      }
    });
  } else {
    D.protectedRanges.forEach(([s, e]) => seg("lane-marks", s, e, "protect"));
  }
}
function drawShorts() {
  $("lane-shorts").innerHTML = "";
  D.shorts.forEach((s) => {
    const cls = s.id === current ? "short active" : "short";
    if (!FOLDER) return seg("lane-shorts", s.keeps.length ? s.keeps[0][0] : 0, s.keeps.length ? s.keeps.at(-1)[1] : 0, cls, s.id);
    // one mark per piece, so a short made of distant moments does not look like one
    // long stretch; the id goes on the widest piece, where it has room to read
    const spans = s.keeps.map(([a, b]) => spanOf(a, b)).filter(Boolean);
    const widest = spans.reduce((w, x) => (x[1] - x[0] > w[1] - w[0] ? x : w), spans[0]);
    spans.forEach((x) => seg("lane-shorts", x[0], Math.max(x[1], x[0] + AX / 300), cls, x === widest ? s.id : ""));
  });
}
drawCuts(); drawMarks(); drawShorts();

// ---------- feedback ----------
function feedback() {
  const lines = [];
  const droppedSelects = [...dropped].filter((id) => id[0] === "V"), droppedPickups = [...dropped].filter((id) => id[0] === "P");
  if (droppedSelects.length) lines.push(`Remove ${droppedSelects.join(", ")} from selects in ${D.projectFile}.`);
  if (droppedPickups.length) lines.push(`Remove ${droppedPickups.join(", ")} from pickups in ${D.projectFile}: no talking head there.`);
  if (rejected.size) {
    lines.push(`Reject ${[...rejected].join(", ")} in ${D.projectFile}. Add to edits.keeps:`);
    D.decisions.filter((d) => rejected.has(d.id)).forEach((d) => lines.push(`  ${keepEntry(d)}`));
  }
  const picks = shortsWith("pick"), maybes = shortsWith("maybe"), nos = shortsWith("reject");
  if (picks.length) {
    lines.push(`Export ${picks.join(", ")}:`);
    lines.push(`  ${D.exportCommand} ${picks.join(" ")}`);
  }
  if (maybes.length) lines.push(`Maybe ${maybes.join(", ")}: keep them in shorts, not ready to export yet.`);
  if (nos.length) lines.push(`Remove ${nos.join(", ")} from shorts in ${D.projectFile}.`);
  const noted = SHORTS.filter((s) => noteOf(s.id));
  if (noted.length) {
    lines.push("Notes on shorts:");
    noted.forEach((s) => lines.push(`  ${s.id} (${s.title || "untitled"}): ${noteOf(s.id)}`));
  }
  $("feedback").value = lines.join("\n") || "Nothing selected yet.";
  const n = dropped.size + rejected.size + SHORTS.filter((s) => statusOf(s.id) !== "review" || noteOf(s.id)).length;
  $("summary").textContent = n ? `${n} change${n > 1 ? "s" : ""} for the agent` : "No changes yet";
  $("send").disabled = !n;
}
function keepEntry(d) {
  if (!FOLDER) return `[${d.start}, ${d.end}, "reject ${d.id}"]`;
  const k = D.media.findIndex((m) => d.start < m.offset + m.duration - 0.002);
  const m = D.media[Math.max(0, k)];
  return `{"clip": "${m.name}", "start": ${(d.start - m.offset).toFixed(3)}, "end": ${(d.end - m.offset).toFixed(3)}, "note": "reject ${d.id}"}`;
}
$("copy").onclick = async () => {
  const box = $("feedback");
  try { await navigator.clipboard.writeText(box.value); }
  catch { box.select(); document.execCommand("copy"); }
  $("copy").textContent = "Copied"; setTimeout(() => ($("copy").textContent = "Copy"), 1200);
};
// served on the local network (cutroom review --serve): the feedback goes to a
// file the agent reads, since a phone has no clipboard shared with the computer
if (D.served) document.body.classList.add("served");
// the phone layout keeps the player on top: scrolling needs its height
new ResizeObserver(([e]) => document.documentElement.style.setProperty("--player-h", `${Math.ceil(e.target.offsetHeight)}px`))
  .observe(document.querySelector(".player"));
$("send").onclick = async () => {
  const b = $("send");
  try {
    const r = await fetch("feedback", { method: "POST", body: $("feedback").value });
    if (!r.ok) throw new Error(await r.text());
    b.textContent = "Sent"; $("summary").textContent = "saved: tell the agent to read it";
  } catch (e) { b.textContent = "Not sent"; }
  setTimeout(() => (b.textContent = "Send to agent"), 2000);
};

// ---------- side lists ----------
function pickupCard(p) {
  const off = dropped.has(p.id);
  const near = nearTime(p) !== null ? `near ${p.near.clip ? `${esc(p.near.clip)} ` : ""}${fmt(p.near.time)}` : "";
  const where = p.after === "start" ? "at the start" : placed(p) ? `after ${p.after}` : near || "suggested by the story, not placed yet";
  return `
    <div class="item pickup ${off ? "dropped" : ""}">
      <div class="top"><span class="id">${p.id}</span><strong>${pickupKind(p)}</strong></div>
      <div class="tag">about ${p.seconds || 20} s  ·  ${where}</div>
      ${p.chapter || p.beat ? `<div class="chips">${[p.chapter, p.beat].filter(Boolean).map((t) => `<span class="chip record">${esc(t)}</span>`).join("")}</div>` : ""}
      <p>${esc(p.purpose)}</p>
      ${p.points && p.points.length ? `<ul>${p.points.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      ${p.draft ? `<p class="intent">Draft, say it your way: "${esc(p.draft)}"</p>` : ""}
      <div class="actions">
        ${(FOLDER && placed(p) && !NOVLOG) || nearTime(p) !== null ? `<button class="small" data-lead-in="${p.id}">Play where it goes</button>` : ""}
        <button class="small ${off ? "on" : ""}" data-drop="${p.id}">${off ? "Dropped" : "Drop"}</button>
      </div>
    </div>`;
}
function recordView() {
  // the shot list: placed talking heads in play order, then the suggestions not placed yet
  const order = (p) => p.after === "start" ? -1 : placed(p) ? D.selects.findIndex((s) => s.id === p.after)
    : nearTime(p) !== null ? 1e6 + nearTime(p) : 1e9;
  return [...PICKUPS].sort((a, b) => order(a) - order(b)).map(pickupCard).join("")
    + `<p class="tag" style="margin-top:12px">Record these in one sitting, put the files in the folder, and tell the agent:
       each recording becomes a select in its place and the pickup is removed.</p>`;
}
function leadIn(p) {
  // the last seconds before the talking head, its slate, the first seconds after it
  const t = nearTime(p);
  if (t !== null) {
    mode = "check";
    return playRanges([[Math.max(0, t - 6), t], [t, Math.min(D.durationSeconds, t + 4)]], `${p.id} near here`, new Map([[1, [p]]]));
  }
  const at = p.after === "start" ? 0 : D.program.findLastIndex(([, , id]) => id === p.after) + 1;
  const before = at > 0 ? [[Math.max(D.program[at - 1][0], D.program[at - 1][1] - 6), D.program[at - 1][1]]] : [];
  const after = at < D.program.length ? [[D.program[at][0], Math.min(D.program[at][1], D.program[at][0] + 4)]] : [];
  mode = "check";
  playRanges([...before, ...after], `${p.id} in place`, new Map([[before.length, [p]]]));
}
function vlogView() {
  if (!D.selects.length) return `<div class="empty">No selects yet: the player plays the whole clean footage.
    Ask the agent to choose moments; they are stored under "selects" in ${esc(D.projectFile)}.</div>`;
  let last = null;
  return (AFTER.start || []).map(pickupCard).join("") + D.selects.map((s) => {
    const head = s.chapter && s.chapter !== last ? `<div class="chapter">${esc(s.chapter)}</div>` : "";
    last = s.chapter || last;
    const off = dropped.has(s.id);
    return `${head}
    <div class="item ${off ? "dropped" : ""}">
      <div class="top"><span class="id">${s.id}</span>${s.title ? `<strong>${esc(s.title)}</strong>` : ""}</div>
      <div class="tag">${esc(s.where)}  ·  ${fmt(spans(s.keeps))} in the ${PROGRAM.toLowerCase()}</div>
      ${s.beat || s.role || s.raw ? `<div class="chips">${[s.beat, s.role !== s.beat ? s.role : ""].filter(Boolean).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}${s.raw ? `<span class="chip raw" title="plays as it happened: no silence or retake cuts inside">raw</span>` : ""}</div>` : ""}
      ${s.intent ? `<p class="intent">${esc(s.intent)}</p>` : ""}
      ${s.text ? `<p>${esc(s.text)}</p>` : ""}
      ${s.why ? `<p class="tag">${esc(s.why)}</p>` : ""}
      <div class="actions">
        <button class="small" data-play-select="${s.id}">Play</button>
        <button class="small ${off ? "on" : ""}" data-drop="${s.id}">${off ? "Dropped" : "Drop"}</button>
      </div>
    </div>${(AFTER[s.id] || []).map(pickupCard).join("")}`; }).join("");
}
// ---------- shorts: review many candidates fast ----------
// the list sorts by priority (rank), quality (score), length or recording order,
// groups by theme and filters by status, theme and words. a decision (pick,
// maybe, reject) and a note per short live in this browser, so a reload keeps
// the review; they are matched by id and title, so a renumbered short starts fresh
const mean = (xs) => xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
const SHORTS = D.shorts.map((s, i) => ({ ...s, order: i, start: s.keeps.length ? s.keeps[0][0] : 0,
  quality: typeof s.score === "number" ? s.score : mean(Object.values(s.scores || {})),
  text: (s.pieces || []).map((p) => p.map((w) => w[1]).join(" ")).join(" / ") }));
const shortById = (id) => SHORTS.find((s) => s.id === id);
const THEMES = [...new Set(SHORTS.map((s) => s.theme).filter(Boolean))].sort();
// the golden angle keeps neighbouring themes far apart on the colour wheel
const themeChip = (name, tag = "span", off = false) => name
  ? `<${tag} class="theme ${off ? "off" : ""}" style="--h:${Math.round((THEMES.indexOf(name) * 137.5 + 220) % 360)}"
      ${tag === "button" ? `data-theme="${esc(name)}"` : ""}>${esc(name)}</${tag}>` : "";
const STORE = `cutroom-shorts ${D.exportCommand}`;
const verdicts = {};
const read = (key, fallback) => { try { return JSON.parse(localStorage[key] || "null") || fallback; } catch (e) { return fallback; } };
Object.entries(read(STORE, {})).forEach(([id, v]) => { const s = shortById(id); if (s && v.title === (s.title || "")) verdicts[id] = v; });
function saveVerdicts() {
  try { localStorage[STORE] = JSON.stringify(verdicts); } catch (e) {}
}
const statusOf = (id) => (verdicts[id] && verdicts[id].status) || "review";
const noteOf = (id) => ((verdicts[id] && verdicts[id].note) || "").trim();
const shortsWith = (status) => SHORTS.filter((s) => statusOf(s.id) === status).map((s) => s.id);
function setVerdict(id, change) {
  verdicts[id] = { status: "review", note: "", ...verdicts[id], ...change, title: shortById(id).title || "" };
  saveVerdicts();
}
const STATUS = { all: "All", review: "To review", pick: "Picked", maybe: "Maybe", reject: "Rejected" };
const last = (x) => x ?? Infinity;
const SORTS = {
  priority: ["Priority", (a, b) => last(a.rank) - last(b.rank) || last(-a.quality) - last(-b.quality) || a.order - b.order],
  quality: ["Quality", (a, b) => last(-a.quality) - last(-b.quality) || last(a.rank) - last(b.rank) || a.order - b.order],
  shortest: ["Shortest first", (a, b) => a.seconds - b.seconds || a.order - b.order],
  recorded: ["Recording order", (a, b) => a.start - b.start || a.order - b.order],
  project: ["Project file order", (a, b) => a.order - b.order],
};
const view = { sort: "priority", group: false, status: "all", ...read("cutroom-shorts-view", {}), themes: new Set(), query: "" };
if (!SORTS[view.sort]) view.sort = "priority";
function visibleShorts() {
  const q = view.query.trim().toLowerCase();
  const list = SHORTS.filter((s) => (view.status === "all" || statusOf(s.id) === view.status)
    && (!view.themes.size || view.themes.has(s.theme))
    && (!q || [s.id, s.title, s.theme, s.text, ...(s.tags || [])].join(" ").toLowerCase().includes(q)))
    .sort(SORTS[view.sort][1]);
  if (!view.group) return list;
  // themes in the order their best short comes in, the shorts inside in the chosen order
  const groups = [...new Set(list.map((s) => s.theme || ""))];
  return list.sort((a, b) => groups.indexOf(a.theme || "") - groups.indexOf(b.theme || ""));
}
function shortsView() {
  if (!SHORTS.length) return `<div class="empty">No short candidates yet. Ask the agent to propose some;
    they are stored under "shorts" in ${esc(D.projectFile)}.</div>`;
  return `<div class="short-head">
      <div class="short-tools">
        <input type="search" id="short-query" placeholder="Search titles, themes and words" value="${esc(view.query)}">
        <select id="short-sort" title="Sort">${Object.entries(SORTS).map(([k, [label]]) =>
          `<option value="${k}" ${k === view.sort ? "selected" : ""}>${label}</option>`).join("")}</select>
        <select id="short-status" title="Show">${Object.entries(STATUS).map(([k, label]) =>
          `<option value="${k}" ${k === view.status ? "selected" : ""}>${label}</option>`).join("")}</select>
        ${THEMES.length ? `<label><input type="checkbox" id="short-group" ${view.group ? "checked" : ""}>Group by theme</label>` : ""}
      </div>
      ${THEMES.length ? `<div class="themes" id="short-themes"></div>` : ""}
      <div class="tally" id="short-tally"></div>
    </div>
    <div id="short-rows"></div>`;
}
function mountShorts() {
  if (!SHORTS.length) return;
  const keep = () => { try { localStorage["cutroom-shorts-view"] = JSON.stringify({ sort: view.sort, group: view.group, status: view.status }); } catch (e) {} };
  $("short-query").oninput = (ev) => { view.query = ev.target.value; renderRows(); };
  $("short-sort").onchange = (ev) => { view.sort = ev.target.value; keep(); renderRows(); };
  $("short-status").onchange = (ev) => { view.status = ev.target.value; keep(); renderRows(); };
  if ($("short-group")) $("short-group").onchange = (ev) => { view.group = ev.target.checked; keep(); renderRows(); };
  if ($("short-themes")) $("short-themes").onclick = (ev) => {
    const b = ev.target.closest("[data-theme]");
    if (!b) return;
    view.themes.has(b.dataset.theme) ? view.themes.delete(b.dataset.theme) : view.themes.add(b.dataset.theme);
    renderRows();
  };
  $("short-rows").onclick = (ev) => { const r = ev.target.closest("[data-short]"); if (r) chooseShort(r.dataset.short, true); };
  renderRows();
}
function renderRows() {
  if (!$("short-rows")) return;
  const list = visibleShorts();
  if ($("short-themes")) $("short-themes").innerHTML = THEMES.map((name) =>
    themeChip(name, "button", view.themes.size && !view.themes.has(name))).join("");
  const n = (st) => shortsWith(st).length;
  $("short-tally").textContent = `${SHORTS.length} shorts  ·  ${n("pick")} picked  ·  ${n("maybe")} maybe  ·  ${n("reject")} rejected  ·  `
    + `${SHORTS.length - n("pick") - n("maybe") - n("reject")} to review` + (list.length < SHORTS.length ? `  ·  showing ${list.length}` : "");
  let group = null;
  $("short-rows").innerHTML = list.map((s) => {
    const head = view.group && (s.theme || "") !== group
      ? `<div class="chapter">${esc(s.theme || "No theme")}  ·  ${list.filter((x) => (x.theme || "") === (s.theme || "")).length}</div>` : "";
    group = s.theme || "";
    const q = s.quality === null ? "" : `<b title="score">${+s.quality.toFixed(1)}</b>`;
    return `${head}<div class="row-short ${statusOf(s.id)} ${s.id === current ? "active" : ""}" data-short="${s.id}">
      <i class="bar"></i>
      <div><div class="name">${esc(s.title || s.id)}</div>
        <div class="meta"><span class="id">${s.id}</span>${s.rank ? `<span>#${s.rank}</span>` : ""}${themeChip(s.theme)}
          ${s.flags.length ? `<span class="warn" title="${esc(s.flags.join("\n"))}">${s.flags.length} to check</span>` : ""}
          ${noteOf(s.id) ? `<span title="${esc(noteOf(s.id))}">note</span>` : ""}</div></div>
      <div class="num">${q}${mmss(s.seconds)}</div>
    </div>`;
  }).join("") || `<div class="empty">No shorts match. Clear the search or the filters.</div>`;
}
function renderDetail() {
  const s = current && shortById(current);
  if (!s) {
    $("detail").innerHTML = SHORTS.length ? `<div class="empty">Choose a short in the list, or press ↓ to start with the first one.</div>` : "";
    return;
  }
  const st = statusOf(s.id), scores = Object.entries(s.scores || {});
  const btn = (k, label, key) => `<button class="${k} ${st === k ? "on" : ""}" data-verdict="${k}">${label}<kbd>${key}</kbd></button>`;
  $("detail").innerHTML = `
    <div class="top"><span class="id">${s.id}</span><h2>${esc(s.title || "Untitled")}</h2></div>
    <div class="tag">${esc(s.where)}  ·  ${fmt(s.seconds)} clean  ·  ${s.keeps.length} ${s.keeps.length === 1 ? "range" : "ranges"}`
      + `${s.rank ? `  ·  priority ${s.rank}` : ""}${s.quality !== null ? `  ·  score ${+s.quality.toFixed(1)}` : ""}</div>
    <div class="progress"><i id="short-bar"></i></div>
    <div class="decide">
      <button data-replay title="Play from the start (R)">Play</button>
      ${btn("pick", "Pick", "P")}${btn("maybe", "Maybe", "M")}${btn("reject", "Reject", "X")}
      <span class="spacer"></span><span class="tag" id="short-clock">${fmt(s.seconds)}</span>
    </div>
    <div class="chips">${themeChip(s.theme)}${(s.tags || []).map((x) => `<span class="chip">${esc(x)}</span>`).join("")}
      ${s.flags.map((f) => `<span class="chip warn" title="check the edge: a short has to make sense with no context">${esc(f)}</span>`).join("")}</div>
    ${scores.length ? `<div class="scores">${scores.map(([k, v]) => `<span>${esc(k)} <b>${v}</b></span>`).join("")}</div>` : ""}
    ${s.why ? `<p>${esc(s.why)}</p>` : ""}
    <div class="words" id="short-words">${(s.pieces || []).map((p) => `<span class="piece">${p.map(([t0, w]) =>
      `<span class="w" data-at="${t0}">${esc(w)}</span>`).join(" ")}</span>`).join("")}</div>
    <textarea id="short-note" placeholder="Note for the agent, for example: start 2 s later, end on the laugh (N)">${esc(noteOf(s.id))}</textarea>`;
  wordEls = [...$("detail").querySelectorAll(".w")];
  lit = -1;
  $("short-note").oninput = (ev) => { setVerdict(s.id, { note: ev.target.value }); feedback(); };
  $("short-note").onchange = () => renderRows();
}
$("detail").onclick = (ev) => {
  const s = current && shortById(current);
  if (!s) return;
  const b = ev.target.closest("[data-verdict],[data-replay],[data-at]");
  if (!b) return;
  if (b.dataset.verdict) decide(b.dataset.verdict);
  else if (b.dataset.replay !== undefined) playShort(s);
  else {
    // a word plays the short from there
    const at = +b.dataset.at, i = Math.max(0, s.keeps.findIndex(([, e]) => e > at));
    if (playlist !== s.keeps) playShort(s);
    idx = i; seek(at, true);
  }
};
let wordEls = [], lit = -1;
function playShort(s) { mode = "short"; playRanges(s.keeps, `${s.id} ${s.title || ""}`); }
function chooseShort(id, go) {
  current = id;
  renderRows(); renderDetail(); drawShorts();
  const row = document.querySelector(`.row-short[data-short="${id}"]`);
  if (row) row.scrollIntoView({ block: "nearest" });
  if (go) playShort(shortById(id));
}
function step(dir) {
  const list = visibleShorts();
  if (!list.length) return;
  const i = list.findIndex((s) => s.id === current);
  const next = i < 0 ? list[dir > 0 ? 0 : list.length - 1] : list[Math.min(Math.max(0, i + dir), list.length - 1)];
  if (next.id !== current) chooseShort(next.id, true);
}
function decide(status) {
  if (!current) return;
  const list = visibleShorts(), i = list.findIndex((s) => s.id === current);
  const undo = statusOf(current) === status;
  setVerdict(current, { status: undo ? "review" : status });
  renderRows(); renderDetail(); feedback(); renderTabs();
  // a decision moves on to the next short in the list, so a review is one key per short
  const next = list[i + 1];
  if (!undo && next) chooseShort(next.id, true);
}
function tickShort() {
  const s = current && shortById(current);
  if (!s || !$("short-bar")) return;
  const on = playlist === s.keeps && idx < s.keeps.length, t = now();
  const done = on ? spans(s.keeps.slice(0, idx)) + Math.min(Math.max(0, t - s.keeps[idx][0]), s.keeps[idx][1] - s.keeps[idx][0]) : 0;
  $("short-bar").style.width = `${(done / Math.max(s.seconds, 0.001)) * 100}%`;
  const clock = on ? `${fmt(done)} / ${fmt(s.seconds)}` : fmt(s.seconds);
  if ($("short-clock").textContent !== clock) $("short-clock").textContent = clock;
  // the word being said
  let k = -1;
  if (on) { for (let lo = 0, hi = wordEls.length - 1; lo <= hi;) { const m = (lo + hi) >> 1; if (+wordEls[m].dataset.at <= t + 0.05) { k = m; lo = m + 1; } else hi = m - 1; } }
  if (k !== lit) {
    if (lit >= 0 && wordEls[lit]) wordEls[lit].classList.remove("now");
    if (k >= 0) { wordEls[k].classList.add("now"); const box = $("short-words"), w = wordEls[k];
      if (w.offsetTop < box.scrollTop || w.offsetTop > box.scrollTop + box.clientHeight - 30) box.scrollTop = w.offsetTop - box.offsetTop - 40; }
    lit = k;
  }
}
// the 9:16 preview stays on between reviews
const vertical = (on) => { $("stage").classList.toggle("vertical", on); $("vertical").classList.toggle("on", on);
  try { localStorage.cutroomVertical = on ? "1" : ""; } catch (e) {} };
$("vertical").onclick = () => vertical(!$("stage").classList.contains("vertical"));
try { vertical(localStorage.cutroomVertical === "1"); } catch (e) {}
function decisionsView() {
  if (!D.decisions.length) return `<div class="empty">No retakes or manual cuts. Only silences were cut.</div>`;
  return D.decisions.map((d) => `
    <div class="item">
      <div class="top"><span class="id">${d.id}</span>
        <span class="tag">${d.reason}  ·  ${fmt(d.start)} - ${fmt(d.end)}  ·  ${(d.end - d.start).toFixed(1)} s
        ${d.status === "rejected" ? "  ·  rejected by a keep" : ""}</span></div>
      ${(d.removed || []).map((t) => `<p class="removed">${esc(t)}</p>`).join("")}
      ${d.kept ? `<p>${esc(d.kept)}</p>` : ""}
      ${d.note ? `<p class="tag">${esc(d.note)}</p>` : ""}
      <div class="actions">
        <button class="small" data-play-result="${d.id}">Play result</button>
        <button class="small" data-play-removed="${d.id}">Play removed</button>
        ${d.status === "cut" ? `<button class="small ${rejected.has(d.id) ? "on" : ""}" data-reject="${d.id}">${rejected.has(d.id) ? "Rejected" : "Reject"}</button>` : ""}
      </div>
    </div>`).join("");
}
function transcriptView() {
  if (!D.sentences.length) return `<div class="empty">No transcript (silence-only run).</div>`;
  const gone = FOLDER
    ? (s) => !D.keeps.some(([a, b]) => s.end > a + 0.05 && s.start < b - 0.05)
    : (s) => D.finalCuts.some(([a, b]) => s.start >= a - 0.05 && s.end <= b + 0.05);
  return D.sentences.map((s) =>
    `<div class="sentence ${gone(s) ? "gone" : ""}" data-seek="${s.start}"><time>${fmt(s.start)}</time><span>${esc(s.text)}</span></div>`
  ).join("");
}
function storyView() {
  return `<div class="story">${D.story}</div>`;
}
const STORY = D.story ? { story: ["Story", storyView, null] } : {};
const RECORD = PICKUPS.length ? { record: ["To record", recordView, () => PICKUPS.filter((p) => !dropped.has(p.id)).length] } : {};
const TABS = FOLDER
  ? { ...STORY, vlog: [VLOG ? "Vlog" : "Edit", vlogView, () => D.selects.length], ...RECORD, shorts: ["Shorts", shortsView, () => D.shorts.length],
      decisions: ["Cuts", decisionsView, () => D.decisions.length], transcript: ["Transcript", transcriptView, () => D.sentences.length] }
  : { ...STORY, ...RECORD, shorts: ["Shorts", shortsView, () => D.shorts.length], decisions: ["Cuts to check", decisionsView, () => D.decisions.length],
      transcript: ["Transcript", transcriptView, () => D.sentences.length] };
$("tabs").innerHTML = Object.keys(TABS).map((k) => `<button data-tab="${k}"></button>`).join("");
const asked = decodeURIComponent(location.hash.slice(1));
tab = TABS[asked] ? asked
  : D.story && !(FOLDER && D.selects.length) ? "story"
  : D.shorts.length && (!FOLDER || (!VLOG && !D.selects.length)) ? "shorts"
  : FOLDER ? "vlog" : "decisions";
const HINTS = { shorts: "pick, maybe or reject each short, add notes, then copy this" };
const hint = FOLDER ? "toggle Drop or Reject, then copy this" : "toggle Reject, then copy this";
function renderTabs() {
  document.querySelectorAll(".tabs button").forEach((b) => {
    const [label, , count] = TABS[b.dataset.tab];
    b.classList.toggle("on", b.dataset.tab === tab);
    const n = count && count();
    b.textContent = n ? `${label} (${n})` : label;
  });
}
function render() {
  renderTabs();
  // the story is a document to read: give it room
  document.querySelector("main").classList.toggle("reading", tab === "story");
  document.body.classList.toggle("shorts-tab", tab === "shorts");
  $("list").innerHTML = TABS[tab][1]();
  if (tab === "shorts") { mountShorts(); renderDetail(); }
  $("hint").textContent = HINTS[tab] || hint;
  feedback();
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
  tab = b.dataset.tab;
  history.replaceState(null, "", `#${tab}`);
  render();
}));
$("list").onclick = (ev) => {
  const b = ev.target.closest("[data-play-result],[data-play-removed],[data-reject],[data-seek],[data-play-select],[data-drop],[data-lead-in]");
  if (!b) return;
  const ds = b.dataset, byId = (id) => D.decisions.find((d) => d.id === id);
  if (ds.playSelect) { const s = D.selects.find((x) => x.id === ds.playSelect); mode = "select"; playRanges(s.keeps, `${s.id} ${s.title || s.chapter}`); }
  if (ds.drop) { dropped.has(ds.drop) ? dropped.delete(ds.drop) : dropped.add(ds.drop); drawCuts(); drawMarks(); render(); }
  if (ds.leadIn) leadIn(PICKUPS.find((p) => p.id === ds.leadIn));
  if (ds.playResult) { const d = byId(ds.playResult); mode = "check";
    playRanges([[Math.max(0, d.start - 3), d.start], [d.end, Math.min(D.durationSeconds, d.end + 3)]], `${d.id} result`); }
  if (ds.playRemoved) { const d = byId(ds.playRemoved); mode = "check"; playRanges([[d.start, d.end]], `${d.id} removed`); }
  if (ds.reject) { rejected.has(ds.reject) ? rejected.delete(ds.reject) : rejected.add(ds.reject); drawCuts(); drawMarks(); render(); }
  if (ds.seek) { setMode("original"); seek(parseFloat(ds.seek), true); }
};

if (FOLDER) {
  $("legend").innerHTML = `<span><i style="background:var(--keep)"></i><i style="background:var(--keep2)"></i>chapters</span>
    <span><i style="background:var(--retake)"></i>retake cut</span><span><i style="background:var(--manual)"></i>manual cut</span>
    <span><i style="outline:1.5px dashed var(--rejected)"></i>rejected</span><span><i style="background:var(--cut)"></i>dropped select</span>
    <span><i style="background:var(--short)"></i>short candidate</span>
    ${PICKUPS.length ? `<span><i style="background:var(--record)"></i>talking head to record</span>` : ""}`;
}
$("title").textContent = D.title;
const live = PICKUPS.filter(placed);
const toRecord = !PICKUPS.length ? ""
  : live.length && !NOVLOG ? `  ·  + ${mmss(live.reduce((n, p) => n + (p.seconds || 20), 0))} to record (${live.length} talking heads)`
  : `  ·  ${PICKUPS.length} talking heads suggested`;
const judged = D.decisions.filter((d) => d.status === "cut").length;
$("stats").textContent = FOLDER && !D.selects.length
  ? `${D.media.length} clips, ${hours(D.durationSeconds)} of footage  ·  `
    + (D.story ? "story outline ready for review, no selects yet" : "no story or selects yet") + toRecord
  : FOLDER
  ? `${D.media.length} clips, ${hours(D.durationSeconds)} of footage → ${fmt(D.keptSeconds)} ${PROGRAM.toLowerCase()}  ·  `
    + `${D.selects.length} selects  ·  ${Object.keys(D.chapters).length} chapters  ·  ${judged} judgment cuts  ·  ${D.shorts.length} short candidates` + toRecord
  : `${fmt(D.durationSeconds)} → ${fmt(D.keptSeconds)} clean  ·  ${judged} judgment cuts  ·  ${D.shorts.length} short candidates` + toRecord;
setMode("clean");
render();
requestAnimationFrame(tick);
</script>
</body>
</html>
"""
