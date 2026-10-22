# joining screen studio recordings: later recordings become the next sessions
# of one project, their files renamed, their slices and zooms moved in time

import json

import pytest

from cutroom.cli import main
from cutroom.screenstudio import mic_sessions, system_audio_sessions
from conftest import make_screenstudio, needs_ffmpeg, slices

pytestmark = needs_ffmpeg


def recording(root, pattern, clock_start, zoom_at=1.0):
    # a package shaped like a real one: top-level sessions, input events, a
    # display channel stored as hls segments, cursor images and a zoom
    pkg = make_screenstudio(root, [pattern], clicks=[0.5], system=[pattern])
    rec = pkg / "recording"
    meta = json.loads((rec / "metadata.json").read_text(encoding="utf-8"))
    dur = meta["recorders"][1]["sessions"][0]["durationMs"]
    clocks = {"processTimeStartMs": clock_start, "processTimeEndMs": clock_start + dur}
    for r in meta["recorders"]:
        for s in r["sessions"]:
            s.update(clocks)
    meta["recorders"][0]["sessions"] = [{"durationMs": dur, "keyStrokesFilename": "keystrokes-0.json",
                                         "mouseClicksFilename": "mouseclicks-0.json", **clocks}]
    meta["recorders"].append({"id": "channel-3-display", "type": "display", "sessions": [
        {"durationMs": dur, "outputFilename": "channel-3-display-0.m3u8",
         "bounds": {"width": 2560, "height": 1440}, "recordingScale": 0.625, **clocks}]})
    meta["recorders"].append({"id": "channel-0-cursor", "type": "cursor",
                              "cursorsInfoFile": "cursors.json", "cursorImagesFolder": "cursors"})
    meta["sessions"] = [{"durationMs": dur, **clocks}]
    (rec / "metadata.json").write_text(json.dumps(meta))
    (rec / "mouseclicks-0.json").write_text(json.dumps([{"type": "mouseDown", "processTimeMs": clock_start + 500}]))
    (rec / "channel-3-display-0.m3u8").write_text(
        '#EXTM3U\n#EXT-X-MAP:URI="channel-3-display-0-0000.mp4"\n#EXTINF:2.0,\n'
        'channel-3-display-0-0001.m4s\n#EXT-X-ENDLIST\n')
    for name in ("channel-3-display-0-0000.mp4", "channel-3-display-0-0001.m4s"):
        (rec / name).write_text(f"{root.name} {name}")
    (rec / "cursors").mkdir()
    (rec / "cursors" / f"{root.name}.png").write_text("png")
    (rec / "cursors.json").write_text(json.dumps([{"id": root.name}]))
    project = json.loads((pkg / "project.json").read_text(encoding="utf-8"))
    project["json"]["scenes"][0]["zooms"] = [{"id": "z1", "sourceStartMs": zoom_at * 1000,
                                              "sourceEndMs": zoom_at * 1000 + 500, "zoom": 2}]
    (pkg / "project.json").write_text(json.dumps(project))
    return pkg


def joined_meta(pkg):
    return json.loads((pkg / "recording" / "metadata.json").read_text(encoding="utf-8"))


def test_join_plays_the_second_recording_after_the_first(tmp_path):
    a = recording(tmp_path / "a", [("tone", 2), ("silence", 1)], clock_start=10000)
    b = recording(tmp_path / "b", [("tone", 2)], clock_start=50000, zoom_at=0.5)
    main(["join", str(a), str(b), "--output", str(tmp_path / "both.screenstudio")])
    out = tmp_path / "both.screenstudio"
    rec = out / "recording"

    assert [s["durationMs"] for s in mic_sessions(out)] == [3000, 2000]
    assert [s["path"].name for s in system_audio_sessions(out)] == [
        "channel-1-system-audio-0.m4a", "channel-1-system-audio-1.m4a"]
    assert slices(out) == [(0, 3000), (3000, 5000)]
    zooms = json.loads((out / "project.json").read_text(encoding="utf-8"))["json"]["scenes"][0]["zooms"]
    assert [(z["sourceStartMs"], z["sourceEndMs"]) for z in zooms] == [(1000, 1500), (3500, 4000)]
    assert len({z["id"] for z in zooms}) == 2

    # the playlist and its segments carry the new session number, content untouched
    playlist = (rec / "channel-3-display-1.m3u8").read_text(encoding="utf-8")
    assert "channel-3-display-1-0000.mp4" in playlist and "channel-3-display-1-0001.m4s" in playlist
    assert (rec / "channel-3-display-1-0001.m4s").read_text() == "b channel-3-display-0-0001.m4s"
    assert (rec / "channel-3-display-0-0001.m4s").read_text() == "a channel-3-display-0-0001.m4s"

    meta = joined_meta(out)
    assert len(meta["sessions"]) == 2
    inputs = next(r for r in meta["recorders"] if r["type"] == "input")["sessions"]
    assert inputs[1]["mouseClicksFilename"] == "mouseclicks-1.json"
    # one app run: the clocks already follow each other, so nothing moves
    assert json.loads((rec / "mouseclicks-1.json").read_text())[0]["processTimeMs"] == 50500
    assert sorted(c["id"] for c in json.loads((rec / "cursors.json").read_text())) == ["a", "b"]
    assert (rec / "cursors" / "b.png").exists()
    assert not (out / ".cutroom-join").exists()
    # the sources are left as they were
    assert slices(b) == [(0, 2000)] and (b / "recording" / "channel-3-display-0.m3u8").exists()


def test_join_moves_a_later_recording_onto_one_clock(tmp_path):
    # recorded in another app run: its clock starts again before the first ended
    a = recording(tmp_path / "a", [("tone", 2)], clock_start=10000)
    b = recording(tmp_path / "b", [("tone", 2)], clock_start=5000)
    main(["join", str(a), str(b), "--output", str(tmp_path / "both.screenstudio")])
    out = tmp_path / "both.screenstudio"
    meta = joined_meta(out)
    starts = [s["processTimeStartMs"] for s in meta["sessions"]]
    assert starts == [10000, 13000]       # 1 s after the first ended
    click = json.loads((out / "recording" / "mouseclicks-1.json").read_text())[0]
    assert click["processTimeMs"] == 13500


def test_join_refuses_recordings_from_another_setup(tmp_path):
    a = recording(tmp_path / "a", [("tone", 2)], clock_start=10000)
    b = recording(tmp_path / "b", [("tone", 2)], clock_start=50000)
    meta = joined_meta(b)
    next(r for r in meta["recorders"] if r["type"] == "display")["sessions"][0]["bounds"]["width"] = 1920
    (b / "recording" / "metadata.json").write_text(json.dumps(meta))
    with pytest.raises(SystemExit, match="bounds differs"):
        main(["join", str(a), str(b), "--output", str(tmp_path / "both.screenstudio")])
