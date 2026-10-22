# the one cut-planning flow shared by every input type: silences, retakes,
# manual cuts, keeps, action protection, cleanup. adapters supply sessions
# (and optionally on-screen action times, and a second audio source that is
# content too: the video a reaction watches) and turn the final cut list into output.

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .core import (
    Range,
    action_windows,
    cleanup_cuts,
    drop_hallucinated_words,
    find_retake_cuts,
    invert_cuts,
    merge_ranges,
    review_cuts,
    silence_cuts,
    subtract_ranges,
    words_to_sentences,
    MIN_CUT_MS,
)
from .media import collect_silences
from .transcribe import transcribe_sessions

Edit = tuple[float, float, str]  # (start_ms, end_ms, note)


@dataclass
class Plan:
    total_ms: float
    final_cuts: list[Range] = field(default_factory=list)
    # every judgment call, each {"id", "startMs", "endMs", "reason", "status", ...}:
    # R* retakes (status "cut" or "rejected" by a keep), M* manual cuts
    decisions: list[dict] = field(default_factory=list)
    keeps_forced: list[Edit] = field(default_factory=list)
    sentences: list[dict] = field(default_factory=list)
    words: list[dict] | None = None
    # the other voice (a reaction's video): never in sentences or retakes, but
    # it counts as speech wherever the cut asks whether a moment has words
    heard_words: list[dict] = field(default_factory=list)
    protected: list[Range] = field(default_factory=list)
    protected_ms: float = 0.0
    absorbed: list[Range] = field(default_factory=list)

    @property
    def all_words(self) -> list[dict]:
        if not self.heard_words:
            return self.words or []
        return sorted((self.words or []) + self.heard_words, key=lambda w: w["startMs"])

    @property
    def keeps(self) -> list[Range]:
        return invert_cuts(self.final_cuts, self.total_ms)

    @property
    def kept_ms(self) -> float:
        return sum(e - s for s, e in self.keeps)

    @property
    def cut_decisions(self) -> list[dict]:
        return [d for d in self.decisions if d["status"] == "cut"]


def parse_range(spec: str, total_ms: float, flag: str) -> tuple[float, float]:
    # "START-END" in seconds -> (start_ms, end_ms) on the source timeline
    try:
        start_s, end_s = (float(x) for x in spec.split("-", 1))
    except ValueError:
        sys.exit(f"bad {flag} value {spec!r}, expected START-END in seconds")
    start_ms, end_ms = start_s * 1000, end_s * 1000
    if not 0 <= start_ms < end_ms <= total_ms:
        sys.exit(f"{flag} {spec} is outside the recording (0-{total_ms / 1000:.2f}s)")
    return start_ms, end_ms


def _overlaps(a: tuple, ranges: list[tuple]) -> bool:
    return any(r[1] > a[0] and r[0] < a[1] for r in ranges)


