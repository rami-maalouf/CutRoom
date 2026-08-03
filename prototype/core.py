# shared core for silence + retake cutting. media-agnostic: works on "sessions"
# (audio files with durations, concatenated on one source timeline) and produces
# cut ranges in source ms. input adapters: screenstudio packages (cut_silences.py,
# cut_retakes.py) and plain video files (cut_video.py). improvements here benefit
# every adapter.

import difflib
import json
import random
import re
import string
import subprocess
import sys
from pathlib import Path

MIN_SLICE_MS = 120  # drop resulting slices/segments shorter than this
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
TRANSCRIPT_CACHE_VERSION = 3
FILLERS = {"um", "uh", "uhm", "erm", "hmm", "like", "so", "okay", "ok", "yeah", "well"}
RESTART_PHRASES = re.compile(
    r"\b(scratch that|let me (redo|start over|try (that|this) again)|start(ing)? over|take two)\b",
    re.IGNORECASE,
)


def new_id() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=10))


# ---------- pacing ----------
# one knob for how rigorous silence cutting is. three levers move together:
# min_silence (how long a gap must be to cut), pad (breathing room kept around
# speech - the residual pause after a cut is 2x this), and min_keep (wordless
# fragments shorter than this are absorbed by cleanup_cuts).

PACING_PRESETS = {
    "tight": {"min_silence": 0.35, "pad": 0.08, "min_keep": 2.0},
    "balanced": {"min_silence": 0.6, "pad": 0.15, "min_keep": 1.5},
    "relaxed": {"min_silence": 1.2, "pad": 0.3, "min_keep": 0.8},
}


def resolve_pacing(args) -> None:
    # fill unset (None) pacing-related args from the chosen preset;
    # explicitly passed flags always win over the preset
    preset = PACING_PRESETS[args.pacing]
    for key, value in preset.items():
        if hasattr(args, key) and getattr(args, key) is None:
            setattr(args, key, value)


# ---------- sessions ----------
# a session is {"path": Path, "durationMs": float}. multi-session recordings
# (screen studio pause/resume) concatenate on one timeline; an mp4 is one session.


def detect_silences(audio: Path, noise_db: float, min_silence_s: float) -> list[tuple[float, float]]:
    # returns (start_ms, end_ms) silence ranges within one audio file
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_s}",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", out)]
    if len(starts) == len(ends) + 1:
        dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
        if dur:
            h, m, s = dur.groups()
            ends.append(int(h) * 3600 + int(m) * 60 + float(s))
        else:
            starts.pop()
    return [(s * 1000, e * 1000) for s, e in zip(starts, ends)]


def collect_silences(
    sessions: list[dict], noise_db: float = -35.0, min_silence_s: float = 0.6
) -> list[tuple[float, float]]:
    # silence ranges across all sessions, offset onto the concatenated timeline
    silences = []
    offset_ms = 0.0
    for session in sessions:
        for s, e in detect_silences(session["path"], noise_db, min_silence_s):
            silences.append((offset_ms + s, offset_ms + min(e, session["durationMs"])))
        offset_ms += session["durationMs"]
    return silences


def silence_cuts(silences: list[tuple[float, float]], pad_ms: float) -> list[tuple[float, float]]:
    # shrink each silence by pad on both sides; keep only if still a real gap
    cuts = []
    for s, e in silences:
        s2, e2 = s + pad_ms, e - pad_ms
        if e2 - s2 >= 200:
            cuts.append((s2, e2))
    return cuts


# ---------- transcription ----------


def transcribe_sessions(sessions: list[dict], cache: Path) -> list[dict]:
    # word timings {"startMs", "endMs", "word"} on the concatenated timeline.
    # cached because transcription is the slow step.
    if cache.exists():
        data = json.loads(cache.read_text())
        if isinstance(data, dict) and data.get("v") == TRANSCRIPT_CACHE_VERSION:
            print(f"using cached transcript: {cache.name}")
            return data["words"]
        print("cache is an older format, re-transcribing")

    import mlx_whisper

    words = []
    offset_ms = 0.0
    for session in sessions:
        print(f"transcribing {session['path'].name} ({session['durationMs'] / 1000:.0f}s)...")
        # condition_on_previous_text=False reduces whisper's repetition loops on silence
        result = mlx_whisper.transcribe(
            str(session["path"]), path_or_hf_repo=WHISPER_MODEL,
            word_timestamps=True, condition_on_previous_text=False,
        )
        for seg in result["segments"]:
            for w in seg.get("words", []):
                text = w["word"].strip()
                if text:
                    words.append({
                        "startMs": offset_ms + w["start"] * 1000,
                        "endMs": offset_ms + min(w["end"] * 1000, session["durationMs"]),
                        "word": text,
                    })
        offset_ms += session["durationMs"]
    cache.write_text(json.dumps({"v": TRANSCRIPT_CACHE_VERSION, "words": words}, indent=1))
    print(f"cached transcript: {cache.name}")
    return words


