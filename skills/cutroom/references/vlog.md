# Vlog

A folder of clips from a shoot, a trip, an event. Nobody scripted it, so the story has to be found, and the picture matters as much as the words: a crowd, a reaction, an empty hall at 1 am can carry a beat with no speech at all. A vlog is always an **edit** (story-first, with the approval gate); there is no clean-up depth, because automatic pause removal barely shortens event footage (3.9 h of Hack the North footage only went to 3.6 h).

cutroom defaults for this style: `pacing relaxed` (only long pauses go), retake detection **off**. In a vlog, not knowing what to say, talking to the person filming, a false start that gets a laugh: that is the process, and the process is the story. Use `--retakes` only for a clip that is really a talking-head take.

Everything lives in `<folder>/cutroom/`: `cutroom.json` (project file), `brief.md`, `transcripts/`, `digest/`, `sheets/`, `log.md`, `story.md`, `candidates/`, `script.md`, `review.html`, `exports/`.

## The runbook

Measured on the Hack the North run (101 clips, 3.9 h of 4K HEVC, an M-series Mac):

| Step | Who | Time |
|---|---|---|
| 1. Brief | lead agent, from the conversation | minutes |
| 2. Digest | `cutroom digest` | 20 min the first time (transcription), 20 s after; contact sheets 5.5 min once |
| 3. Clip log | 5 vision sub-agents in parallel | 1-4 min each |
| 4. Story + **approval gate** | lead agent alone, then the user | |
| 5. Fill beats | 4 sub-agents in parallel, one per part | 1-2 min each |
| 6. Selects | `cutroom candidates --write-selects --story-order` | seconds |
| 7. Lead edit + read-through | lead agent | the parts ran 30% over budget: expect to cut |
| 8. Review, feedback loop | the user on the review page | |
| 9. Export | `cutroom export <folder> vlog S1 ...` | seconds |

### 1. Brief

`cutroom/brief.md` (core step 1). Include: the angle (what does this video show that nobody else shows?), the target length, the intro rule (open on the premise, never on arriving), what to keep (the process, things going wrong, payoffs) and what to cut (dead time, music lyrics, criticism of named people, anything a guest would be embarrassed by). Keep only editorial direction in it; the steps below supply inputs and outputs.

### 2. Digest

First list the folder's videos. A copy of a clip (a `-bad-quality.mp4` export, a re-encode, the same length as another clip) is not footage: add it to the project file's `"ignore"` (`["*-bad-quality.mp4"]`) before the digest, or it is transcribed and logged twice. DJI `.LRF` proxies and photos are skipped anyway.

```bash
cutroom digest <folder> --shards 5
```

Transcribes each clip once (cached per clip), drops words Whisper invented inside silence, and writes `digest/all.md` plus `digest/shard-N.md` (one block per clip in capture order, one line per sentence `[start-end] text`, run-on lines split into ~8 s pieces) and a contact sheet for every clip (`sheets/*.jpg`, a 4x3 grid of 12 frames spread over the clip). Clips with few words per minute are marked "mostly visual".

### 3. Clip log (vision sub-agents, one per shard)

Prompt that worked (fill in N):

> You are writing a clip log for a vlog edit. Work only with files; write only your output file. Folder: `<folder>/cutroom/`. Read `brief.md` and `digest/shard-N.md`. For EVERY clip in your shard, open its contact sheet (path in the clip header, relative to the folder); frame i (0-11, left to right, top to bottom) is at about t = (i + 0.5) x duration / 12. Write `log/shard-N.md`, one entry per clip in the shard's order:
> `## <clip path>  (<day time>, <length>)` / `where:` place, light. `who:` people / `happens:` one or two sentences from the words AND the picture / `picture:` camera, energy, usable visual-only moments with times / `story value:` which beat it could serve and the key times (setup, process, payoff), or "low" with a reason.
> About 60 words per clip (list the distinct moments of a very long clip with times). Note process moments explicitly: the vlogger not knowing what to say, asking the person filming, figuring things out. Flag guest-comfort risks and copyrighted music. Reply with the number of clips logged and the five with the highest story value.

Then `cat log/shard-*.md > log.md`. The log is reused by every later cut of the same footage.

### 4. Story, then the approval gate

Read the brief, all of `log.md` and the digest lines you need, yourself: this is the one step that cannot be split across agents, because a story needs the whole shoot in one head. Write `cutroom/story.md` (template in core.md). For a vlog:

