---
name: cutroom
description: Cut silences, pauses, and retakes (repeated takes, restarts, "iterations") out of a talking recording with the cutroom CLI - Screen Studio projects (.screenstudio) or any video file (mp4/mov), output as a cleaned Screen Studio project, a rendered mp4, or a Final Cut Pro / DaVinci Resolve FCPXML timeline. Use when the user asks to clean up, tighten, process, or "remove the silences and repeats" from a recording, says "process my latest video", or wants a word-level transcript cache of a video.
---

# cutroom

Deterministic silence and retake cutting. Repo and full docs: https://github.com/rami-maalouf/CutRoom

## Check the install

```bash
cutroom --version
```

If it is missing: `uv tool install git+https://github.com/rami-maalouf/CutRoom` (needs `uv` and `ffmpeg`). Apple Silicon transcribes with mlx-whisper; Linux, Windows and Intel Macs use faster-whisper automatically. The first transcription downloads the model once.

## Workflow

Without a terminal, cutroom approves every proposed cut, so the dry run IS the review. Never skip it.

1. **Find the input.** "My latest video" with no path: the newest `.screenstudio` (or video) in the folder the user records to that has no `-clean` sibling. Ask when the folder is unknown.
2. **Dry run with a report:**
   ```bash
   cutroom project <recording.screenstudio> --dry-run --yes --report /tmp/cutroom-report.json
   cutroom video <file.mp4> --dry-run --yes --report /tmp/cutroom-report.json
   ```
3. **Read the report's `sentences`.** The detector only catches a redo that opens with the same words as the bad take. Find redos that start differently by reading, and add each as `--cut START-END` (seconds: start of the bad take to 0.1 s before the kept take). Also check every entry in `retakeCuts`: `kept` must be the complete final take.
4. **Run for real** with the same flags plus any `--cut`, without `--dry-run`:
   - Screen Studio: writes `<name>-clean.screenstudio` next to the source (timeline only, no re-encode).
   - Video: `--export mp4` (default, re-encodes) or `--export fcpxml` (no re-encode, editable in Final Cut Pro or Resolve).
5. **Report** the before and after duration from the log and every retake decision, including any you added by hand.

## Choices

- `--pacing balanced` is the default. Use `tight` for punchy social cuts and `relaxed` for calm tutorials.
- `--no-retakes` cuts silences only and skips transcription.
- Screen Studio pauses that contain a click or keystroke stay on screen (`--action-before 0.5`, `--action-after 1.0`). Use `--no-protect-actions` only when the user wants the tightest cut and the screen does not matter.
- Outputs never overwrite anything; a second run writes `-clean-v2`.

## Steps that need computer use

cutroom stops at files. Opening the result in Screen Studio (`open -a "Screen Studio" <name>-clean.screenstudio`), exporting from Screen Studio, and importing an FCPXML into Final Cut Pro (File > Import > XML) are GUI steps. Do them only with computer use or ask the user to do them, and ask the user to check the retake boundaries and protected moments by eye.