def drop_hallucinated_words(
    words: list[dict], silences: list[tuple[float, float]]
) -> tuple[list[dict], list[dict]]:
    # whisper invents words during long silences (repetition loops, "LA LA LA"),
    # often with dense fake timings that bridge real takes into one run-on.
    # a hallucinated word's timing sits inside silence; real speech doesn't.
    kept, dropped = [], []
    for w in words:
        dur = w["endMs"] - w["startMs"]
        overlap = sum(
            max(0.0, min(w["endMs"], e) - max(w["startMs"], s)) for s, e in silences
        )
        if dur <= 0 or overlap / dur > 0.5:
            dropped.append(w)
        else:
            kept.append(w)
    return kept, dropped


def words_to_sentences(words: list[dict], gap_ms: float = 1000.0) -> list[dict]:
    # whisper's segment boundaries are unreliable: a retake can start mid-segment or
    # span two segments, which hides it from opening comparison. rebuild sentences
    # from word timings, splitting at sentence-ending punctuation AND at pauses:
    # whisper often omits punctuation between restarts, gluing takes into one
    # run-on sentence, but a retake is always preceded by a pause in the audio.
    sentences = []
    current: list[dict] = []

    def flush():
        if not current:
            return
        text = " ".join(w["word"] for w in current)
        if re.search(r"\w", text):  # drop hallucinated punctuation-only segments
            sentences.append({
                "startMs": current[0]["startMs"],
                "endMs": current[-1]["endMs"],
                "text": text,
            })
        current.clear()

    for i, w in enumerate(words):
        current.append(w)
        next_gap = words[i + 1]["startMs"] - w["endMs"] if i + 1 < len(words) else 0
        if re.search(r"[.!?…]$", w["word"]) or next_gap > gap_ms:
            flush()
    flush()
    return sentences


# ---------- retake detection ----------


def opening_words(text: str, n: int = 8) -> list[str]:
    words = re.sub(r"[^\w\s']", " ", text.lower()).split()
    return [w for w in words if w not in FILLERS][:n]


def opening_similarity(a: str, b: str) -> float:
    wa, wb = opening_words(a), opening_words(b)
    if len(wa) < 3 or len(wb) < 3:
        return 0.0
    return difflib.SequenceMatcher(None, " ".join(wa), " ".join(wb)).ratio()


def find_retake_cuts(
    segments: list[dict], window_s: float = 60.0,
    threshold: float = 0.75, pre_roll_ms: float = 100.0,
) -> list[dict]:
    # greedy scan: for each sentence, find the LAST later sentence inside the window
    # whose opening matches; cut from the earlier take's start to the kept take's start.
    cuts = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        match_j = None
        for j in range(i + 1, len(segments)):
            if segments[j]["startMs"] - seg["startMs"] > window_s * 1000:
                break
            if opening_similarity(seg["text"], segments[j]["text"]) >= threshold:
                match_j = j
        if match_j is not None:
            kept = segments[match_j]
            cuts.append({
                "startMs": seg["startMs"],
                "endMs": max(seg["startMs"], kept["startMs"] - pre_roll_ms),
                "removed": [s["text"] for s in segments[i:match_j]],
                "kept": kept["text"],
                "reason": "repeated opening",
            })
            i = match_j
            continue
        if RESTART_PHRASES.search(seg["text"]):
            cuts.append({
                "startMs": seg["startMs"],
                "endMs": seg["endMs"],
                "removed": [seg["text"]],
                "kept": segments[i + 1]["text"] if i + 1 < len(segments) else "(end)",
                "reason": "restart phrase",
            })
        i += 1
    return cuts


# ---------- review / approval ----------


