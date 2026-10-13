# shorts review: the fields the review page sorts and groups by, each short's
# words for the page, and the edge checks that start the standalone gate

import json
import re

import pytest

from cutroom import project
from cutroom.cli import main
from cutroom.review import edge_flags
from conftest import make_video, needs_ffmpeg, write_transcript

# 0-2 speech, 2-4 pause, 4-6 speech, 6-8 pause, 8-10 speech
PATTERN = [("tone", 2), ("silence", 2), ("tone", 2), ("silence", 2), ("tone", 2)]
WORDS = [(0.1, 0.9, "Rejection"), (0.9, 1.9, "redirects."),
         (4.1, 4.9, "because"), (4.9, 5.9, "it"),
         (8.1, 8.9, "Keep"), (8.9, 9.9, "going.")]


def page(src):
    html = src.with_suffix(".review.html").read_text(encoding="utf-8")
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))


def write(src, shorts):
    project.save(src, {"v": 2, "edits": {"cuts": [], "keeps": []}, "shorts": shorts})


@pytest.fixture
def talk(tmp_path):
    video = make_video(tmp_path / "talk.mp4", PATTERN)
    write_transcript(video.with_suffix(".transcript.json"), WORDS)
    return video


@needs_ffmpeg
def test_the_page_gets_each_shorts_words_by_piece_and_its_edge_checks(talk):
    write(talk, [
        {"id": "S1", "title": "redirects", "theme": "Rejection", "rank": 1, "score": 8.5,
         "scores": {"hook": 8, "payoff": 9}, "tags": ["v04"],
         "segments": [{"start": 0.0, "end": 2.0}, {"start": 8.0, "end": 10.0}]},
        {"id": "S2", "title": "leans on what came before", "start": 4.0, "end": 6.0},
    ])
    main(["review", str(talk)])
    s1, s2 = page(talk)["shorts"]
    assert [[w for _, w in piece] for piece in s1["pieces"]] == [["Rejection", "redirects."], ["Keep", "going."]]
    assert s1["pieces"][1][0][0] == pytest.approx(8.1)  # source time, to mark the word being said
    assert s1["seconds"] == pytest.approx(sum(e - s for s, e in s1["keeps"]), abs=0.01)
    assert s1["flags"] == []
    assert (s1["theme"], s1["rank"], s1["score"], s1["tags"]) == ("Rejection", 1, 8.5, ["v04"])
    assert s2["flags"] == ['opens on "because"', 'ends mid-sentence: "...it"']


def test_edge_flags_read_the_first_and_last_words():
    assert edge_flags([[[0, "So"], [1, "yeah."]]]) == ['opens on "So"']
    assert edge_flags([[[0, "places,"], [1, "strangers."]]]) == ['starts mid-sentence: "places,"']
    assert edge_flags([[[0, "I"], [1, "left."]], [[5, "Why?"]]]) == []
    assert edge_flags([[[0, "Who"], [1, "knew"]]]) == ['ends mid-sentence: "...knew"']
    assert edge_flags([[]]) == []


@pytest.mark.parametrize("field, value, message", [
    ("rank", 0, '"rank" must be a whole number'),
    ("rank", True, '"rank" must be a whole number'),
    ("score", 11, '"score" must be a number from 0 to 10'),
    ("scores", {"hook": "high"}, '"scores" must look like'),
    ("tags", "v04", '"tags" must be a list of text'),
    ("theme", 3, '"theme" must be text'),
])
def test_review_fields_are_checked(tmp_path, field, value, message):
    src = tmp_path / "talk.mp4"
    write(src, [{"id": "S1", "start": 0, "end": 1, field: value}])
    with pytest.raises(SystemExit, match=message):
        project.load(src)


@needs_ffmpeg
def test_a_talking_head_in_linked_files_reviews_as_an_edit_with_its_shorts(tmp_path):
    # a talking head recorded in several files, linked into one folder from where they live
    store = tmp_path / "drive"
    store.mkdir()
    make_video(store / "a.mp4", PATTERN, "-metadata", "creation_time=2026-04-12T19:00:00Z")
    make_video(store / "b.mp4", PATTERN, "-metadata", "creation_time=2026-07-01T23:00:00Z")
    root = tmp_path / "story"
    root.mkdir()
    try:
        for name in ("a.mp4", "b.mp4"):
            (root / name).symlink_to(store / name)
    except OSError:
        pytest.skip("this system does not allow symbolic links")
    transcripts = root / "cutroom" / "transcripts"
    transcripts.mkdir(parents=True)
    for name in ("a.mp4", "b.mp4"):
        write_transcript(transcripts / f"{name}.transcript.json", WORDS)
    project.save(root, {"v": 2, "style": "talking-head", "edits": {"cuts": [], "keeps": []}, "shorts": [
        {"id": "S1", "title": "across two files", "theme": "Rejection",
         "segments": [{"clip": "a.mp4", "start": 0.0, "end": 2.0}, {"clip": "b.mp4", "start": 8.0, "end": 10.0}]}]})
    main(["review", str(root)])
    html = (root / "cutroom" / "review.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))
    assert data["style"] == "talking-head" and [m["name"] for m in data["media"]] == ["a.mp4", "b.mp4"]
    assert [[w for _, w in p] for p in data["shorts"][0]["pieces"]] == [["Rejection", "redirects."], ["Keep", "going."]]
