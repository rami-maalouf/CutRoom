# synthetic media fixtures: tones stand in for speech, digital silence for
# pauses, and transcripts are pre-written into the cache so no whisper model
# is ever downloaded. timings are known exactly, so assertions can be tight.

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cutroom.transcribe import CACHE_VERSION

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def audio_filter(pattern: list[tuple[str, float]]) -> str:
    # [("tone", 2.0), ("silence", 1.5), ...] -> one lavfi graph producing that audio
    parts, labels = [], []
    for i, (kind, secs) in enumerate(pattern):
        src = f"sine=frequency=440:sample_rate=48000:duration={secs}" if kind == "tone" \
            else f"anullsrc=r=48000:cl=mono,atrim=duration={secs}"
        parts.append(f"{src}[p{i}]")
        labels.append(f"[p{i}]")
    return ";".join(parts) + f";{''.join(labels)}concat=n={len(pattern)}:v=0:a=1[out]"


def make_audio(path: Path, pattern: list[tuple[str, float]]) -> Path:
    ffmpeg("-filter_complex", audio_filter(pattern), "-map", "[out]", "-c:a", "aac", str(path))
    return path


def make_video(path: Path, pattern: list[tuple[str, float]], *extra: str) -> Path:
    total = sum(secs for _, secs in pattern)
    ffmpeg("-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=30:duration={total}",
           "-filter_complex", audio_filter(pattern),
           "-map", "0:v", "-map", "[out]", "-c:v", "libx264", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", *extra, str(path))
    return path


def write_transcript(cache: Path, words: list[tuple[float, float, str]]) -> None:
    # words as (start_s, end_s, text) -> cutroom's cache format
    cache.write_text(json.dumps({"v": CACHE_VERSION, "words": [
        {"startMs": s * 1000, "endMs": e * 1000, "word": w} for s, e, w in words
    ]}), encoding="utf-8")


def make_screenstudio(root: Path, sessions: list[list[tuple[str, float]]],
                      clicks: list[float] = (), keys: list[float] = ()) -> Path:
    # a minimal .screenstudio package: one recording scene covering everything,
    # one mic file per session, and input events on screen studio's process clock.
    # session i starts on that clock at 10000 + 100000 * i ms; clicks/keys are given
    # in seconds on the concatenated timeline and converted back to that clock.
    pkg = root / "demo.screenstudio"
    rec = pkg / "recording"
    rec.mkdir(parents=True)
    meta_sessions, offset = [], 0.0
    clock = []
    for i, pattern in enumerate(sessions):
        name = f"channel-2-microphone-{i}.m4a"
        make_audio(rec / name, pattern)
        dur = sum(secs for _, secs in pattern) * 1000
        start = 10000 + 100000 * i
        meta_sessions.append({"durationMs": dur, "outputFilename": name,
                              "processTimeStartMs": start, "processTimeEndMs": start + dur})
        clock.append((offset, start, dur))
        offset += dur

    def to_clock(t_s: float) -> float:
        t = t_s * 1000
        for off, start, dur in clock:
            if off <= t <= off + dur:
                return start + (t - off)
        raise ValueError(t_s)

    (rec / "metadata.json").write_text(json.dumps({"recorders": [
        {"id": "channel-0-input", "type": "input", "sessions": []},
        {"id": "channel-2-microphone", "type": "microphone", "sessions": meta_sessions},
    ]}))
    (rec / "mouseclicks-0.json").write_text(json.dumps(
        [{"type": "mouseDown", "processTimeMs": to_clock(t)} for t in clicks]
        + [{"type": "mouseUp", "processTimeMs": to_clock(t) + 80} for t in clicks]))
    (rec / "keystrokes-0.json").write_text(json.dumps(
        [{"type": "keyDown", "processTimeMs": to_clock(t)} for t in keys]))
    (pkg / "meta.json").write_text(json.dumps({"json": {"version": "test"}}))
    (pkg / "project.json").write_text(json.dumps({"json": {"scenes": [
        {"id": "scene1", "type": "recording",
         "slices": [{"id": "slice1", "sourceStartMs": 0, "sourceEndMs": offset, "speed": 1}]},
    ]}}))
    return pkg


def slices(pkg: Path) -> list[tuple[float, float]]:
    project = json.loads((pkg / "project.json").read_text())["json"]
    return [(s["sourceStartMs"], s["sourceEndMs"])
            for scene in project["scenes"] for s in scene["slices"]]


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())
