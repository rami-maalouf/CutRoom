# fcpxml output adapter: writes the kept segments as a final cut pro timeline
# referencing the original media - no re-encoding, every cut visible and
# adjustable in fcp (or resolve, which imports fcpxml too). retake cuts get a
# marker on the clip that follows them so the judgment calls are easy to
# spot-check on the timeline.

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
import os
from urllib.parse import urlparse
from urllib.request import url2pathname
from xml.sax.saxutils import escape, quoteattr

from .core import Range, merge_ranges

REC709 = "1-1-1 (Rec. 709)"
HLG = "9-18-9 (Rec. 2020 HLG)"
PQ = "9-16-9 (Rec. 2020 PQ)"

# fcp maps <format> resources onto its internal catalog; name the format
# explicitly when the source matches a known fcp video format, and use fcp's
# canonical frameDuration spelling. unnamed formats need a colorSpace.
FCP_RATES = {
    (24000, 1001): ("2398", "1001/24000s"),
    (24, 1): ("24", "100/2400s"),
    (25, 1): ("25", "100/2500s"),
    (30000, 1001): ("2997", "1001/30000s"),
    (30, 1): ("30", "100/3000s"),
    (50, 1): ("50", "100/5000s"),
    (60000, 1001): ("5994", "1001/60000s"),
    (60, 1): ("60", "100/6000s"),
}
FCP_SIZES = {(1920, 1080): "1080", (1280, 720): "720", (3840, 2160): "3840x2160"}
DROP_FRAME_RATES = {Fraction(30000, 1001): 2, Fraction(60000, 1001): 4}


