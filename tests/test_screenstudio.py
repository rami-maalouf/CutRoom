import json

import pytest

from cutroom.screenstudio import action_times, check_package, mic_sessions, write_cut_package
from conftest import make_screenstudio, needs_ffmpeg, slices

pytestmark = needs_ffmpeg


def test_sessions_and_actions_map_onto_one_timeline(tmp_path):
    pkg = make_screenstudio(tmp_path, [[("tone", 2), ("silence", 2)], [("tone", 3)]],
                            clicks=[1.0, 5.5], keys=[3.0])
    sessions = mic_sessions(pkg)
    assert [s["durationMs"] for s in sessions] == [4000, 3000]
    assert action_times(pkg, sessions) == pytest.approx([1000, 3000, 5500])


def test_events_outside_every_session_are_ignored(tmp_path):
    pkg = make_screenstudio(tmp_path, [[("tone", 2)]])
    (pkg / "recording" / "mouseclicks-1.json").write_text(json.dumps(
        [{"type": "mouseDown", "processTimeMs": 999999}]))
    assert action_times(pkg, mic_sessions(pkg)) == []


def test_recordings_without_clock_metadata_have_no_actions(tmp_path):
    pkg = make_screenstudio(tmp_path, [[("tone", 2)]], clicks=[1.0])
    meta_path = pkg / "recording" / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for s in meta["recorders"][1]["sessions"]:
        del s["processTimeStartMs"], s["processTimeEndMs"]
    meta_path.write_text(json.dumps(meta))
    assert action_times(pkg, mic_sessions(pkg)) == []


def test_write_cut_package_clones_and_never_touches_the_source(tmp_path):
    pkg = make_screenstudio(tmp_path, [[("tone", 2), ("silence", 2), ("tone", 2)]])
    before = (pkg / "project.json").read_text(encoding="utf-8")
    out = write_cut_package(pkg, [(2000, 4000)], None)
    assert out.name == "demo-clean.screenstudio"
    assert (pkg / "project.json").read_text(encoding="utf-8") == before
    assert slices(out) == [(0, 2000), (4000, 6000)]
    assert (out / "recording" / "channel-2-microphone-0.m4a").exists()
    assert write_cut_package(pkg, [(2000, 4000)], None).name == "demo-clean-v2.screenstudio"


def test_not_a_package_exits(tmp_path):
    with pytest.raises(SystemExit, match="not a .screenstudio package"):
        check_package(tmp_path)
