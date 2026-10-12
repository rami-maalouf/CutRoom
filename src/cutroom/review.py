# the review page: one self-contained html file next to the source. it plays
# the ORIGINAL media and skips the cut ranges, so reviewing costs no render and
# no new media files. every judgment call (R*/M*) and short candidate (S*) has
# an id, a play button and a toggle; the toggles build feedback text to paste
# back to the agent, which edits the project file and re-plans in a second.

import json
from pathlib import Path

from .pipeline import Plan, plan_data
from .project import project_path


def short_keeps(plan_keeps: list[list[float]], start: float, end: float) -> list[list[float]]:
    # the clean-cut segments that fall inside a short's range (seconds)
    out = []
    for s, e in plan_keeps:
        a, b = max(s, start), min(e, end)
        if b - a > 0.05:
            out.append([round(a, 3), round(b, 3)])
    return out


def write_review(plan: Plan, source: Path, sessions: list[dict], kind: str,
                 shorts: list[dict], dst: Path) -> Path:
    data = plan_data(plan, source)
    offset = 0.0
    media = []
    for s in sessions:
        media.append({"uri": s["path"].resolve().as_uri(), "offset": round(offset / 1000, 3),
                      "duration": round(s["durationMs"] / 1000, 3)})
        offset += s["durationMs"]
    data.update(
        title=source.stem,
        kind=kind,
        media=media,
        projectFile=project_path(source).name,
        exportCommand=f"cutroom export {json.dumps(str(source))}",
        shorts=[{**s, "keeps": short_keeps(data["keeps"], s["start"], s["end"])} for s in shorts],
    )
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    dst.write_text(PAGE.replace("__TITLE__", source.stem).replace("__DATA__", payload), encoding="utf-8")
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
    --keep: #34c759; --cut: #c7c7cc; --retake: #ff453a; --manual: #ff9f0a; --rejected: #8e8e93;
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
  .seg.short { background: rgba(94, 92, 230, .14); border: 1px solid var(--short); border-radius: 4px;
               color: var(--short); font-size: 10px; font-weight: 600; padding-left: 3px; overflow: hidden; white-space: nowrap; }
  .playhead { position: absolute; top: -3px; height: 64px; width: 2px; background: var(--ink); pointer-events: none; }
  .legend { display: flex; flex-wrap: wrap; gap: 14px; color: var(--muted); font-size: 12px; margin-top: 8px; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 5px; vertical-align: -1px; }
  aside { display: flex; flex-direction: column; min-height: 0; max-height: calc(100vh - 150px); }
  .tabs { display: flex; gap: 4px; padding: 10px 10px 0; }
  .tabs button { border: none; background: none; color: var(--muted); padding: 6px 10px; }
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
    <div class="legend">
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
    <div class="tabs">
      <button data-tab="shorts">Shorts</button>
      <button data-tab="decisions">Cuts to check</button>
      <button data-tab="transcript">Transcript</button>
    </div>
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
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const spans = (r) => r.reduce((n, [s, e]) => n + (e - s), 0);

