# end to end through the real command line, on synthetic recordings with
# pre-written transcripts (no model download)

import json
import xml.etree.ElementTree as ET

from cutroom.cli import main
from conftest import make_screenstudio, make_video, needs_ffmpeg, probe_duration, slices, write_transcript

pytestmark = needs_ffmpeg

# speech, a 3s pause, speech, a 3s pause, speech
PATTERN = [("tone", 2), ("silence", 3), ("tone", 2), ("silence", 3), ("tone", 2)]
WORDS = [(0.1, 1.9, "first."), (5.1, 6.9, "second."), (10.1, 11.9, "third.")]


def project(tmp_path, clicks=()):
    pkg = make_screenstudio(tmp_path, [PATTERN], clicks=clicks)
    write_transcript(pkg.with_suffix(".transcript.json"), WORDS)
    return pkg


def removed_seconds(pkg, out):
    return (sum(e - s for s, e in slices(pkg)) - sum(e - s for s, e in slices(out))) / 1000


def test_project_cuts_both_pauses(tmp_path):
    pkg = project(tmp_path)
    main(["project", str(pkg), "--yes"])
    out = tmp_path / "demo-clean.screenstudio"
    assert len(slices(out)) == 3
    assert 5.0 < removed_seconds(pkg, out) < 6.0  # two 3s pauses minus trail + lead


def test_a_click_inside_a_pause_keeps_that_moment_on_screen(tmp_path):
    pkg = project(tmp_path, clicks=[3.5])
    main(["project", str(pkg), "--yes"])
    out = tmp_path / "demo-clean.screenstudio"
    assert any(s <= 3500 < e for s, e in slices(out))
    assert any(s <= 2000 + 1500 - 500 and 3500 + 1000 <= e for s, e in slices(out))
    main(["project", str(pkg), "--yes", "--no-protect-actions"])
    unprotected = tmp_path / "demo-clean-v2.screenstudio"
    assert not any(s <= 3500 < e for s, e in slices(unprotected))


def test_dry_run_writes_nothing_but_the_report(tmp_path):
    pkg = project(tmp_path)
    report = tmp_path / "report.json"
    main(["project", str(pkg), "--yes", "--dry-run", "--report", str(report)])
    assert not (tmp_path / "demo-clean.screenstudio").exists()
    data = json.loads(report.read_text(encoding="utf-8"))
    assert [s["text"] for s in data["sentences"]] == ["first.", "second.", "third."]
    assert len(data["finalCuts"]) == 2 and len(data["keeps"]) == 3


def test_manual_cut_removes_a_take(tmp_path):
    pkg = project(tmp_path)
    main(["project", str(pkg), "--yes", "--no-silences", "--cut", "4.9-10.0"])
    out = tmp_path / "demo-clean.screenstudio"
    assert slices(out) == [(0, 4900), (10000, 12000)]


def test_video_fcpxml_export_marks_retakes(tmp_path):
    video = make_video(tmp_path / "talk.mp4", PATTERN)
    write_transcript(video.with_suffix(".transcript.json"), [
        (0.1, 0.5, "Today"), (0.5, 0.9, "we"), (0.9, 1.2, "are"), (1.2, 1.5, "building"), (1.5, 1.9, "apps."),
        (5.1, 5.5, "Today"), (5.5, 5.9, "we"), (5.9, 6.2, "are"), (6.2, 6.5, "building"), (6.5, 6.9, "apps."),
        (10.1, 11.9, "Done."),
    ])
    main(["video", str(video), "--yes", "--export", "fcpxml"])
    root = ET.parse(tmp_path / "talk-clean.fcpxml").getroot()
    markers = root.findall(".//asset-clip/marker")
    assert len(markers) == 1 and "repeated opening" in markers[0].get("value")


def test_video_render_matches_the_plan(tmp_path):
    video = make_video(tmp_path / "talk.mp4", PATTERN)
    write_transcript(video.with_suffix(".transcript.json"), WORDS)
    report = tmp_path / "r.json"
    main(["video", str(video), "--yes", "--report", str(report)])
    kept = json.loads(report.read_text(encoding="utf-8"))["keptSeconds"]
    assert abs(probe_duration(tmp_path / "talk-clean.mp4") - kept) < 0.15


def test_transcribe_reuses_the_cache(tmp_path, capsys):
    video = make_video(tmp_path / "talk.mp4", PATTERN)
    write_transcript(video.with_suffix(".transcript.json"), WORDS)
    main(["transcribe", str(video)])
    assert "3 words" in capsys.readouterr().out
