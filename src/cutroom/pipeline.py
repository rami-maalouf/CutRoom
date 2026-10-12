# the one cut-planning flow shared by every input type: silences, retakes,
# manual cuts, action protection, cleanup. adapters supply sessions (and
# optionally on-screen action times) and turn the final cut list into output.

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


@dataclass
class Plan:
    total_ms: float
    final_cuts: list[Range] = field(default_factory=list)
    retakes: list[dict] = field(default_factory=list)
    sentences: list[dict] = field(default_factory=list)
    words: list[dict] | None = None
    protected: list[Range] = field(default_factory=list)
    protected_ms: float = 0.0
    absorbed: list[Range] = field(default_factory=list)

    @property
    def keeps(self) -> list[Range]:
        return invert_cuts(self.final_cuts, self.total_ms)

    @property
    def kept_ms(self) -> float:
        return sum(e - s for s, e in self.keeps)


def parse_cut(spec: str, total_ms: float) -> dict:
    # "START-END" in seconds -> cut dict on the source timeline
    try:
        start_s, end_s = (float(x) for x in spec.split("-", 1))
    except ValueError:
        sys.exit(f"bad --cut value {spec!r}, expected START-END in seconds")
    start_ms, end_ms = start_s * 1000, end_s * 1000
    if not 0 <= start_ms < end_ms <= total_ms:
        sys.exit(f"--cut {spec} is outside the recording (0-{total_ms / 1000:.2f}s)")
    return {"startMs": start_ms, "endMs": end_ms, "reason": "manual"}


def plan_cuts(sessions: list[dict], args, cache: Path,
              action_ms: list[float] | None = None) -> Plan:
    total_ms = sum(s["durationMs"] for s in sessions)
    plan = Plan(total_ms=total_ms)
    interactive = sys.stdin.isatty() and not args.yes
    approved: list[Range] = []

    # silence detection (ffmpeg) and transcription (whisper) are independent;
    # run them side by side
    with ThreadPoolExecutor(2) as pool:
        silences_job = pool.submit(collect_silences, sessions, args.noise, args.min_silence)
        words_job = None
        if not args.no_retakes:
            words_job = pool.submit(transcribe_sessions, sessions, cache, args.backend)
        silences = silences_job.result()
        words = words_job.result() if words_job else None

    # retake cuts: reviewed one by one, they carry semantic content
    if words is not None:
        words, dropped = drop_hallucinated_words(words, silences)
        if dropped:
            print(f"dropped {len(dropped)} hallucinated words (inside silence)")
        plan.words = words
        plan.sentences = words_to_sentences(words)
        print(f"transcript sentences: {len(plan.sentences)}")
        retakes = find_retake_cuts(plan.sentences, args.window, args.threshold, args.pre_roll * 1000)
        print(f"proposed retake cuts: {len(retakes)}")
        plan.retakes = review_cuts(retakes, args.yes) if retakes else []
        approved += [(c["startMs"], c["endMs"]) for c in plan.retakes]

    # manual cuts: retakes the detector missed, reviewed like retakes
    if args.cut:
        manual = [parse_cut(c, total_ms) for c in args.cut]
        print(f"\nmanual cuts: {len(manual)}")
        reviewed = review_cuts(manual, args.yes)
        plan.retakes += reviewed
        approved += [(c["startMs"], c["endMs"]) for c in reviewed]

    # on-screen actions protect a window around themselves from silence cuts
    if action_ms:
        plan.protected = action_windows(
            action_ms, args.action_before * 1000, args.action_after * 1000, total_ms)

    # silence cuts: batch approval by default (there are usually hundreds)
    if not args.no_silences:
        cuts = silence_cuts(silences, args.trail * 1000, args.lead * 1000, total_ms)
        if plan.protected:
            unprotected = subtract_ranges(cuts, plan.protected, MIN_CUT_MS)
            plan.protected_ms = sum(e - s for s, e in cuts) - sum(e - s for s, e in unprotected)
            print(f"\nscreen actions: {len(action_ms)} clicks/keystrokes keep "
                  f"{plan.protected_ms / 1000:.1f}s of silence on screen")
            cuts = unprotected
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

    # cleanup layer: absorb tiny wordless fragments left between approved cuts
    plan.final_cuts, plan.absorbed = cleanup_cuts(
        merge_ranges(approved), total_ms, plan.words, args.min_keep * 1000,
        protected=plan.protected,
    )
    if plan.absorbed:
        gone = sum(e - s for s, e in plan.absorbed) / 1000
        print(f"cleanup: absorbed {len(plan.absorbed)} wordless fragments ({gone:.1f}s)")
        for s, e in plan.absorbed:
            print(f"  absorbed {s / 1000:8.2f}s -> {e / 1000:8.2f}s  ({(e - s) / 1000:.2f}s)")
    return plan


def write_report(plan: Plan, path: Path, source: Path) -> None:
    # machine-readable summary for agents: the sentence list (to spot retakes
    # the detector missed), every cut with its reason, and what survives
    def secs(ranges):
        return [[round(s / 1000, 3), round(e / 1000, 3)] for s, e in ranges]

    report = {
        "source": str(source),
        "durationSeconds": round(plan.total_ms / 1000, 3),
        "keptSeconds": round(plan.kept_ms / 1000, 3),
        "sentences": [
            {"start": round(s["startMs"] / 1000, 3), "end": round(s["endMs"] / 1000, 3), "text": s["text"]}
            for s in plan.sentences
        ],
        "retakeCuts": [
            {"start": round(c["startMs"] / 1000, 3), "end": round(c["endMs"] / 1000, 3),
             "reason": c["reason"], "removed": c.get("removed", []), "kept": c.get("kept")}
            for c in plan.retakes
        ],
        "protectedRanges": secs(plan.protected),
        "finalCuts": secs(plan.final_cuts),
        "keeps": secs(plan.keeps),
    }
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote report: {path}")