def timecode_frames(tc: str, fps: Fraction) -> tuple[int, str]:
    # "hh:mm:ss:ff" (non-drop) or "hh:mm:ss;ff" (drop-frame) -> (frame count, tcFormat)
    hh, mm, ss, ff = (int(x) for x in re.split(r"[:;.]", tc))
    nominal = round(fps)
    frames = (hh * 3600 + mm * 60 + ss) * nominal + ff
    drop = DROP_FRAME_RATES.get(fps)
    if drop and ";" in tc:
        minutes = 60 * hh + mm
        return frames - drop * (minutes - minutes // 10), "DF"
    return frames, "NDF"


def probe_media(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,r_frame_rate,width,height,sample_rate,channels,color_transfer"
         ":stream_tags=timecode:stream_side_data=rotation:format_tags=timecode:format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    info = {"fps": Fraction(30), "width": 1920, "height": 1080, "color": REC709,
            "audio_rate": 48000, "audio_channels": 2, "has_audio": False, "timecode": None}
    timecodes = [(data.get("format", {}).get("tags") or {}).get("timecode")]
    video_seen = False
    for s in data["streams"]:
        timecodes.append((s.get("tags") or {}).get("timecode"))
        if s.get("codec_type") == "video" and not video_seen:
            video_seen = True
            num, den = (int(x) for x in s["r_frame_rate"].split("/"))
            width, height = s["width"], s["height"]
            rotation = next((int(sd["rotation"]) for sd in s.get("side_data_list") or []
                             if "rotation" in sd), 0)
            if abs(rotation) == 90:
                width, height = height, width
            transfer = s.get("color_transfer", "")
            color = HLG if transfer == "arib-std-b67" else PQ if transfer == "smpte2084" else REC709
            info.update(fps=Fraction(num, den), width=width, height=height, color=color)
        elif s.get("codec_type") == "audio" and not info["has_audio"]:
            info.update(has_audio=True, audio_rate=int(s.get("sample_rate", 48000)),
                        audio_channels=int(s.get("channels", 2)))
    info["timecode"] = next((tc for tc in timecodes if tc), None)
    info["duration"] = float(data.get("format", {}).get("duration") or 0)
    return info


Segment = tuple  # (media path, start_ms, end_ms) or (media path, start_ms, end_ms, label)


def write_fcpxml(
    video: Path,
    keeps: list[Range],
    dst: Path,
    total_ms: float,
    retake_markers: list[tuple[float, str]] | None = None,
    project_name: str | None = None,
) -> None:
    # one source file: its kept ranges in order, retake markers on the clips that follow them
    write_timeline([(video, s, e) for s, e in keeps], dst,
                   project_name or f"{video.stem} (CutRoom)",
                   markers=[(video, ms, text) for ms, text in retake_markers or []])


def write_timeline(
    segments: list[Segment],
    dst: Path,
    project_name: str,
    markers: list[tuple[Path, float, str]] = (),
    chapters: dict[int, str] | None = None,
) -> None:
    # a final cut pro timeline (fcpxml 1.10) of source ranges from any number of
    # files, referencing the original media - no re-encoding. fcp needs
    # frame-aligned rational times: clip starts sit on each file's own frame
    # grid (offset by the file's timecode, which fcp reads), offsets and
    # durations on the sequence grid. chapters: segment index -> title.
    chapters = chapters or {}
    media = {}
    for seg in segments:
        if seg[0] not in media:
            media[seg[0]] = probe_media(seg[0])

    # the sequence takes the format that carries most of the program
    weight: dict[tuple, float] = {}
    for seg in segments:
        m = media[seg[0]]
        key = (m["width"], m["height"], m["fps"], m["color"])
        weight[key] = weight.get(key, 0) + seg[2] - seg[1]
    seq_w, seq_h, seq_fps, seq_color = max(weight, key=weight.get)

    formats: dict[tuple, str] = {}
    resources, assets = [], {}

    def format_id(w: int, h: int, fps: Fraction, color: str) -> str:
        key = (w, h, fps, color)
        if key not in formats:
            fid = f"r{len(formats) + 1}"
            rate = FCP_RATES.get((fps.numerator, fps.denominator))
            size = FCP_SIZES.get((w, h))
            name = f' name="FFVideoFormat{size}p{rate[0]}"' if rate and size else ""
            fd = rate[1] if rate else f"{fps.denominator}/{fps.numerator}s"
            resources.append(f'    <format id="{fid}"{name} frameDuration="{fd}" width="{w}" '
                             f'height="{h}" colorSpace="{color}"/>')
            formats[key] = fid
        return formats[key]

    seq_format = format_id(seq_w, seq_h, seq_fps, seq_color)

    def at(fr: int, fps: Fraction) -> str:
        return "0s" if fr == 0 else f"{fr * fps.denominator}/{fps.numerator}s"

    for path, m in media.items():
        fps = m["fps"]
        tc_frames, tc_format = timecode_frames(m["timecode"], fps) if m["timecode"] else (0, "NDF")
        aid = f"a{len(assets) + 1}"
        assets[path] = {"id": aid, "fps": fps, "tc": tc_frames, "tcFormat": tc_format}
        fid = format_id(m["width"], m["height"], fps, m["color"])
        total_fr = round(m["duration"] * fps)
        resources.append(
            f'    <asset id="{aid}" name={quoteattr(path.stem)} start="{at(tc_frames, fps)}" '
            f'duration="{at(total_fr, fps)}" hasVideo="1" hasAudio="{1 if m["has_audio"] else 0}" '
            f'format="{fid}" audioSources="1" audioChannels="{m["audio_channels"]}" '
            f'audioRate="{m["audio_rate"]}">\n'
            f'      <media-rep kind="original-media" src={quoteattr(path.resolve().as_uri())}/>\n'
            f'    </asset>')

    pending = {p: sorted((ms, text) for mp, ms, text in markers if mp == p) for p in media}
    clips, offset = [], 0
    for i, seg in enumerate(segments):
        path, s_ms, e_ms = seg[0], seg[1], seg[2]
        a = assets[path]
        fps = a["fps"]
        start_fr, end_fr = round(s_ms / 1000 * fps), round(e_ms / 1000 * fps)
        dur_seq = round((end_fr - start_fr) / fps * seq_fps)
        if dur_seq <= 0:
            continue
        inner = ""
        if i in chapters:
            inner += (f'\n            <chapter-marker start="{at(a["tc"] + start_fr, fps)}" '
                      f'duration="{at(1, fps)}" value={quoteattr(chapters[i])} posterOffset="0s"/>')
        # a marker lands on the first clip of its file that ends after it:
        # the clip holding the kept take, even when its cut merged with silence
        queue = pending[path]
        while queue and round(queue[0][0] / 1000 * fps) < end_fr:
            ms, text = queue.pop(0)
            m_fr = max(round(ms / 1000 * fps), start_fr)
            inner += (f'\n            <marker start="{at(a["tc"] + m_fr, fps)}" '
                      f'duration="{at(1, fps)}" value={quoteattr(text)}/>')
        tc = ' tcFormat="DF"' if a["tcFormat"] == "DF" else ""
        label = seg[3] if len(seg) > 3 else f"{path.stem} {s_ms / 1000:.1f}s"
        clips.append(
            f'          <asset-clip ref="{a["id"]}" offset="{at(offset, seq_fps)}" '
            f'start="{at(a["tc"] + start_fr, fps)}" duration="{at(dur_seq, seq_fps)}"{tc} '
            f'name={quoteattr(label)} audioRole="dialogue">{inner}\n'
            f'          </asset-clip>')
        offset += dur_seq

    main_tc = next(a["tcFormat"] for p, a in assets.items()
                   if (media[p]["width"], media[p]["height"], a["fps"]) == (seq_w, seq_h, seq_fps))
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
{chr(10).join(resources)}
  </resources>
  <library>
    <event name="CutRoom">
      <project name={quoteattr(project_name)}>
        <sequence format="{seq_format}" duration="{at(offset, seq_fps)}" tcStart="0s" tcFormat="{main_tc}"
                  audioLayout="stereo" audioRate="48k">
          <spine>
{chr(10).join(clips)}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
'''
    dst.write_text(xml, encoding="utf-8")
    print(f"wrote fcpxml timeline: {dst} ({len(clips)} clips from {len(media)} files)")


def _time(value: str | None) -> Fraction:
    # fcpxml rational time "1001/30000s", "12s" or "0s" -> seconds
    if not value:
        return Fraction(0)
    return Fraction(value.rstrip("s"))


def uri_to_path(uri: str) -> Path:
    # file:///C:/x%20y.mp4 -> C:\\x y.mp4 on windows, /x y.mp4 elsewhere
    return Path(url2pathname(urlparse(uri).path))


def _same_file_key(path: Path) -> str:
    # windows paths are case-insensitive and may arrive as 8.3 short names
    return os.path.normcase(str(path.resolve()))


def read_keeps(timeline: Path, media: Path) -> list[Range]:
    # the source ranges (ms) a final cut pro timeline uses from one media file,
    # in timeline order. this is how edits made by hand in fcp come back: fcp
    # exports the project (file > export xml) and these ranges become the cut.
    root = ET.parse(timeline).getroot()
    target = _same_file_key(media)
    assets = {}
    for asset in root.iter("asset"):
        rep = asset.find("media-rep")
        src = rep.get("src") if rep is not None else asset.get("src")
        if src and _same_file_key(uri_to_path(src)) == target:
            assets[asset.get("id")] = _time(asset.get("start"))
    if not assets:
        sys.exit(f"{timeline.name} does not reference {media.name}")
    spine = root.find(".//sequence/spine")
    if spine is None:
        sys.exit(f"{timeline.name} has no sequence")
    ranges = []
    for el in spine:
        if el.tag == "gap":
            continue
        if el.tag == "asset-clip" and el.get("ref") in assets:
            start = _time(el.get("start")) - assets[el.get("ref")]
            end = start + _time(el.get("duration"))
            ranges.append((float(start) * 1000, float(end) * 1000))
            continue
        refs = {x.get("ref") for x in el.iter() if x.get("ref")}
        if refs & assets.keys():
            sys.exit(f"{timeline.name}: a <{el.tag}> on the main storyline uses {media.name}; only plain "
                     f"clips can be read back (no compound, multicam or retimed clips)")
    if not ranges:
        sys.exit(f"{timeline.name} has no clips from {media.name} on its main storyline")
    if any(b[0] < a[1] - 1 for a, b in zip(ranges, ranges[1:])):
        sys.exit(f"{timeline.name}: clips are reordered or repeated; cutroom edits keep source order")
    return merge_ranges(ranges)
