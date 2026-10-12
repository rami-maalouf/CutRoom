---
name: cutroom
description: Edit real footage into a finished cut with the cutroom CLI - a talking-head recording (one take, a Screen Studio project, a podcast-style video) or a vlog (a folder of clips from a shoot or event). Story-first: transcripts (and for vlogs, contact sheets and a clip log) feed a story outline, the cut follows the story, silences and retakes are removed where the style calls for it, and the user reviews on a page that plays the cut without rendering, then exports FCPXML, an mp4, a Screen Studio project, or short-form clips. Use when the user asks to clean up, cut, edit, tighten or "process" a recording, "remove the silences and repeats", make a vlog from a folder of clips, wants short-form clip ideas from a long video, says "export S3" / "take clip 5 for a short", reviews or iterates on a cut, or brings back an FCPXML edited in Final Cut.
---

# cutroom

Story-first editing of real footage. The CLI is deterministic (it plans, plays, exports); the editorial judgment is yours, guided by the references below. Repo: https://github.com/rami-maalouf/CutRoom

## 1. Check the install

```bash
cutroom --version
```

Missing: `uv tool install git+https://github.com/rami-maalouf/CutRoom` (needs `uv` and `ffmpeg`).

## 2. Decide the style, then read its instructions

| The user has | Style | Read |
|---|---|---|
| one recording of one person talking: a talk to camera, a tutorial, a Screen Studio project, an interview | `talking-head` | [references/core.md](references/core.md), then [references/talking-head.md](references/talking-head.md) |
| a folder of clips from a shoot, a trip, an event, a day | `vlog` | [references/core.md](references/core.md), then [references/vlog.md](references/vlog.md) |

Always also read [references/taste.md](references/taste.md): the user's own corrections, which beat any general rule.

Unsure (for example one long recording of an event)? Ask. The style decides what you look at (a talking head is audio only; a vlog needs the picture), whether fumbles are mistakes or story, and the defaults cutroom applies. Store it in the project file as `"style"` (a folder defaults to `vlog`, a single file to `talking-head`).

## 3. Command reference

| Command | Does |
|---|---|
| `cutroom digest <folder>` | vlog: transcribes every clip once, contact sheets, digest shards for parallel agents |
| `cutroom candidates <folder> [--write-selects --min-score N]` | vlog: checks agents' candidate files, shows length per score, writes selects |
| `cutroom review <source> [--open]` | the review page: story, the cut playing from the originals, judgment calls, shorts |
| `cutroom script <source> [--print]` | the read-through: the cut as a script in play order (" / " = a cut inside a moment) |
| `cutroom export <source> vlog\|S1\|V3 ...` | FCPXML (or `--format mp4`) of the program, a short, or a select |
| `cutroom video <file> [--export fcpxml\|mp4]`, `cutroom project <pkg.screenstudio>` | talking head: write the clean cut |
| `cutroom import <video> <edited.fcpxml>` | a timeline edited by hand in Final Cut becomes the edit |
| `cutroom transcribe <media>` | word-level transcript cache only |

Every command reads the project file (`<name>.cutroom.json`, or `<folder>/cutroom/cutroom.json`): `style`, `edits.cuts`, `edits.keeps`, `selects` (V1...), `shorts` (S1...). Edit the file, never rely on one-off flags you will forget. Without a terminal cutroom approves everything it proposes, so review comes before export.

## 4. Steps that need computer use

cutroom stops at files. Watching the review page, seeing a Screen Studio project's picture, exporting from Screen Studio, and importing an FCPXML into Final Cut Pro (once, at the end, with "leave files in place") are GUI steps: do them with computer use or ask the user.
