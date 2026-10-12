# folder sources: a directory of clips (a vlog shoot, a conference day) is one
# source. clips sit on one timeline in capture order; everything cutroom keeps
# about the folder lives in a visible <folder>/cutroom/ subfolder.
#
#   cutroom/cutroom.json        project file (edits, selects, shorts)
#   cutroom/manifest.json       probe cache: duration, audio, capture time per clip
#   cutroom/transcripts/        one word-level transcript per clip
#   cutroom/digest/             compact transcript text for agents, split in shards
#   cutroom/sheets/             one contact sheet per clip (for clips without speech)
#   cutroom/review.html, exports/

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .core import words_to_sentences

MEDIA_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".mts"}
WORKDIR = "cutroom"


def workdir(folder: Path) -> Path:
    return folder / WORKDIR


def media_files(folder: Path) -> list[Path]:
    # every video under the folder, except cutroom's own outputs and hidden files
    out = []
    for path in folder.rglob("*"):
        rel = path.relative_to(folder)
        if rel.parts[0] == WORKDIR or any(p.startswith(".") for p in rel.parts):
            continue
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES:
            out.append(path)
    return out


def _parse_time(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(value.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
    return None


def _probe_clip(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:format_tags=creation_time,com.apple.quicktime.creationdate:stream=codec_type",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    data = json.loads(out.stdout or "{}")
    if "format" not in data:
        return {"error": (out.stderr or "unreadable").strip()[-200:]}
    tags = data["format"].get("tags") or {}
    # iphone: creationdate carries the real local offset; dji and most cameras
    # write true utc in creation_time; fall back to the file's modified time
    captured = None
    for key in ("com.apple.quicktime.creationdate", "creation_time"):
        if tags.get(key) and (captured := _parse_time(tags[key])):
            break
    if captured is None:
        captured = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    streams = {s.get("codec_type") for s in data.get("streams", [])}
    return {
        "durationMs": float(data["format"].get("duration", 0)) * 1000,
        "hasAudio": "audio" in streams,
        "hasVideo": "video" in streams,
        "captured": captured.astimezone(timezone.utc).isoformat(),
    }


def clips(folder: Path) -> list[dict]:
    # clips in capture order, probed once and cached by size + modified time
    cache_path = workdir(folder) / "manifest.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    files = media_files(folder)

    def info(path: Path) -> tuple[str, dict]:
        rel = path.relative_to(folder).as_posix()
        stat = path.stat()
        key = f"{stat.st_size}:{int(stat.st_mtime)}"
        hit = cache.get(rel)
        return rel, hit if hit and hit.get("key") == key else {**_probe_clip(path), "key": key}

    with ThreadPoolExecutor(max(1, min(16, os.cpu_count() or 1))) as pool:
        probed = dict(pool.map(info, files))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(probed, indent=1), encoding="utf-8")

    result, skipped = [], []
    for rel, meta in probed.items():
        if "error" in meta or not meta.get("hasVideo") or meta["durationMs"] <= 0:
            skipped.append(rel)
            continue
        result.append({"rel": rel, "path": folder / rel, **meta})
    if skipped:
        print(f"skipped {len(skipped)} unreadable or audio-only files: {', '.join(skipped[:5])}")
    return sorted(result, key=lambda c: (c["captured"], c["rel"]))


def sessions(folder: Path) -> list[dict]:
    # clips as pipeline sessions, each with its own transcript cache
    work = workdir(folder) / "transcripts"
    return [{"path": c["path"], "durationMs": c["durationMs"], "hasAudio": c["hasAudio"],
             "rel": c["rel"], "captured": c["captured"],
             "cache": work / (c["rel"].replace("/", "__") + ".transcript.json")}
            for c in clips(folder)]


def offsets(sess: list[dict]) -> dict[str, float]:
    # clip rel -> start of the clip on the folder timeline (ms)
    out, acc = {}, 0.0
    for s in sess:
        out[s["rel"]] = acc
        acc += s["durationMs"]
    return out


def _fmt(seconds: float) -> str:
    m, s = divmod(max(0.0, seconds), 60)
    return f"{int(m)}:{s:04.1f}"


def _digest_lines(words: list[dict], longest_ms: float = 12000, piece_ms: float = 8000) -> list[dict]:
    # sentences, but a run-on without punctuation (whisper writes some passages
    # as one 60 s "sentence") is split into ~8 s pieces at word boundaries, so
    # an agent can still place a cut precisely
    out = []
    for sent in words_to_sentences(words):
        if sent["endMs"] - sent["startMs"] <= longest_ms:
            out.append(sent)
            continue
        piece: list[dict] = []
        for w in (w for w in words if sent["startMs"] <= w["startMs"] <= sent["endMs"]):
            piece.append(w)
            if piece[-1]["endMs"] - piece[0]["startMs"] >= piece_ms:
                out.append({"startMs": piece[0]["startMs"], "endMs": piece[-1]["endMs"],
                            "text": " ".join(x["word"] for x in piece)})
                piece = []
        if piece:
            out.append({"startMs": piece[0]["startMs"], "endMs": piece[-1]["endMs"],
                        "text": " ".join(x["word"] for x in piece)})
    return out


def write_digest(sess: list[dict], words: list[dict], dst: Path, shards: int,
                 sheets: dict[str, Path] | None = None) -> list[Path]:
    # compact, agent-readable transcript: one block per clip, one line per
    # sentence with clip-relative times. shards split the shoot into time
    # slices of similar speech length so parallel agents get equal work.
    # clips are never split; clips without speech are listed so b-roll is seen.
    blocks, weights, offset = [], [], 0.0
    for s in sess:
        end = offset + s["durationMs"]
        clip_words = [{**w, "startMs": w["startMs"] - offset, "endMs": w["endMs"] - offset}
                      for w in words if offset <= w["startMs"] < end]
        local = datetime.fromisoformat(s["captured"]).astimezone()
        head = (f"## {s['rel']}\ncaptured {local:%a %Y-%m-%d %H:%M}  ·  {_fmt(s['durationMs'] / 1000)}"
                f"  ·  {len(clip_words)} words")
        lines = [f"[{x['startMs'] / 1000:.2f}-{x['endMs'] / 1000:.2f}] {x['text']}"
                 for x in _digest_lines(clip_words)]
        sheet = sheets.get(s["rel"]) if sheets else None
        if not lines:
            lines = ["(no speech)" + (f" contact sheet: {sheet}" if sheet else "")]
        elif sheet:
            lines.insert(0, f"(mostly visual) contact sheet: {sheet}")
        blocks.append(head + "\n" + "\n".join(lines))
        weights.append(max(1, len(clip_words)))
        offset = end

    dst.mkdir(parents=True, exist_ok=True)
    for old in dst.glob("shard-*.md"):
        old.unlink()
    header = ("# transcript digest\n\ntimes are seconds inside each clip. a select is "
              '{"clip": "<path after ##>", "start": s, "end": s}.\n\n')
    (dst / "all.md").write_text(header + "\n\n".join(blocks) + "\n", encoding="utf-8")
    # each shard's target is what is left divided by the shards left, so one
    # very long clip does not leave the last shard empty
    paths, current, load, left = [], [], 0, sum(weights)
    for block, weight in zip(blocks, weights):
        current.append(block)
        load += weight
        if len(paths) < shards - 1 and load >= left / (shards - len(paths)):
            paths.append(current)
            left -= load
            current, load = [], 0
    if current:
        paths.append(current)
    written = []
    for i, group in enumerate(paths, 1):
        path = dst / f"shard-{i}.md"
        path.write_text(header + f"shard {i} of {len(paths)}\n\n" + "\n\n".join(group) + "\n",
                        encoding="utf-8")
        written.append(path)
    return written


def mostly_visual(words: int, duration_ms: float) -> bool:
    # a clip whose value is probably its picture: at an event every clip has some
    # talking in it, so "no speech" is too strict; few words per minute is the sign
    return words < 8 or words / max(duration_ms / 60000, 1 / 60) < 20


def contact_sheet(clip: Path, dst: Path, frames: int = 12) -> Path:
    # one 4x3 grid of evenly spaced frames, decoded from keyframes only (fast on 4k)
    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(clip)],
        capture_output=True, text=True).stdout.strip() or 0)
    step = max(duration / frames, 0.5)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-skip_frame", "nokey", "-i", str(clip),
         "-vf", f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{step:.2f})',"
                "scale=320:-2,tile=4x3", "-frames:v", "1", "-fps_mode", "vfr", str(dst)],
        check=True,
    )
    return dst
