---
name: cutroom
description: Cut silences, pauses, and retakes (repeated takes, restarts, "iterations") out of a talking recording with the cutroom CLI, review the cut on a page that plays it without rendering, propose short-form clips, and export them - Screen Studio projects (.screenstudio) or any video file (mp4/mov), output as a cleaned Screen Studio project, a rendered mp4, or a Final Cut Pro / DaVinci Resolve FCPXML timeline. Use when the user asks to clean up, tighten, process, or "remove the silences and repeats" from a recording, says "process my latest video", wants to review or iterate on a cut, wants short-form clip ideas from a long video, says "export S3" / "take clip 5 for a short", or brings back an FCPXML they edited in Final Cut.
---

# cutroom

Deterministic silence and retake cutting with a review loop. Repo and full docs: https://github.com/rami-maalouf/CutRoom

## Check the install

```bash
cutroom --version
```

If it is missing: `uv tool install git+https://github.com/rami-maalouf/CutRoom` (needs `uv` and `ffmpeg`). Apple Silicon transcribes with mlx-whisper; Linux, Windows and Intel Macs use faster-whisper automatically. The first transcription downloads the model once.

## The project file

All iteration state lives in `<name>.cutroom.json` next to the source. Edit it; never re-run with ad hoc flags you will forget. Times are seconds on the source timeline.

- `edits.cuts`: `[[start, end, note]]` extra cuts, for retakes the detector missed (shown as M1, M2, ...)
- `edits.keeps`: `[[start, end, note]]` never cut; a keep overlapping a retake (R1, R2, ...) rejects it
- `shorts`: `[{"id": "S1", "start", "end", "title", "why"}]` short-form candidates

## Workflow

Without a terminal, cutroom approves every proposed cut, so planning and review come before any export.

1. **Find the input.** "My latest video" with no path: the newest `.screenstudio` (or video) in the folder the user records to that has no `-clean` sibling. Ask when the folder is unknown.
2. **Plan and read.** `cutroom review <source> --report /tmp/cutroom-report.json`. Read `sentences`: the detector only catches a redo that opens with the same words as the bad take. Add redos that start differently to `edits.cuts` (start of the bad take to 0.1 s before the kept take). Check every `decisions` entry: `kept` must be the complete final take.
3. **Short-form ideas, when asked.** Choose clips from the verbatim `sentences`, never from a summary. Apply the standalone gate first: a clip fails if any load-bearing word ("this", "that", "as I said", "for example") points outside it; move the start or end until nothing does. Then rank. Titles come from the speaker's own words, with no hype phrasing. Write them to `shorts` with ids S1, S2, ... and a one-line `why`. If the long-to-short skill is installed, follow it for ranking and headlines.
4. **Hand over the review page.** Run `cutroom review <source> --open` and tell the user what to check. The page plays the cut without rendering. The user toggles Reject and Pick and pastes back feedback such as `Reject R2 ... [498.2, 506.22, "reject R2"]` and `cutroom export "<source>" S3`.
5. **Apply feedback.** Put rejections in `edits.keeps`, new cuts in `edits.cuts`, then run `cutroom review` again (about a second, from the cached transcript). Repeat until the user is happy.
6. **Export once.**
   - Clean long form: `cutroom video <file> --yes --export fcpxml` (no re-encode) or `--export mp4`; Screen Studio: `cutroom project <pkg> --yes` writes `<name>-clean.screenstudio`.
   - Shorts: `cutroom export <source> S3 [S5 ...]` writes `<name>-S3.fcpxml` (video, already cleaned) or `<name>-S3.screenstudio`. Add `--format mp4` for a rendered file.
7. **Edits made in Final Cut.** If the user changed the cut by hand and wants you to continue: they export it (File > Export XML), you run `cutroom import <video> <file.fcpxml>`. That timeline becomes the edit in the project file.
8. **Report** the before and after duration and every decision, including the ones you added.

## Choices

- `--pacing balanced` is the default. Use `tight` for punchy social cuts and `relaxed` for calm tutorials. Pass the same pacing to `review`, `video`, `project` and `export`.
- `--no-retakes` cuts silences only and skips transcription.
- Screen Studio pauses that contain a click or keystroke stay on screen (`--action-before 0.5`, `--action-after 1.0`). Use `--no-protect-actions` only when the user wants the tightest cut and the screen does not matter.
- For Screen Studio, what the user already trimmed in Screen Studio counts as cut.

## Steps that need computer use

cutroom stops at files. Watching the review page, seeing a Screen Studio project's picture (`open -a "Screen Studio" <name>-clean.screenstudio`), exporting from Screen Studio, and importing an FCPXML into Final Cut Pro (File > Import > XML, once, at the end) are GUI steps. Do them only with computer use or ask the user to do them.
