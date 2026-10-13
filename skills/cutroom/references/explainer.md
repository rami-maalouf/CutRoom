# Explainer

One speaker teaching or showing something, mostly for work: an Expo product walkthrough, a feature demo, a "how it works" over a diagram, a tutorial. The video switches between three modes, often inside one sentence:

- **camera**: the speaker talks to the lens (the hook, opinions, the close);
- **screen**: code, a diagram, a dashboard, a doc, often with the speaker's face in a corner;
- **demo**: something happening live on screen (a simulator, a terminal, a click-through).

The words carry most of it, so work from the transcript like a talking head. But the words often point at the picture ("this diagram right here", "as you can see", "this one"), and the pauses in a demo can hold the action (a build finishing, a test passing). So read the transcript first, and look at the picture where the words point at it.

cutroom defaults for this style are the talking head's: `pacing balanced`, retake detection **on**. A Screen Studio recording keeps every pause that holds a click or keystroke. A plain video file has no click data: check the silence cuts inside demos (Cuts tab, Play result) before you write anything.

Set it in the project file: `"style": "explainer"` (a single file defaults to `talking-head`).

## Seeing the picture

`cutroom frames <source> S1 S3` writes a grid of 8 frames spread over what each short (or select) plays: `<name>.frames/S1.jpg` (in a folder: `cutroom/frames/`), with the time of each frame printed. Seven shorts take a few seconds on 4K. Read a grid when:

- the words point at the screen (the review page flags "needs the screen");
- you need to know the mode of a short (tag it `camera`, `screen` or `mixed`);
- a stretch has few words (a demo running).

For the whole video, one contact sheet is enough to learn its modes and layout: `ffmpeg -i <video> -map 0:v:0 -vf "fps=1/10,scale=480:-1,tile=5x10" -frames:v 1 sheet.jpg` (one frame every 10 s).

## Clean-up and edit

As in talking-head.md, with these differences:

- **Demo pauses are content.** A silence while the app loads, a test runs or the diagram animates stays unless it is dead time. In a plain video file, check every silence cut over a demo.
- **Retakes are often re-demos.** A second attempt at a demo can open with different words than the first. Read for them, as you read for missed retakes.
- **Story for an edit:** the problem (what hurts today), the promise (what this video shows), the proof (the demo, early), how it works (the diagram), setup (how to get it), the payoff (what it unlocks: time, cost), the close. Show the working thing before the theory when you can.

## Shorts

The rules in core.md ("Shorts") apply, plus:

1. **The words must stand alone, and so must the picture.** "This" and "right here" are fine when the short keeps the screen that shows them. The review page flags them ("needs the screen"). Read the short's frame grid and decide: does it work with the screen, or only with the screen? Tag every short `camera`, `screen` or `mixed`; the vertical version is decided per short later (a centre crop only works for `camera`).
2. **Words that point to earlier in the video fail the gate** ("as I mentioned", "as I showed you a few minutes ago"; flagged "points to earlier"). Start after them, or cut them out with a second segment.
3. **Every term a stranger needs is explained inside the short.** A product name can stay if the short says what it does. Jargon the target viewer knows (PR, simulator, CI) can stay.
4. **Leave out what dates the short**: "they just dropped this a few hours ago", "this is in limited access", "sign up for the waitlist" (unless that is the point of the short).
5. **Scores for explainers:** `hook`, `standalone`, `clarity` (can a stranger follow it?), `usefulness` (will the viewer learn or want something?), `payoff`. These replace emotion and relatability.
6. **A finished export is already paced by hand**, and screen motion fills its pauses: mark its shorts `"raw": true` so no second round of silence cuts runs inside them.
7. **Product names:** spell them the way the company does in titles and notes. Whisper writes "ETE" for E2E, "argent" for Argent, "Expos" for Expo's.

**A short as a Screen Studio project.** When the video was made in Screen Studio, a picked short can also become a Screen Studio project, so the user can restyle it there (vertical canvas, zooms):

```bash
cutroom export <final video> S2 --screenstudio e2e-1.screenstudio --screenstudio e2e-2.screenstudio
```

It finds the short's words in each project (the words its slices show; the whole recording if they are not there), takes the project that holds them, and writes `e2e-1-S2.screenstudio` next to it with only those parts, keeping the project's own slice edges, zooms and layout. The finished video's times do not matter: an intro added after Screen Studio, a trim in Final Cut, retakes still in the recording are all fine. It stops when under 90% of the words are found, when the short mixes two recordings, or when its pieces play out of recorded order (a project keeps recorded order). Check the result by ear: on TesterArmy S2 (19.4 s in the video) it wrote 3 slices, 19.5 s, the same sentences.

Then check every edge by ear (shorts.md, step 6): in this style, Whisper often places a product name late ("Agent.act" was heard as "dot act" until the start moved 1 s earlier).

## Proven on

TesterArmy E2E (2026-10-13): an 8:13 finished export from Final Cut, 4K, made from 3 Screen Studio recordings. Shorts mined from the export: 7 candidates (3 screen, 3 mixed, 1 camera), 15-70 s, each checked by frame grid and by ear.
