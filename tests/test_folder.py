# folder sources: a shoot of several clips becomes one vlog through ordered
# selects, with transcripts pre-written per clip (no model download)

import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from cutroom import project
from cutroom.cli import main
from conftest import ffmpeg, make_video, needs_ffmpeg, write_transcript
from test_fcpxml import FCP_DTDS

pytestmark = needs_ffmpeg

SPEECH = [("tone", 2), ("silence", 2), ("tone", 2)]
WORDS = [(0.1, 0.6, "Hello"), (0.6, 1.9, "everyone."), (4.1, 5.9, "Welcome back.")]


@pytest.fixture
def shoot(tmp_path):
    # names sort a < b < c, but capture order is c (morning), a (noon), broll (evening)
    root = tmp_path / "shoot"
    (root / "cam").mkdir(parents=True)
    (root / "phone").mkdir()
    make_video(root / "cam" / "a.mp4", SPEECH, "-metadata", "creation_time=2026-09-19T16:00:00Z")
    make_video(root / "phone" / "c.mov", SPEECH, "-metadata", "creation_time=2026-09-19T13:00:00Z")
    ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=4", "-c:v", "libx264",
           "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-metadata", "creation_time=2026-09-19T23:00:00Z",
           str(root / "cam" / "broll.mp4"))
    transcripts = root / "cutroom" / "transcripts"
    transcripts.mkdir(parents=True)
    for rel in ("cam/a.mp4", "phone/c.mov"):
        write_transcript(transcripts / (rel.replace("/", "__") + ".transcript.json"), WORDS)
    return root


def save(root, **data):
    project.save(root, {"v": 2, "edits": {"cuts": [], "keeps": []}, "selects": [], "shorts": [], **data})


def page_data(root):
    page = (root / "cutroom" / "review.html").read_text(encoding="utf-8")
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S).group(1))


def test_clips_are_ordered_by_capture_time_and_digested(shoot):
    main(["digest", str(shoot), "--shards", "2"])
    digest = (shoot / "cutroom" / "digest" / "all.md").read_text(encoding="utf-8")
    assert digest.index("## phone/c.mov") < digest.index("## cam/a.mp4") < digest.index("## cam/broll.mp4")
    assert "[0.10-1.90] Hello everyone." in digest
    assert "(no speech  ·  contact sheet: sheets/cam__broll.mp4.jpg)" in digest
    assert "contact sheet: sheets/phone__c.mov.jpg" in digest  # every clip gets one
    assert (shoot / "cutroom" / "sheets" / "cam__broll.mp4.jpg").stat().st_size > 1000
    assert len(list((shoot / "cutroom" / "digest").glob("shard-*.md"))) == 2


def test_ignored_files_are_not_footage(shoot):
    # a lower-quality copy of a clip is not a second clip
    shutil.copy(shoot / "cam" / "a.mp4", shoot / "cam" / "a-bad-quality.mp4")
    save(shoot, ignore=["*-bad-quality.mp4"])
    main(["digest", str(shoot), "--shards", "1"])
    digest = (shoot / "cutroom" / "digest" / "all.md").read_text(encoding="utf-8")
    assert "## cam/a.mp4" in digest and "bad-quality" not in digest
    save(shoot, ignore=["*-bad-quality.mp4"],
         selects=[{"id": "V1", "clip": "cam/a-bad-quality.mp4", "start": 0.0, "end": 2.0}])
    with pytest.raises(SystemExit, match="or is ignored"):
        main(["review", str(shoot)])
    save(shoot, ignore="*-bad-quality.mp4")
    with pytest.raises(SystemExit, match="ignore must be a list"):
        main(["review", str(shoot)])