def plan_cuts(sessions: list[dict], args, cache: Path | None,
              action_ms: list[float] | None = None,
              edits: dict[str, list[Edit]] | None = None,
              scopes: list[Range] | None = None,
              need_words: bool = False,
              heard: list[dict] | None = None,
              heard_cache: Path | None = None) -> Plan:
    # scopes: when an editor has chosen moments (a folder's selects and shorts),
    # a retake cut only applies if it lies completely inside one of them. in
    # conversations short phrases repeat naturally ("there you go"), and a cut
    # that crosses a chosen moment's edge would override the editor's choice.
    # heard: sessions of a second audio source on the same timeline that is
    # content too (a reaction's video). a pause is only a pause where both are
    # quiet, and a retake cut never removes its sound.
    total_ms = sum(s["durationMs"] for s in sessions)
    plan = Plan(total_ms=total_ms)
    interactive = sys.stdin.isatty() and not args.yes
    edits = edits or {"cuts": [], "keeps": []}
    plan.keeps_forced = list(edits["keeps"]) + [
        (*parse_range(k, total_ms, "--keep"), "--keep") for k in getattr(args, "keep", []) or []]
    keep_ranges = [(s, e) for s, e, _ in plan.keeps_forced]
    approved: list[Range] = []

    # silence detection (ffmpeg) and transcription (whisper) are independent;
    # run them side by side
    def transcribe_all():
        # one after the other: both use the same model
        words = transcribe_sessions(sessions, cache, args.backend)
        return words, transcribe_sessions(heard, heard_cache, args.backend) if heard else []

    with ThreadPoolExecutor(3) as pool:
        silences_job = pool.submit(collect_silences, sessions, args.noise, args.min_silence)
        heard_job = pool.submit(collect_silences, heard, args.noise, args.min_silence) if heard else None
        words_job = None
        if not args.no_retakes or need_words or heard:
            words_job = pool.submit(transcribe_all)
        silences = silences_job.result()
        heard_silences = heard_job.result() if heard_job else None
        words, heard_words = words_job.result() if words_job else (None, [])

    # where the other voice sounds: never cut by a pause or a retake
    heard_sound: list[Range] = []
    if heard_silences is not None:
        heard_words, dropped = drop_hallucinated_words(heard_words, heard_silences)
        if dropped:
            print(f"dropped {len(dropped)} hallucinated words in the system audio (inside silence)")
        plan.heard_words = heard_words
        heard_sound = invert_cuts(merge_ranges(heard_silences), total_ms)
        print(f"system audio: {len(heard_words)} words, sound in {sum(e - s for s, e in heard_sound) / 1000:.1f}s")

    # retake cuts: numbered in detection order so ids stay stable between runs.
    # a keep range overlapping a retake rejects it; the rest are reviewed one by one.
    if words is not None:
        words, dropped = drop_hallucinated_words(words, silences)
        if dropped:
            print(f"dropped {len(dropped)} hallucinated words (inside silence)")
        plan.words = words
        plan.sentences = words_to_sentences(words)
        print(f"transcript sentences: {len(plan.sentences)}")
        retakes = [] if args.no_retakes else find_retake_cuts(
            plan.sentences, args.window, args.threshold, args.pre_roll * 1000)
        for n, cut in enumerate(retakes, 1):
            cut["id"] = f"R{n}"
        if scopes is not None:
            inside = [c for c in retakes
                      if any(a - 500 <= c["startMs"] and c["endMs"] <= b + 500 for a, b in scopes)]
            if len(inside) < len(retakes):
                print(f"retakes outside the chosen moments ignored: {len(retakes) - len(inside)}")
            retakes = inside
        open_retakes = [c for c in retakes if not _overlaps((c["startMs"], c["endMs"]), keep_ranges)]
        print(f"proposed retake cuts: {len(retakes)}"
              + (f" ({len(retakes) - len(open_retakes)} rejected by keeps)" if len(open_retakes) < len(retakes) else ""))
        accepted = {c["id"] for c in review_cuts(open_retakes, args.yes)} if open_retakes else set()
        for cut in retakes:
            cut["status"] = "cut" if cut["id"] in accepted else "rejected"
        plan.decisions += retakes
        retake_ranges = [(c["startMs"], c["endMs"]) for c in retakes if c["status"] == "cut"]
        if heard_sound:
            # a redo said after the video played on: the bad take goes, the video stays
            trimmed = subtract_ranges(retake_ranges, heard_sound, MIN_CUT_MS)
            if sum(e - s for s, e in trimmed) < sum(e - s for s, e in retake_ranges) - 1:
                print("  retake cuts keep the system audio that plays inside them")
            retake_ranges = trimmed
        approved += retake_ranges

    # manual cuts (project file, then --cut): retakes the detector missed
    manual = list(edits["cuts"]) + [
        (*parse_range(c, total_ms, "--cut"), "--cut") for c in getattr(args, "cut", []) or []]
    if manual:
        cuts = [{"id": f"M{n}", "startMs": s, "endMs": e, "reason": "manual", "note": note}
                for n, (s, e, note) in enumerate(manual, 1)]
        print(f"\nmanual cuts: {len(cuts)}")
        accepted = {c["id"] for c in review_cuts(cuts, args.yes)}
        for cut in cuts:
            cut["status"] = "cut" if cut["id"] in accepted else "rejected"
        plan.decisions += cuts
        approved += [(c["startMs"], c["endMs"]) for c in cuts if c["status"] == "cut"]

    # on-screen actions protect a window around themselves from silence cuts
    if action_ms:
        plan.protected = action_windows(
            action_ms, args.action_before * 1000, args.action_after * 1000, total_ms)

    # silence cuts: batch approval by default (there are usually hundreds).
    # they never touch protected actions or keep ranges.
    if not args.no_silences:
        if heard_sound:
            # a pause is where both are quiet, and at least as long as any pause
            silences = subtract_ranges(silences, heard_sound, args.min_silence * 1000)
        cuts = silence_cuts(silences, args.trail * 1000, args.lead * 1000, total_ms)
        if plan.protected:
            unprotected = subtract_ranges(cuts, plan.protected, MIN_CUT_MS)
            plan.protected_ms = sum(e - s for s, e in cuts) - sum(e - s for s, e in unprotected)
            print(f"\nscreen actions: {len(action_ms)} clicks/keystrokes keep "
                  f"{plan.protected_ms / 1000:.1f}s of silence on screen")
            cuts = unprotected
        if keep_ranges:
            cuts = subtract_ranges(cuts, keep_ranges, MIN_CUT_MS)
        total_cut_s = sum(e - s for s, e in cuts) / 1000
        print(f"\nproposed silence cuts: {len(cuts)}, total {total_cut_s:.1f}s")
        if args.review_silences:
            reviewed = review_cuts(
                [{"startMs": s, "endMs": e, "reason": "silence"} for s, e in cuts], args.yes
            )
            approved += [(c["startMs"], c["endMs"]) for c in reviewed]
        else:
            take_all = True
            if interactive:
                take_all = input("  approve all silence cuts? [Y/n] ").strip().lower() not in ("n", "no")
            if take_all:
                approved += cuts
            else:
                print("  silence cuts skipped (use --review-silences for one-by-one)")

    if not approved:
        return plan

    # cleanup layer: absorb tiny wordless fragments left between approved cuts.
    # keep ranges win over everything, including manual cuts that overlap them.
    cleaned, plan.absorbed = cleanup_cuts(
        merge_ranges(approved), total_ms, plan.all_words if words is not None else None, args.min_keep * 1000,
        protected=plan.protected + keep_ranges,
    )
    plan.final_cuts = subtract_ranges(cleaned, keep_ranges) if keep_ranges else cleaned
    if plan.absorbed:
        gone = sum(e - s for s, e in plan.absorbed) / 1000
        print(f"cleanup: absorbed {len(plan.absorbed)} wordless fragments ({gone:.1f}s)")
    return plan


