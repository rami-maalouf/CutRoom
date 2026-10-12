import glob
import shutil
import subprocess
import xml.etree.ElementTree as ET
from fractions import Fraction

import pytest

from cutroom.fcpxml import timecode_frames, write_fcpxml
from conftest import make_video, needs_ffmpeg

FCP_DTDS = sorted(glob.glob(
    "/Applications/Final Cut Pro*.app/Contents/Frameworks/Interchange.framework/"
    "Versions/A/Resources/FCPXMLv1_10.dtd"))


def rational(value: str) -> Fraction:
    return Fraction(0) if value == "0s" else Fraction(value[:-1])


def test_drop_frame_timecode_math():
    ntsc = Fraction(30000, 1001)
    assert timecode_frames("01:00:00;00", ntsc) == (107892, "DF")
    assert timecode_frames("00:01:00;02", ntsc) == (1800, "DF")
    assert timecode_frames("00:10:00;00", ntsc) == (17982, "DF")


def test_non_drop_timecode_math():
    assert timecode_frames("01:00:00:00", Fraction(25)) == (90000, "NDF")
    assert timecode_frames("00:00:01:05", Fraction(30000, 1001)) == (35, "NDF")


@needs_ffmpeg
def test_clips_are_contiguous_and_frame_aligned(tmp_path):
    video = make_video(tmp_path / "v.mp4", [("tone", 3), ("silence", 2), ("tone", 3)])
    dst = tmp_path / "v.fcpxml"
    write_fcpxml(video, [(0, 3000), (5000, 8000)], dst, 8000)
    root = ET.parse(dst).getroot()
    clips = root.findall(".//spine/asset-clip")
    assert len(clips) == 2
    assert rational(clips[1].get("offset")) == rational(clips[0].get("duration"))
    assert rational(clips[1].get("start")) == Fraction(5)
    fmt = root.find(".//format")
    assert fmt.get("colorSpace") == "1-1-1 (Rec. 709)"


@needs_ffmpeg
def test_retake_marker_survives_when_its_cut_merged_with_silence(tmp_path):
    # the retake cut ends at 4.9s, but a merged silence cut runs to 5.0s, so the
    # marker time sits inside removed media: it must land on the next kept clip
    video = make_video(tmp_path / "v.mp4", [("tone", 3), ("silence", 2), ("tone", 3)])
    dst = tmp_path / "v.fcpxml"
    write_fcpxml(video, [(0, 3000), (5000, 8000)], dst, 8000, [(4900, "retake cut, kept: hi")])
    markers = ET.parse(dst).getroot().findall(".//asset-clip/marker")
    assert len(markers) == 1
    assert rational(markers[0].get("start")) == Fraction(5)


@needs_ffmpeg
def test_timecode_offsets_asset_and_clip_starts(tmp_path):
    video = make_video(tmp_path / "v.mp4", [("tone", 2), ("silence", 1), ("tone", 2)],
                       "-timecode", "01:00:00:00")
    dst = tmp_path / "v.fcpxml"
    write_fcpxml(video, [(0, 2000), (3000, 5000)], dst, 5000)
    root = ET.parse(dst).getroot()
    assert rational(root.find(".//asset").get("start")) == Fraction(3600)
    assert rational(root.findall(".//spine/asset-clip")[1].get("start")) == Fraction(3603)


@needs_ffmpeg
@pytest.mark.skipif(not FCP_DTDS or shutil.which("xmllint") is None,
                    reason="final cut pro's fcpxml dtd (macos only) or xmllint not available")
def test_output_validates_against_final_cut_pro_dtd(tmp_path):
    video = make_video(tmp_path / "v.mp4", [("tone", 3), ("silence", 2), ("tone", 3)],
                       "-timecode", "00:59:58:00")
    dst = tmp_path / "v.fcpxml"
    write_fcpxml(video, [(0, 3000), (5000, 8000)], dst, 8000, [(4900, "retake & <marker>")])
    dtd = tmp_path / "fcpxml.dtd"  # xmllint can't resolve a dtd path with spaces
    shutil.copyfile(FCP_DTDS[0], dtd)
    result = subprocess.run(["xmllint", "--noout", "--dtdvalid", str(dtd), str(dst)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
