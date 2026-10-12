# the review and iteration loop end to end: project file edits, the review
# page data, short export and final cut pro read-back

import json
import re
import xml.etree.ElementTree as ET
from fractions import Fraction

import pytest

from cutroom import project
from cutroom.cli import main
from conftest import make_screenstudio, make_video, needs_ffmpeg, slices, write_transcript

pytestmark = needs_ffmpeg

# 0-2 a retake of the opening, 2-4 pause, 4-6 the kept take, 6-9 pause,
# 9-11 a second point, 11-14 pause, 14-16 a closing line
PATTERN = [("tone", 2), ("silence", 2), ("tone", 2), ("silence", 3), ("tone", 2),
           ("silence", 3), ("tone", 2)]
WORDS = [(0.1, 0.5, "Today"), (0.5, 0.9, "we"), (0.9, 1.3, "build"), (1.3, 1.9, "apps."),
         (4.1, 4.5, "Today"), (4.5, 4.9, "we"), (4.9, 5.3, "build"), (5.3, 5.9, "apps."),
         (9.1, 10.9, "Second."), (14.1, 15.9, "Closing.")]


@pytest.fixture
def talk(tmp_path):
    video = make_video(tmp_path / "talk.mp4", PATTERN)
    write_transcript(video.with_suffix(".transcript.json"), WORDS)
    return video


def write_project(src, **data):
    project.save(src, {"v": 1, "edits": {"cuts": [], "keeps": []}, "shorts": [], **data})


def report(tmp_path, src, *extra):
    out = tmp_path / "r.json"
    main(["video", str(src), "--yes", "--dry-run", "--report", str(out), *extra])
    return json.loads(out.read_text(encoding="utf-8"))


def clips(fcpxml):
    def t(v):
        return Fraction(v.rstrip("s")) if v != "0s" else Fraction(0)
    return [(float(t(c.get("start"))), float(t(c.get("start")) + t(c.get("duration"))))
            for c in ET.parse(fcpxml).getroot().findall(".//spine/asset-clip")]


def test_retakes_get_stable_ids_and_a_keep_rejects_one(tmp_path, talk):
    first = report(tmp_path, talk)
    assert [d["id"] for d in first["decisions"]] == ["R1"]
    assert first["decisions"][0]["status"] == "cut"

    write_project(talk, edits={"cuts": [], "keeps": [[0.0, 2.0, "reject R1"]]})
    second = report(tmp_path, talk)
    assert second["decisions"][0]["status"] == "rejected"
    assert any(s <= 0.5 and e >= 1.9 for s, e in second["keeps"])  # the first take plays again


def test_keeps_also_block_silence_cuts(tmp_path, talk):
    write_project(talk, edits={"cuts": [], "keeps": [[6.5, 8.5, "keep the pause"]]})
    data = report(tmp_path, talk)
    assert any(s <= 6.5 and e >= 8.5 for s, e in data["keeps"])


def test_project_file_cuts_are_manual_decisions(tmp_path, talk):
    write_project(talk, edits={"cuts": [[9.0, 11.0, "drop the second point"]], "keeps": []})
    data = report(tmp_path, talk)
    manual = [d for d in data["decisions"] if d["id"] == "M1"]
    assert manual and manual[0]["note"] == "drop the second point"
    assert not any(s < 10 < e for s, e in data["keeps"])


def test_cli_cut_and_keep_apply_for_one_run(tmp_path, talk):
    data = report(tmp_path, talk, "--keep", "0-2", "--cut", "14-16")
    assert data["decisions"][0]["status"] == "rejected"
    assert not any(s < 15 < e for s, e in data["keeps"])
    assert not project.project_path(talk).exists()


