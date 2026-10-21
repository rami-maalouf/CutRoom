# the inclusion list: an agent's verdict on every moment worth judging, "in" or
# "out" with the reason, so a moment left out can be seen and brought back

import json

import pytest

from cutroom import project
from cutroom.cli import main
from conftest import needs_ffmpeg
from test_folder import page_data, save, shoot  # noqa: F401 (fixture)

pytestmark = needs_ffmpeg


def write(shoot, name, items):
    path = shoot / "cutroom" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items), encoding="utf-8")


def test_verdicts_become_inclusions_in_capture_order_and_are_checked(shoot, capsys):
    write(shoot, "candidates/part-1.json", [
        {"clip": "cam/a.mp4", "start": 0.0, "end": 6.0, "chapter": "Noon", "title": "the whole scene"}])
    write(shoot, "inclusions/part-1.json", [
        {"clip": "cam/a.mp4", "start": 0.0, "end": 6.0, "verdict": "in", "why": "the scene", "title": "noon",
         "chapter": "Noon"},
        {"clip": "phone/c.mov", "start": 0.0, "end": 6.0, "verdict": "out", "why": "repeats noon",
         "title": "morning"},
        {"clip": "phone/c.mov", "start": 4.0, "end": 6.0, "verdict": "in", "why": "should play",
         "title": "missing"},
        {"clip": "cam/a.mp4", "start": 0.0, "end": 1.0, "verdict": "maybe", "why": "?"},
    ])
    main(["candidates", str(shoot), "--write-selects", "--story-order"])
    out = capsys.readouterr().out
    assert "needs \"verdict\"" in out
    assert "inclusions: 2 in, 1 out" in out
    assert "I2 is in, but no select plays it (missing)" in out
    data = json.loads(project.project_path(shoot).read_text(encoding="utf-8"))
    # capture order: c (morning) before a (noon)
    assert [(m["id"], m["clip"], m["verdict"]) for m in data["inclusions"]] == [
        ("I1", "phone/c.mov", "out"), ("I2", "phone/c.mov", "in"), ("I3", "cam/a.mp4", "in")]
    assert data["inclusions"][2]["chapter"] == "Noon"


def test_review_page_and_read_through_show_the_verdicts(shoot):
    save(shoot,
         selects=[{"id": "V1", "clip": "cam/a.mp4", "start": 0.0, "end": 6.0, "chapter": "Noon"}],
         inclusions=[
             {"id": "I1", "clip": "phone/c.mov", "start": 0.0, "end": 6.0, "verdict": "out",
              "why": "repeats noon", "title": "morning"},
             {"id": "I2", "clip": "cam/a.mp4", "start": 0.0, "end": 6.0, "verdict": "in", "why": "the scene"}])
    main(["review", str(shoot)])
    moments = {m["id"]: m for m in page_data(shoot)["inclusions"]}
    assert moments["I2"]["selects"] == ["V1"] and moments["I1"]["selects"] == []
    assert moments["I1"]["text"] == "Hello everyone. Welcome back."
    assert moments["I1"]["range"][1] - moments["I1"]["range"][0] == pytest.approx(6.0)
    page = (shoot / "cutroom" / "review.html").read_text(encoding="utf-8")
    assert "data-bring-back" in page
    main(["script", str(shoot)])
    script = (shoot / "cutroom" / "script.md").read_text(encoding="utf-8")
    assert "## Left out (1 of 2 judged moments)" in script
    assert "- I1  morning  (phone/c.mov 0:00.0-0:06.0): repeats noon" in script


def test_an_out_moment_that_plays_is_reported(shoot):
    data = {"selects": [{"id": "V1", "clip": "cam/a.mp4", "start": 0.0, "end": 3.0}],
            "inclusions": [{"id": "I1", "clip": "cam/a.mp4", "start": 2.0, "end": 6.0, "verdict": "out", "why": "x"},
                           {"id": "I2", "clip": "cam/a.mp4", "start": 2.8, "end": 6.0, "verdict": "out", "why": "y"}]}
    # I2 only touches the end of V1 (0.2 s): an edge, not a moment that plays
    assert project.inclusion_problems(data, {"cam/a.mp4": 0.0}) == ["I1 is out, but V1 play part of it ()"]


@pytest.mark.parametrize("item, message", [
    ({"id": "X1", "clip": "cam/a.mp4", "start": 0, "end": 1, "verdict": "in", "why": "w"}, "unique id like I1"),
    ({"id": "I1", "clip": "cam/a.mp4", "start": 0, "end": 1, "verdict": "keep", "why": "w"}, '"verdict" must be'),
    ({"id": "I1", "clip": "cam/a.mp4", "start": 0, "end": 1, "verdict": "out"}, 'needs a "why"'),
    ({"id": "I1", "start": 0, "end": 1, "verdict": "out", "why": "w"}, 'needs a "clip"'),
])
def test_inclusions_are_validated(shoot, item, message):
    save(shoot, inclusions=[item])
    with pytest.raises(SystemExit, match=message):
        main(["review", str(shoot)])
