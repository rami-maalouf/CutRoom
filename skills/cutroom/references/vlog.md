# Vlog

A folder of clips from a shoot, a trip, an event. Nobody scripted it, so the story has to be found, and the picture matters as much as the words: a crowd, a reaction, an empty hall at 1 am can carry a beat with no speech at all. A vlog is always an **edit** (story-first, with the approval gate); there is no clean-up depth, because automatic pause removal barely shortens event footage (3.9 h of Hack the North footage only went to 3.6 h).

**Scenes, not quotes.** A vlog puts the viewer inside a moment: the walk up to a stranger, the whole conversation, the laugh at the end. A beat is a scene, and a scene plays whole, from where it starts to where it resolves. Cut the dead time between scenes, not the life inside them. A cut built from the best line of each conversation feels like a list of clips that start and stop at random. There is no target length: a scene that deserves its place stays, at its full length. A short version for a channel is a separate, later cut. The one place for single lines is the hook's flash-forward.

Every moment the editors judge gets a verdict, "in" or "out", with the reason (the **inclusion list**, `inclusions` in the project file). The review page shows the moments left out, so the user can play any of them and bring it back.

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
| 5. Fill scenes + inclusion list | 4 sub-agents in parallel, one per part | a few minutes each |
| 6. Selects | `cutroom candidates --write-selects --story-order` | seconds |
| 7. Lead edit + read-through | lead agent | check every scene is whole, read the moments left out |
| 8. Review, feedback loop | the user on the review page | |
| 9. Export | `cutroom export <folder> vlog S1 ...` | seconds |

### 1. Brief

