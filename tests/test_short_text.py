# the text on a finished short: the copy a short carries in the project file
# (headline and calls to action, proposed by an agent, approved by a person),
# what the review page gets of it, the job file `cutroom export --text` writes
# for the shorts-text skill, and the check for a phrase said twice

import json
import re

import pytest
from conftest import make_video, needs_ffmpeg, write_transcript
from test_shorts import PATTERN, page, write

from cutroom import project
from cutroom.cli import main
from cutroom.review import find_words, repeat_flags

# 0-2 speech, 2-4 pause, 4-6 speech, 6-8 pause, 8-10 speech
WORDS = [(0.1, 0.9, "Widgets"), (0.9, 1.9, "work."),
         (4.1, 4.9, "We"), (4.9, 5.4, "got"), (5.4, 5.9, "demos."),
         (8.1, 8.9, "Keep"), (8.9, 9.9, "going.")]
COPY = {"status": "proposed", "texts": [
    {"kind": "headline", "text": "Android widgets\nare here!"},
    {"kind": "cta", "text": "comment “code” for the repo link", "at": "got demos"},
    {"kind": "cta", "text": "full video on YouTube!", "at": "last sentence"}]}


@pytest.fixture
def talk(tmp_path):
    video = make_video(tmp_path / "talk.mp4", PATTERN)
    write_transcript(video.with_suffix(".transcript.json"), WORDS)
    return video


def words(text: str, step: float = 0.4) -> list[list]:
    # one piece of [time, word] pairs, a word every 0.4 s
    return [[[round(i * step, 2), w] for i, w in enumerate(text.split())]]


def test_a_shorts_copy_is_checked_when_the_project_file_loads(tmp_path):
    src = tmp_path / "talk.mp4"
    ok = {"id": "S1", "start": 0.0, "end": 2.0, "copy": COPY}
    write(src, [ok])
    assert project.load(src)["shorts"][0]["copy"] == COPY
    bad = [
        ({"texts": []}, "must look like"),
        ({"status": "done", "texts": COPY["texts"]}, '"proposed" or "approved"'),
        ({"texts": [{"kind": "title", "text": "x"}]}, '"headline" or "cta"'),
        ({"texts": [{"kind": "cta", "text": "x"}]}, 'needs "at"'),
        ({"texts": [{"kind": "headline", "text": " "}]}, 'needs a "text"'),
        ({"texts": [{"kind": "cta", "text": "x", "at": "y", "hold": 0}]}, '"hold" must be a positive number'),
        ({"texts": [{"kind": "cta", "text": "x", "at": "y", "until": "later"}]}, '"until" can only be "end"'),
        ({"texts": [{"kind": "cta", "text": "x", "at": "y", "colour": "red"}]}, "unknown keys ['colour']"),
        ({"texts": [{"kind": "headline", "text": "a"}, {"kind": "headline", "text": "b"}]}, "more than one headline"),
    ]
    for copy, message in bad:
        write(src, [{**ok, "copy": copy}])
        with pytest.raises(SystemExit, match=re.escape(message)):
            project.load(src)


@needs_ffmpeg
def test_the_page_shows_each_text_with_the_words_it_starts_on(talk):
    write(talk, [{"id": "S1", "title": "widgets", "start": 0.0, "end": 10.0, "copy": COPY},
                 {"id": "S2", "title": "no text", "start": 0.0, "end": 2.0},
                 {"id": "S3", "title": "wrong words", "start": 0.0, "end": 10.0,
                  "copy": {"texts": [{"kind": "cta", "text": "full video", "at": "never said"}]}}])
    main(["review", str(talk)])
    s1, s2, s3 = page(talk)["shorts"]
    head, mid, end = s1["copy"]["texts"]
    assert s1["copy"]["status"] == "proposed"
    assert head["text"] == "Android widgets\nare here!" and head["found"]
    # "got demos" is said at 4.9 s in the source; the pauses before it are cut in the short
    assert mid["found"] and mid["atWords"].startswith("got demos.")
    assert 0 < mid["atSec"] < 4.9
    assert end["atWords"].startswith("Keep going.") and end["atSec"] > mid["atSec"]
    assert not any(f.startswith("text ") for f in s1["flags"])
    assert "copy" not in s2
    assert s3["copy"]["texts"][0]["found"] is False
    assert 'text "full video" starts on "never said", which the short does not say' in s3["flags"]