- **Hook:** a cold open on the premise line (the one that states the angle), a flash-forward of 4-6 one-line beats from later (the strongest images and lines), then the title over a strong picture. Not "we arrived".
- **Chapters follow time and place** (Friday night, Saturday morning...), each with its own small payoff. About 6-8 chapters for a 10-12 minute vlog.
- **Beats are sequences across clips:** setup -> process -> payoff. The process part is often `raw`.
- **Running threads** make it feel written: a gag planted early and paid off later, a person who appears twice, a question the hook asks and the ending answers.
- **Visual-only beats** (2-5 s) between talking moments give rhythm.
- **Talking heads to record** (core.md): where a line from the creator would clarify a jump or deliver the brief's lesson. Write them to the story and to `cutroom.json` `pickups` (no `after` yet), so the review page lists them on the To record tab.
- **List what you leave out and why**, and **the facts only the user can confirm** (is this the same person? may we use this guest's line? the spelling of a name). Settle what the footage can settle yourself (compare contact sheets, read a slide).

Run `cutroom review <folder> --open` and stop. The page opens on the Story tab; before selects exist its player says "All footage" (the whole shoot with pauses removed, not the cut).

### 5. Fill the beats (one sub-agent per part of the story)

Split the story into 3-5 parts in play order. Prompt that worked (fill in the part, its chapters and budgets):

> You are an editor filling an approved story outline with exact footage ranges for a vlog. Work only with files; write only your output file. Folder: `<folder>/cutroom/`. Read `brief.md`, `story.md` (APPROVED: follow it) and `log.md`. Exact times: `digest/all.md`; do not read all of it, `grep -A 80 "## <clip path>" digest/all.md` for the clips you need (a larger -A for very long clips; story times like 52:43 are 3163 s).
> Your part: <beats and their chapter strings>. Rules: every range is one continuous piece of one clip; start at the start time of a transcript line and end at the end time of a line (copy the numbers), so speech is never cut mid-sentence; "(trimmed)" in the story means choose the strongest short ranges inside it; take every part a beat needs (setup, process, payoff), not just the best line; mark `"raw": true` where the imperfection is the point; picture-only moments still need a range, and must end before anyone starts talking; note "music muted in Final Cut" where the room plays music; never use the ranges the story excludes. Budgets: <from story.md>.
> Write `candidates/part-N.json`, a JSON array IN PLAY ORDER of `{"clip", "start", "end", "chapter", "beat", "role", "raw", "intent", "title"}` (`chapter` and `beat` are names from story.md, as text, never numbers; leave out `beat` when the chapter already is the beat; `role` is one of hook, setup, process, payoff, reaction, bridge, broll, ending; `raw` is true or false). Validate with python3 -c "import json; d=json.load(open('<path>')); print(len(d), round(sum(x['end']-x['start'] for x in d)), 's')". Reply with the count, the total seconds, and any story item you could not find.

Move an earlier attempt's candidates into `candidates/previous/` first: `cutroom candidates` reads every `*.json` directly in `candidates/`.

Rules the user asked for explicitly (a moment that must play uncut, a range to avoid) go into the prompt word for word, with exact clip names and times, as FIXED rules. When two clips join on one continuous moment (see taste.md, "Keep the run-up uncut"), give the agent both ranges: the first to the end of its clip, the second from 0.0.

### 6. Selects

```bash
cutroom candidates <folder>                                   # checks clips and ranges
cutroom candidates <folder> --write-selects --story-order     # selects in play order, with beat, role, raw, intent
```

(Without `--story-order`, candidates are sorted by capture time and filtered by `score`: that mode is for free-standing highlights, not a story.)

### 7. Lead edit and read-through

`cutroom script <folder>` writes `cutroom/script.md` with the length on line 3. Then, as the lead editor:

1. **Fit the length.** Parts usually overrun their budgets. Cut in this order: repeats, the middle of long answers, a second piece that says what the first said, warm-up lines before the real line. Never cut a setup whose payoff stays, or a payoff whose setup stays. To trim a select precisely, read its words with times from `transcripts/<clip>.transcript.json` and set `start`/`end` on word boundaries.
2. **Run the read-through checklist** (core.md), then re-run `cutroom script`. Renumber selects (V1, V2, ...) before the user sees them; after that, keep ids stable.
3. **Place the talking heads:** set each pickup's `"after"` to the select it follows (`cutroom candidates --write-selects` renumbers selects and unplaces them). Add one where the read-through finds a jump the footage cannot bridge. The read-through prints them in place, with the time still to record in its header.
4. **Shorts:** one beat each from the finished cut, `{"id": "S1", "title", "why", "segments": [{"clip", "start", "end"}, ...]}`, standalone gate from core.md.

### 8. Review and feedback

`cutroom review <folder> --open`. The user watches the Vlog (Play; a slate marks each talking head to record), plays any select or short, and toggles Drop (a select or a talking head), Reject (a retake cut, if retakes were on) and Pick (a short), then Copy. When the user has recorded the talking heads (To record tab), add the files to the folder, make each a select in its place and remove its pickup. Apply the feedback to `cutroom.json` (remove dropped selects, add keeps, note picked shorts), re-run `cutroom script` and `cutroom review`, and write every correction into taste.md as a rule.

### 9. Export

`cutroom export <folder> vlog S1 S2` writes `cutroom/exports/<folder>-vlog.fcpxml` (all clips, chapter markers) and one FCPXML per short, replaced on every export. Tell the user which clips need their music muted. Rendering a folder to mp4 is not supported: the FCPXML is the deliverable.