def plan_data(plan: Plan, source: Path) -> dict:
    # json-ready summary of a plan (seconds): what the report and review page show
    def secs(ranges):
        return [[round(s / 1000, 3), round(e / 1000, 3)] for s, e in ranges]

    return {
        "source": str(source),
        "durationSeconds": round(plan.total_ms / 1000, 3),
        "keptSeconds": round(plan.kept_ms / 1000, 3),
        "sentences": [
            {"start": round(s["startMs"] / 1000, 3), "end": round(s["endMs"] / 1000, 3), "text": s["text"]}
            for s in plan.sentences
        ],
        # a reaction: what the video says, for reading the two voices side by side
        **({"heardSentences": [
            {"start": round(s["startMs"] / 1000, 3), "end": round(s["endMs"] / 1000, 3), "text": s["text"]}
            for s in words_to_sentences(plan.heard_words)
        ]} if plan.heard_words else {}),
        "decisions": [
            {"id": d["id"], "start": round(d["startMs"] / 1000, 3), "end": round(d["endMs"] / 1000, 3),
             "reason": d["reason"], "status": d["status"], "removed": d.get("removed", []),
             "kept": d.get("kept"), "note": d.get("note")}
            for d in plan.decisions
        ],
        "forcedKeeps": [[round(s / 1000, 3), round(e / 1000, 3), note] for s, e, note in plan.keeps_forced],
        "protectedRanges": secs(plan.protected),
        "finalCuts": secs(plan.final_cuts),
        "keeps": secs(plan.keeps),
    }


def write_report(plan: Plan, path: Path, source: Path) -> None:
    # machine-readable summary for agents: the sentence list (to spot retakes
    # the detector missed), every decision with its id, and what survives
    path.write_text(json.dumps(plan_data(plan, source), indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote report: {path}")