`cutroom/brief.md` (core step 1). Include: the angle (what does this video show that nobody else shows?), the intro rule (open on the premise, never on arriving), what to keep (the process, things going wrong, payoffs) and what to cut (dead time, music lyrics, criticism of named people, anything a guest would be embarrassed by). Leave out a target length unless the user gives one: the scenes decide the length. Never tell the agents to split scenes into short pieces or to keep moments under a number of seconds. Keep only editorial direction in it; the steps below supply inputs and outputs.

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
- **Beats are scenes:** setup -> process -> payoff, played whole, often across two or three clips filmed back to back. The process part is often `raw`. List the full range of each scene in the Footage column, not the best lines inside it.
- **Lengths are information, not limits.** Give each scene its rough length so the user sees the shape of the video. Do not cut a scene to fit a number.
- **Running threads** make it feel written: a gag planted early and paid off later, a person who appears twice, a question the hook asks and the ending answers.
- **Visual-only beats** (2-5 s) between talking moments give rhythm.
- **Talking heads to record** (core.md): where a line from the creator would clarify a jump or deliver the brief's lesson. Write them to the story and to `cutroom.json` `pickups` (no `after` yet, but a `near` clip and time), so the review page marks them on the timeline and lists them on the To record tab.
- **List what you leave out and why** (the inclusion list in step 5 makes this complete), and **the facts only the user can confirm** (is this the same person? may we use this guest's line? the spelling of a name). Settle what the footage can settle yourself (compare contact sheets, read a slide).

Run `cutroom review <folder> --open` and stop. The page opens on the Story tab; before selects exist its player says "All footage" (the whole shoot with pauses removed, not the cut).

### 5. Fill the scenes and write the inclusion list (one sub-agent per part of the story)

Split the story into 3-5 parts in play order. Give each part the clips captured in its time window (by the digest's capture times), so that together the parts cover every clip once; the part with the hook also fills the hook from any clip. Move an earlier attempt's files into `candidates/previous/` and `inclusions/previous/` first: `cutroom candidates` reads every `*.json` directly in `candidates/` and `inclusions/`.

Prompt (fill in the part, its chapters and its clips):

> You are an editor filling an approved story outline with footage for a vlog, and judging every moment of your clips. Work only with files; write only your two output files. Folder: `<folder>/cutroom/`. Read `brief.md`, `story.md` (APPROVED: follow it) and `log.md`. Exact times: `digest/all.md`; do not read all of it, `grep -A 80 "## <clip path>" digest/all.md` for the clips you need (a larger -A for very long clips; story times like 52:43 are 3163 s).
> Your part: <scenes and their chapter strings>. Your clips for the inclusion list: <clip paths>.
>
> **1. The scenes.** A vlog puts the viewer inside a moment, so a scene plays whole. Rules: start where the scene starts (the line that sets it up, or the camera arriving) and end where it resolves (the answer, the laugh, the reaction, walking away), never on the best line alone; start at the start time of a transcript line and end at the end time of a line (copy the numbers), so speech is never cut mid-sentence; never split one continuous scene into several pieces to skip a few seconds; cut inside a scene only for a long stretch where nothing happens, or for something the brief says to cut, and say so in `intent`; when two clips were filmed back to back on one moment, take the first to its end and the second from 0.0; mark `"raw": true` where the imperfection is the point; picture-only moments still need a range, and must end before anyone starts talking; note "music muted in Final Cut" where the room plays music; never use the ranges the story excludes. There is no length limit: a scene that deserves its place plays at its full length.
> Write `candidates/part-N.json`, a JSON array IN PLAY ORDER of `{"clip", "start", "end", "chapter", "beat", "role", "raw", "intent", "title"}` (`chapter` and `beat` are names from story.md, as text, never numbers; leave out `beat` when the chapter already is the beat; `role` is one of hook, setup, process, payoff, reaction, bridge, broll, ending; `raw` is true or false; `intent` says why the scene is here).
>
> **2. The inclusion list.** For EVERY clip in your list, judge every distinct moment the log names (a long clip has several; a clip with nothing in it gets one entry for the whole clip). Verdict "in" when your scenes play it, with the scene's `chapter` and `beat`; "out" when they do not. Ask of each "out": would a viewer who loves this vlog miss it? If yes, it is a scene: add it to your part where it fits and make it "in". `why` is one specific sentence: what the moment is worth, or why it stays out (repeats scene X, dead time, a guest would be embarrassed, copyrighted music...). Write `inclusions/part-N.json`, a JSON array of `{"clip", "start", "end", "verdict", "why", "title", "chapter", "beat"}` (`chapter` and `beat` only for "in").
>
> Validate both files with python3 -c "import json; d=json.load(open('<path>')); print(len(d), round(sum(x['end']-x['start'] for x in d)), 's')". Reply with the number of scenes and their total seconds, the in and out counts, every moment you added that the story did not list, and any story item you could not find.

Rules the user asked for explicitly (a moment that must play uncut, a range to avoid) go into the prompt word for word, with exact clip names and times, as FIXED rules. When two clips join on one continuous moment (see taste.md, "Keep the run-up uncut"), give the agent both ranges: the first to the end of its clip, the second from 0.0.

### 6. Selects

```bash
cutroom candidates <folder>                                   # checks clips and ranges
cutroom candidates <folder> --write-selects --story-order     # selects in play order, with beat, role, raw, intent
```

With `inclusions/*.json` present it also writes the inclusion list (`I1`, `I2`, ... in capture order) and prints every verdict the selects do not follow: a moment "in" that no select plays, or "out" that a select plays. Fix each one, in the selects or in the verdict.

(Without `--story-order`, candidates are sorted by capture time and filtered by `score`: that mode is for free-standing highlights, not a story.)

### 7. Lead edit and read-through

`cutroom script <folder>` writes `cutroom/script.md` with the length on line 3. Then, as the lead editor:

1. **Check that every scene is whole.** Read each select's first and last lines: does it start where the scene starts and end where it resolves? Two selects from one clip with a short gap between them are usually one scene cut in two: join them. Do not cut a scene for length. Cut only repeats (the same story told twice: keep the better telling) and long stretches where nothing happens. To set an edge precisely, read the words with times from `transcripts/<clip>.transcript.json` and set `start`/`end` on word boundaries.
2. **Read the moments left out.** The read-through lists them at the end with the reason. Bring back every one a viewer would miss: a select in its place and the verdict "in".
3. **Run the read-through checklist** (core.md), then re-run `cutroom script`. Renumber selects (V1, V2, ...) before the user sees them; after that, keep ids stable.
4. **Place the talking heads:** set each pickup's `"after"` to the select it follows (`cutroom candidates --write-selects` renumbers selects and unplaces them). Add one where the read-through finds a jump the footage cannot bridge. The read-through prints them in place, with the time still to record in its header.
5. **Shorts:** one beat each from the finished cut, `{"id": "S1", "title", "why", "segments": [{"clip", "start", "end"}, ...]}`, standalone gate from core.md.

### 8. Review and feedback

`cutroom review <folder> --open`. The user watches the Vlog (Play; a slate marks each talking head to record), plays any select or short (on a phone: `cutroom review <folder> --serve`, feedback arrives in `cutroom/feedback.md`), and toggles Drop (a select or a talking head), Reject (a retake cut, if retakes were on), Pick (a short) and Bring back (a moment left out, on the Inclusions tab), then Copy. When the user has recorded the talking heads (To record tab), add the files to the folder, make each a select in its place and remove its pickup. Apply the feedback to `cutroom.json` (remove dropped selects, give each moment brought back its place as a select and the verdict "in", add keeps, note picked shorts), re-run `cutroom script` and `cutroom review`, and write every correction into taste.md as a rule.

### 9. Export

`cutroom export <folder> vlog S1 S2` writes `cutroom/exports/<folder>-vlog.fcpxml` (all clips, chapter markers) and one FCPXML per short, replaced on every export. Tell the user which clips need their music muted. Rendering a folder to mp4 is not supported: the FCPXML is the deliverable.
