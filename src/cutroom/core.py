# pure cut logic: no files, no subprocesses. everything works on ranges in
# source ms on one concatenated timeline (multi-session recordings are laid end
# to end). adapters (screenstudio.py, media.py) do the i/o; improvements here
# benefit every input type.

import difflib
import random
import re
import string
import sys

MIN_SLICE_MS = 120  # drop resulting slices/segments shorter than this
MIN_CUT_MS = 200  # silence cuts shorter than this are not worth a cut
FILLERS = {"um", "uh", "uhm", "erm", "hmm", "like", "so", "okay", "ok", "yeah", "well"}
RESTART_PHRASES = re.compile(
    r"\b(scratch that|let me (redo|start over|try (that|this) again)|start(ing)? over|take two)\b",
    re.IGNORECASE,
)

Range = tuple[float, float]


def new_id() -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=10))


# ---------- pacing ----------
# one knob for how rigorous silence cutting is. pacing decides WHICH pauses get
# cut (min_silence) and what cleanup absorbs (min_keep). it deliberately does
# NOT decide how a cut sounds: once a pause is cut, the boundary is tight for
# every preset - a short natural trail after speech ends (trail) and almost
# nothing before speech resumes (lead). residual pause = trail + lead.
# asymmetry is intentional: trailing silence feels human, leading silence
# feels dead.

PACING_PRESETS = {
    "tight": {"min_silence": 0.35, "trail": 0.12, "lead": 0.05, "min_keep": 2.0},
    "balanced": {"min_silence": 0.6, "trail": 0.2, "lead": 0.08, "min_keep": 1.5},
    "relaxed": {"min_silence": 1.2, "trail": 0.28, "lead": 0.1, "min_keep": 0.8},
}


def resolve_pacing(args) -> None:
    # fill unset (None) pacing-related args from the chosen preset;
    # explicitly passed flags always win over the preset
    preset = PACING_PRESETS[args.pacing]
    for key, value in preset.items():
        if hasattr(args, key) and getattr(args, key) is None:
            setattr(args, key, value)


# ---------- silences ----------


def silence_cuts(
    silences: list[Range],
    trail_ms: float,
    lead_ms: float,
    total_ms: float | None = None,
) -> list[Range]:
    # shrink each silence asymmetrically: keep `trail` after speech ends and
    # `lead` before speech resumes. silences at the very start/end of the
    # recording trim flush - there is no speech to trail from or lead into.
    cuts = []
    for s, e in silences:
        s2 = s if s <= 1 else s + trail_ms
        e2 = e if (total_ms is not None and e >= total_ms - 1) else e - lead_ms
        if e2 - s2 >= MIN_CUT_MS:
            cuts.append((s2, e2))
    return cuts


# ---------- screen actions ----------
# silence cutting only hears audio. a click or keystroke during a pause is
# still content: the viewer needs to see the cursor arrive, the click land and
# the result appear. each action protects a short window around itself from
# silence cuts. retake and manual cuts are content decisions and ignore it.


def action_windows(events_ms: list[float], before_ms: float, after_ms: float,
                   total_ms: float) -> list[Range]:
    windows = [(max(0.0, t - before_ms), min(total_ms, t + after_ms)) for t in events_ms]
    return merge_ranges(windows)


def subtract_ranges(ranges: list[Range], holes: list[Range],
                    min_len_ms: float = 0.0) -> list[Range]:
    # ranges minus holes; pieces shorter than min_len_ms are dropped
    result = []
    holes = merge_ranges(holes)
    for s, e in merge_ranges(ranges):
        pieces = [(s, e)]
        for h_start, h_end in holes:
            if h_end <= s:
                continue
            if h_start >= e:
                break
            next_pieces = []
            for p_start, p_end in pieces:
                if h_end <= p_start or h_start >= p_end:
                    next_pieces.append((p_start, p_end))
                    continue
                if h_start > p_start:
                    next_pieces.append((p_start, h_start))
                if h_end < p_end:
                    next_pieces.append((h_end, p_end))
            pieces = next_pieces
        result += [(a, b) for a, b in pieces if b - a >= min_len_ms]
    return result


# ---------- transcript ----------


def drop_hallucinated_words(
    words: list[dict], silences: list[Range]
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


def merge_ranges(ranges: list[Range]) -> list[Range]:
    merged: list[list[float]] = []
    for s, e in sorted(ranges):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def invert_cuts(cuts: list[Range], total_ms: float) -> list[Range]:
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


def _overlaps_any(start: float, end: float, ranges: list[Range]) -> bool:
    return any(e > start and s < end for s, e in ranges)


def cleanup_cuts(
    cuts: list[Range],
    total_ms: float,
    words: list[dict] | None = None,
    min_keep_ms: float = 1500.0,
    min_keep_wordless_ms: float = 400.0,
    protected: list[Range] | None = None,
) -> tuple[list[Range], list[Range]]:
    # final cleanup pass over an approved cut list: absorb tiny kept fragments
    # between cuts that carry no speech (breaths, mouth clicks, chair noise).
    # these survive silence detection because they have energy, but they chop
    # the timeline into micro-slices that add nothing.
    # with a transcript: any keep shorter than min_keep_ms containing no word
    # is absorbed; longer wordless keeps survive (deliberate on-screen action).
    # without a transcript: only keeps shorter than min_keep_wordless_ms are
    # absorbed, since speech can't be ruled out.
    # a keep that overlaps a protected range (a click or keystroke) is never absorbed.
    # returns (cleaned cuts, absorbed fragments for reporting).
    merged = merge_ranges(cuts)
    word_ranges = [(w["startMs"], w["endMs"]) for w in words] if words is not None else None
    absorbed = []
    for k_start, k_end in invert_cuts(merged, total_ms):
        if protected and _overlaps_any(k_start, k_end, protected):
            continue
        if word_ranges is None:
            wordless, threshold = True, min_keep_wordless_ms
        else:
            wordless = not _overlaps_any(k_start, k_end, word_ranges)
            threshold = min_keep_ms
        if wordless and k_end - k_start < threshold:
            absorbed.append((k_start, k_end))
    if not absorbed:
        return merged, []
    return merge_ranges(merged + absorbed), absorbed


def subtract_cuts(slices: list[dict], cuts: list[Range]) -> list[dict]:
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
