# a short (or select) made on a finished video, found again in the screen studio
# project it came from, by its words. the finished video's times say nothing
# about the project's: it may open on an intro the project does not have, and
# the project's source still holds every retake. the words are the same, so each
# piece of the short is matched, in order, against the words the project shows
# (its slices), and the matched words become source ranges. cutting the project
# down to those ranges keeps everything else about it: zooms, layout, its own
# slice edges.

import re
from difflib import SequenceMatcher

from .core import HEARD_MS, Range

LEAD_MS, TRAIL_MS = 100.0, 250.0
# whisper starts the first word after a pause early, deep in the pause; no word
# takes longer than this, so its start is never put further back
LONGEST_WORD_MS = 1200.0


def _norm(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


def _match(piece: list[str], pool: list[dict]) -> list[int]:
    # indexes into pool of the piece's words, anchored on the longest run: a
    # stray match far from it (a "but not anymore" said twice) is not the piece
    blocks = [b for b in SequenceMatcher(None, [_norm(w) for w in piece], [_norm(w["word"]) for w in pool],
                                         autojunk=False).get_matching_blocks() if b.size]
    if not blocks:
        return []
    anchor = max(blocks, key=lambda b: b.size)
    slack = max(10, len(piece) // 4)
    return [b.b + k for b in blocks if abs((b.b - b.a) - (anchor.b - anchor.a)) <= slack for k in range(b.size)]


def find_short(pieces: list[list[str]], words: list[dict], shown: list[Range]) -> tuple[list[Range], list[dict]]:
    # (source ranges in ms, one report per piece). shown: the project's slices;
    # a word is shown when it ends inside them, the reliable edge of a word
    def heard(w):
        return not shown or any(a + HEARD_MS <= w["endMs"] <= b + HEARD_MS for a, b in shown)

    keeps, report = [], []
    for piece in pieces:
        if not piece:
            continue
        best = None
        for where, pool in (("in the project's edit", [w for w in words if heard(w)]), ("anywhere in the recording", words)):
            hits = _match(piece, pool)
            if best is None or len(hits) > len(best[1]):
                best = (where, hits, pool)
            if len(hits) >= 0.9 * len(piece):
                break
        where, hits, pool = best
        entry = {"words": len(piece), "matched": len(hits), "where": where}
        if hits:
            first, last = pool[min(hits)], pool[max(hits)]
            i0, i1 = words.index(first), words.index(last)
            lo = max(first["startMs"], first["endMs"] - LONGEST_WORD_MS, words[i0 - 1]["endMs"] if i0 else 0.0) - LEAD_MS
            hi = min(last["endMs"] + TRAIL_MS, words[i1 + 1]["startMs"] if i1 + 1 < len(words) else float("inf"))
            keeps.append((max(0.0, lo), hi))
            entry.update(start=keeps[-1][0], end=hi, first=first["word"].strip(), last=last["word"].strip())
        report.append(entry)
    return keeps, report
