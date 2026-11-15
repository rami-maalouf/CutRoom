# the highlight-reel job: `cutroom export <source> S5 --reel` hands the
# pieces a reel plays, in its own order, with the words heard in each, to the
# highlight-reel skill in openmontage. the look and the music live there.

import json

import pytest
from conftest import make_video, needs_ffmpeg, write_transcript
from test_shorts import PATTERN, WORDS, write

from cutroom.cli import main

REEL = {"style": "joy", "cards": [{"kind": "title", "text": "keep going.", "after": 1}]}


@pytest.fixture
def talk(tmp_path):
    video = make_video(tmp_path / "talk.mp4", PATTERN)
    write_transcript(video.with_suffix(".transcript.json"), WORDS)
    return video


@needs_ffmpeg
def test_the_reel_job_lists_each_piece_in_play_order_with_its_words(talk):
    # played out of recorded order: the end first, then the opening
    write(talk, [{"id": "S1", "title": "reel", "raw": True, "reel": REEL, "segments": [
        {"start": 8.0, "end": 10.0, "beat": "payoff", "music": "out"},
        {"start": 0.0, "end": 2.0, "beat": "hook", "captions": False}]}])
    main(["export", str(talk), "S1", "--reel"])
    job = json.loads((talk.parent / "talk-S1.reel.json").read_text())
    assert job["short"] == "S1" and job["reel"] == REEL
    assert job["segments"] == [{"beat": "payoff", "music": "out"}, {"beat": "hook", "captions": False}]
    first, second = job["pieces"]
    assert first["segment"] == 0 and second["segment"] == 1
    assert first["file"] == str(talk.resolve())
    assert [w[2] for w in first["words"]] == ["Keep", "going."]
    assert [w[2] for w in second["words"]] == ["Rejection", "redirects."]
    # word times are seconds from the start of their own piece
    assert 0 <= first["words"][0][0] < 0.5
    assert first["words"][-1][1] <= first["end"] - first["start"] + 0.01
    assert 3.5 < job["seconds"] < 4.5


@needs_ffmpeg
def test_a_reel_job_needs_the_reel_block(talk):
    write(talk, [{"id": "S1", "title": "plain", "start": 0.0, "end": 2.0}])
    with pytest.raises(SystemExit, match='has no "reel"'):
        main(["export", str(talk), "S1", "--reel"])
