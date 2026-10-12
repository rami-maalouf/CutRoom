# Editing core (every style)

What makes a cut feel intelligent is not finding good moments. It is a story: every moment is there because of the one before it and earns the one after it.

This file is the shared core. A talking-head **clean-up** ("process my latest video") only needs the read-through checklist and the shorts section; it has no story. Every **edit** (any vlog, any restructured talking head) follows the order of work below. Do not skip ahead.

## The order of work

1. **Brief.** From the conversation, write the brief: who is talking, for whom, the angle (why this video exists), the target length, must-haves and must-nots. Talking head: `<name>.brief.md`; vlog: `<folder>/cutroom/brief.md`. Ask about anything you would otherwise guess.
2. **Understand the material.** Read all of it before deciding anything (the style file says how: audio only for a talking head; transcript, contact sheets and a clip log for a vlog).
3. **Story outline, then the approval gate.** Write the story (below) to `story.md` (`<name>.story.md` for a talking head, `<folder>/cutroom/story.md` for a vlog), run `cutroom review <source> --open`, and stop. Point the user to the page's Story tab. Never suggest opening the markdown in TextEdit (`open -e`): saving there converts it to `story.rtf` and cutroom no longer finds it. The user approves or corrects the story on the page's Story tab before any selection. This is the cheapest place to change direction.
4. **Select by beat.** Fill the approved beats with footage. Each select carries `beat`, `role` and a one-line `intent` (see the schema below).
5. **Read-through review.** `cutroom script <source>` and read the cut as a viewer would hear it. Fix every story problem (checklist below) before handing over.
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
## What I am leaving out, and why
```

A **beat** is a small sequence, not a quote: a setup (what we are about to see or why it matters), the process (the attempt, the struggle, the conversation), and a payoff (the result, the reaction, the joke landing). Most beats need two or three selects, often from more than one clip. A payoff without its setup confuses; a setup without its payoff disappoints.

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
- Do two neighbouring selects connect, or is there a jump nobody explains? Fix with an order change, a bridge line, or a chapter break.
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

A short must stand alone: no load-bearing word ("this", "as I said", "for example") may point outside it. Cut it from the finished story, not from raw footage. A short is often one beat (setup + payoff) from the long cut. Title it in the speaker's own words, no hype phrasing. Store it as `{"id": "S1", "title", "why", "segments": [...]}` (or `start`/`end` for a single file).
