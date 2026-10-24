import json

import pytest

from cutroom import transcribe
from cutroom.transcribe import CACHE_VERSION, load_audio_16k, load_cache, pick_backend
from conftest import make_audio, needs_ffmpeg


def test_flag_beats_env_beats_platform_default(monkeypatch):
    monkeypatch.setenv("CUTROOM_BACKEND", "faster-whisper")
    assert pick_backend("mlx") == "mlx"
    assert pick_backend(None) == "faster-whisper"


def test_platform_default(monkeypatch):
    monkeypatch.delenv("CUTROOM_BACKEND", raising=False)
    monkeypatch.setattr(transcribe, "is_apple_silicon", lambda: False)
    assert pick_backend(None) == "faster-whisper"


def test_unknown_backend_exits(monkeypatch):
    monkeypatch.delenv("CUTROOM_BACKEND", raising=False)
    with pytest.raises(SystemExit, match="unknown transcription backend"):
        pick_backend("whisper-cpp")


def test_cache_versions(tmp_path):
    cache = tmp_path / "x.transcript.json"
    assert load_cache(cache) is None
    cache.write_text(json.dumps({"v": CACHE_VERSION - 1, "words": [1]}))
    assert load_cache(cache) is None
    cache.write_text(json.dumps({"v": CACHE_VERSION, "words": [{"word": "é"}]}), encoding="utf-8")
    assert load_cache(cache) == [{"word": "é"}]


def test_cache_from_other_media_is_stale(tmp_path):
    # a short exported again under the same name must not keep the old transcript
    media = tmp_path / "short.mp4"
    media.write_bytes(b"x" * 100)
    sessions = [{"path": media, "durationMs": 53200.0}]
    cache = tmp_path / "short.transcript.json"
    words = [{"startMs": 0, "endMs": 500, "word": "And"}]
    cache.write_text(json.dumps({"v": CACHE_VERSION, "media": transcribe._media(sessions), "words": words}))
    assert load_cache(cache, sessions) == words
    media.write_bytes(b"x" * 90)  # exported again: other bytes
    assert load_cache(cache, sessions) is None
    assert load_cache(cache) == words  # without the sessions, no check


def test_old_cache_is_stale_when_its_words_run_past_the_media(tmp_path):
    # caches from before "media" was kept: a re-export that got shorter still shows
    media = tmp_path / "short.mp4"
    media.write_bytes(b"x")
    sessions = [{"path": media, "durationMs": 53200.0}]
    cache = tmp_path / "short.transcript.json"
    cache.write_text(json.dumps({"v": CACHE_VERSION, "words": [{"startMs": 115000, "endMs": 115600, "word": "yourself."}]}))
    assert load_cache(cache, sessions) is None
    cache.write_text(json.dumps({"v": CACHE_VERSION, "words": [{"startMs": 52000, "endMs": 52900, "word": "you."}]}))
    assert load_cache(cache, sessions) == [{"startMs": 52000, "endMs": 52900, "word": "you."}]


@needs_ffmpeg
def test_audio_is_decoded_to_16k_mono_float_by_ffmpeg(tmp_path):
    samples = load_audio_16k(make_audio(tmp_path / "a.m4a", [("tone", 1), ("silence", 1)]))
    assert samples.dtype.name == "float32"
    assert abs(len(samples) - 32000) < 1600
    assert abs(samples[:8000]).max() > 0.1 and abs(samples[-4000:]).max() < 0.01
