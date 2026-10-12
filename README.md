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
cutroom project ~/Movies/demo.screenstudio --dry-run --yes --report /tmp/demo.json
cutroom project ~/Movies/demo.screenstudio --yes             # writes demo-clean.screenstudio
cutroom video talk.mp4 --yes                                 # renders talk-clean.mp4
cutroom video talk.mp4 --yes --export fcpxml                 # writes talk-clean.fcpxml, no re-encode
cutroom transcribe talk.mp4                                  # only writes talk.transcript.json
```

Useful flags (all commands that cut):

| Flag | Effect |
|---|---|
| `--pacing tight\|balanced\|relaxed` | how hard pauses are cut |
| `--min-silence`, `--trail`, `--lead`, `--min-keep` | override one value of the preset (seconds) |
| `--cut START-END` | cut a range by hand (seconds, repeatable); for retakes the detector missed |
| `--no-retakes` | silences only, no transcription (fast) |
| `--no-silences` | retakes and manual cuts only |
| `--window`, `--threshold`, `--pre-roll` | retake search window, opening similarity (0-1), air kept before the kept take |
| `--review-silences` | approve silence cuts one by one instead of as a batch |
| `--dry-run` | decide and print, write no media |
| `--report FILE` | JSON with every sentence, cut, protected range and kept segment |
| `--yes` | approve everything without asking (also the behavior without a terminal) |

Screen Studio only: `--no-protect-actions`, `--action-before 0.5`, `--action-after 1.0` (seconds kept on screen around each click or keystroke). Video only: `--export mp4|fcpxml`, `--output`.

## Agent workflow

The repo ships an agent skill ([`skills/cutroom`](skills/cutroom/SKILL.md)) that tells Claude Code, Codex, Cursor and other agents when and how to run CutRoom. Install it once per machine:

```bash
bunx skills add rami-maalouf/CutRoom -g     # or: npx skills add rami-maalouf/CutRoom -g
```

CutRoom is built for agents to run deterministically. Without a terminal every proposed cut is approved, so the dry run is the review step:

1. `cutroom project <recording> --dry-run --yes --report /tmp/report.json`
2. Read `sentences` in the report. A retake that starts with different words than its redo is not detected; find those by reading, then add `--cut START-END` (start of the bad take to 0.1 s before the kept take).
3. Run again without `--dry-run`. Check `output duration` in the log.

## Steps that need computer use

These steps happen in GUI apps. CutRoom does not automate them, and they need a person or a computer-use agent:

| Step | How | What to check |
|---|---|---|
| Review a cut Screen Studio project | `open -a "Screen Studio" demo-clean.screenstudio` | cuts land between sentences; protected pauses show the click or typing; the kept take of each retake starts on its first word |
| Export the final video from Screen Studio | Screen Studio's Export button | Screen Studio has no command-line export |
| Import an FCPXML into Final Cut Pro | File > Import > XML, or `open -a "<your Final Cut Pro app>" talk-clean.fcpxml` | the media links (it is referenced, not copied); retake markers sit at the start of each kept take |
| Import into DaVinci Resolve | File > Import > Timeline | Resolve reads the same FCPXML |

## Limits

- Retakes are matched on their opening words only. A redo that starts differently needs `--cut`.
- Filler words ("um", "uh") are not removed, and a stumble inside a sentence with no pause is not detected.
- Protected screen actions keep their pauses, so a click-heavy demo gets longer than with `--no-protect-actions`. Mouse movement alone does not protect a pause.
- Silence detection is energy based (`--noise`, default -35 dB). A noisy room may need a higher value, such as `--noise -30`.

## Development

```bash
uv sync
uv run pytest
```

The tests generate their own audio and video with ffmpeg and pre-write transcripts, so they need no model download and run in a few seconds. On a Mac with Final Cut Pro installed, the FCPXML output is also validated against Final Cut's own DTD. CI runs the suite on Linux, Windows and macOS.
