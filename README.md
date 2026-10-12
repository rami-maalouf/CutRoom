# CutRoom

Cut silences and retakes from talking recordings. CutRoom works on Screen Studio projects (it rewrites the timeline, no re-encode) and on any video file (it renders an MP4 or writes a Final Cut Pro timeline).

Everything CutRoom decides is deterministic and reviewable: the same recording, transcript and flags always give the same cuts, and `--dry-run --report` shows every decision before anything is written.

## What it does

1. **Transcribes** the audio locally with Whisper large-v3-turbo, word by word. The transcript is cached next to the media as `<name>.transcript.json`, so later runs are instant.
2. **Finds pauses** with ffmpeg's `silencedetect`. A pacing preset decides which pauses are cut and how much air stays at each cut.
3. **Finds retakes**: when a later sentence (within 60 s) opens with the same words as an earlier one, the earlier takes are cut and the last take is kept. Restart phrases ("scratch that", "let me redo that", "take two") cut their sentence.
4. **Protects screen actions** (Screen Studio only): a pause that contains a click or keystroke stays on screen, so viewers see what you did.
5. **Cleans up**: words Whisper invented inside silence are dropped, and tiny wordless fragments left between cuts (breaths, clicks) are absorbed.
6. **Writes** a new output next to the source. Originals are never modified and outputs are never overwritten (`-clean`, `-clean-v2`, ...).

| Pacing | Cuts pauses longer than | Kept after speech | Kept before speech |
|---|---|---|---|
| `tight` | 0.35 s | 0.12 s | 0.05 s |
| `balanced` (default) | 0.6 s | 0.2 s | 0.08 s |
| `relaxed` | 1.2 s | 0.28 s | 0.1 s |

## Install

