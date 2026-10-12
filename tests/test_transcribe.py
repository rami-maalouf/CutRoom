import json

import pytest

from cutroom import transcribe
from cutroom.transcribe import CACHE_VERSION, load_cache, pick_backend


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


def test_audio_is_decoded_to_16k_mono_float_by_ffmpeg(tmp_path):
    from conftest import make_audio, needs_ffmpeg
    from cutroom.transcribe import load_audio_16k

    if needs_ffmpeg.args[0]:
        pytest.skip("ffmpeg not installed")
    samples = load_audio_16k(make_audio(tmp_path / "a.m4a", [("tone", 1), ("silence", 1)]))
    assert samples.dtype.name == "float32"
    assert abs(len(samples) - 32000) < 1600
    assert abs(samples[:8000]).max() > 0.1 and abs(samples[-4000:]).max() < 0.01
