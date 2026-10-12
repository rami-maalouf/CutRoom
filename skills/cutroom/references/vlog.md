# Vlog

A folder of clips from a shoot, a trip, an event. Nobody scripted it, so the story has to be found, and the picture matters as much as the words: a crowd, a reaction, an empty hall at 1 am can carry a beat with no speech at all.

cutroom defaults for this style: `pacing relaxed` (only long pauses go), retake detection **off**. In a vlog, not knowing what to say, talking to the person filming, a false start that gets a laugh: that is the process, and the process is the story. Use `--retakes` only for a clip that is really a talking-head take.

Everything lives in `<folder>/cutroom/`.

## 1. Brief

`cutroom/brief.md` (core step 1). Include the angle: what does this video show that nobody else shows?

## 2. Understand the material: words and picture

1. `cutroom digest <folder> --shards 5` transcribes each clip once and writes `digest/all.md`, `digest/shard-N.md` and a contact sheet per clip (`sheets/*.jpg`, a 4x3 grid of frames spread over the clip).
2. **Clip log.** Start one vision sub-agent per shard (a fast model is enough). Each reads its shard and opens the contact sheet of every clip in it, then writes `cutroom/log/shard-N.md`, one entry per clip:
   ```markdown
   ## pocket4/DJI_..._0017_D.MP4  (Fri 23:58, 4:20)
   where: lecture hall corridor, night. who: Rami with a megaphone, Nathan filming, students passing.
   happens: Rami tries to recruit people into the workshop over a megaphone; fumbles the first line; asks Nathan what to say.
   picture: handheld, dark, strong energy. usable visual moments: 0:40 crowd turns to look; 3:35 empty room.
   story value: the megaphone beat (setup at 2:10, attempt 2:20-2:40, payoff "we got four people" 3:35).
   ```
   The log is reused by every later cut of the same footage. Concatenate the shards into `cutroom/log.md`.

## 3. Story outline, then the approval gate

Read the brief, `log.md` and `digest/all.md` yourself; this is the one step that cannot be split across agents, because a story needs the whole weekend in one head. Write `cutroom/story.md` (template in core.md). For a vlog:

- **Hook:** a cold open on the premise line (the one that states the angle), then a flash-forward of 3-5 one-second beats from later (the strongest images and lines), then the title. Not "we arrived".
- **Chapters follow time and place** (Friday night, Saturday morning...), each with its own small payoff.
- **Beats are sequences across clips.** Example: the megaphone: setup ("we got a megaphone, guess what I'm gonna do"), process (the fumbling first attempt, asking the person filming), payoff ("we got four people"). The process part is often `raw`.
- **Running threads** make it feel written: a gag planted early and paid off later (the 3D printed logo), a goal stated at the start and resolved at the end.
- **Visual-only beats** (2-5 s) between talking moments give rhythm: place them in the outline.
- **Ending:** a reflection or the drive home; close the hook's promise.

Run `cutroom review <folder> --open` (the Story tab shows it) and stop for approval.

## 4. Select by beat

Start one sub-agent per chapter or shard with: the brief, the approved `story.md`, `log.md` entries for its clips, and its digest shard. Each fills its beats and writes `cutroom/candidates/<name>.json`:

```json
[{"clip": "...", "start": 0.0, "end": 0.0, "score": 1, "chapter": "...", "beat": "the megaphone",
  "role": "process", "raw": true, "intent": "...", "title": "...", "why": "..."}]
```

Rules for the agents: take every part a beat needs (setup, process, payoff), not just the best line; keep fumbles and crosstalk when they show the process (`raw: true`); cut true dead time (walking with nothing happening, waiting, unrelated chatter); include visual-only moments the outline asks for, using the contact sheets for timing.

Then `cutroom candidates <folder>` to check them, write `selects` in story order (not score order: the story decides), and keep `beat`, `role`, `raw`, `intent`. `cutroom candidates --write-selects` writes capture order; reorder afterwards if the story needs it.

## 5. Read-through, review, export

`cutroom script <folder>`, fix every checklist problem (core.md), then `cutroom review <folder> --open` for the user. Export: `cutroom export <folder> vlog S1 S2`.
