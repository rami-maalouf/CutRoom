import json
import re
import subprocess

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


def stream_durations(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return {s["codec_type"]: float(s["duration"]) for s in json.loads(out)["streams"]}


def test_chunked_render_keeps_audio_in_sync_across_chunk_joins(tmp_path):
    # 12 tone segments separated by silence; keeping only the tones in 3 chunks
    # must leave no silence behind and keep audio and video the same length
    pattern = [p for _ in range(12) for p in (("tone", 0.5), ("silence", 0.5))]
    video = make_video(tmp_path / "v.mp4", pattern)
    keeps = [(i * 1000, i * 1000 + 500) for i in range(12)]
    out = tmp_path / "out.mp4"
    render(video, keeps, out, chunk_segments=4)
    assert abs(probe_duration(out) - 6.0) < 0.15
    durations = stream_durations(out)
    assert abs(durations["video"] - durations["audio"]) < 0.1
    assert detect_silences(out, -35, 0.2, 6000) == []


def flash_and_beep_onsets(path):
    # filter arguments treat ":" as a separator (windows drive letters), so escape it
    movie = path.as_posix().replace(":", "\\:")
    out = subprocess.run(["ffprobe", "-v", "error", "-f", "lavfi", f"movie={movie},signalstats",
                          "-show_entries", "frame=pts_time:frame_tags=lavfi.signalstats.YAVG", "-of", "json"],
                         capture_output=True, text=True, check=True).stdout
    frames = [(float(f["pts_time"]), float(f["tags"]["lavfi.signalstats.YAVG"]))
              for f in json.loads(out)["frames"]]
    flashes = [t for (t, y), (_, prev) in zip(frames[1:], frames) if y > 128 >= prev]
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                          "-af", "silencedetect=noise=-30dB:d=0.05", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    beeps = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return flashes, beeps


@pytest.mark.parametrize("chunk_segments", [1000, 7], ids=["single-pass", "chunked"])
def test_render_keeps_picture_and_sound_in_sync(tmp_path, chunk_segments):
    # a white flash and a beep start together every 1.37s; 30 kept segments with
    # boundaries off the frame grid. every beep must stay within one frame of its flash.
    src = tmp_path / "sync.mp4"
    period, length = 1.37, 0.12
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "color=black:s=320x240:r=30:d=60",
                    "-f", "lavfi", "-i",
                    f"aevalsrc='if(lt(mod(t,{period}),{length}),sin(2*PI*1000*t),0)':s=48000:d=60",
                    "-vf", f"drawbox=c=white:t=fill:enable='lt(mod(t,{period}),{length})'",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    out = tmp_path / "out.mp4"
    render(src, [(i * 2000 + 13, i * 2000 + 1517) for i in range(30)], out, chunk_segments=chunk_segments)
    flashes, beeps = flash_and_beep_onsets(out)
    assert len(flashes) > 30
    offsets = [min((b - f for b in beeps), key=abs) for f in flashes]
    assert max(map(abs, offsets)) < 0.045
