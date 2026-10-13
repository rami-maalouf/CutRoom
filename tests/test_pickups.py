# talking heads to record (pickups): planned in the project file, shown where
# they will play in the read-through, the review page and the exported timeline

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from cutroom import project
from cutroom.cli import main
from conftest import needs_ffmpeg
from test_fcpxml import FCP_DTDS
from test_folder import page_data, save, shoot  # noqa: F401  (fixture)

pytestmark = needs_ffmpeg

SELECTS = [
    {"id": "V1", "clip": "phone/c.mov", "start": 0.0, "end": 1.9, "chapter": "Morning"},
    {"id": "V2", "clip": "cam/a.mp4", "start": 4.0, "end": 6.0, "chapter": "Noon"},
]
CARD = {"id": "P1", "after": "V1", "purpose": "why a question on a card is easier to answer",
        "points": ["the card asks, not you", "skip is always allowed"], "seconds": 15}


def test_a_pickup_plays_after_its_select_in_the_read_through(shoot):
    save(shoot, selects=SELECTS, pickups=[
        CARD,
        {"id": "P2", "after": "start", "kind": "voiceover", "purpose": "who I am and why I do this"},
        {"id": "P3", "purpose": "a story idea, not placed yet", "near": {"clip": "cam/a.mp4", "time": 4.5}},
    ])
    main(["script", str(shoot)])
    text = (shoot / "cutroom" / "script.md").read_text(encoding="utf-8")
    assert "+ 0:35.0 to record (2 talking heads)" in text  # P1 15 s + P2 20 s by default
    assert text.index("P2  voiceover to record") < text.index("### V1") < text.index("### P1  talking head")
    assert text.index("### P1") < text.index("### V2") < text.index("## To record, not placed yet") < text.index("### P3")
    assert "- skip is always allowed" in text
    assert "near: cam/a.mp4 0:04.5" in text


def test_the_review_page_and_the_vlog_export_carry_pickups(shoot):
    save(shoot, selects=SELECTS, pickups=[CARD])
    main(["review", str(shoot)])
    assert page_data(shoot)["pickups"][0]["purpose"] == CARD["purpose"]
    main(["export", str(shoot), "vlog"])
    root = ET.parse(shoot / "cutroom" / "exports" / "shoot-vlog.fcpxml").getroot()
    clips = root.findall(".//spine/asset-clip")
    # the marker sits at the end of V1, the last clip before the talking head goes in
    marks = [m.get("value") for m in clips[0].iter("marker")]
    assert marks == [f"P1 to record (15 s): {CARD['purpose']}"]
    assert not list(clips[-1].iter("marker"))
    if FCP_DTDS and shutil.which("xmllint"):
        dtd = shoot / "fcpxml.dtd"
        shutil.copyfile(FCP_DTDS[0], dtd)
        result = subprocess.run(["xmllint", "--noout", "--dtdvalid", str(dtd),
                                 str(shoot / "cutroom" / "exports" / "shoot-vlog.fcpxml")], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_new_selects_unplace_pickups(shoot, capsys):
    save(shoot, selects=SELECTS, pickups=[CARD, {"id": "P2", "after": "start", "purpose": "the intro"}])
    cand = shoot / "cutroom" / "candidates"
    cand.mkdir(parents=True)
    (cand / "part-1.json").write_text(json.dumps([{"clip": "cam/a.mp4", "start": 4.0, "end": 5.9}]))
    main(["candidates", str(shoot), "--write-selects", "--story-order"])
    pickups = json.loads(project.project_path(shoot).read_text(encoding="utf-8"))["pickups"]
    assert "after" not in pickups[0] and pickups[1]["after"] == "start"
    assert "P1 are no longer placed" in capsys.readouterr().out


@pytest.mark.parametrize("pickup, error", [
    ({"id": "X1", "purpose": "x"}, "unique id like P1"),
    ({"id": "P1"}, 'needs a "purpose"'),
    ({"id": "P1", "purpose": "x", "after": "V9"}, "which is not a select"),
    ({"id": "P1", "purpose": "x", "kind": "interview"}, '"kind" must be one of'),
    ({"id": "P1", "purpose": "x", "seconds": 0}, '"seconds" must be a positive number'),
    ({"id": "P1", "purpose": "x", "points": "one"}, '"points" must be a list'),
    ({"id": "P1", "purpose": "x", "near": {"clip": "cam/zzz.mp4", "time": 1}}, "which is not in the folder"),
    ({"id": "P1", "purpose": "x", "near": {"clip": "cam/a.mp4"}}, '"near" must be'),
])
def test_bad_pickups_are_clear_errors(shoot, pickup, error):
    save(shoot, selects=SELECTS, pickups=[pickup])
    with pytest.raises(SystemExit, match=error):
        main(["review", str(shoot)])