// ---------- media: one element, one or more sessions on a single source timeline ----------
const isVideo = D.kind === "video";
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
  // offsets are rounded to the millisecond, so allow that much at session joins
  let k = D.media.findIndex((m) => t < m.offset + m.duration - 0.002);
  if (k < 0) k = D.media.length - 1;
  load(k, Math.max(0, t - D.media[k].offset), play);
}
const now = () => session < 0 ? 0 : D.media[session].offset + el.currentTime;
// one file per recording session: when a file ends, carry on into the next one
// unless the current playlist range ends here anyway
el.addEventListener("ended", () => {
  if (session >= D.media.length - 1) return;
  const next = D.media[session + 1].offset, r = playlist && playlist[idx];
  if (!playlist || (r && r[1] > next)) load(session + 1, 0, true);
});

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
  if (m === "clean") { idx = Math.max(0, D.keeps.findIndex(([, e]) => e > now())); }
}
function tick() {
  if (playlist && !el.paused && !el.seeking) {
    const t = now(), r = playlist[idx];
    if (r && t >= r[1] - 0.02) {
      idx += 1;
      if (idx >= playlist.length) { el.pause(); if (playlist !== D.keeps) setMode("clean"); }
      else seek(playlist[idx][0], true);
    } else if (r && t < r[0] - 0.3) {
      seek(r[0], true);
    }
  }
  const t = now();
  $("playhead").style.left = `${(t / D.durationSeconds) * 100}%`;
  let clock = `source ${fmt(t)} / ${fmt(D.durationSeconds)}`;
  if (mode === "clean" && playlist === D.keeps) {
    const done = spans(D.keeps.slice(0, idx)) + Math.max(0, t - (D.keeps[idx] || [t])[0]);
    clock = `clean ${fmt(done)} / ${fmt(D.keptSeconds)}  ·  ${clock}`;
  } else if (playlist && playlist !== D.keeps) {
    clock = `${$("clock").dataset.label}  ·  ${clock}`;
  }
  $("clock").textContent = clock;
  $("toggle").textContent = el.paused ? "Play" : "Pause";
  requestAnimationFrame(tick);
}

$("mode-clean").onclick = () => setMode("clean");
$("mode-original").onclick = () => setMode("original");
$("toggle").onclick = () => {
  if (!el.paused) return el.pause();
  if (session < 0) seek(mode === "clean" ? D.keeps[0][0] : 0, true); else el.play();
};
$("timeline").onclick = (ev) => {
  const box = $("timeline").getBoundingClientRect();
  const t = ((ev.clientX - box.left) / box.width) * D.durationSeconds;
  setMode("original"); seek(t, true);
};

// ---------- timeline ----------
const rejected = new Set(), picked = new Set();
const pct = (t) => `${(t / D.durationSeconds) * 100}%`;
function seg(lane, s, e, cls, text) {
  const d = document.createElement("div");
  d.className = `seg ${cls}`; d.style.left = pct(s); d.style.width = `calc(${pct(e - s)} + 1px)`;
  if (text) { d.textContent = text; d.title = text; }
  $(lane).appendChild(d);
}
function drawCuts() {
  $("lane-base").innerHTML = "";
  D.finalCuts.forEach(([s, e]) => seg("lane-base", s, e, "cut"));
  D.decisions.forEach((d) => seg("lane-base", d.start, d.end,
    d.status === "cut" && !rejected.has(d.id) ? (d.reason === "manual" ? "manual" : "retake") : "rejected"));
}
drawCuts();
D.protectedRanges.forEach(([s, e]) => seg("lane-marks", s, e, "protect"));

// ---------- feedback ----------
D.shorts.forEach((s) => seg("lane-shorts", s.start, s.end, "short", s.id));


function feedback() {
  const lines = [];
  if (rejected.size) {
    lines.push(`Reject ${[...rejected].join(", ")} in ${D.projectFile}. Add to edits.keeps:`);
    D.decisions.filter((d) => rejected.has(d.id)).forEach((d) =>
      lines.push(`  [${d.start}, ${d.end}, "reject ${d.id}"]`));
  }
  if (picked.size) {
    lines.push(`Export ${[...picked].join(", ")}:`);
    lines.push(`  ${D.exportCommand} ${[...picked].join(" ")}`);
  }
  $("feedback").value = lines.join("\n") || "Nothing selected yet.";
}
$("copy").onclick = async () => {
  const box = $("feedback");
  try { await navigator.clipboard.writeText(box.value); }
  catch { box.select(); document.execCommand("copy"); }
  $("copy").textContent = "Copied"; setTimeout(() => ($("copy").textContent = "Copy"), 1200);
};

