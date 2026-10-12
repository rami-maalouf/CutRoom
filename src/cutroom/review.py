# the review page: one self-contained html file. it plays the ORIGINAL media
# and skips the cut ranges, so reviewing costs no render and no new media
# files. every judgment call (R*/M*), select (V*) and short candidate (S*) has
# an id, a play button and a toggle; the toggles build feedback text to paste
# back to the agent, which edits the project file and re-plans in a second.
# for a folder of clips the page shows the vlog: the selects in order, by chapter.

import json
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


def write_review(job, dst: Path) -> Path:
    plan = job.plan
    data = plan_data(plan, job.src)
    media, offset = [], 0.0
    for s in job.sessions:
        media.append({"uri": s["path"].resolve().as_uri(), "offset": round(offset / 1000, 3),
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
        shorts=[{**s, "where": _where(s), "keeps": [_secs(r) for r in job.item_segments(s)]}
                for s in job.data["shorts"]],
    )
    data["style"] = job.data["style"]
    data["pickups"] = job.data["pickups"]
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
            program=[[*_secs(r), r[2]] for r in job.program],
            keptSeconds=round(sum(r[1] - r[0] for r in job.program) / 1000, 3),
            chapters={str(i): title for i, title in job.chapters.items()},
            selects=selects,
            sentences=[x for x in data["sentences"]
                       if any(x["end"] * 1000 > a and x["start"] * 1000 < b for a, b in raw)],
            finalCuts=[],
            protectedRanges=[],
        )
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(PAGE.replace("__TITLE__", job.stem).replace("__DATA__", payload), encoding="utf-8")
    print(f"wrote review page: {dst}")
    return dst


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
  button { font: inherit; border: 1px solid var(--line); background: #fff; color: var(--ink);
           border-radius: 8px; padding: 5px 11px; cursor: pointer; }
  button:hover { border-color: #c8c8c4; }
  button.on { background: var(--ink); color: #fff; border-color: var(--ink); }
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
  kbd { font-family: inherit; font-size: 11px; line-height: 16px; min-width: 18px; text-align: center; color: var(--ink); background: #fff;
        border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 4px; padding: 0 4px; }
  .clock { flex: 1 1 240px; min-width: 0; text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
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
  .seg.select-line { width: 1px !important; top: auto; height: 5px; background: rgba(255, 255, 255, .85); }
  .chapter { margin: 16px 2px 2px; font-size: 12px; font-weight: 600; color: var(--muted);
             text-transform: none; letter-spacing: .01em; }
  .item.dropped { opacity: .5; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
  .chip { font-size: 11px; padding: 1px 7px; border-radius: 999px; background: var(--bg); color: var(--muted); }
  .chip.raw { background: rgba(255, 159, 10, .14); color: #b25000; }
  .intent { color: var(--muted); font-style: italic; }
  .item.pickup { border: 1.5px dashed var(--record); background: rgba(15, 163, 163, .05); }
  .item.pickup .id { color: var(--record); }
  .item.pickup ul { margin: 6px 0 0; padding-left: 18px; }
  .item.pickup li { margin: 2px 0; }
  .chip.record { background: rgba(15, 163, 163, .14); color: #0b7a7a; }
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
  .item.picked { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
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
                    border-radius: 8px; padding: 8px; font: 12px/1.5 ui-monospace, Menlo, monospace; color: var(--ink); }
  @media (max-width: 1000px) { main, main.reading { grid-template-columns: 1fr; } aside { max-height: none; } }
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
      <span><kbd>J</kbd><kbd>L</kbd>10 s</span><span><kbd>&lt;</kbd><kbd>&gt;</kbd>speed</span></div>
  </section>
  <aside class="card">
    <div class="tabs" id="tabs"></div>
    <div class="list" id="list"></div>
  </aside>
</main>
<footer class="card">
  <div class="row"><strong>Feedback for the agent</strong>
    <span class="tag" id="hint">toggle Reject or Pick, then copy this</span>
    <button id="copy" style="margin-left:auto">Copy</button></div>
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
  if (playlist && !el.paused && !el.seeking) {
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
  if (inProgram) clock = `${NOVLOG ? "all footage, pauses removed" : FOLDER ? "vlog" : "clean"} ${fmt(x)} / ${fmt(D.keptSeconds)}  ·  ${clock}`;
  else if (playlist && playlist !== D.keeps) clock = `${$("clock").dataset.label}  ·  ${clock}`;
  if ($("clock").textContent !== clock) {
    $("clock").textContent = clock;
    $("clock").title = FOLDER && session >= 0 ? `${clock}\n${D.media[session].name}` : clock;
  }
  $("toggle").textContent = el.paused ? "Play" : "Pause";
  requestAnimationFrame(tick);
}

// before selects exist a folder has no vlog yet: the player shows all footage
const NOVLOG = FOLDER && !D.selects.length;
$("mode-clean").textContent = NOVLOG ? "All footage" : FOLDER ? "Vlog" : "Clean cut";
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
  if (ev.metaKey || ev.ctrlKey || ev.altKey || ev.target.closest("textarea, input")) return;
  const k = ev.key.length === 1 ? ev.key.toLowerCase() : ev.key, step = RATES.indexOf(rate);
  if (k === " " || k === "k") $("toggle").click();
  else if (k === "ArrowLeft") skip(-5);
  else if (k === "ArrowRight") skip(5);
  else if (k === "j") skip(-10);
  else if (k === "l") skip(10);
  else if (k === "<" || k === ">") setRate(RATES[Math.min(Math.max(0, step + (k === ">" ? 1 : -1)), RATES.length - 1)]);
  else return;
  ev.preventDefault();
  // a focused button would also take the space bar on key up
  if (document.activeElement && document.activeElement.tagName === "BUTTON") document.activeElement.blur();
});

// ---------- timeline ----------
const rejected = new Set(), picked = new Set(), dropped = new Set();
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
    PICKUPS.filter((p) => placed(p) && !dropped.has(p.id)).forEach((p) => {
      const x = p.after === "start" ? 0 : ends[p.after];
      // a bar through the chapters where the talking head goes in
      if (x !== undefined) seg("lane-marks", x, x, "record", "", { width: "3px", marginLeft: "-1.5px", top: "-28px", bottom: "-2px" });
    });
  } else {
    D.protectedRanges.forEach(([s, e]) => seg("lane-marks", s, e, "protect"));
  }
}
function drawShorts() {
  $("lane-shorts").innerHTML = "";
  D.shorts.forEach((s) => {
    if (!FOLDER) return seg("lane-shorts", s.keeps.length ? s.keeps[0][0] : 0, s.keeps.length ? s.keeps.at(-1)[1] : 0, "short", s.id);
    // one mark per piece, so a short made of distant moments does not look like one
    // long stretch; the id goes on the widest piece, where it has room to read
    const spans = s.keeps.map(([a, b]) => spanOf(a, b)).filter(Boolean);
    const widest = spans.reduce((w, x) => (x[1] - x[0] > w[1] - w[0] ? x : w), spans[0]);
    spans.forEach((x) => seg("lane-shorts", x[0], Math.max(x[1], x[0] + AX / 300), "short", x === widest ? s.id : ""));
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
  if (picked.size) {
    lines.push(`Export ${[...picked].join(", ")}:`);
    lines.push(`  ${D.exportCommand} ${[...picked].join(" ")}`);
  }
  $("feedback").value = lines.join("\n") || "Nothing selected yet.";
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

// ---------- side lists ----------
function pickupCard(p) {
  const off = dropped.has(p.id);
  const where = p.after === "start" ? "at the start" : placed(p) ? `after ${p.after}` : "suggested by the story, not placed yet";
  return `
    <div class="item pickup ${off ? "dropped" : ""}">
      <div class="top"><span class="id">${p.id}</span><strong>${pickupKind(p)}</strong></div>
      <div class="tag">about ${p.seconds || 20} s  ·  ${where}</div>
      ${p.chapter || p.beat ? `<div class="chips">${[p.chapter, p.beat].filter(Boolean).map((t) => `<span class="chip record">${esc(t)}</span>`).join("")}</div>` : ""}
      <p>${esc(p.purpose)}</p>
      ${p.points && p.points.length ? `<ul>${p.points.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
      ${p.draft ? `<p class="intent">Draft, say it your way: "${esc(p.draft)}"</p>` : ""}
      <div class="actions">
        ${FOLDER && placed(p) && !NOVLOG ? `<button class="small" data-lead-in="${p.id}">Play where it goes</button>` : ""}
        <button class="small ${off ? "on" : ""}" data-drop="${p.id}">${off ? "Dropped" : "Drop"}</button>
      </div>
    </div>`;
}
function recordView() {
  // the shot list: placed talking heads in play order, then the suggestions not placed yet
  const order = (p) => p.after === "start" ? -1 : placed(p) ? D.selects.findIndex((s) => s.id === p.after) : 1e9;
  return [...PICKUPS].sort((a, b) => order(a) - order(b)).map(pickupCard).join("")
    + `<p class="tag" style="margin-top:12px">Record these in one sitting, put the files in the folder, and tell the agent:
       each recording becomes a select in its place and the pickup is removed.</p>`;
}
function leadIn(p) {
  // the last seconds before the talking head, its slate, the first seconds after it
  const at = p.after === "start" ? 0 : D.program.findLastIndex(([, , id]) => id === p.after) + 1;
  const before = at > 0 ? [[Math.max(D.program[at - 1][0], D.program[at - 1][1] - 6), D.program[at - 1][1]]] : [];
  const after = at < D.program.length ? [[D.program[at][0], Math.min(D.program[at][1], D.program[at][0] + 4)]] : [];
  mode = "check";
  playRanges([...before, ...after], `${p.id} in place`, new Map([[before.length, [p]]]));
}
function vlogView() {
  if (!D.selects.length) return `<div class="empty">No selects yet: the vlog is the whole clean footage.
    Ask the agent to choose moments; they are stored under "selects" in ${esc(D.projectFile)}.</div>`;
  let last = null;
  return (AFTER.start || []).map(pickupCard).join("") + D.selects.map((s) => {
    const head = s.chapter && s.chapter !== last ? `<div class="chapter">${esc(s.chapter)}</div>` : "";
    last = s.chapter || last;
    const off = dropped.has(s.id);
    return `${head}
    <div class="item ${off ? "dropped" : ""}">
      <div class="top"><span class="id">${s.id}</span>${s.title ? `<strong>${esc(s.title)}</strong>` : ""}</div>
      <div class="tag">${esc(s.where)}  ·  ${fmt(spans(s.keeps))} in the vlog</div>
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
function shortsView() {
  if (!D.shorts.length) return `<div class="empty">No short candidates yet. Ask the agent to propose some;
    they are stored under "shorts" in ${esc(D.projectFile)}.</div>`;
  return D.shorts.map((s) => `
    <div class="item ${picked.has(s.id) ? "picked" : ""}">
      <div class="top"><span class="id">${s.id}</span><strong>${esc(s.title)}</strong></div>
      <div class="tag">${esc(s.where)}  ·  ${fmt(spans(s.keeps))} clean  ·  ${s.keeps.length} segments</div>
      ${s.why ? `<p>${esc(s.why)}</p>` : ""}
      <div class="actions">
        <button class="small" data-play-short="${s.id}">Play clean</button>
        <button class="small ${picked.has(s.id) ? "on" : ""}" data-pick="${s.id}">${picked.has(s.id) ? "Picked" : "Pick"}</button>
      </div>
    </div>`).join("");
}
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
  ? { ...STORY, vlog: ["Vlog", vlogView, () => D.selects.length], ...RECORD, shorts: ["Shorts", shortsView, () => D.shorts.length],
      decisions: ["Cuts", decisionsView, () => D.decisions.length], transcript: ["Transcript", transcriptView, () => D.sentences.length] }
  : { ...STORY, ...RECORD, shorts: ["Shorts", shortsView, () => D.shorts.length], decisions: ["Cuts to check", decisionsView, () => D.decisions.length],
      transcript: ["Transcript", transcriptView, () => D.sentences.length] };
$("tabs").innerHTML = Object.keys(TABS).map((k) => `<button data-tab="${k}"></button>`).join("");
let tab = D.story && !(FOLDER && D.selects.length) ? "story" : FOLDER ? "vlog" : (D.shorts.length ? "shorts" : "decisions");
function render() {
  document.querySelectorAll(".tabs button").forEach((b) => {
    const [label, , count] = TABS[b.dataset.tab];
    b.classList.toggle("on", b.dataset.tab === tab);
    const n = count && count();
    b.textContent = n ? `${label} (${n})` : label;
  });
  // the story is a document to read: give it room
  document.querySelector("main").classList.toggle("reading", tab === "story");
  $("list").innerHTML = TABS[tab][1]();
  feedback();
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => { tab = b.dataset.tab; render(); }));
$("list").onclick = (ev) => {
  const b = ev.target.closest("[data-play-short],[data-pick],[data-play-result],[data-play-removed],[data-reject],[data-seek],[data-play-select],[data-drop],[data-lead-in]");
  if (!b) return;
  const ds = b.dataset, byId = (id) => D.decisions.find((d) => d.id === id);
  if (ds.playShort) { const s = D.shorts.find((x) => x.id === ds.playShort); mode = "short"; playRanges(s.keeps, `${s.id} ${s.title}`); }
  if (ds.playSelect) { const s = D.selects.find((x) => x.id === ds.playSelect); mode = "select"; playRanges(s.keeps, `${s.id} ${s.title || s.chapter}`); }
  if (ds.pick) { picked.has(ds.pick) ? picked.delete(ds.pick) : picked.add(ds.pick); render(); }
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
  $("hint").textContent = "toggle Drop, Reject or Pick, then copy this";
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
  ? `${D.media.length} clips, ${hours(D.durationSeconds)} of footage → ${fmt(D.keptSeconds)} vlog  ·  `
    + `${D.selects.length} selects  ·  ${Object.keys(D.chapters).length} chapters  ·  ${judged} judgment cuts  ·  ${D.shorts.length} short candidates` + toRecord
  : `${fmt(D.durationSeconds)} → ${fmt(D.keptSeconds)} clean  ·  ${judged} judgment cuts  ·  ${D.shorts.length} short candidates` + toRecord;
setMode("clean");
render();
requestAnimationFrame(tick);
</script>
</body>
</html>
"""
