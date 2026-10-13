# Editing core (every style)

What makes a cut feel intelligent is not finding good moments. It is a story: every moment is there because of the one before it and earns the one after it.

This file is the shared core. A talking-head **clean-up** ("process my latest video") only needs the read-through checklist and the shorts section; it has no story. Every **edit** (any vlog, any restructured talking head) follows the order of work below. Do not skip ahead.

## The order of work

1. **Brief.** From the conversation, write the brief: who is talking, for whom, the angle (why this video exists), the target length, must-haves and must-nots. Talking head: `<name>.brief.md`; vlog: `<folder>/cutroom/brief.md`. Ask about anything you would otherwise guess.
2. **Understand the material.** Read all of it before deciding anything (the style file says how: audio only for a talking head; transcript, contact sheets and a clip log for a vlog).
3. **Story outline, then the approval gate.** Write the story (below) to `story.md` (`<name>.story.md` for a talking head, `<folder>/cutroom/story.md` for a vlog), run `cutroom review <source> --open`, and stop. Point the user to the page's Story tab. Never suggest opening the markdown in TextEdit (`open -e`): saving there converts it to `story.rtf` and cutroom no longer finds it. The user approves or corrects the story on the page's Story tab before any selection. This is the cheapest place to change direction.
4. **Select by beat.** Fill the approved beats with footage. Each select carries `beat`, `role` and a one-line `intent` (see the schema below). Place every approved talking head to record after its select (`"after": "V12"`).
5. **Read-through review.** `cutroom script <source>` and read the cut as a viewer would hear it. Fix every story problem (checklist below) before handing over. A problem the footage cannot fix becomes a talking head to record.
6. **Hand over the review page.** `cutroom review <source> --open`. Feedback comes back as Drop V7, Reject R2, Pick S3; apply it to the project file and re-run (seconds, from the cache).
7. **Export once** (`cutroom export ...`), then propose shorts if asked.
8. **Learn.** When the user corrects a decision, write the lesson into [taste.md](taste.md) as a rule, so the next cut does not repeat it.

## The story outline (story.md)

```markdown
# <title>
## The story in one line
<who, what is at stake, what changes> - one sentence a stranger understands.
## Hook (the first 30 seconds)
<the exact opening: which line or moment, why it hooks, what it promises>
## Beats
| # | Beat | What happens (setup -> process -> payoff) | Footage (clip / time) | Budget |
|---|---|---|---|---|
| 1 | ... | ... | ... | 0:30 |
## Ending
<the last line or moment, and why it closes the promise of the hook>
## Talking heads to record
<P1, P2...: where each goes, what it explains, why the footage cannot. Also in cutroom.json "pickups".>
## What I am leaving out, and why
```

A **beat** is a small sequence, not a quote: a setup (what we are about to see or why it matters), the process (the attempt, the struggle, the conversation), and a payoff (the result, the reaction, the joke landing). Most beats need two or three selects, often from more than one clip. A payoff without its setup confuses; a setup without its payoff disappoints.

## Talking heads to record (pickups)

Some things the footage cannot say: who this person is, why we are suddenly on a subway, what the game is, what the creator felt, the lesson the brief wants. Then propose a short piece for the creator to record: to camera (`talking-head`) or a voiceover over footage (`voiceover`). The user approves them with the story and records them all in one sitting.

Propose one when:
- **The viewer lacks context** a single line would give: the rules, the place, why we are here, who someone is.
- **A jump has no bridge** in the footage: a new place, a new time, a change of plan ("we said we'd go home, but...").
- **The brief wants a lesson or commentary** that nobody said on camera (the psychology behind a moment, what a word means to the community).
- **A key moment needs the inside view:** how it felt, what the creator noticed, what they learned. Right after the moment, never before it.
- **A setup was never filmed** but its payoff is strong.

Rules:
- Never to repeat what the footage already shows or says. A pickup earns its place like any select.
- 10-30 seconds each, about one per 2-3 minutes of video at most. The footage carries the video; talking heads clarify it.
- Give the purpose and 2-4 talking points in the creator's terms. A `draft` line is optional and only a starting point: the creator says it in their own words. Never invent facts, feelings or opinions for them.
- In the story phase, write them to the story and to `cutroom.json` as `pickups` without `after`, each with `"near": {"clip": ..., "time": s}` at the spot in the raw footage where it belongs (no `clip` for a single source). The review page then marks them on the All footage timeline and lists them on the To record tab. After selection, place each one with `"after": "V12"` (or `"start"`).
- Once recorded: the new file goes into the folder (or is a new source for a talking head); make it a select in that place and remove the pickup.

```json
{"id": "P1", "after": "V12", "kind": "talking-head", "seconds": 20,
 "chapter": "The first table", "beat": "why a card works",
 "purpose": "why a question on a card is easier to answer than a question from a stranger",
 "points": ["the card asks, not you", "skip is always allowed: safety makes openness possible"],
 "draft": "optional first line, in the creator's voice"}
```

The review page shows each one on its To record tab (a shot list), in the Vlog list after its select, as a mark on the timeline and as a 3-second slate when the cut plays through that point; the read-through prints it in place and the exported timeline carries a marker there.

## Hooks (first 30 seconds)

- Open on the line that states the premise or the stakes, not on logistics ("we made it to the venue" is not a hook).
- A cold open can borrow the strongest moment from later, then rewind: "Here is how that happened."
- Promise something specific the video then delivers: a question, a challenge, a reveal.
- Viewers decide in the first 30 seconds; the hook must be complete by then.

## Structure and pacing (borrowed from OpenMontage long-form guidance)

