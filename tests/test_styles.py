# video styles (talking head vs vlog), raw moments, the read-through and the story

import json
import re

import pytest

from cutroom import project
from cutroom.cli import main
from cutroom.review import markdown
from conftest import make_video, needs_ffmpeg, write_transcript
from test_folder import SPEECH, WORDS, page_data, save, shoot  # noqa: F401  (fixture)

pytestmark = needs_ffmpeg


def test_a_folder_is_a_vlog_and_a_file_is_a_talking_head(tmp_path, shoot, capsys):
    main(["review", str(shoot)])
    assert "style: vlog (pacing relaxed, retakes off)" in capsys.readouterr().out
    video = make_video(tmp_path / "talk.mp4", SPEECH)
    write_transcript(video.with_suffix(".transcript.json"), WORDS)
    main(["review", str(video)])
    assert "style: talking-head (pacing balanced, retakes on)" in capsys.readouterr().out


def test_explicit_flags_and_the_project_style_win(tmp_path, capsys):
    video = make_video(tmp_path / "talk.mp4", SPEECH)
    write_transcript(video.with_suffix(".transcript.json"), WORDS)
    project.save(video, {"v": 2, "style": "vlog", "edits": {"cuts": [], "keeps": []}, "selects": [], "shorts": []})
    main(["review", str(video), "--pacing", "tight", "--retakes"])
    assert "style: vlog (pacing tight, retakes on)" in capsys.readouterr().out


def test_unknown_style_is_refused(tmp_path):
    video = make_video(tmp_path / "talk.mp4", SPEECH)
    project.save(video, {"v": 2, "style": "podcast", "edits": {"cuts": [], "keeps": []}})
    with pytest.raises(SystemExit, match="style must be one of"):
        main(["review", str(video)])


def test_a_raw_moment_keeps_its_pauses(shoot):
    save(shoot, selects=[{"id": "V1", "clip": "phone/c.mov", "start": 0.0, "end": 6.0},
                         {"id": "V2", "clip": "cam/a.mp4", "start": 0.0, "end": 6.0, "raw": True}])
    main(["review", str(shoot), "--pacing", "tight"])
    selects = {s["id"]: s for s in page_data(shoot)["selects"]}
    assert len(selects["V1"]["keeps"]) == 2          # the 2 s pause inside is cut
    assert len(selects["V2"]["keeps"]) == 1          # raw: plays as it happened
    assert selects["V2"]["raw"] is True


def test_read_through_shows_chapters_tags_and_cuts_inside(shoot):
    save(shoot, selects=[
        {"id": "V1", "clip": "phone/c.mov", "start": 0.0, "end": 6.0, "chapter": "Morning",
         "beat": "arrival", "role": "setup", "intent": "open on the premise"},
        {"id": "V2", "clip": "cam/broll.mp4", "start": 0.0, "end": 3.0, "chapter": "Evening", "raw": True},
    ])
    main(["script", str(shoot), "--pacing", "tight"])
    text = (shoot / "cutroom" / "script.md").read_text()
    assert "## Morning" in text and "## Evening" in text
    assert "### V1" in text and "arrival · setup" in text and "intent: open on the premise" in text
    assert "> Hello everyone. / Welcome back." in text   # the pause between them was cut
    assert "> (no speech)" in text and "raw" in text


def test_story_tab_renders_the_outline(shoot):
    (shoot / "cutroom" / "story.md").write_text("# The story\n\nTwo people, a box of ducks.\n\n"
                                                 "- hook: cold open\n\n| beat | budget |\n|---|---|\n| intro | 0:30 |\n")
    main(["review", str(shoot)])
    story = page_data(shoot)["story"]
    assert "<h3>The story</h3>" in story and "<li>hook: cold open</li>" in story
    assert "<th>beat</th>" in story and "<td>0:30</td>" in story


def test_markdown_escapes_html():
    assert "&lt;script&gt;" in markdown("a <script> b")


def test_story_order_keeps_beats_and_their_fields(shoot):
    cand = shoot / "cutroom" / "candidates"
    cand.mkdir(parents=True)
    (cand / "part-1.json").write_text(json.dumps([
        {"clip": "cam/a.mp4", "start": 4.0, "end": 5.9, "chapter": "Cold open", "beat": "hook", "role": "hook", "raw": True},
        {"clip": "phone/c.mov", "start": 0.0, "end": 1.9, "chapter": "Morning", "beat": "arrival", "role": "setup",
         "intent": "open the day"},
    ]))
    main(["candidates", str(shoot), "--write-selects", "--story-order"])
    selects = json.loads(project.project_path(shoot).read_text())["selects"]
    assert [s["clip"] for s in selects] == ["cam/a.mp4", "phone/c.mov"]  # not capture order
    assert selects[0]["raw"] is True and selects[1]["intent"] == "open the day"


def test_a_reordered_talking_head_exports_and_renders_in_select_order(tmp_path):
    from conftest import probe_duration
    video = make_video(tmp_path / "talk.mp4", SPEECH)
    write_transcript(video.with_suffix(".transcript.json"), WORDS)
    # the closing line moved to the front as a hook, then the opening
    project.save(video, {"v": 2, "edits": {"cuts": [], "keeps": []}, "shorts": [], "selects": [
        {"id": "V1", "start": 4.0, "end": 6.0}, {"id": "V2", "start": 0.0, "end": 2.0}]})
    main(["video", str(video), "--yes", "--export", "fcpxml"])
    import xml.etree.ElementTree as ET
    from fractions import Fraction
    starts = [Fraction(c.get("start").rstrip("s")) for c in
              ET.parse(tmp_path / "talk-clean.fcpxml").getroot().findall(".//spine/asset-clip")]
    assert starts[0] > starts[1]  # V1 (later in the source) plays first
    main(["video", str(video), "--yes"])
    assert 3.4 < probe_duration(tmp_path / "talk-clean.mp4") < 4.6
