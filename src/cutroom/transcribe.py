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


def _mlx_words(audio):
    # audio: a file path, or 16 khz mono float32 samples
    import mlx_whisper

    # condition_on_previous_text=False reduces whisper's repetition loops on silence
    result = mlx_whisper.transcribe(
        audio, path_or_hf_repo=MLX_MODEL,
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


def _faster_whisper_words(samples):
    segments, _info = _faster_whisper_model().transcribe(
        samples, word_timestamps=True, condition_on_previous_text=False,
    )
    for seg in segments:
        for w in seg.words or []:
            yield w.start, w.end, w.word


def _clean(words) -> list[tuple[float, float, str]]:
    return [(s, e, w.strip()) for s, e, w in words if w.strip()]


def transcribe_file(path: Path, backend: str) -> list[tuple[float, float, str]]:
    # (start_s, end_s, word) for one media file
    return _clean(_mlx_words(str(path)) if backend == "mlx" else _faster_whisper_words(load_audio_16k(path)))


def transcribe_samples(samples, backend: str) -> list[tuple[float, float, str]]:
    # the same for 16 khz mono samples already in memory
    return _clean(_mlx_words(samples) if backend == "mlx" else _faster_whisper_words(samples))


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


SAMPLES_PER_MS = 16


def _shown_audio(sessions: list[dict], shown: list[tuple[float, float]]):
    # the samples the ranges play, end to end (what an export of the project
    # sounds like), and per piece (source start ms, source end ms, start ms in the samples)
    import numpy as np

    offsets, acc = [], 0.0
    for s in sessions:
        offsets.append(acc)
        acc += s["durationMs"]
    decoded, chunks, places, at = {}, [], [], 0.0
    for a, b in shown:
        for off, s in zip(offsets, sessions):
            lo, hi = max(a, off), min(b, off + s["durationMs"])
            if hi <= lo or not s.get("hasAudio", True):
                continue
            if s["path"] not in decoded:
                decoded[s["path"]] = load_audio_16k(s["path"])
            x = decoded[s["path"]][int((lo - off) * SAMPLES_PER_MS):int((hi - off) * SAMPLES_PER_MS)]
            if not len(x):
                continue
            places.append((lo, lo + len(x) / SAMPLES_PER_MS, at))
            chunks.append(x)
            at += len(x) / SAMPLES_PER_MS
    return (np.concatenate(chunks) if chunks else np.zeros(0, np.float32)), places


def to_source(words: list[tuple[float, float, str]], places: list[tuple[float, float, float]]) -> list[dict]:
    # word times in the joined samples (s) -> source times (ms). a word belongs
    # to the piece it ends in (whisper's reliable edge: a start after a join
    # often lands before it) and never starts before that piece
    out = []
    for start, end, text in words:
        t = end * 1000
        lo, hi, at = next((p for p in reversed(places) if p[2] < t), places[0])
        out.append({"startMs": lo + max(0.0, start * 1000 - at), "endMs": min(hi, lo + max(0.0, t - at)), "word": text})
    return out


def transcribe_shown(sessions: list[dict], shown: list[tuple[float, float]], cache: Path | None,
                     backend: str | None = None, what: str = "what the project shows") -> list[dict]:
    # the audio the ranges play, transcribed as one piece, in source times: what
    # a screen studio project's slices play, or what a short plays. a transcript
    # of the whole recording is not enough: after a pause whisper often starts a
    # sentence seconds early, deep in the pause, so a word that plays looks cut,
    # and a retake said ten times blurs which take is which. the cache (none for
    # a short: seconds of audio) holds the ranges it was made for.
    key = [[round(a, 1), round(b, 1)] for a, b in shown]
    if cache is not None and cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("v") == CACHE_VERSION and data.get("shown") == key:
            print(f"using cached transcript: {cache.name}")
            return data["words"]
    backend = pick_backend(backend)
    samples, places = _shown_audio(sessions, shown)
    if not places:
        return []
    print(f"transcribing {what} ({len(samples) / SAMPLES_PER_MS / 1000:.0f}s, {backend})...")
    words = to_source(transcribe_samples(samples, backend), places)
    if cache is not None:
        model = MLX_MODEL if backend == "mlx" else FASTER_WHISPER_MODEL
        cache.write_text(json.dumps({"v": CACHE_VERSION, "backend": backend, "model": model,
                                     "shown": key, "words": words}, indent=1), encoding="utf-8")
    return words
