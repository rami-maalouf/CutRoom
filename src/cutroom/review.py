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
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
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
    --protect: #0a84ff; --short: #5e5ce6; --accent: #0a84ff;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif; }
  header { display: flex; align-items: baseline; gap: 16px; padding: 18px 24px 10px; }
  header h1 { font-size: 18px; font-weight: 600; margin: 0; }
  header .stats { color: var(--muted); }
  main { display: grid; grid-template-columns: minmax(0, 1fr) 400px; gap: 16px; padding: 0 24px; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; }
  .player { padding: 12px; }
  video, .audio-stage { width: 100%; aspect-ratio: 16 / 9; background: #000; border-radius: 8px; display: block; }
  .audio-stage { display: flex; align-items: center; justify-content: center; color: #aaa; text-align: center; padding: 24px; }
  .controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; }
  button { font: inherit; border: 1px solid var(--line); background: #fff; color: var(--ink);
           border-radius: 8px; padding: 5px 11px; cursor: pointer; }
  button:hover { border-color: #c8c8c4; }
  button.on { background: var(--ink); color: #fff; border-color: var(--ink); }
  button.small { padding: 2px 8px; font-size: 12px; }
  .clock { margin-left: auto; font-variant-numeric: tabular-nums; color: var(--muted); }
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
  .seg.select-line { width: 1px !important; top: auto; height: 5px; background: rgba(255, 255, 255, .85); }
  .chapter { margin: 16px 2px 2px; font-size: 12px; font-weight: 600; color: var(--muted);
             text-transform: none; letter-spacing: .01em; }
  .item.dropped { opacity: .5; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
  .chip { font-size: 11px; padding: 1px 7px; border-radius: 999px; background: var(--bg); color: var(--muted); }
  .chip.raw { background: rgba(255, 159, 10, .14); color: #b25000; }
  .intent { color: var(--muted); font-style: italic; }
  .story { padding: 4px 6px 12px; }
  .story h3, .story h4, .story h5 { margin: 14px 0 6px; font-size: 14px; }
  .story h3 { font-size: 16px; }
  .story p { margin: 6px 0; }
  .story li { margin: 3px 0 3px 18px; }
  .story table { border-collapse: collapse; width: 100%; font-size: 12px; margin: 8px 0; }
  .story th, .story td { border: 1px solid var(--line); padding: 4px 6px; vertical-align: top; text-align: left; }
  .story code { font-size: 12px; background: var(--bg); padding: 0 4px; border-radius: 4px; }
  .seg.short { background: rgba(94, 92, 230, .14); border: 1px solid var(--short); border-radius: 4px;
               color: var(--short); font-size: 10px; font-weight: 600; padding-left: 3px; overflow: hidden; white-space: nowrap; }
  .playhead { position: absolute; top: -3px; height: 64px; width: 2px; background: var(--ink); pointer-events: none; }
  .legend { display: flex; flex-wrap: wrap; gap: 14px; color: var(--muted); font-size: 12px; margin-top: 8px; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
  aside { display: flex; flex-direction: column; min-height: 0; max-height: calc(100vh - 150px); }
  .tabs { display: flex; gap: 4px; padding: 10px 10px 0; }
  .tabs button { border: none; background: none; color: var(--muted); padding: 6px 8px; white-space: nowrap; font-size: 13px; }
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
  @media (max-width: 1000px) { main { grid-template-columns: 1fr; } aside { max-height: none; } }
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
      <button id="toggle">Play</button>
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
  </section>
  <aside class="card">
    <div class="tabs" id="tabs"></div>
    <div class="list" id="list"></div>
  </aside>
</main>
<footer class="card">
  <div class="row"><strong>Feedback for the agent</strong>
    <span class="tag">toggle Reject or Pick, then copy this</span>
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
let session = -1;
function load(k, local, play) {
  if (k !== session) {
    session = k;
    el.src = D.media[k].uri;
    el.addEventListener("loadedmetadata", () => { el.currentTime = local; if (play) el.play(); }, { once: true });
  } else {
    el.currentTime = local;
    if (play) el.play();
  }
}
function seek(t, play) {
  // offsets are rounded to the millisecond, so allow that much at file joins
  let k = D.media.findIndex((m) => t < m.offset + m.duration - 0.002);
  if (k < 0) k = D.media.length - 1;
  load(k, Math.max(0, t - D.media[k].offset), play);
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
function programAt(x) {
  // axis position -> [range index, source time]
  let acc = 0;
  for (let i = 0; i < D.keeps.length; i++) {
    const [s, e] = D.keeps[i];
    if (x < acc + (e - s)) return [i, s + (x - acc)];
    acc += e - s;
  }
  return [D.keeps.length - 1, D.keeps[D.keeps.length - 1][1]];
}

// ---------- playback: a playlist of source ranges, or the plain original ----------
let playlist = null, idx = 0, mode = "clean";
function playRanges(ranges, label) {
  if (!ranges.length) return;
  playlist = ranges; idx = 0; seek(ranges[0][0], true);
  $("clock").dataset.label = label || "";
  $("mode-clean").classList.remove("on"); $("mode-original").classList.remove("on");
}
function setMode(m) {
  mode = m;
  $("mode-clean").classList.toggle("on", m === "clean");
  $("mode-original").classList.toggle("on", m === "original");
  playlist = m === "clean" ? D.keeps : null;
  if (m === "clean" && !FOLDER) { idx = Math.max(0, D.keeps.findIndex(([, e]) => e > now())); }
}
function tick() {
  if (playlist && !el.paused && !el.seeking) {
    const t = now(), r = playlist[idx];
    if (r && t >= r[1] - 0.02) {
      idx += 1;
      if (idx >= playlist.length) { el.pause(); if (playlist !== D.keeps) setMode("clean"); }
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
  const file = FOLDER && session >= 0 ? `${D.media[session].name} ${fmt(el.currentTime)}` : `source ${fmt(t)} / ${fmt(D.durationSeconds)}`;
  let clock = file;
  if (inProgram) clock = `${FOLDER ? "vlog" : "clean"} ${fmt(x)} / ${fmt(D.keptSeconds)}  ·  ${clock}`;
  else if (playlist && playlist !== D.keeps) clock = `${$("clock").dataset.label}  ·  ${clock}`;
  $("clock").textContent = clock;
  $("toggle").textContent = el.paused ? "Play" : "Pause";
  requestAnimationFrame(tick);
}

$("mode-clean").textContent = FOLDER ? "Vlog" : "Clean cut";
$("mode-clean").onclick = () => setMode("clean");
$("mode-original").onclick = () => setMode("original");
$("toggle").onclick = () => {
  if (!el.paused) return el.pause();
  if (session < 0) seek(mode === "clean" ? D.keeps[0][0] : 0, true); else el.play();
};
$("timeline").onclick = (ev) => {
  const box = $("timeline").getBoundingClientRect();
  const x = ((ev.clientX - box.left) / box.width) * AX;
  if (FOLDER) { const [i, t] = programAt(x); setMode("clean"); idx = i; seek(t, true); }
  else { setMode("original"); seek(x, true); }
};

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
  } else {
    D.protectedRanges.forEach(([s, e]) => seg("lane-marks", s, e, "protect"));
  }
}
function drawShorts() {
  $("lane-shorts").innerHTML = "";
  D.shorts.forEach((s) => {
    if (!FOLDER) return seg("lane-shorts", s.keeps.length ? s.keeps[0][0] : 0, s.keeps.length ? s.keeps.at(-1)[1] : 0, "short", s.id);
    const xs = s.keeps.flatMap(([a, b]) => [axisOf(a), axisOf(b)]);
    if (xs.length && xs.every((x) => x !== null)) seg("lane-shorts", Math.min(...xs), Math.max(...xs), "short", s.id);
  });
}
drawCuts(); drawMarks(); drawShorts();

// ---------- feedback ----------
function feedback() {
  const lines = [];
  if (dropped.size) lines.push(`Remove ${[...dropped].join(", ")} from selects in ${D.projectFile}.`);
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
function vlogView() {
  if (!D.selects.length) return `<div class="empty">No selects yet: the vlog is the whole clean footage.
    Ask the agent to choose moments; they are stored under "selects" in ${esc(D.projectFile)}.</div>`;
  let last = null;
  return D.selects.map((s) => {
    const head = s.chapter && s.chapter !== last ? `<div class="chapter">${esc(s.chapter)}</div>` : "";
    last = s.chapter || last;
    const off = dropped.has(s.id);
    return `${head}
    <div class="item ${off ? "dropped" : ""}">
      <div class="top"><span class="id">${s.id}</span>${s.title ? `<strong>${esc(s.title)}</strong>` : ""}</div>
      <div class="tag">${esc(s.where)}  ·  ${fmt(spans(s.keeps))} in the vlog</div>
      ${s.beat || s.role || s.raw ? `<div class="chips">${[s.beat, s.role].filter(Boolean).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}${s.raw ? `<span class="chip raw" title="plays as it happened: no silence or retake cuts inside">raw</span>` : ""}</div>` : ""}
      ${s.intent ? `<p class="intent">${esc(s.intent)}</p>` : ""}
      ${s.text ? `<p>${esc(s.text)}</p>` : ""}
      ${s.why ? `<p class="tag">${esc(s.why)}</p>` : ""}
      <div class="actions">
        <button class="small" data-play-select="${s.id}">Play</button>
        <button class="small ${off ? "on" : ""}" data-drop="${s.id}">${off ? "Dropped" : "Drop"}</button>
      </div>
    </div>`; }).join("");
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
const TABS = FOLDER
  ? { ...STORY, vlog: ["Vlog", vlogView, () => D.selects.length], shorts: ["Shorts", shortsView, () => D.shorts.length],
      decisions: ["Cuts", decisionsView, () => D.decisions.length], transcript: ["Transcript", transcriptView, () => D.sentences.length] }
  : { ...STORY, shorts: ["Shorts", shortsView, () => D.shorts.length], decisions: ["Cuts to check", decisionsView, () => D.decisions.length],
      transcript: ["Transcript", transcriptView, () => D.sentences.length] };
$("tabs").innerHTML = Object.keys(TABS).map((k) => `<button data-tab="${k}"></button>`).join("");
let tab = D.story && !(FOLDER && D.selects.length) ? "story" : FOLDER ? "vlog" : (D.shorts.length ? "shorts" : "decisions");
function render() {
  document.querySelectorAll(".tabs button").forEach((b) => {
    const [label, , count] = TABS[b.dataset.tab];
    b.classList.toggle("on", b.dataset.tab === tab);
    b.textContent = count ? `${label} (${count()})` : label;
  });
  $("list").innerHTML = TABS[tab][1]();
  feedback();
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => { tab = b.dataset.tab; render(); }));
$("list").onclick = (ev) => {
  const b = ev.target.closest("[data-play-short],[data-pick],[data-play-result],[data-play-removed],[data-reject],[data-seek],[data-play-select],[data-drop]");
  if (!b) return;
  const ds = b.dataset, byId = (id) => D.decisions.find((d) => d.id === id);
  if (ds.playShort) { const s = D.shorts.find((x) => x.id === ds.playShort); mode = "short"; playRanges(s.keeps, `${s.id} ${s.title}`); }
  if (ds.playSelect) { const s = D.selects.find((x) => x.id === ds.playSelect); mode = "select"; playRanges(s.keeps, `${s.id} ${s.title || s.chapter}`); }
  if (ds.pick) { picked.has(ds.pick) ? picked.delete(ds.pick) : picked.add(ds.pick); render(); }
  if (ds.drop) { dropped.has(ds.drop) ? dropped.delete(ds.drop) : dropped.add(ds.drop); drawCuts(); render(); }
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
    <span><i style="background:var(--short)"></i>short candidate</span>`;
}
$("title").textContent = D.title;
const judged = D.decisions.filter((d) => d.status === "cut").length;
$("stats").textContent = FOLDER
  ? `${D.media.length} clips, ${hours(D.durationSeconds)} of footage → ${fmt(D.keptSeconds)} vlog  ·  `
    + `${D.selects.length} selects  ·  ${Object.keys(D.chapters).length} chapters  ·  ${judged} judgment cuts  ·  ${D.shorts.length} short candidates`
  : `${fmt(D.durationSeconds)} → ${fmt(D.keptSeconds)} clean  ·  ${judged} judgment cuts  ·  ${D.shorts.length} short candidates`;
setMode("clean");
render();
requestAnimationFrame(tick);
</script>
</body>
</html>
"""