- First real payoff before 2:00; the 2-3 minute mark is where attention drops.
- A change of pace every 60-90 seconds: a new place, a new person, a burst of quick moments, a reaction.
- Chapters of 1-3 minutes, each a mini story with its own small payoff; the chapter title is the beat, not the clock.
- End on a closing line that answers the hook. Cut everything after it.

## What never to cut (unless the user says so)

- Reactions and emphasis pauses: they are where meaning lands.
- Bridges that carry flow ("So...", "Okay, now...") when the next moment depends on them.
- The setup of a payoff that stays in, and the payoff of a setup that stays in.

## Read-through checklist (`cutroom script`)

- Does the first select hook? Would a stranger keep watching after 30 seconds?
- Does every "this", "that", "he", "they" have something earlier in the cut to point to?
- Does every payoff have its setup, and every setup its payoff?
- Do two neighbouring selects connect, or is there a jump nobody explains? Fix with an order change, a bridge line, or a chapter break; when the footage has no bridge, propose a talking head to record.
- Is anything said twice? Keep the better delivery.
- `(NOTHING LEFT AFTER CUTS)` or `(empty)` on a select means automatic cuts removed it: make it raw, or fix its range.
- **First and last words of every select:** a stray word from the previous sentence ("meeting but like this time...", "logs which is...") means the start sits inside a word. cutroom snaps outward to whole words, so move the start to the END time of that word.
- **No early reveal:** the payoff of the video (a winner, a result) plays once, at its place in the story. A one-line tease in the hook is fine; a second reveal before the payoff is a spoiler, cut it.
- **Chapter joins:** going from one place or time to another needs a bridge line ("we're about to go to the sponsor party") or the jump confuses.
- **Picture-only items** must not carry speech: end them before anyone starts talking.
- **Hook lines are raw:** a one-line flash-forward must play whole; silence cuts inside it ruin the joke.
- Is the length inside the brief's target?

## Select schema

```json
{"id": "V7", "clip": "pocket4/DJI_..._0017_D.MP4", "start": 129.2, "end": 157.7,
 "chapter": "Friday night", "beat": "the megaphone", "role": "process",
 "intent": "Rami does not know what to say yet - keep the fumbling", "raw": true,
 "title": "who in here wants free AirPods", "why": "the attempt between setup and payoff"}
```

- `role`: `hook`, `setup`, `process`, `payoff`, `reaction`, `bridge`, `broll`, `ending`.
- `raw: true`: the moment plays as it happened (no silence or retake cuts inside). Use it whenever the imperfection is the point.
- For a single file, leave out `clip`. Times are seconds in that clip.

## Shorts

A short must stand alone: no load-bearing word ("this", "as I said", "for example") may point outside it. Cut it from the finished cut when there is one; a long recording that will never be edited as a whole (a 4-hour life story) can be mined directly. Title it in the speaker's own words, no hype phrasing.

Finding them, in this order:

1. **Verbatim first.** Read the exact words of every candidate (the transcript, or `cutroom script`), never a summary of them. The strong picks are the passages already well said out loud.
2. **The gate is a filter, not a score.** Read only the candidate's words: if the first sentence leans on something before it ("Because...", "And it came down to...", "Which also..."), or a name or "that thing" does work the clip never explains, move the start or drop it. The review page flags openings on a leaning word or mid-sentence, endings without a full stop, words that point to earlier in the video ("as I mentioned") and words that need the screen ("right here"), as "to check": fix every flag or say in `why` why it stays.
3. **Short means short.** One idea, the hook in the first seconds, the payoff at the end. Most land at 30-90 s. A long story is not one short: take the 1-3 strongest stretches inside it as their own shorts (tag them `lift-out`).
4. **Start and end on whole sentences.** Start at the first word of a sentence that works with no context; end on the payoff line, not on the "so yeah" after it. cutroom snaps to words; pick the right sentence.
5. **Then score and rank.** `scores` out of 10 each for `hook`, `standalone`, `emotion`, `relatability`, `payoff` (an explainer scores `clarity` and `usefulness` instead of emotion and relatability); `score` is the overall quality; `rank` is the review order (1 first), the best shorts first. Never let a criterion that is really a requirement (standalone) be averaged away.
6. **Theme every short** with one short name from the content ("Social anxiety", "Friendship", "Improv", "Travel", "Career"), the same name for the same theme, 4-8 themes in all, so the user can review one theme at a time.

Store each one as:

```json
{"id": "S1", "title": "The only way to lose is to stop", "why": "one idea, opens on the line itself, ends on the payoff",
 "theme": "Failure", "rank": 1, "score": 8.4, "scores": {"hook": 9, "standalone": 9, "emotion": 8, "relatability": 8, "payoff": 8},
 "tags": ["lift-out"], "segments": [{"clip": "c10.mp4", "start": 41.2, "end": 128.8}]}
```

(`start`/`end` instead of `segments` for one range of a single file; no `clip` for a single file.) Every field but `id` and the range is optional, but the review page sorts by `rank` and `score` and groups by `theme`, so fill them in for any set larger than a handful.

**Out:** `cutroom export <source> S1 S4` (FCPXML). When the video was made in Screen Studio, add `--screenstudio <project>` (once per project) to also get `<project>-S1.screenstudio`, the project cut down to the short by its words (explainer.md has the details and the checks).

The user reviews on the Shorts tab: a sortable list on the side, the chosen short under the player with its words and checks, P / M / X to pick, maybe or reject, a note per short. The copied feedback lists the picks to export, the maybes, the rejects to remove, and the notes ("S4: start 2 s later"). Apply notes to the ranges, remove rejects, keep ids stable for the rest, then re-run `cutroom review`.

