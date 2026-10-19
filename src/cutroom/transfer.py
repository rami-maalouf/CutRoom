# a short (or select) made on a finished video, found again in the screen studio
# project it came from, by its words. the finished video's times say nothing
# about the project's: it may open on an intro the project does not have, and
# the project's source still holds every retake. the words are the same, so each
# piece of the short is matched, in order, against the words the project shows
# (its slices, transcribed as they play), and the matched words become source
# ranges. cutting the project down to those ranges keeps everything else about
# it: zooms, layout, its own slice edges.

import re
from difflib import SequenceMatcher

from .core import Range

LEAD_MS, TRAIL_MS = 100.0, 250.0
# whisper starts the first word after a pause early, deep in the pause; no word
# takes longer than this, so its start is never put further back
LONGEST_WORD_MS = 1200.0
SENTENCE_END = (".", "?", "!")
# a pause at least this long (or a join between two slices) ends a phrase
PHRASE_GAP_MS = 500.0


def _norm(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def _match(piece: list[str], pool: list[dict]) -> list[tuple[int, int]]:
    # (piece index, pool index) of the piece's words, anchored on the longest
    # run: a stray match far from it (a "but not anymore" said twice) is not the piece
    blocks = [b for b in SequenceMatcher(None, [_norm(w) for w in piece], [_norm(w["word"]) for w in pool],
                                         autojunk=False).get_matching_blocks() if b.size]
    if not blocks:
        return []
    anchor = max(blocks, key=lambda b: b.size)
    slack = max(10, len(piece) // 4)
    return [(b.a + k, b.b + k) for b in blocks if abs((b.b - b.a) - (anchor.b - anchor.a)) <= slack
            for k in range(b.size)]


def _grow(pool: list[dict], i0: int, i1: int, lead: int, trail: int) -> tuple[int, int]:
    # the piece's first or last words can match nothing even when they play
    # ("2 times." in one transcript, "two times." in the other): take as many
    # pool words at that edge, while the phrase runs on. never past a sentence
    # end, a pause or a join between slices: what the short leaves out stays out
    def joined(a: dict, b: dict) -> bool:
        return not a["word"].endswith(SENTENCE_END) and b["startMs"] - a["endMs"] < PHRASE_GAP_MS

    while lead and i0 > 0 and joined(pool[i0 - 1], pool[i0]):
        i0, lead = i0 - 1, lead - 1
    while trail and i1 + 1 < len(pool) and joined(pool[i1], pool[i1 + 1]):
        i1, trail = i1 + 1, trail - 1
    return i0, i1


def find_short(pieces: list[list[str]], shown: list[dict], words: list[dict]) -> tuple[list[Range], list[dict]]:
    # (source ranges in ms, one report per piece). shown: the words the project's
    # slices play (transcribe_shown); words: the whole recording, for a piece the
    # edit does not hold
    keeps, report = [], []
    for piece in pieces:
        if not piece:
            continue
        best = None
        for where, pool in (("in the project's edit", shown), ("anywhere in the recording", words)):
            hits = _match(piece, pool)
            if best is None or len(hits) > len(best[1]):
                best = (where, hits, pool)
            if len(hits) >= 0.9 * len(piece):
                break
        where, hits, pool = best
        entry = {"words": len(piece), "matched": len(hits), "where": where}
        if hits:
            lead, trail = min(a for a, _ in hits), len(piece) - 1 - max(a for a, _ in hits)
            i0, i1 = _grow(pool, min(b for _, b in hits), max(b for _, b in hits), lead, trail)
            first, last = pool[i0], pool[i1]
            lo = max(first["startMs"], first["endMs"] - LONGEST_WORD_MS, pool[i0 - 1]["endMs"] if i0 else 0.0) - LEAD_MS
            hi = min(last["endMs"] + TRAIL_MS, pool[i1 + 1]["startMs"] if i1 + 1 < len(pool) else float("inf"))
            keeps.append((max(0.0, lo), hi))
            entry.update(start=keeps[-1][0], end=hi, first=first["word"].strip(), last=last["word"].strip())
        report.append(entry)
    return keeps, report