def review_cuts(cuts: list[dict], auto_yes: bool) -> list[dict]:
    # interactive approve/reject per cut; auto-approves when not a tty or --yes
    approved = []
    interactive = sys.stdin.isatty() and not auto_yes
    for n, cut in enumerate(cuts, 1):
        dur = (cut["endMs"] - cut["startMs"]) / 1000
        print(f"\n[{n}/{len(cuts)}] cut {cut['startMs'] / 1000:8.2f}s -> "
              f"{cut['endMs'] / 1000:8.2f}s  ({dur:.2f}s, {cut['reason']})")
        for line in cut.get("removed", []):
            print(f"    remove: {line}")
        if "kept" in cut:
            print(f"    keep:   {cut['kept']}")
        if interactive:
            answer = input("  approve? [Y/n] ").strip().lower()
            if answer in ("n", "no"):
                print("  rejected")
                continue
        approved.append(cut)
    return approved


# ---------- range math ----------


def merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for s, e in sorted(ranges):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def invert_cuts(cuts: list[tuple[float, float]], total_ms: float) -> list[tuple[float, float]]:
    # keep-ranges = timeline minus cuts (for renderers that assemble kept segments)
    keeps = []
    pos = 0.0
    for s, e in merge_ranges(cuts):
        if s - pos >= MIN_SLICE_MS:
            keeps.append((pos, min(s, total_ms)))
        pos = max(pos, e)
    if total_ms - pos >= MIN_SLICE_MS:
        keeps.append((pos, total_ms))
    return keeps


def cleanup_cuts(
    cuts: list[tuple[float, float]],
    total_ms: float,
    words: list[dict] | None = None,
    min_keep_ms: float = 1500.0,
    min_keep_wordless_ms: float = 400.0,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    # final cleanup pass over an approved cut list: absorb tiny kept fragments
    # between cuts that carry no speech (breaths, mouth clicks, chair noise).
    # these survive silence detection because they have energy, but they chop
    # the timeline into micro-slices that add nothing.
    # with a transcript: any keep shorter than min_keep_ms containing no word
    # is absorbed; longer wordless keeps survive (deliberate on-screen action).
    # without a transcript: only keeps shorter than min_keep_wordless_ms are
    # absorbed, since speech can't be ruled out.
    # returns (cleaned cuts, absorbed fragments for reporting).
    merged = merge_ranges(cuts)
    absorbed = []
    for k_start, k_end in invert_cuts(merged, total_ms):
        if words is None:
            wordless, threshold = True, min_keep_wordless_ms
        else:
            wordless = not any(
                w["endMs"] > k_start and w["startMs"] < k_end for w in words
            )
            threshold = min_keep_ms
        if wordless and k_end - k_start < threshold:
            absorbed.append((k_start, k_end))
    if not absorbed:
        return merged, []
    return merge_ranges(merged + absorbed), absorbed


def subtract_cuts(slices: list[dict], cuts: list[tuple[float, float]]) -> list[dict]:
    # subtract cut ranges (source ms) from screenstudio-style slices,
    # preserving all other fields
    result = []
    for sl in slices:
        segments = [(sl["sourceStartMs"], sl["sourceEndMs"])]
        for c_start, c_end in cuts:
            next_segments = []
            for seg_start, seg_end in segments:
                if c_end <= seg_start or c_start >= seg_end:
                    next_segments.append((seg_start, seg_end))
                    continue
                if c_start > seg_start:
                    next_segments.append((seg_start, c_start))
                if c_end < seg_end:
                    next_segments.append((c_end, seg_end))
            segments = next_segments
        for i, (seg_start, seg_end) in enumerate(segments):
            if seg_end - seg_start < MIN_SLICE_MS:
                continue
            new_slice = dict(sl)
            new_slice["sourceStartMs"] = seg_start
            new_slice["sourceEndMs"] = seg_end
            if i > 0:
                new_slice["id"] = new_id()
            result.append(new_slice)
    return result


def versioned_output(base: Path, src: Path | None = None) -> Path:
    # never delete or overwrite: version the output name if it already exists
    dst, n = base, 2
    while dst.exists() or (src is not None and dst.resolve() == src.resolve()):
        dst = base.with_name(f"{base.stem}-v{n}{base.suffix}")
        n += 1
    return dst
