# local word-level transcription with two interchangeable backends running the
# same whisper large-v3-turbo weights, so cut decisions match across machines:
# - mlx: apple silicon (metal), the default on m-series macs
# - faster-whisper: ctranslate2 on cpu or cuda - linux, windows, intel macs
# transcription is the slow step, so results are cached next to the media.

import functools
import importlib.util
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

CACHE_VERSION = 3
MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
FASTER_WHISPER_MODEL = "large-v3-turbo"
BACKENDS = ("mlx", "faster-whisper")


def is_apple_silicon() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def pick_backend(requested: str | None = None) -> str:
    # explicit flag > CUTROOM_BACKEND env > platform default
    choice = requested or os.environ.get("CUTROOM_BACKEND") or "auto"
    if choice != "auto":
        if choice not in BACKENDS:
            sys.exit(f"unknown transcription backend {choice!r}, expected one of {BACKENDS}")
        return choice
    if is_apple_silicon() and importlib.util.find_spec("mlx_whisper"):
        return "mlx"
    return "faster-whisper"


def _mlx_words(path: Path):
    import mlx_whisper

    # condition_on_previous_text=False reduces whisper's repetition loops on silence
    result = mlx_whisper.transcribe(
        str(path), path_or_hf_repo=MLX_MODEL,
        word_timestamps=True, condition_on_previous_text=False,
    )
    for seg in result["segments"]:
        for w in seg.get("words", []):
            yield w["start"], w["end"], w["word"]


@functools.cache
def _faster_whisper_model():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is not installed - install cutroom with the "
                 "faster-whisper extra: uv tool install 'cutroom[faster-whisper]'")
    # auto picks cuda when available and the fastest compute type the device supports
    return WhisperModel(FASTER_WHISPER_MODEL, device="auto", compute_type="auto")


def load_audio_16k(path: Path):
    # mono 16 khz float32 samples, decoded by ffmpeg exactly like mlx-whisper
    # does. faster-whisper's own decoder (pyav) breaks across pyav releases.
    import numpy as np

    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0",
         "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, np.float32)


def _faster_whisper_words(path: Path):
    segments, _info = _faster_whisper_model().transcribe(
        load_audio_16k(path), word_timestamps=True, condition_on_previous_text=False,
    )
    for seg in segments:
        for w in seg.words or []:
            yield w.start, w.end, w.word


def transcribe_file(path: Path, backend: str) -> list[tuple[float, float, str]]:
    # (start_s, end_s, word) for one media file
    words = _mlx_words(path) if backend == "mlx" else _faster_whisper_words(path)
    return [(s, e, w.strip()) for s, e, w in words if w.strip()]


def load_cache(cache: Path) -> list[dict] | None:
    if not cache.exists():
        return None
    data = json.loads(cache.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("v") == CACHE_VERSION:
        return data["words"]
    return None


def _transcribe_into(cache: Path, sessions: list[dict], backend: str | None) -> list[dict]:
    # one cache file for these sessions laid end to end
    cached = load_cache(cache)
    if cached is not None:
        return cached
    if cache.exists():
        print(f"{cache.name} is an older format, re-transcribing")
    backend = pick_backend(backend)
    words = []
    offset_ms = 0.0
    for session in sessions:
        if session.get("hasAudio", True):
            print(f"transcribing {session['path'].name} ({session['durationMs'] / 1000:.0f}s, {backend})...")
            for start, end, text in transcribe_file(session["path"], backend):
                words.append({
                    "startMs": offset_ms + start * 1000,
                    "endMs": offset_ms + min(end * 1000, session["durationMs"]),
                    "word": text,
                })
        offset_ms += session["durationMs"]
    model = MLX_MODEL if backend == "mlx" else FASTER_WHISPER_MODEL
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({"v": CACHE_VERSION, "backend": backend, "model": model, "words": words}, indent=1),
        encoding="utf-8",
    )
    return words


def transcribe_sessions(sessions: list[dict], cache: Path | None, backend: str | None = None) -> list[dict]:
    # word timings {"startMs", "endMs", "word"} on the concatenated timeline.
    # with a cache path, all sessions share one cache (a screen studio recording);
    # with None, each session carries its own "cache" (a folder of clips), so
    # adding a clip later only transcribes that clip.
    if cache is not None:
        hit = load_cache(cache) is not None
        words = _transcribe_into(cache, sessions, backend)
        print(f"{'using cached' if hit else 'cached'} transcript: {cache.name}")
        return words
    words, offset_ms, fresh = [], 0.0, 0
    for session in sessions:
        fresh += load_cache(session["cache"]) is None and session.get("hasAudio", True)
        for w in _transcribe_into(session["cache"], [session], backend):
            words.append({**w, "startMs": w["startMs"] + offset_ms, "endMs": w["endMs"] + offset_ms})
        offset_ms += session["durationMs"]
    print(f"transcripts: {len(sessions)} clips ({fresh} transcribed now, the rest cached)")
    return words
