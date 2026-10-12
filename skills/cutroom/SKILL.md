---
name: cutroom
description: Edit real footage into a finished cut with the cutroom CLI - a talking-head recording (one take, a Screen Studio project, a podcast-style video) or a vlog (a folder of clips from a shoot or event). Quick clean-ups remove silences and retakes; full edits are story-first - transcripts (and for vlogs, contact sheets and a clip log) feed a story outline the user approves, the cut follows the story, and the user reviews on a page that plays the cut without rendering, then exports FCPXML, an mp4, a Screen Studio project, or short-form clips. Use when the user asks to clean up, cut, edit, tighten or "process" a recording, "remove the silences and repeats", make a vlog from a folder of clips, wants short-form clip ideas from a long video, says "export S3" / "take clip 5 for a short", reviews or iterates on a cut, or brings back an FCPXML edited in Final Cut.
---

# cutroom

Editing real footage. The CLI is deterministic (it plans, plays, exports); the editorial judgment is yours, guided by the references below. Repo: https://github.com/rami-maalouf/CutRoom

## 1. Check the install

```bash
cutroom --version
```

Missing: `uv tool install git+https://github.com/rami-maalouf/CutRoom` (needs `uv` and `ffmpeg`).

## 2. Decide the style and the depth

| The user has | Style |
|---|---|
| one recording of one person talking: a talk to camera, a tutorial, a Screen Studio project, an interview | `talking-head` |
| a folder of clips from a shoot, a trip, an event, a day | `vlog` |

| The user wants | Depth | What happens |
|---|---|---|
| "process my latest video", "remove the silences and repeats", "clean this up" (talking head) | **clean-up** | no story: plan, check the judgment calls, write the clean cut. Minutes. |
| "edit this", "make it tighter / better", "turn this into a video", any vlog, any reordering | **edit** | story-first, with the approval gate on the story. |
| short-form clips | after either | shorts come from the finished cut |

Then read, in this order:

1. [references/taste.md](references/taste.md): the user's own corrections. They beat every general rule.
2. [references/core.md](references/core.md): the shared core (story outline, hooks, read-through, schemas). For a clean-up, only "Read-through checklist" and "Shorts" apply.
3. [references/talking-head.md](references/talking-head.md) or [references/vlog.md](references/vlog.md): the style's steps, with the commands in order.

Unsure about the style (for example one long recording of an event) or the depth? Ask. The style decides what you look at (a talking head is audio only; a vlog needs the picture), whether fumbles are mistakes or story, and the defaults cutroom applies. It is stored in the project file as `"style"` (a folder defaults to `vlog`, a single file to `talking-head`).

## 3. Command reference

| Command | Does |
|---|---|
| `cutroom review <source> [--open]` | plans the cut and writes the review page: Story tab, the cut playing from the originals, judgment calls, shorts, transcript |
| `cutroom script <source> [--print]` | the read-through: the cut as a script in play order (" / " = a cut inside a moment) |
| `cutroom video <file> [--export fcpxml\|mp4]` | talking head file: write the cut (follows `selects` if there are any) |
| `cutroom project <pkg.screenstudio>` | Screen Studio: write `<name>-clean.screenstudio` (recorded order) |
| `cutroom export <source> clean\|vlog\|S1\|V3 ...` | FCPXML (or `--format mp4`) of the whole program, a short, or one select |
| `cutroom digest <folder> [--shards 5]` | vlog: transcribes every clip once, contact sheets for every clip, digest shards for parallel agents |
| `cutroom candidates <folder> [--write-selects --story-order]` | vlog: checks agents' candidate files, writes them as selects in story order |
| `cutroom import <video> <edited.fcpxml>` | a timeline edited by hand in Final Cut becomes the edit |
| `cutroom transcribe <media>` | word-level transcript cache only |

Every command reads the project file (`<name>.cutroom.json`, or `<folder>/cutroom/cutroom.json`): `style`, `edits.cuts`, `edits.keeps`, `selects` (V1...), `shorts` (S1...). Edit the file; never rely on one-off flags you will forget. Without a terminal cutroom approves everything it proposes, so review comes before any write. Transcripts are cached, so every re-plan after the first takes seconds.

## 4. Steps that need computer use

cutroom stops at files. Watching the review page, seeing a Screen Studio project's picture, exporting from Screen Studio, muting music in Final Cut, and importing an FCPXML into Final Cut Pro (once, at the end, with "leave files in place") are GUI steps: do them with computer use or ask the user. Point the user to the review page (`open <path>/review.html`), never to the markdown files in TextEdit.
