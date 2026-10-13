# CutRoom

Edit real footage into a finished cut: a **talking head** (one recording, a Screen Studio project, a podcast-style video) or a **vlog** (a folder of clips from a shoot or an event). CutRoom removes silences and retakes, plays any cut on a review page without rendering, and exports Final Cut Pro / DaVinci Resolve timelines (FCPXML), mp4 files, cleaned Screen Studio projects and short-form clips.

The CLI is deterministic: the same footage, transcript and project file always give the same cut. The editorial judgment (which moments tell the story) comes from an AI agent following the bundled skill ([`skills/cutroom`](skills/cutroom/SKILL.md)), and from you on the review page.

## Install

CutRoom needs [uv](https://docs.astral.sh/uv/) and [ffmpeg](https://ffmpeg.org/download.html) on `PATH`.

```bash
uv tool install git+https://github.com/rami-maalouf/CutRoom
bunx skills add rami-maalouf/CutRoom -g     # the agent skill (or: npx skills add rami-maalouf/CutRoom -g)
cutroom --version
```

| Platform | Transcription backend | Notes |
|---|---|---|
| macOS, Apple Silicon | mlx-whisper (Metal) | fastest; the default |
| Linux, Windows, Intel Mac | faster-whisper (CTranslate2, CPU or CUDA) | same Whisper weights; picks CUDA automatically when present |

The first transcription downloads Whisper large-v3-turbo (about 1.6 GB). Both backends run the same weights; their transcripts can still differ in small ways. Force a backend with `--backend mlx|faster-whisper` or `CUTROOM_BACKEND`. To work on CutRoom itself and use your checkout everywhere: `uv tool install --editable .`

## Styles and depths

Every project has a `style` in its project file. It sets CutRoom's defaults and tells the agent which instructions to follow.

| | `talking-head` (a single file, the default) | `vlog` (a folder, the default) |
|---|---|---|
| What the agent looks at | audio only: the words carry it | words and picture: a contact sheet and a clip log for every clip |
| Retakes | detected and cut: a repeated opening is a mistake | off: fumbles and asides are part of the story (`--retakes` turns it on) |
| Pacing | `balanced` | `relaxed`: only long pauses go |
| Depth | a quick **clean-up** ("process my latest video"), or a story-first **edit** | always a story-first **edit** |

A story-first edit: a brief, then a story outline (`story.md`) that you approve on the review page's Story tab, then selects that fill the story's beats, then a read-through (`cutroom script`), then your review. Explicit flags always beat the style defaults.

## Commands

```bash
# talking head
cutroom review talk.mp4 --open                     # plan the cut and open the review page
cutroom script talk.mp4                            # read-through: the cut as a script
cutroom video talk.mp4 --yes --export fcpxml       # talk-clean.fcpxml, no re-encode (follows selects)
cutroom video talk.mp4 --yes                       # talk-clean.mp4
cutroom project ~/Movies/demo.screenstudio --yes   # demo-clean.screenstudio (no re-encode)

# vlog
cutroom digest ~/Movies/weekend --shards 5         # transcripts, contact sheets, digest shards for agents
cutroom candidates ~/Movies/weekend --write-selects --story-order   # agents' picks -> selects
cutroom review ~/Movies/weekend --open             # the vlog by chapter, played from the original files
cutroom export ~/Movies/weekend vlog S1 S2         # cutroom/exports/weekend-vlog.fcpxml and the shorts

# both
cutroom export <source> clean|vlog|S3|V7           # FCPXML (or --format mp4) of the program, a short, a select
cutroom import talk.mp4 edited-in-fcp.fcpxml       # a timeline edited by hand in Final Cut becomes the edit
cutroom transcribe talk.mp4                        # only the word-level transcript cache
```

Flags for every command that plans a cut:

| Flag | Effect |
|---|---|
| `--pacing tight\|balanced\|relaxed` | how hard pauses are cut (default by style) |
| `--min-silence`, `--trail`, `--lead`, `--min-keep` | override one value of the preset (seconds) |
| `--cut START-END`, `--keep START-END` | one-off cut or protected range for this run; the project file makes them permanent |
| `--retakes`, `--no-retakes` | retake detection on or off (default by style) |
| `--no-silences` | retakes and manual cuts only |
| `--window`, `--threshold`, `--pre-roll` | retake search window, opening similarity (0-1), air kept before the kept take |
| `--no-protect-actions`, `--action-before`, `--action-after` | Screen Studio: clicks and keystrokes keep their pause on screen (default on, 0.5 s before, 1.0 s after) |
| `--review-silences` | approve silence cuts one by one instead of as a batch |
| `--dry-run` (`project`, `video`) | decide and print, write nothing |
| `--report FILE` | JSON with every sentence, decision, protected range and kept segment |
| `--yes` | approve everything without asking (also the behavior without a terminal) |

| Pacing | Cuts pauses longer than | Kept after speech | Kept before speech |
|---|---|---|---|
| `tight` | 0.35 s | 0.12 s | 0.05 s |
| `balanced` | 0.6 s | 0.2 s | 0.08 s |
| `relaxed` | 1.2 s | 0.28 s | 0.1 s |

## How a cut is made

1. **Transcribe** locally, word by word, cached (`<name>.transcript.json`, or one per clip in `<folder>/cutroom/transcripts/`). Re-plans after the first take seconds.
2. **Pauses**: ffmpeg's `silencedetect`, shaped by the pacing preset.
3. **Retakes** (talking head): a later sentence (within 60 s) that opens with the same words replaces the earlier takes; restart phrases ("scratch that", "take two") cut their sentence. In a folder, a retake only applies when it lies completely inside one select or short.
4. **Screen actions** (Screen Studio): a pause that contains a click or keystroke stays on screen.
5. **Cleanup**: words Whisper invented inside silence are dropped; tiny wordless fragments between cuts are absorbed.
6. **Selects** (when the story chose moments): each is snapped to whole words with a little air, never past its own clip, and its clean parts play in the story's order. A select marked `"raw": true` plays exactly as recorded.
7. **Write**: never over the original, never over an earlier output next to your media (`-clean`, `-clean-v2`, `-S3`, ...). Folder exports in `cutroom/exports/` are replaced, because the project file can always make them again.

For a Screen Studio project, what you already trimmed in Screen Studio counts as cut, and the cut keeps recorded order (a Screen Studio project is not reordered from outside).

## The project file

`<name>.cutroom.json` next to a single source, or `<folder>/cutroom/cutroom.json`. It is the one place iteration state lives; agents and people edit it, every command reads it. Times are seconds inside a clip; in a folder every range names its `clip`, so adding a file never moves a decision.

```json
{
 "v": 2,
 "style": "vlog",
 "edits": {
  "cuts":  [{"clip": "cam/DJI_0017.MP4", "start": 50.7, "end": 54.7, "note": "missed retake"}],
  "keeps": [{"clip": "cam/DJI_0099.MP4", "start": 498.2, "end": 506.2, "note": "reject R2"}]
 },
 "selects": [
  {"id": "V1", "clip": "cam/DJI_0051.MP4", "start": 0.0, "end": 10.4, "chapter": "Cold open",
   "beat": "hook", "role": "hook", "raw": true, "intent": "the premise line"}
 ],
 "shorts": [
  {"id": "S1", "title": "Who in here wants free AirPods Pro?",
   "segments": [{"clip": "cam/DJI_0016.MP4", "start": 0.0, "end": 14.2}, {"clip": "cam/DJI_0017.MP4", "start": 129.3, "end": 154.6}]}
 ]
}
```

- **edits.cuts** become manual decisions `M1`, `M2`, ...; **edits.keeps** are never cut (a keep overlapping a retake rejects it).
- **selects** (`V1`...) are the program in play order, with the story's `chapter`, `beat`, `role` and `intent`. Without selects, the program is the clean cut in recorded order.
- **shorts** (`S1`...) are short-form candidates, exported from the clean cut.
- **pickups** (`P1`...) are talking heads still to record: `{"id": "P1", "after": "V12", "kind": "talking-head", "seconds": 20, "purpose": "...", "points": ["..."]}`. The agent proposes one where the footage cannot explain itself (a jump with no bridge, missing context, the lesson the brief wants). `after` places it after a select (`"start"` opens the video); before selects exist, `"near": {"clip": ..., "time": s}` marks where in the raw footage it belongs. Once recorded, the file becomes a select.
- **ignore** (folders) lists patterns for files that are not footage, such as `["*-bad-quality.mp4"]` for a lower-quality copy of a clip. They match the path inside the folder. DJI `.LRF` proxies and photos are skipped anyway (only `.mp4`, `.mov`, `.m4v`, `.mkv` and `.mts` are clips).
- For a single file, leave out `clip` (and the short list form `[start, end, note]` still works).

## The review page

`cutroom review <source> --open` writes one small self-contained page (`<name>.review.html`, or `<folder>/cutroom/review.html`). It plays the original media and skips the cut ranges, so reviewing costs no render and no new media; 4K HEVC plays directly in Safari and Chromium on a Mac.

- **Story**: the outline to approve before any selection.
- **Vlog / Clean cut**: the program with a timeline (chapters, retake marks, short marks); each select with Play and Drop, its beat, role, intent and a `raw` tag.
- **To record**: the talking heads to record, as a shot list with each one's purpose, talking points and length; Play where it goes plays the seconds around it. In the Vlog list each one sits after its select, the timeline marks it, and playback shows a 3-second slate in its place.
- **Shorts**: Play clean and Pick. **Cuts**: each retake or manual cut with Play result, Play removed and Reject. **Transcript**: removed sentences struck through.
- **Feedback**: toggle Drop (a select or a talking head), Reject and Pick, press Copy, paste to the agent. It edits the project file and re-plans in seconds.
- **Player keys, as on YouTube**: Space or K plays and pauses, ← → skip 5 s, J L skip 10 s, < > change the speed (1x, 1.5x, 2x; the page remembers it). On the clean cut or the vlog, a skip moves through what plays, so removed ranges never count.

Before a vlog has selects, the player is labelled "All footage": it plays the whole shoot with pauses removed, not a cut.

If you then edit by hand in Final Cut Pro and want the agent to continue from there: File > Export XML, then `cutroom import <video> <exported.fcpxml>`. The Final Cut timeline becomes the edit (plain clips in source order; compound, multicam and retimed clips are refused).

**On a phone:** `cutroom review <source> --serve` also serves the page and the project's media on your local network, and prints a URL and a QR code to scan (same Wi-Fi). On a phone the player stays on top while you scroll, a tap plays or pauses, a double tap on the left or right skips 10 s, and **Send to agent** writes the feedback to `cutroom/feedback.md` (or `<name>.feedback.md`) for the agent to read. Reload the page after the agent edits the project: it re-plans when the project file or the story changes. The URL carries a random token and only the project's own media files are served; stop the server with ctrl-c. macOS may ask once to allow incoming connections. 4K footage plays over Wi-Fi, but a weak connection can stutter.

Why iterate here and not in Final Cut: every FCPXML import creates a new project, and Final Cut can copy the media into the library (one measured library held 43.9 GB of copied source files). Import once, at the end.

## A vlog from a folder of clips

Clips sit on one timeline in capture order (iPhone creation date, then the file's `creation_time`, then its modified time). The full procedure, with the agent prompts that worked, is in [`skills/cutroom/references/vlog.md`](skills/cutroom/references/vlog.md). In short:

1. brief, 2. `cutroom digest`, 3. a clip log from vision sub-agents reading every contact sheet, 4. the story outline and your approval, 5. sub-agents fill the story's beats in parallel, 6. `cutroom candidates --write-selects --story-order`, 7. lead edit and read-through, 8. your review, 9. `cutroom export <folder> vlog S1 ...`.

On the first run (Hack the North, 101 clips, 3.9 h of 4K HEVC): transcription 20 minutes once, contact sheets 5.5 minutes once, every later re-plan seconds; the result was a 12-minute vlog in 8 chapters with 5 short candidates, all CutRoom state in 3.6 MB.

## Steps that need computer use

CutRoom stops at files. These happen in GUI apps, done by a person or a computer-use agent:

| Step | How | What to check |
|---|---|---|
| Review the cut | `open <path>/review.html`, or on a phone `cutroom review <source> --serve` | cuts land between sentences; each retake keeps the full final take; the story flows; shorts stand on their own |
| See a cut Screen Studio project | `open -a "Screen Studio" demo-clean.screenstudio` | protected pauses show the click or typing |
| Export from Screen Studio | Screen Studio's Export button | Screen Studio has no command-line export |
| Import into Final Cut Pro, once | File > Import > XML | media links in place (set Final Cut to leave files in place); mute the clips the agent flagged for room music |
| Import into DaVinci Resolve | File > Import > Timeline | Resolve reads the same FCPXML |

## Limits

- Retakes are matched on their opening words only; a redo that starts differently needs an `edits.cuts` entry.
- Automatic pause removal barely shortens event footage (a crowd is never silent): a vlog's length comes from the story's selects.
- Filler words ("um", "uh") are not removed, and a stumble inside a sentence with no pause is not detected.
- Music playing in the room stays in the audio; mute it in your editor.
- A folder exports FCPXML only (no mp4 render). A Screen Studio project keeps recorded order.
- The review page plays what the browser decodes: on a Mac, Safari and Chromium play H.264 and HEVC; ProRes plays in Safari.
- Protected screen actions keep their pauses, so a click-heavy demo is longer than with `--no-protect-actions`. Mouse movement alone does not protect a pause.
- Silence detection is energy based (`--noise`, default -35 dB). A noisy room may need `--noise -30`.

## Development

```bash
uv sync
uv run pytest
```

The tests generate their own audio and video with ffmpeg and pre-write transcripts, so they need no model download and run in seconds. On a Mac with Final Cut Pro installed, FCPXML output is validated against Final Cut's own DTD. CI runs the suite on Linux, Windows and macOS (ffmpeg 6 and 7+ both covered).
