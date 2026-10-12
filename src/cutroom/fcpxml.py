# fcpxml output adapter: writes the kept segments as a final cut pro timeline
# referencing the original media - no re-encoding, every cut visible and
# adjustable in fcp (or resolve, which imports fcpxml too). retake cuts get a
# marker on the clip that follows them so the judgment calls are easy to
# spot-check on the timeline.

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .core import Range

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
         ":stream_tags=timecode:stream_side_data=rotation:format_tags=timecode",
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
    return info


def write_fcpxml(
    video: Path,
    keeps: list[Range],
    dst: Path,
    total_ms: float,
    retake_markers: list[tuple[float, str]] | None = None,
    project_name: str | None = None,
) -> None:
    # fcp requires frame-aligned rational times ("N/60s"); snap everything to
    # the source frame rate so import produces no boundary warnings. media with
    # a timecode track starts at that timecode in fcp, so the asset and every
    # clip start are offset by it.
    m = probe_media(video)
    fps = m["fps"]
    num, den = fps.numerator, fps.denominator

    rate = FCP_RATES.get((num, den))
    size = FCP_SIZES.get((m["width"], m["height"]))
    frame_duration = rate[1] if rate else f"{den}/{num}s"
    format_name = f' name="FFVideoFormat{size}p{rate[0]}"' if rate and size else ""
    tc_frames, tc_format = timecode_frames(m["timecode"], fps) if m["timecode"] else (0, "NDF")

    def frames(ms: float) -> int:
        return round(ms / 1000 * num / den)

    def t(fr: int) -> str:
        return "0s" if fr == 0 else f"{fr * den}/{num}s"

    clip_tc = ' tcFormat="DF"' if tc_format == "DF" else ""
    pending = sorted(retake_markers or [])
    clips = []
    offset_fr = 0
    for k_start, k_end in keeps:
        start_fr, end_fr = frames(k_start), frames(k_end)
        dur_fr = end_fr - start_fr
        if dur_fr <= 0:
            continue
        # a retake marker lands on the first clip that ends after it: the clip
        # holding the kept take, even when the cut merged with nearby silence
        marker_xml = ""
        while pending and frames(pending[0][0]) < end_fr:
            m_ms, m_text = pending.pop(0)
            m_fr = max(frames(m_ms), start_fr)
            marker_xml += (
                f'\n            <marker start={quoteattr(t(tc_frames + m_fr))} '
                f'duration={quoteattr(t(1))} value={quoteattr(m_text)}/>'
            )
        clips.append(
            f'          <asset-clip ref="r2" offset="{t(offset_fr)}" '
            f'start="{t(tc_frames + start_fr)}" duration="{t(dur_fr)}"{clip_tc} '
            f'name={quoteattr(f"{video.stem} {k_start / 1000:.1f}s")} '
            f'audioRole="dialogue">{marker_xml}\n'
            f'          </asset-clip>'
        )
        offset_fr += dur_fr

    name = escape(project_name or f"{video.stem} (CutRoom)")
    audio_rate = "48k" if m["audio_rate"] == 48000 else "44.1k"
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
    <format id="r1"{format_name} frameDuration="{frame_duration}" width="{m['width']}" height="{m['height']}" colorSpace="{m['color']}"/>
    <asset id="r2" name={quoteattr(video.stem)} start="{t(tc_frames)}" duration="{t(frames(total_ms))}"
           hasVideo="1" hasAudio="{1 if m['has_audio'] else 0}" format="r1" audioSources="1"
           audioChannels="{m['audio_channels']}" audioRate="{m['audio_rate']}">
      <media-rep kind="original-media" src={quoteattr(video.resolve().as_uri())}/>
    </asset>
  </resources>
  <library>
    <event name="CutRoom">
      <project name="{name}">
        <sequence format="r1" duration="{t(offset_fr)}" tcStart="0s" tcFormat="{tc_format}"
                  audioLayout="stereo" audioRate="{audio_rate}">
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
    print(f"wrote fcpxml timeline: {dst} ({len(clips)} clips)")
