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
