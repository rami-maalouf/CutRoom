# Highlight reel: a long video in 30-90 seconds that makes people feel it

A highlight reel is not a short. A short is one idea that stands alone, cut from inside the video. A reel is the whole video's feeling in 30-90 seconds: the premise, a few real moments that build, a turn, and the payoff, with title cards, captions and music. The model is tinodoesnyc's street episodes (instagram De0QHXGOIvK): plain clips that become joyful through the cut, the cards and the song. Rami's reason (2026-11-15): content that converts evokes emotion, and his plain clips do not do that alone.

CutRoom decides which seconds play and in what order. The look and the music belong to the highlight-reel skill in OpenMontage (`.agents/skills/highlight-reel`), which renders with HyperFrames. The bridge is a reel job: `cutroom export <source> S5 --reel`.

| Step | Who | Gate |
|---|---|---|
| 1. Read the video | lead: transcript, frames, the story the video tells | |
| 2. The beat list | lead: 6-12 beats on the arc below, verbatim quotes, played length | **the user approves the beats** |
| 3. The reel short | lead: one short (S#) with segments, cards and overlays | `cutroom review` plays it |
| 4. Songs | lead: 4-6 songs that fit the feeling, each started on a chosen line | |
| 5. Render and auditions | `reel.py render`: the same cut with each song, one page | **the user picks the song** |
| 6. The reel | `reel.py mix` with `"chosen"` | the user watches it |

## 1. Read the video

A finished vlog (one file) or the CutRoom project it was cut from. Read the whole transcript and `cutroom frames` over the candidate moments: a reel lives on faces and reactions, so the picture matters as much as the words. For a vlog folder, use the digest.

## 2. The beat list (the arc)

| Beat | What it does | Length |
|---|---|---|
| Premise | the first frames: the first words say what this is ("Today we're in Eaton Centre giving out free bad career advice") | 4-7 s |
| Presents | right after the premise: "the chalant society" with "presents" under it (`{"kind": "brand", "presents": true, "before": 1}`) | 1.3 s |
| Title | then the vlog's title on one title card ("bad advice, good people.", `"before": 1`) | 1.3 s |
| Build | 3-6 moments of people reacting: comic exchanges, surprises, the awkward start. Show, never explain | 1-6 s each |
| Turn | the moment it becomes something more (a reset card, a stranger joins in) | |
| Payoff | the shared high: singing together, the cheer. It plays long and live | 10-16 s |
| Close | the payoff's last moment. No brand card here when the reel opened with "presents" | |

Rules:

- **30-90 seconds as played**, cards included. Not 60 exactly: the moments decide.
- **Show the feeling, never explain it** (taste.md "advice-vlog teaser energy": the explanation of curiosity was boring; reactions and celebration were not). One line of Rami's own reflection is fine when it is short and sincere.
- **Verbatim and complete.** Every beat starts and ends on a whole sentence or a whole reaction; check the first and last words that play (the review page's edge checks, then by ear).
- **Live music stays live.** When people sing, the song plays with its own sound: no captions on lyrics, the background song out.
- **Chronological** unless a flash-forward is the hook.
- **The opening (Rami, 2026-11-15):** the premise footage first, then "the chalant society presents", then the vlog's title (its published title: ask when you do not know it), then the build. The cards are short: 1.3 s each (Rami: "the text shouldn't stay for so long"); 1.3 s is also the floor for reading four words.
- **Not from the reference:** no creator name card ("rami. presents"), no "that's it." ending (Rami, 2026-11-15).

Write the list for the user as: beat, the quote, the source time, the played length, and the total. Wait for the yes.

## 3. The reel short

One short in the project file with a `"reel"` block. Segment keys beyond `start`/`end` pass through to the job:

```json
{"id": "S5", "title": "Bad advice, good people (highlight reel)", "raw": false,
 "segments": [
   {"start": 16.6, "end": 22.3, "beat": "premise"},
   {"start": 411.98, "end": 415.34, "beat": "greeting", "fix": {"yeah": "Ahlen khayya!"}},
   {"start": 568.03, "end": 581.5, "beat": "a thousand years", "music": "out", "captions": false, "label": "A Thousand Years"}],
 "reel": {
   "style": "joy",
   "cards": [{"kind": "brand", "presents": true, "before": 1},
             {"kind": "title", "text": "bad advice, good people.", "before": 1},
             {"kind": "plain", "text": "new plan.", "before": 2, "music": "out"},
             {"kind": "insert", "file": "/abs/meme.mp4", "start": 0, "end": 0.56, "before": 2}],
   "overlays": [{"kind": "cheer", "text": "WE KILLED IT", "at": "We killed it"}],
   "fix": {"Eden Center": "Eaton Centre"},
   "drop": ["have to let it go"],
   "music": {"options": [{"song": "walking-on-sunshine", "hit": 51.7, "why": "..."}], "chosen": null}}}
```

- Segment: `music` is `bed` (default: under speech), `out` (live singing, a punchline that needs silence) or `up` (no speech, a montage); `captions: false` for singing; `label` names a song on screen; `fix` corrects the transcript for this segment only (Whisper misses other languages); `gain` for a loud clip.
- Cards: `before` is the segment index they play before (the number of segments = at the end). `title` (red serif), `plain` (a white reset line), `brand` (the chalant society; no text needed; `"presents": true` adds "presents" under it for the opening), `insert` (a short clip, a reaction meme). Cards play with music `up` unless `music` says otherwise.
- Overlays: `cheer` (one big line on the payoff, at the words) and `label`.
- `fix` and `drop` (caption phrases to remove, such as lyrics Whisper heard) apply to the whole reel.

Run `cutroom review <source>`: the Shorts tab plays the reel's footage without cards, to check every edge.

## 4. Songs

Recommend 4-6 songs that fit the feeling of this video, not one default: Rami wants options and picks with you. Mix the obvious choice (the reference's own song) with ones that fit this footage (night, crowd, singing, a city). For each: `reel.py song add "Artist - Title" --slug x` (the library is `~/.media/music`, shared by every project), check the title it found (not a cover or live take), then `reel.py song lyrics x` and set `"hit"` to the second of the song where a strong line starts (the chorus, a lyric that matches the moment): that line lands on the title card, wherever the cards move. `"start"` (the second the song starts from) is the fixed alternative. Write one sentence of why for each: the audition page shows it.

Commercial songs are for choosing. Before posting, Rami adds the chosen song from the platform's music library, or uses a licensed one.

## 5-6. Render, pick, finish

`cutroom export <source> S5 --reel`, then in OpenMontage: `reel.py render <job>` (see the highlight-reel skill). It writes `auditions.html`: the same cut with each song. Rami picks one; set `"chosen"` in the short's reel block, export again, and run `reel.py mix <job>` (the music only, seconds). For Final Cut Pro, `reel.py fcpxml <job>` writes the timeline with real titles and the song on keyframes. Every correction Rami makes becomes a rule here or in taste.md.