def test_review_page_embeds_the_plan_and_short_segments(tmp_path, talk):
    write_project(talk, shorts=[{"id": "S1", "start": 3.5, "end": 11.5, "title": "the point", "why": "standalone"}])
    main(["review", str(talk)])
    page = (tmp_path / "talk.review.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S).group(1))
    assert data["kind"] == "video" and data["media"][0]["uri"].startswith("file://")
    assert [d["id"] for d in data["decisions"]] == ["R1"]
    short = data["shorts"][0]
    assert short["id"] == "S1" and len(short["keeps"]) == 2  # the kept take and the second point
    assert "cutroom export" in data["exportCommand"]


def test_export_short_to_fcpxml_uses_only_its_clean_segments(tmp_path, talk):
    write_project(talk, shorts=[{"id": "S1", "start": 3.5, "end": 11.5, "title": "the point"}])
    main(["export", str(talk), "S1"])
    ranges = clips(tmp_path / "talk-S1.fcpxml")
    assert len(ranges) == 2
    assert 3.5 <= ranges[0][0] and ranges[-1][1] <= 11.5
    assert "S1" in ET.parse(tmp_path / "talk-S1.fcpxml").getroot().find(".//project").get("name")


def test_export_unknown_short_exits(tmp_path, talk):
    write_project(talk, shorts=[{"id": "S1", "start": 1, "end": 2}])
    with pytest.raises(SystemExit, match="no 'S9' in the project file"):
        main(["export", str(talk), "S9"])


def test_export_short_from_screen_studio_writes_a_project(tmp_path):
    pkg = make_screenstudio(tmp_path, [PATTERN])
    write_transcript(pkg.with_suffix(".transcript.json"), WORDS)
    write_project(pkg, shorts=[{"id": "S2", "start": 8.0, "end": 16.0, "title": "closing"}])
    main(["export", str(pkg), "S2"])
    out = slices(tmp_path / "demo-S2.screenstudio")
    assert len(out) == 2 and out[0][0] >= 8000 and out[-1][1] <= 16000


def test_final_cut_timeline_comes_back_as_the_edit(tmp_path, talk):
    before = report(tmp_path, talk)
    main(["video", str(talk), "--yes", "--export", "fcpxml"])
    timeline = tmp_path / "talk-clean.fcpxml"
    # an editor in final cut drops the closing line: remove the last clip
    root = ET.parse(timeline)
    spine = root.getroot().find(".//spine")
    spine.remove(spine.findall("asset-clip")[-1])
    root.write(timeline)

    main(["import", str(talk), str(timeline)])
    edits = json.loads(project.project_path(talk).read_text(encoding="utf-8"))["edits"]
    assert len(edits["keeps"]) == len(before["keeps"]) - 1
    after = report(tmp_path, talk)
    assert len(after["keeps"]) == len(before["keeps"]) - 1
    for (s, e), (s2, e2) in zip(after["keeps"], before["keeps"]):
        assert abs(s - s2) < 0.04 and abs(e - e2) < 0.04  # within one frame of the timeline


def test_reordered_timeline_is_refused(tmp_path, talk):
    main(["video", str(talk), "--yes", "--export", "fcpxml"])
    timeline = tmp_path / "talk-clean.fcpxml"
    root = ET.parse(timeline)
    spine = root.getroot().find(".//spine")
    first = spine.findall("asset-clip")[0]
    spine.remove(first)
    spine.append(first)
    root.write(timeline)
    with pytest.raises(SystemExit, match="reordered"):
        main(["import", str(talk), str(timeline)])


def test_bad_project_file_is_explained(tmp_path, talk):
    write_project(talk, shorts=[{"id": "short-1", "start": 1, "end": 2}])
    with pytest.raises(SystemExit, match="unique id like S1"):
        report(tmp_path, talk)


def test_screen_studio_edit_made_before_cutroom_counts_as_cut(tmp_path):
    pkg = make_screenstudio(tmp_path, [PATTERN])
    write_transcript(pkg.with_suffix(".transcript.json"), WORDS)
    # the user had already trimmed the project to 8-16 s in screen studio
    path = pkg / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["json"]["scenes"][0]["slices"] = [{"id": "a", "sourceStartMs": 8000, "sourceEndMs": 16000}]
    path.write_text(json.dumps(data))
    out = tmp_path / "r.json"
    main(["project", str(pkg), "--yes", "--dry-run", "--report", str(out)])
    r = json.loads(out.read_text(encoding="utf-8"))
    assert all(s >= 8.0 and e <= 16.0 for s, e in r["keeps"])
    assert r["decisions"] == []  # the retake at 0-4 s is outside the edit