def test_selects_make_a_vlog_in_their_own_order(shoot):
    save(shoot, selects=[
        {"id": "V1", "clip": "cam/a.mp4", "start": 4.0, "end": 6.0, "chapter": "Afternoon"},
        {"id": "V2", "clip": "phone/c.mov", "start": 0.0, "end": 2.0, "chapter": "Morning"},
        {"id": "V3", "clip": "phone/c.mov", "start": 4.0, "end": 6.0, "chapter": "Morning"},
    ])
    main(["export", str(shoot), "vlog"])
    out = shoot / "cutroom" / "exports" / "shoot-vlog.fcpxml"
    root = ET.parse(out).getroot()
    assets = {a.get("id"): a.get("name") for a in root.iter("asset")}
    clips = root.findall(".//spine/asset-clip")
    assert [assets[c.get("ref")] for c in clips] == ["a", "c", "c"]
    assert [m.get("value") for m in root.iter("chapter-marker")] == ["Afternoon", "Morning"]
    if FCP_DTDS and shutil.which("xmllint"):
        dtd = shoot / "fcpxml.dtd"
        shutil.copyfile(FCP_DTDS[0], dtd)
        result = subprocess.run(["xmllint", "--noout", "--dtdvalid", str(dtd), str(out)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_selects_snap_out_to_whole_words(shoot):
    # a select that starts mid-word and ends mid-word grows to whole words plus air
    save(shoot, selects=[{"id": "V1", "clip": "phone/c.mov", "start": 0.3, "end": 1.0}])
    main(["review", str(shoot)])
    keeps = page_data(shoot)["selects"][0]["keeps"]
    assert keeps[0][0] < 0.1 + 0.001 and keeps[-1][1] >= 1.9


def test_vlog_review_page_shows_selects_by_chapter(shoot):
    save(shoot,
         selects=[{"id": "V1", "clip": "phone/c.mov", "start": 0.0, "end": 6.0, "chapter": "Morning",
                   "why": "the opener"},
                  {"id": "V2", "clip": "cam/a.mp4", "start": 0.0, "end": 2.0, "chapter": "Noon"}],
         shorts=[{"id": "S1", "title": "hello", "segments": [{"clip": "phone/c.mov", "start": 0, "end": 2}]}])
    main(["review", str(shoot)])
    data = page_data(shoot)
    assert data["kind"] == "folder" and len(data["media"]) == 3
    assert [s["id"] for s in data["selects"]] == ["V1", "V2"]
    assert data["selects"][0]["text"] == "Hello everyone. Welcome back."
    assert data["chapters"] == {"0": "Morning", str(len(data["selects"][0]["keeps"])): "Noon"}
    assert 4.0 < data["keptSeconds"] < 7.0  # pauses inside V1 are cut
    assert data["shorts"][0]["keeps"] and data["projectFile"] == "cutroom/cutroom.json"


def test_without_selects_the_vlog_is_the_whole_clean_footage(shoot):
    main(["review", str(shoot)])
    data = page_data(shoot)
    assert data["selects"] == [] and data["keeps"]


def test_folder_ranges_must_name_a_clip(shoot):
    save(shoot, selects=[{"id": "V1", "start": 0, "end": 1}])
    with pytest.raises(SystemExit, match='needs a "clip"'):
        main(["review", str(shoot)])
    save(shoot, selects=[{"id": "V1", "clip": "cam/missing.mp4", "start": 0, "end": 1}])
    with pytest.raises(SystemExit, match="not in the folder"):
        main(["review", str(shoot)])


def test_clip_relative_keep_survives_new_files(shoot):
    # an earlier clip added later shifts every clip on the timeline; decisions stay put
    save(shoot, selects=[{"id": "V1", "clip": "cam/a.mp4", "start": 0, "end": 6}],
         edits={"cuts": [], "keeps": [{"clip": "cam/a.mp4", "start": 2.0, "end": 4.0}]})
    main(["review", str(shoot)])
    before = page_data(shoot)["selects"][0]["keeps"]
    make_video(shoot / "phone" / "early.mov", SPEECH, "-metadata", "creation_time=2026-09-19T08:00:00Z")
    write_transcript(shoot / "cutroom" / "transcripts" / "phone__early.mov.transcript.json", WORDS)
    main(["review", str(shoot)])
    after = page_data(shoot)
    assert after["media"][0]["name"] == "phone/early.mov"  # every clip moved 6 s later
    assert len(after["selects"][0]["keeps"]) == len(before)
    assert all(abs((a[0] - b[0]) - 6.0) < 0.01 and abs((a[1] - b[1]) - 6.0) < 0.01
               for a, b in zip(after["selects"][0]["keeps"], before))


def test_candidates_are_checked_merged_and_written_as_selects(shoot, capsys):
    cand = shoot / "cutroom" / "candidates"
    cand.mkdir(parents=True)
    (cand / "shard-1.json").write_text(json.dumps([
        {"clip": "cam/a.mp4", "start": 0.0, "end": 2.0, "score": 8, "chapter": "Noon", "title": "hello"},
        {"clip": "cam/a.mp4", "start": 1.5, "end": 5.9, "score": 7, "chapter": "Noon", "title": "welcome"},
        {"clip": "phone/c.mov", "start": 0.0, "end": 1.9, "score": 9, "chapter": "Morning", "title": "open"},
        {"clip": "phone/c.mov", "start": 4.0, "end": 5.9, "score": 3, "chapter": "Morning", "title": "weak"},
        {"clip": "cam/nope.mp4", "start": 0, "end": 1, "score": 9},
        {"clip": "cam/a.mp4", "start": 5, "end": 60, "score": 9},
    ]))
    main(["candidates", str(shoot)])
    out = capsys.readouterr().out
    assert "unknown clip 'cam/nope.mp4'" in out and "outside cam/a.mp4" in out
    main(["candidates", str(shoot), "--write-selects", "--min-score", "7"])
    selects = json.loads(project.project_path(shoot).read_text(encoding="utf-8"))["selects"]
    # capture order (c before a), the two overlapping noon moments merged, the weak one dropped
    assert [(s["id"], s["clip"], s["start"], s["end"]) for s in selects] == [
        ("V1", "phone/c.mov", 0.0, 1.9), ("V2", "cam/a.mp4", 0.0, 5.9)]
    assert selects[1]["title"] == "hello / welcome"


def test_retake_crossing_a_select_edge_does_not_erase_it(shoot):
    # "We build apps." at 0.1 s and again at 4.1 s look like a retake, but the
    # editor chose 4-6 s and 0-2 s as separate moments: neither may vanish
    write_transcript(shoot / "cutroom" / "transcripts" / "phone__c.mov.transcript.json",
                     [(0.1, 0.5, "We"), (0.5, 0.9, "build"), (0.9, 1.3, "great"), (1.3, 1.9, "apps."),
                      (4.1, 4.5, "We"), (4.5, 4.9, "build"), (4.9, 5.3, "great"), (5.3, 5.9, "apps.")])
    save(shoot, selects=[{"id": "V1", "clip": "phone/c.mov", "start": 0.0, "end": 2.0},
                         {"id": "V2", "clip": "phone/c.mov", "start": 4.0, "end": 6.0}])
    main(["review", str(shoot), "--retakes"])
    data = page_data(shoot)
    assert all(s["keeps"] for s in data["selects"])
    assert data["decisions"] == []
    # one select spanning both takes keeps the retake cut inside it (vlogs only
    # detect retakes when asked: fumbles are usually part of the story)
    save(shoot, selects=[{"id": "V1", "clip": "phone/c.mov", "start": 0.0, "end": 6.0}])
    main(["review", str(shoot), "--retakes"])
    data = page_data(shoot)
    assert [d["id"] for d in data["decisions"]] == ["R1"]
    assert data["selects"][0]["keeps"][0][0] >= 3.9
