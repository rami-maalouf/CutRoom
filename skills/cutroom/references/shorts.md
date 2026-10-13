# Shorts from a long recording

The procedure for mining short-form candidates out of hours of talking head (a life story, a podcast, a long talk), proven on "my story" (2026-10-12: 14 files, 3.99 h, 83 candidates). The rules for a single short are in core.md ("Shorts") and taste.md; this file is the order of work and the prompts that worked. For a finished cut of normal length, core.md alone is enough.

| Step | Who | Time on my story |
|---|---|---|
| 1. Folder and project file | lead | minutes |
| 2. Digest | `cutroom digest <folder> --shards 6 --sheets none` | 20 min the first time |
| 3. Find candidates | one sub-agent per chapter, in parallel (8 there) | 11-20 min each |
| 4. One judge ranks them all | one sub-agent | 7 min |
| 5. Merge into the project file | lead | minutes |
| 6. Check every edge by ear (audio) | lead, a script | 3 min for 83 |
| 7. Review | the user, Shorts tab | |

## 1. Folder and project file

- Files in several places (a phone drive, a desk folder): link them into one folder (`ln -s`), one subfolder per place, so clip names say where they come from. Nothing is copied.
- `"style": "talking-head"` in `<folder>/cutroom/cutroom.json` before the first command (a folder defaults to vlog).
- An earlier cleanup (another tool, an older cut) becomes `edits.cuts`: every gap between its kept ranges, with a note ("v04 pause", "v04 retake: <phrase>"). Then mark every short `"raw": true`: a raw short gets only the manual cuts, so it plays exactly as that cleanup did, with no second round of cutting. Check the labels: on my story the old tool's retake times ran over a file it later left out of its edit, and every label after it was 37.9 s off until the offsets included it.

## 2. Digest

Audio only: `--sheets none`. Agents read `digest/all.md` (one block per clip, one line per sentence) and `transcripts/<clip>.transcript.json` (word times). An earlier analysis of the same footage is a MAP of where the stories are, never a source of in and out points: on my story 26 of 34 earlier picks started mid-sentence or leaned on earlier context.

## 3. Find candidates (the brief that worked)

Split the recording into parts by chapter (20-40 minutes each); give every agent the same brief and its own part, and let it read 2 minutes past its edges to finish a story. The brief, with the part filled in:

> You are a short-form editor. You find the shorts hidden in one part of a long talking-head recording, with exact in and out points. Work only with files. Write only your output file. **Delete nothing outside it; keep scratch files in a folder of your own.**
>
> Inputs: `digest/all.md` (print only your part with awk), the word-level transcripts, the map, and `edits.cuts` (the cleanup already done; every short plays with it removed). Your part: <files and time windows, the stories in them, the map entries>.
>
> Hard rules: 1. it stands alone (read only the words that play, as a stranger; any load-bearing word pointing outside fails it, generic references pass; filter first, score second). 2. it opens strong, on the start of a sentence that works alone, never on a connector ("And", "So", "Because", "Which") unless the sentence works with it; start at any word. 3. it ends on the payoff, at the end of a sentence, never on "so yeah". 4. 30-90 s as played, up to 180 s only when the point needs the depth. 5. one idea or one story; several segments only when every join reads as said. 6. verbatim first.
>
> Find every short you would post, including two or three inside a long story. Two versions of one moment are fine with `"version_of"` on the longer one. If a cleanup cut removes words the short needs (deliberate repetition, dialogue, a clipped word), list it in `"restore"` by clip and start.
>
> Title from the passage's own words, under about 7 words, no hype phrasing. Spell the names Whisper gets wrong (give the list). Score 1-10, harshly: hook, standalone, emotion, relatability, payoff. One theme from a fixed list of 6-8. `review`: any line that could hurt the speaker or someone else if posted.
>
> Output a JSON array, best first: `{"title", "hook", "payoff", "why", "theme", "scores", "segments": [{"clip", "start", "end"}], "restore", "review", "from", "version_of"}`. Run the checker until every short passes. Reply with the count, one line per short, and every story with no short and why.

Give the agents a **checker**: it plays each candidate the way it will play (segments minus the cuts, minus its restores) and prints the played length and the first and last words that play. Without it, agents trust their own ranges and the old picks' mistakes come back.

What the agents reported, so expect it: Whisper's word times run across cut edges (a word shown missing usually plays: check by ear before you move an edge); cleanup cuts sometimes remove real speech, labelled as pauses (they restored those too); a restore changes the long edit as well, since the cut goes for every item.

## 4. One judge ranks them all

Each agent scores on its own scale (the best of one part was 36/50, of another 41/50), so a merged list sorted by their scores is not a ranking. Give one judge the full played text of every candidate in one file, and ask for the five scores on one scale across the whole set, a gate pass/fail with the reason, 15 picks spread over the themes (never a long and a short version both), a one-line note per short (often "open on <line> instead"), and the pairs that are too similar to keep both. On my story it failed one candidate at the gate and found 8 near-duplicates the time overlap did not catch.

## 5. Merge

Into `shorts`, in this order: the judge's picks first, then by score; the gate failures out. The fields the review page sorts and groups by: `rank` (the order), `score` (the judge's total / 5, 0-10), `scores`, `theme` (short names: "Friendship", "Travel"), `tags` (`judge pick`, `longer version`, `check before posting`). Put the notes in `why`: "Longer version of S5.", "Similar to S12: keep one.", "Judge: ...", "Check before posting: ...". Apply every `restore` by removing that cut. Then check that no short's played length changed through another short's restore.

## 6. Check every edge by ear

The page's edge checks read Whisper's words, which write many sentence starts in lowercase and hide pauses, so they are hints. The truth is the audio: cut the first and last 6 s that really play (the `keeps` of each short in `review.html`'s data), transcribe them fresh (mlx-whisper, the same model), and compare with the intended first and last sentence. On my story this found what no flag named: a stray word left at the start ("problem if you have...", "is my self esteem..."), and showed most flags were false. To move an edge, transcribe a few seconds around it with word times and set the start on the next word. A connector that runs into the next word with no gap ("So during...") cannot be removed without clipping that word: leave it.

## 7. Review

`cutroom review <folder> --serve` (or `--open`) and the Shorts tab: the side list sorted by priority, theme chips, P / M / X with a note per short, Copy. Apply the feedback (notes to ranges, rejects removed, ids stable), re-run the review, and write every correction into taste.md.
