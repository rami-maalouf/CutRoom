import pytest

from cutroom.media import collect_silences, detect_silences, probe_video, render, versioned_output
from conftest import make_audio, make_video, needs_ffmpeg, probe_duration

pytestmark = needs_ffmpeg
TOL_MS = 60  # aac frames and silencedetect windows blur edges by a few tens of ms


def close(a, b, tol=TOL_MS):
    return abs(a - b) <= tol


def test_detect_silences_finds_known_pauses(tmp_path):
    audio = make_audio(tmp_path / "a.m4a", [("tone", 2), ("silence", 1.5), ("tone", 2), ("silence", 1)])
    found = detect_silences(audio, -35, 0.6, 6500)
    assert len(found) == 2
    assert close(found[0][0], 2000) and close(found[0][1], 3500)
    # a pause that runs to the end of the file closes at the file's duration
    assert close(found[1][0], 5500) and found[1][1] == 6500


def test_collect_silences_offsets_sessions_onto_one_timeline(tmp_path):
    a = make_audio(tmp_path / "a.m4a", [("tone", 1), ("silence", 1), ("tone", 1)])
    b = make_audio(tmp_path / "b.m4a", [("tone", 1), ("silence", 1), ("tone", 1)])
    found = collect_silences([{"path": a, "durationMs": 3000}, {"path": b, "durationMs": 3000}],
                             -35, 0.6)
    assert len(found) == 2
    assert close(found[0][0], 1000) and close(found[1][0], 4000) and close(found[1][1], 5000)


def test_detect_silences_reads_audio_from_a_video_file(tmp_path):
    video = make_video(tmp_path / "v.mp4", [("tone", 1), ("silence", 1), ("tone", 1)])
    found = detect_silences(video, -35, 0.6, 3000)
    assert len(found) == 1 and close(found[0][0], 1000)


def test_probe_and_render_kept_segments(tmp_path):
    video = make_video(tmp_path / "v.mp4", [("tone", 2), ("silence", 2), ("tone", 2)])
    duration_ms, has_audio = probe_video(video)
    assert has_audio and close(duration_ms, 6000, 100)
    out = tmp_path / "out.mp4"
    render(video, [(0, 2000), (4000, 6000)], out)
    assert abs(probe_duration(out) - 4.0) < 0.1


def test_versioned_output_never_overwrites(tmp_path):
    base = tmp_path / "x-clean.mp4"
    assert versioned_output(base) == base
    base.write_text("")
    assert versioned_output(base).name == "x-clean-v2.mp4"


def test_silencedetect_failure_exits_with_message(tmp_path):
    bogus = tmp_path / "not-media.m4a"
    bogus.write_text("nope")
    with pytest.raises(SystemExit, match="silencedetect failed"):
        detect_silences(bogus, -35, 0.6, 1000)
