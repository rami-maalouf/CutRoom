# fcpxml output adapter: writes the kept segments as a final cut pro timeline
# referencing the original media - no re-encoding, every cut visible and
# adjustable in fcp. retake cuts get a marker on the following clip so the
# judgment calls are easy to spot-check on the timeline.

import json
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr


def probe_media(video: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,r_frame_rate,width,height,sample_rate,channels",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    info = {"fps_num": 30, "fps_den": 1, "width": 1920, "height": 1080,
            "audio_rate": 48000, "audio_channels": 2}
    for s in json.loads(out)["streams"]:
        if s.get("codec_type") == "video":
            num, den = s["r_frame_rate"].split("/")
            info.update(fps_num=int(num), fps_den=int(den),
                        width=s["width"], height=s["height"])
        elif s.get("codec_type") == "audio":
            info.update(audio_rate=int(s.get("sample_rate", 48000)),
                        audio_channels=int(s.get("channels", 2)))
    return info


# fcp maps <format> resources onto its internal catalog; an unnamed format it
# can't map triggers "Encountered an unexpected value" on every element that
# references it. name the format explicitly when the source matches a known
# fcp video format, and use fcp's canonical frameDuration spelling.
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


def write_fcpxml(
    video: Path,
    keeps: list[tuple[float, float]],
    dst: Path,
    total_ms: float,
    retake_markers: list[tuple[float, str]] | None = None,
    project_name: str | None = None,
) -> None:
    # fcp requires frame-aligned rational times ("N/60s"); snap everything
    # to the source frame rate so import produces no boundary warnings
    m = probe_media(video)
    num, den = m["fps_num"], m["fps_den"]

    rate = FCP_RATES.get((num, den))
    size = FCP_SIZES.get((m["width"], m["height"]))
    frame_duration = rate[1] if rate else f"{den}/{num}s"
    format_name = (
        f' name="FFVideoFormat{size}p{rate[0]}"' if rate and size else ""
    )

    def frames(ms: float) -> int:
        return round(ms / 1000 * num / den)

    def t(fr: int) -> str:
        return "0s" if fr == 0 else f"{fr * den}/{num}s"

    markers = retake_markers or []
    clips = []
    offset_fr = 0
    for k_start, k_end in keeps:
        start_fr, end_fr = frames(k_start), frames(k_end)
        dur_fr = end_fr - start_fr
        if dur_fr <= 0:
            continue
        marker_xml = ""
        for m_ms, m_text in markers:
            # a marker belongs to the clip whose source range contains its time
            m_fr = frames(m_ms)
            if start_fr <= m_fr < end_fr:
                marker_xml += (
                    f'\n            <marker start={quoteattr(t(max(m_fr, start_fr)))} '
                    f'duration={quoteattr(t(1))} value={quoteattr(m_text)}/>'
                )
        # no format/tcFormat here: asset-clips inherit both from the asset,
        # and redundant copies are extra surface for fcp's semantic checks
        clips.append(
            f'          <asset-clip ref="r2" offset="{t(offset_fr)}" '
            f'start="{t(start_fr)}" duration="{t(dur_fr)}" '
            f'name={quoteattr(f"{video.stem} {k_start / 1000:.1f}s")} '
            f'audioRole="dialogue">{marker_xml}\n'
            f'          </asset-clip>'
        )
        offset_fr += dur_fr

    name = escape(project_name or f"{video.stem} (CutRoom)")
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
    <format id="r1"{format_name} frameDuration="{frame_duration}" width="{m['width']}" height="{m['height']}"/>
    <asset id="r2" name={quoteattr(video.stem)} start="0s" duration="{t(frames(total_ms))}"
           hasVideo="1" hasAudio="1" format="r1" audioSources="1"
           audioChannels="{m['audio_channels']}" audioRate="{m['audio_rate']}">
      <media-rep kind="original-media" src={quoteattr(video.resolve().as_uri())}/>
    </asset>
  </resources>
  <library>
    <event name="CutRoom">
      <project name="{name}">
        <sequence format="r1" duration="{t(offset_fr)}" tcStart="0s" tcFormat="NDF"
                  audioLayout="stereo" audioRate="{'48k' if m['audio_rate'] == 48000 else '44.1k'}">
          <spine>
{chr(10).join(clips)}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
'''
    dst.write_text(xml)
    print(f"wrote fcpxml timeline: {dst} ({len(clips)} clips)")
