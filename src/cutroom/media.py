# ffmpeg/ffprobe helpers shared by every adapter: silence detection, probing,
# rendering kept segments, and never-overwrite output naming.

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .core import Range


def require_ffmpeg() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        sys.exit(f"{' and '.join(missing)} not found on PATH - install ffmpeg: "
                 "https://ffmpeg.org/download.html")


def detect_silences(audio: Path, noise_db: float, min_silence_s: float,
                    duration_ms: float) -> list[Range]:
    # (start_ms, end_ms) silence ranges within one media file. mapping only the
    # first audio stream keeps ffmpeg from decoding (and discarding) the video.
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio),
        "-map", "0:a:0", "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_s}",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.exit(f"ffmpeg silencedetect failed on {audio.name}:\n{proc.stderr.strip()[-800:]}")
    starts = [float(m) * 1000 for m in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr)]
    ends = [float(m) * 1000 for m in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    if len(starts) == len(ends) + 1:
        ends.append(duration_ms)  # silence runs to the end of the file
    return [(max(0.0, s), min(e, duration_ms)) for s, e in zip(starts, ends)]


def collect_silences(sessions: list[dict], noise_db: float = -35.0,
                     min_silence_s: float = 0.6) -> list[Range]:
    # silence ranges across all sessions, offset onto the concatenated timeline.
    # one ffmpeg process per session, run in parallel.
    workers = max(1, min(len(sessions), os.cpu_count() or 1))
    with ThreadPoolExecutor(workers) as pool:
        per_session = list(pool.map(
            # a clip without audio (b-roll) is silent from start to end
            lambda s: detect_silences(s["path"], noise_db, min_silence_s, s["durationMs"])
            if s.get("hasAudio", True) else [(0.0, s["durationMs"])],
            sessions,
        ))
    silences = []
    offset_ms = 0.0
    for session, found in zip(sessions, per_session):
        silences += [(offset_ms + s, offset_ms + e) for s, e in found]
        offset_ms += session["durationMs"]
    return silences


def probe_video(video: Path) -> tuple[float, bool]:
    # returns (duration_ms, has_audio)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-show_entries", "stream=codec_type", "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    duration_ms = float(data["format"]["duration"]) * 1000
    has_audio = any(s.get("codec_type") == "audio" for s in data["streams"])
    return duration_ms, has_audio


VIDEO_CODEC = ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]
AUDIO_CODEC = ["-c:a", "aac", "-b:a", "192k"]
# every decoded frame passes through every segment's trim filter, on one
# thread, so a single pass slows down with (source length x segment count).
# long cut lists are rendered as chunks of at most this many segments.
CHUNK_SEGMENTS = 24


def _trim_script(keeps: list[Range], offset_ms: float) -> str:
    # trim/concat graph for kept ranges, times relative to offset_ms (the seek point).
    # concat pads each segment to its longest stream, so audio never drifts.
    parts_v, parts_a, labels = [], [], []
    for i, (s, e) in enumerate(keeps):
        ss, es = (s - offset_ms) / 1000, (e - offset_ms) / 1000
        parts_v.append(f"[0:v:0]trim=start={ss:.3f}:end={es:.3f},setpts=PTS-STARTPTS[v{i}];")
        parts_a.append(f"[0:a:0]atrim=start={ss:.3f}:end={es:.3f},asetpts=PTS-STARTPTS[a{i}];")
        labels.append(f"[v{i}][a{i}]")
    return "\n".join(parts_v + parts_a) + f"\n{''.join(labels)}concat=n={len(keeps)}:v=1:a=1[v][a]"


def _render_pass(video: Path, keeps: list[Range], dst: Path, codec_args: list[str],
                 seek_ms: float = 0.0, extra: list[str] = ()) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "filter.txt"
        script_path.write_text(_trim_script(keeps, seek_ms), encoding="utf-8")
        seek = ["-ss", f"{seek_ms / 1000:.3f}"] if seek_ms else []
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", *extra, *seek,
             "-i", str(video), "-filter_complex_script", str(script_path),
             "-map", "[v]", "-map", "[a]", *codec_args, str(dst)],
            check=True,
        )


def render(video: Path, keeps: list[Range], dst: Path,
           chunk_segments: int = CHUNK_SEGMENTS) -> None:
    # frame-accurate assembly of kept ranges, re-encoded
    if len(keeps) <= chunk_segments:
        print(f"rendering {len(keeps)} segments -> {dst.name} ...")
        _render_pass(video, keeps, dst, VIDEO_CODEC + AUDIO_CODEC, extra=["-stats"])
        return

    # long cut lists: each chunk seeks straight to its first segment (accurate
    # seek) and renders in parallel. audio stays pcm until one final aac encode,
    # and each chunk starts both streams together, so the joins stay in sync.
    chunks = [keeps[i:i + chunk_segments] for i in range(0, len(keeps), chunk_segments)]
    cpus = os.cpu_count() or 1
    workers = max(1, min(len(chunks), cpus // 4))
    threads = max(1, cpus // workers)
    print(f"rendering {len(keeps)} segments in {len(chunks)} chunks "
          f"({workers} at a time) -> {dst.name} ...")
    with tempfile.TemporaryDirectory(dir=dst.parent, prefix=".cutroom-render-") as tmp:
        parts = [Path(tmp) / f"part-{i:04d}.mkv" for i in range(len(chunks))]

        def render_chunk(i: int) -> None:
            _render_pass(video, chunks[i], parts[i],
                         VIDEO_CODEC + ["-threads", str(threads), "-c:a", "pcm_s16le"],
                         seek_ms=chunks[i][0][0])
            print(f"  chunk {i + 1}/{len(chunks)} done")

        with ThreadPoolExecutor(workers) as pool:
            list(pool.map(render_chunk, range(len(chunks))))
        listing = Path(tmp) / "parts.txt"
        quoted = (p.as_posix().replace("'", "'\\''") for p in parts)  # concat list quoting
        listing.write_text("".join(f"file '{q}'\n" for q in quoted), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-map", "0:v", "-map", "0:a", "-c:v", "copy", *AUDIO_CODEC,
             "-movflags", "+faststart", str(dst)],
            check=True,
        )


def versioned_output(base: Path, src: Path | None = None) -> Path:
    # never delete or overwrite: version the output name if it already exists
    dst, n = base, 2
    while dst.exists() or (src is not None and dst.resolve() == src.resolve()):
        dst = base.with_name(f"{base.stem}-v{n}{base.suffix}")
        n += 1
    return dst