CutRoom needs [uv](https://docs.astral.sh/uv/) and [ffmpeg](https://ffmpeg.org/download.html) on `PATH`.

```bash
uv tool install git+https://github.com/rami-maalouf/CutRoom
cutroom --version
```

| Platform | Transcription backend | Notes |
|---|---|---|
| macOS, Apple Silicon | mlx-whisper (Metal) | fastest; the default |
| Linux, Windows, Intel Mac | faster-whisper (CTranslate2, CPU or CUDA) | same Whisper weights; picks CUDA automatically when present |

The first transcription downloads the model (about 1.6 GB) from Hugging Face. Both backends run the same weights; their transcripts can still differ in small ways, so always dry-run first. Force a backend with `--backend mlx|faster-whisper` or `CUTROOM_BACKEND`. On Apple Silicon, `uv tool install 'cutroom[faster-whisper] @ git+https://github.com/rami-maalouf/CutRoom'` adds the second backend for comparison.

To work on CutRoom itself and use your checkout everywhere: `uv tool install --editable .`

## Use

```bash
cutroom review talk.mp4 --open                               # review page: watch the cut, no render
cutroom video talk.mp4 --yes --export fcpxml                 # writes talk-clean.fcpxml, no re-encode
cutroom video talk.mp4 --yes                                 # renders talk-clean.mp4
cutroom project ~/Movies/demo.screenstudio --yes             # writes demo-clean.screenstudio
cutroom export talk.mp4 S3 S5                                # short candidates -> talk-S3.fcpxml, talk-S5.fcpxml
cutroom import talk.mp4 edited-in-fcp.fcpxml                 # make a Final Cut timeline the edit
cutroom transcribe talk.mp4                                  # only writes talk.transcript.json
cutroom digest ~/Movies/weekend                              # a folder of clips: see below
```

Every command reads the project file `<name>.cutroom.json` next to the source, so decisions persist between runs (see below). Outputs never overwrite anything (`-clean`, `-clean-v2`, `-S3`, ...).

Useful flags (all commands that plan cuts):

| Flag | Effect |
|---|---|
| `--pacing tight\|balanced\|relaxed` | how hard pauses are cut |
| `--min-silence`, `--trail`, `--lead`, `--min-keep` | override one value of the preset (seconds) |
| `--cut START-END`, `--keep START-END` | one-off cut or protected range for this run (seconds, repeatable); the project file makes them permanent |
| `--no-retakes` | silences only, no transcription (fast) |
| `--no-silences` | retakes and manual cuts only |
| `--window`, `--threshold`, `--pre-roll` | retake search window, opening similarity (0-1), air kept before the kept take |
| `--no-protect-actions`, `--action-before`, `--action-after` | Screen Studio: screen action protection (default on, 0.5 s before and 1.0 s after each click or keystroke) |
| `--review-silences` | approve silence cuts one by one instead of as a batch |
| `--dry-run` | decide and print, write no media (`project`, `video`) |
| `--report FILE` | JSON with every sentence, decision, protected range and kept segment |
| `--yes` | approve everything without asking (also the behavior without a terminal) |

For Screen Studio projects, an edit you already made in Screen Studio counts as cut: CutRoom only works inside the part your project shows.

## The project file

`<name>.cutroom.json` is the one place iteration state lives. People and agents edit it; CutRoom only reads it. Times are seconds on the source timeline.

```json
{
 "v": 1,
 "edits": {
  "cuts":  [[412.3, 418.0, "retake the detector missed"]],
  "keeps": [[498.2, 506.22, "reject R2"]]
 },
 "shorts": [
  {"id": "S3", "start": 367.45, "end": 382.35, "title": "Do you really care about getting a big tech job?",
   "why": "15 s, hook in the first words, nothing points outside the clip"}
 ]
}
```

- **cuts** become manual decisions `M1`, `M2`, ...
- **keeps** are never cut. A keep that overlaps a proposed retake rejects it, and silence cuts and cleanup never enter a keep.
- **shorts** are short-form candidates. Choosing them is an editorial judgment, made by an agent or a person; CutRoom stores, shows and exports them. A short is exported from the clean cut, so silences and retakes inside its range are already removed.

## Review loop

Reviewing should cost no rendering and no new media. The loop:

1. The agent plans the cut, and if asked, writes short candidates into the project file.
2. `cutroom review <source> --open` writes `<name>.review.html` (one small self-contained file) and opens it. The page plays the original media and skips the cut ranges. It shows every judgment call (`R1` retakes, `M1` manual cuts) with Play result, Play removed and Reject; every short (`S1`) with Play clean and Pick; the transcript with removed sentences struck through; and a timeline of kept, cut, rejected and protected ranges. For Screen Studio projects it plays the microphone audio; the picture is in Screen Studio.
3. Toggle Reject and Pick, press Copy, and paste the feedback to the agent. It reads like: `Reject R2 ... Add to edits.keeps: [498.2, 506.22, "reject R2"]` and `cutroom export "<source>" S3`.
4. The agent edits the project file and re-plans from the cached transcript, in about a second. Repeat until the cut is right.
5. Export once: `cutroom video ... --export fcpxml`, `cutroom export <source> S3`, or `cutroom project ...`. Import into Final Cut Pro once, for finishing.

If you then edit by hand in Final Cut Pro and want the agent to continue from your edit: File > Export XML, then `cutroom import <video> <exported.fcpxml>`. The Final Cut timeline becomes the edit in the project file (plain clips in source order; compound, multicam and retimed clips are refused).

Why not iterate inside Final Cut Pro: an FCPXML import always creates a new project, and Final Cut can copy the media into the library on import. One measured library held 43.9 GB of copied source files. Iterating in the project file and the review page avoids both.

## A vlog from a folder of clips

A folder of clips (a shoot, an event weekend) is one source. Clips sit on one timeline in capture order (iPhone creation date, then the file's `creation_time`, then its modified time), and everything CutRoom keeps lives in a visible `<folder>/cutroom/` subfolder: the project file, one transcript per clip, the digest, contact sheets, the review page and exports.

```bash
cutroom digest ~/Movies/weekend --shards 5 --sheets   # transcribe every clip once, write agent digest shards
cutroom review ~/Movies/weekend --open                # the vlog, by chapter, played from the original files
cutroom export ~/Movies/weekend vlog S2               # cutroom/exports/weekend-vlog.fcpxml and -S2.fcpxml
```

The vlog is `selects` in the project file: an ordered list of moments `{"id": "V1", "clip": "cam/DJI_0051.MP4", "start": 12.3, "end": 40.1, "chapter": "Friday"}`. Choosing them is the agent's job (see the skill): parallel sub-agents read one digest shard each and propose scored candidates, and a lead edit orders the best into selects. CutRoom snaps every select to whole words, removes silences and retakes inside it, and exports the program as one FCPXML across all clips, with chapter markers. Times are anchored to clips, so adding a file to the folder never moves a decision. Without selects, the program is the whole clean footage.

## Agent skill

The repo ships an agent skill ([`skills/cutroom`](skills/cutroom/SKILL.md)) that tells Claude Code, Codex, Cursor and other agents when and how to run CutRoom. Install it once per machine:

```bash
bunx skills add rami-maalouf/CutRoom -g     # or: npx skills add rami-maalouf/CutRoom -g
```

Without a terminal every proposed cut is approved, so agents plan with `--dry-run` or `review` first, read `sentences` in the report for retakes that start with different words than their redo (the detector misses those), and add them to `edits.cuts`.

## Steps that need computer use

These steps happen in GUI apps. CutRoom does not automate them, and they need a person or a computer-use agent:

| Step | How | What to check |
|---|---|---|
| Review the cut | `cutroom review <source> --open` (a browser page) | cuts land between sentences; the kept take of each retake starts on its first word; shorts stand on their own |
| See the picture of a cut Screen Studio project | `open -a "Screen Studio" demo-clean.screenstudio` | protected pauses show the click or typing |
| Export the final video from Screen Studio | Screen Studio's Export button | Screen Studio has no command-line export |
| Import an FCPXML into Final Cut Pro, once | File > Import > XML | the media links in place; set Final Cut to leave files in place so the library does not copy them |
| Import into DaVinci Resolve | File > Import > Timeline | Resolve reads the same FCPXML |

## Limits

- Retakes are matched on their opening words only. A redo that starts differently needs an `edits.cuts` entry (or `--cut`).
- The review page plays what the browser can decode. Safari on a Mac plays H.264, HEVC and ProRes; other browsers may not play ProRes or HEVC.
- Filler words ("um", "uh") are not removed, and a stumble inside a sentence with no pause is not detected.
- Protected screen actions keep their pauses, so a click-heavy demo gets longer than with `--no-protect-actions`. Mouse movement alone does not protect a pause.
- Silence detection is energy based (`--noise`, default -35 dB). A noisy room may need a higher value, such as `--noise -30`.

## Development

```bash
uv sync
uv run pytest
```

The tests generate their own audio and video with ffmpeg and pre-write transcripts, so they need no model download and run in a few seconds. On a Mac with Final Cut Pro installed, the FCPXML output is also validated against Final Cut's own DTD. CI runs the suite on Linux, Windows and macOS.