def test_a_text_finds_its_words_when_the_two_transcripts_differ_in_small_words():
    toks = ["what", "else", "do", "we", "got", "got", "a", "few", "more", "demos", "within", "the", "app"]
    # the export's transcript heard "We got a few more demos", the video's only "got a few more demos"
    assert find_words(toks, "We got a few more demos") == 5
    assert find_words(toks, "a few more demos") == 6
    # content words skip only small words: "more" is not one, so "a few demos" is not said
    assert find_words(toks, "a few demos") is None
    assert find_words(toks, "more apps") is None


def test_a_phrase_said_twice_close_together_is_flagged():
    # sdk 58 S6: Rami cut the second telling by hand
    s6 = words("It's available both on Android and iOS. You can also now add variables to your SVGs, "
               "both in Android and iOS, through the Expo image package.", step=0.35)
    assert repeat_flags(s6) == ['says it twice, 5 s apart: "both on Android and iOS" / "both in Android and iOS"']
    # a retake said straight after the first try
    assert repeat_flags(words("The subtle art of not giving an F. The subtle art of not giving an F. But of course")) == [
        'says it twice, 3 s apart: "subtle art of not giving an F" / "subtle art of not giving an F"']


def test_a_parallel_an_idiom_or_a_late_recap_is_not_flagged():
    # two sentences that share an opening and then go different ways
    assert repeat_flags(words("the consequences of pursuing something you don't care about is so high. "
                              "But the consequences of pursuing something you deeply care about is so low.")) == []
    assert repeat_flags(words("for others who want to make friends who want to make the best of it")) == []
    # an idiom said twice: three words
    assert repeat_flags(words("you'd run this every single time, and it costs tokens every single time.")) == []
    # a recap at the end of the short, 17 s after the first telling
    recap = words("in the span of two minutes, you get a config file", step=0.4)[0]
    later = [[t + 17, w] for t, w in words("All in the span of two minutes.")[0]]
    assert repeat_flags([recap + later]) == []


@needs_ffmpeg
def test_review_prints_each_shorts_checks(talk, capsys):
    write(talk, [{"id": "S1", "title": "cut off", "start": 4.0, "end": 5.0},
                 {"id": "S2", "title": "fine", "start": 0.0, "end": 2.0}])
    main(["review", str(talk)])
    out = capsys.readouterr().out
    assert "shorts to check (1 of 2):" in out
    assert '  S1: ends mid-sentence: "...We"' in out
    assert "S2:" not in out


@needs_ffmpeg
def test_export_text_writes_the_job_for_approved_copy(talk, tmp_path, capsys):
    export = make_video(tmp_path / "talk-S1.mp4", PATTERN)
    write(talk, [{"id": "S1", "title": "widgets", "start": 0.0, "end": 10.0, "copy": {**COPY, "status": "approved"}}])
    main(["export", str(talk), "S1", "--text", str(export)])
    job = json.loads(export.with_suffix(".text.json").read_text(encoding="utf-8"))
    assert job == {"video": str(export.resolve()), "short": "S1",
                   "project": str(project.project_path(talk.resolve())), "texts": COPY["texts"]}
    assert "wrote shorts-text job" in capsys.readouterr().out
    # the job is the copy, nothing else: no fcpxml next to the source
    assert not list(tmp_path.glob("*.fcpxml"))


@needs_ffmpeg
def test_export_text_refuses_copy_that_is_not_approved(talk, tmp_path, capsys):
    export = make_video(tmp_path / "talk-S1.mp4", PATTERN)
    write(talk, [{"id": "S1", "start": 0.0, "end": 10.0, "copy": COPY},
                 {"id": "S2", "start": 0.0, "end": 2.0}])
    with pytest.raises(SystemExit, match="not approved yet"):
        main(["export", str(talk), "S1", "--text", str(export)])
    assert not export.with_suffix(".text.json").exists()
    main(["export", str(talk), "S1", "--text", str(export), "--force"])
    assert "(copy not approved)" in capsys.readouterr().out
    with pytest.raises(SystemExit, match='S2 has no "copy"'):
        main(["export", str(talk), "S2", "--text", str(export)])
    with pytest.raises(SystemExit, match="one short"):
        main(["export", str(talk), "S1", "S2", "--text", str(export)])
    with pytest.raises(SystemExit, match="as a video file"):
        main(["export", str(talk), "S1", "--text", str(tmp_path / "missing.mp4")])