// ---------- side lists ----------
function shortsView() {
  if (!D.shorts.length) return `<div class="empty">No short candidates yet. Ask the agent to propose some;
    they are stored under "shorts" in ${esc(D.projectFile)}.</div>`;
  return D.shorts.map((s) => `
    <div class="item ${picked.has(s.id) ? "picked" : ""}">
      <div class="top"><span class="id">${s.id}</span><strong>${esc(s.title)}</strong></div>
      <div class="tag">${fmt(s.start)} - ${fmt(s.end)} source  ·  ${fmt(spans(s.keeps))} clean  ·  ${s.keeps.length} segments</div>
      ${s.why ? `<p>${esc(s.why)}</p>` : ""}
      <div class="actions">
        <button class="small" data-play-short="${s.id}">Play clean</button>
        <button class="small ${picked.has(s.id) ? "on" : ""}" data-pick="${s.id}">${picked.has(s.id) ? "Picked" : "Pick"}</button>
      </div>
    </div>`).join("");
}
function decisionsView() {
  if (!D.decisions.length) return `<div class="empty">No retakes or manual cuts. Only silences were cut.</div>`;
  return D.decisions.map((d) => {
    const off = rejected.has(d.id) || d.status === "rejected";
    return `
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
    </div>`; }).join("");
}
function transcriptView() {
  if (!D.sentences.length) return `<div class="empty">No transcript (silence-only run).</div>`;
  const inCut = (s) => D.finalCuts.some(([a, b]) => s.start >= a - 0.05 && s.end <= b + 0.05);
  return D.sentences.map((s) =>
    `<div class="sentence ${inCut(s) ? "gone" : ""}" data-seek="${s.start}"><time>${fmt(s.start)}</time><span>${esc(s.text)}</span></div>`
  ).join("");
}
let tab = D.shorts.length ? "shorts" : "decisions";
function render() {
  document.querySelectorAll(".tabs button").forEach((b) => {
    b.classList.toggle("on", b.dataset.tab === tab);
    const n = { shorts: D.shorts.length, decisions: D.decisions.length, transcript: D.sentences.length }[b.dataset.tab];
    b.textContent = `${{ shorts: "Shorts", decisions: "Cuts to check", transcript: "Transcript" }[b.dataset.tab]} (${n})`;
  });
  $("list").innerHTML = { shorts: shortsView, decisions: decisionsView, transcript: transcriptView }[tab]();
  feedback();
}
document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => { tab = b.dataset.tab; render(); }));
$("list").onclick = (ev) => {
  const b = ev.target.closest("[data-play-short],[data-pick],[data-play-result],[data-play-removed],[data-reject],[data-seek]");
  if (!b) return;
  const ds = b.dataset, byId = (id) => D.decisions.find((d) => d.id === id);
  if (ds.playShort) { const s = D.shorts.find((x) => x.id === ds.playShort); mode = "short"; playRanges(s.keeps, `${s.id} ${s.title}`); }
  if (ds.pick) { picked.has(ds.pick) ? picked.delete(ds.pick) : picked.add(ds.pick); render(); }
  if (ds.playResult) { const d = byId(ds.playResult); mode = "check";
    playRanges([[Math.max(0, d.start - 3), d.start], [d.end, Math.min(D.durationSeconds, d.end + 3)]], `${d.id} result`); }
  if (ds.playRemoved) { const d = byId(ds.playRemoved); mode = "check"; playRanges([[d.start, d.end]], `${d.id} removed`); }
  if (ds.reject) { rejected.has(ds.reject) ? rejected.delete(ds.reject) : rejected.add(ds.reject); drawCuts(); render(); }
  if (ds.seek) { setMode("original"); seek(parseFloat(ds.seek), true); }
};

$("title").textContent = D.title;
$("stats").textContent = `${fmt(D.durationSeconds)} → ${fmt(D.keptSeconds)} clean  ·  `
  + `${D.decisions.filter((d) => d.status === "cut").length} judgment cuts  ·  ${D.shorts.length} short candidates`;
setMode("clean");
render();
requestAnimationFrame(tick);
</script>
</body>
</html>
"""
