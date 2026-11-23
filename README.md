# CutRoom

CutRoom is a command-line video editor for footage you've already recorded. Give it a video file, a Screen Studio project, or a folder of clips. It transcribes speech locally, finds long pauses and likely retakes, and gives you a browser preview of the proposed cut before you export. Your source footage stays intact.

Use it to clean up a talking-head recording, keep the on-screen action in a demo, cut a Screen Studio reaction with two audio tracks, or build a vlog from a shoot. You can also review shorter clips from a longer recording and export the ones you pick.

## Get started with one video

### Install

Install [uv](https://docs.astral.sh/uv/) and [FFmpeg](https://ffmpeg.org/download.html), with `ffmpeg` and `ffprobe` available on your PATH. Then install CutRoom with Python 3.11. uv can download that interpreter if needed.

```bash
uv tool install --python 3.11 git+https://github.com/rami-maalouf/CutRoom
cutroom --version
```

### Preview and export

Use a short MP4 with an audio track for your first run. Replace `talk.mp4` with its path:

```bash
cutroom review talk.mp4 --open
```

The first transcription downloads the Whisper speech model (about 1.6 GB). Transcription runs on your machine and saves word timings in `talk.transcript.json` for later runs. The review command creates `talk.review.html` and opens it in your browser. Press play to hear the suggested edit. The page plays the original file and skips the cut ranges, so there is no video render to wait for.

Open **Cuts** to listen to the result of a retake cut or hear what was removed. To restore a cut for the next run, add its time range to `edits.keeps` in `talk.cutroom.json`, or use Reject and copy the review feedback to the agent helping with the edit. You can also keep a range for one run with `--keep 12.4-15.8`. Pass the same options when you export.

When the cut is ready, choose an output:

```bash
# Render a new video next to the source
cutroom export talk.mp4 clean --format mp4

# Write an editable timeline next to the source
cutroom export talk.mp4 clean
```

These commands produce `talk-clean.mp4` and `talk-clean.fcpxml`, respectively, on the first export. Import the FCPXML into Final Cut Pro or DaVinci Resolve to keep editing. The timeline references the source file, so keep the original media available when you import it.

## What CutRoom does for you

| What you have | How to use it |
|---|---|
| A talk, interview, podcast, or camera recording | Review a first pass that shortens long pauses and looks for restarted sentences. Use `--pacing relaxed` to leave more room around the words. |
| A Screen Studio demo or tutorial | Review the audio, then run `cutroom project demo.screenstudio --yes` to create a trimmed copy when there are cuts. CutRoom can keep pauses around clicks and keystrokes so viewers still see the action. Open the copy in Screen Studio to review the picture and export the video. |
| A Screen Studio reaction | Set `"style": "reaction"` in `demo.cutroom.json` beside the project. With system audio recorded separately, CutRoom can keep the watched video's audio when it cuts a mic retake and trim pauses where both tracks are quiet. [Reaction workflow](skills/cutroom/references/reaction.md) |
| Several Screen Studio recordings from one setup | Run `cutroom join part1.screenstudio part2.screenstudio --output both.screenstudio` to make one project in the order you supplied. It uses the first project's look and layout. |
| A folder of footage for a vlog | Run `cutroom digest weekend` to index the clips with transcripts and contact sheets, then choose the ranges and order that tell the story. Review the edit with `cutroom review weekend --open` and export a timeline with `cutroom export weekend vlog`. [Vlog workflow](skills/cutroom/references/vlog.md) |
| A long recording with potential shorts | Add candidate clips to the project file, then watch, pick, or reject them on the **Shorts** tab. `cutroom export talk.mp4 S1` writes a timeline for the candidate named `S1`. [Shorts workflow](#shorts) |

For a cleanup, CutRoom can go from a source file to a proposed cut on its own. For a story edit, someone chooses the scenes worth keeping, their order, and which moments work as shorts. You can do that by hand in [the project file](#the-project-file) or use an agent with the bundled [CutRoom skill](skills/cutroom/SKILL.md). The agent can draft a story outline and propose clips for you to review. The CLI reads those decisions and plays or exports the resulting edit.

To install the optional agent skill:

```bash
bunx skills add rami-maalouf/CutRoom -g
```

## Choose an output

| Output | Use it for |
|---|---|
| **MP4** | A playable video rendered from one source video. |
| **FCPXML** | An editable timeline for a single video or a folder of clips. It links to the original media and can carry chapter markers and select speed changes. |
| **Screen Studio project** | An editable copy of a recording with cuts applied in recorded order, without re-encoding. Render it inside Screen Studio. |
| **Shorts text job** (`.text.json`) | Hand off a short's approved headline and calls to action to the `shorts-text` skill in OpenMontage. CutRoom needs the finished short video for this handoff. |
| **Highlight reel job** (`.reel.json`) | Hand off the chosen footage ranges, word timings, and reel settings to the `highlight-reel` skill in OpenMontage for titles, captions, and music. [How to set up a reel](skills/cutroom/references/highlight.md) |

The two JSON handoffs supply instructions and timing for the corresponding skill to render.

## Transcription settings

| Platform | Transcription backend | Notes |
|---|---|---|
| macOS, Apple Silicon | mlx-whisper (Metal) | fastest; the default |
| Linux, Windows, Intel Mac | faster-whisper (CTranslate2, CPU or CUDA) | same Whisper weights; picks CUDA automatically when present |

Both backends run Whisper large-v3-turbo. Their transcripts can differ in small ways. Set `--backend mlx` or `--backend faster-whisper` on an individual command, or set `CUTROOM_BACKEND` for your environment.

## Styles and depths

Every project has a `style` in its project file. It sets CutRoom's defaults and tells the agent which instructions to follow.

| | `talking-head` (a single file, the default) | `explainer` (set it in the project file) | `vlog` (a folder, the default) |
|---|---|---|---|
| What the agent looks at | audio only: the words carry it | the words first, the picture where they point at it (`cutroom frames`) | words and picture: a contact sheet and a clip log for every clip |
| Retakes | detected and cut: a repeated opening is a mistake | detected and cut; a re-demo can open differently, so the agent reads for it | off: fumbles and asides are part of the story (`--retakes` turns it on) |
| Pacing | `balanced` | `balanced`; demo pauses that hold action stay (Screen Studio clicks and keystrokes are kept automatically) | no automatic pause cuts: a scene plays as filmed, the editor cuts dead time by choosing ranges (`--silences` brings them back, `relaxed`) |
| Depth | a quick **clean-up** ("process my latest video"), or a story-first **edit** | the same as a talking head | always a story-first **edit** |

A `reaction` (set it in the project file) cuts like a talking head, with three differences: a pause is only cut where the mic and the video are both quiet, a retake cut never removes the video's sound, and clicks protect no pauses (they pause and seek the video). The read-through marks the video's lines with `video:`. See [reaction.md](skills/cutroom/references/reaction.md), also for making a whole version and a replies-only version.

A story-first edit: a brief, then a story outline (`story.md`) that you approve on the review page's Story tab, then selects that fill the story's beats, then a read-through (`cutroom script`), then your review. Explicit flags always beat the style defaults.

## Commands

Run `cutroom --help` to list commands or `cutroom export --help` to see the options for one command.

```bash
cutroom script talk.mp4                          # read the edit as a script in playback order
cutroom check talk.mp4 R1                        # transcribe both sides of retake cut R1
cutroom transcribe talk.mp4                      # write word timings without planning an edit
cutroom review talk.mp4 --serve                  # review on a phone on the same Wi-Fi
cutroom import talk.mp4 edited.fcpxml            # reuse cuts from a compatible Final Cut timeline

cutroom candidates weekend --write-selects --story-order  # apply candidate files already in the project
cutroom export weekend vlog S1 S2                # write the main timeline and two short timelines

cutroom frames final.mov S1 S2                   # see frames from two short candidates
cutroom export final.mov S2 --screenstudio demo.screenstudio  # also cut the source Screen Studio project to S2
cutroom export final.mov S2 --text S2-export.mp4  # write S2-export.text.json for an existing finished export
cutroom export final.mov S5 --reel               # write final-S5.reel.json when S5 has reel settings
```

Use these flags on commands that plan a cut. The command's help lists which ones it accepts.

| Flag | Effect |
|---|---|
| `--pacing tight\|balanced\|relaxed` | how hard pauses are cut (default by style) |
| `--min-silence`, `--trail`, `--lead`, `--min-keep` | override one value of the preset (seconds) |
| `--cut START-END`, `--keep START-END` | one-off cut or protected range for this run; the project file makes them permanent |
| `--retakes`, `--no-retakes` | retake detection on or off (default by style) |
| `--no-silences` / `--silences` | retakes and manual cuts only (the vlog default) / also cut long pauses |
| `--window`, `--threshold`, `--pre-roll` | retake search window, opening similarity (0-1), air kept before the kept take |
| `--no-protect-actions` / `--protect-actions`, `--action-before`, `--action-after` | Screen Studio: clicks and keystrokes keep their pause on screen (default on except for reactions, 0.5 s before, 1.0 s after) |
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

1. **Transcribe** locally, word by word, cached (`<name>.transcript.json`, or one per clip in `<folder>/cutroom/transcripts/`). Later plans reuse the cached transcript.
2. **Pauses**: ffmpeg's `silencedetect`, shaped by the pacing preset.
3. **Retakes** (enabled by default for talking heads, explainers, and reactions): a later sentence (within 60 s) that opens with the same words replaces the earlier takes; restart phrases ("scratch that", "take two") cut their sentence. In a folder, a retake only applies when it lies completely inside one select or short.
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

- **style** is `talking-head`, `explainer`, `reaction` or `vlog` (see above). Set it before the first command: a folder defaults to `vlog`, a single file to `talking-head`.
- **edits.cuts** become manual decisions `M1`, `M2`, ...; **edits.keeps** are never cut (a keep overlapping a retake rejects it).
- **selects** (`V1`...) are the program in play order, with the story's `chapter`, `beat`, `role` and `intent`. Without selects, the program is the clean cut in recorded order.
- **shorts** (`S1`...) are short-form candidates, exported from the clean cut (`"raw": true` plays a short exactly as recorded: right for a finished export, already paced by hand). Optional `theme`, `rank` (1 = review first), `score` (0-10), `scores` (`{"hook": 8, ...}`) and `tags` drive the Shorts tab; `copy` is the text on the finished short (a headline and calls to action, each on the words it starts on, proposed by the agent and approved by you); see [core.md](skills/cutroom/references/core.md#shorts) for how to find good ones.
- **pickups** (`P1`...) are talking heads still to record: `{"id": "P1", "after": "V12", "kind": "talking-head", "seconds": 20, "purpose": "...", "points": ["..."]}`. The agent proposes one where the footage cannot explain itself (a jump with no bridge, missing context, the lesson the brief wants). `after` places it after a select (`"start"` opens the video); before selects exist, `"near": {"clip": ..., "time": s}` marks where in the raw footage it belongs. Once recorded, the file becomes a select.
- **inclusions** (`I1`..., folders) are the editors' verdicts on every moment worth judging: `{"id": "I1", "clip": ..., "start": s, "end": s, "verdict": "in" | "out", "why": "...", "title": "..."}`. They play nothing (the selects do); they make each choice visible. `cutroom candidates` writes them from the agents' `inclusions/*.json` and reports a verdict the selects do not follow.
- **ignore** (folders) lists patterns for files that are not footage, such as `["*-bad-quality.mp4"]` for a lower-quality copy of a clip. They match the path inside the folder. DJI `.LRF` proxies and photos are skipped anyway (only `.mp4`, `.mov`, `.m4v`, `.mkv` and `.mts` are clips).
- For a single file, leave out `clip` (and the short list form `[start, end, note]` still works).

## The review page

`cutroom review <source> --open` writes one small self-contained page (`<name>.review.html`, or `<folder>/cutroom/review.html`). It plays the original media and skips the cut ranges, so reviewing costs no render and no new media; 4K HEVC plays directly in Safari and Chromium on a Mac.

- **Story**: the outline to approve before any selection.
- **Vlog / Edit / Clean cut**: the program (Edit for a talking head made of several files) with a timeline (chapters, retake marks, short marks); each select with Play and Drop, its beat, role, intent and a `raw` tag.
- **Inclusions** (vlogs): every moment the agents judged, with its verdict and the reason. The moments left out come first; Play shows one as it was filmed, and Bring back asks the agent to give it its place.
- **To record**: the talking heads to record, as a shot list with each one's purpose, talking points and length; Play where it goes plays the seconds around it. In the Vlog list each one sits after its select, the timeline marks it, and playback shows a 3-second slate in its place.
- **Shorts**: built to review dozens of candidates fast. The page opens on it when shorts are the job.
  - The side list sorts by priority (`rank`), quality (`score`), length or recording order, groups by `theme`, and filters by status, theme and words.
  - Click a short (or press ↓) and it plays, clean, with its words under the player and the word being said marked. Click a word to play from there.
  - Each short shows its edge checks ("opens on \"Because\"", "ends mid-sentence", "needs the screen", "points to earlier"), its scores and the agent's reason.
  - P, M and X pick, mark maybe or reject, then the next short plays. N writes a note ("start 2 s later"). V shows a 9:16 centre crop.
  - Decisions and notes stay in the browser after a reload, and go into the feedback text.
- **Cuts**: each retake or manual cut with Play result, Play removed and Reject. **Transcript**: removed sentences struck through.
- **Feedback**: toggle Drop (a select or a talking head), Reject and Bring back, decide on shorts, press Copy, paste to the agent. It edits the project file and re-plans in seconds.
- **Player keys, as on YouTube**: Space or K plays and pauses, ← → skip 5 s, J L skip 10 s, < > change the speed (1x, 1.5x, 2x; the page remembers it). On the clean cut or the vlog, a skip moves through what plays, so removed ranges never count.

Before a vlog has selects, the player is labelled "All footage": it plays the whole shoot, not a cut.

To carry manual edits back from Final Cut Pro, choose **File > Export XML**, then run `cutroom import talk.mp4 edited.fcpxml`. Import supports plain clips in source order. Compound, multicam and retimed clips are refused.

**On a phone:** `cutroom review <source> --serve` also serves the page and the project's media on your local network, and prints a URL and a QR code to scan (same Wi-Fi). On a phone the player stays on top while you scroll, a tap plays or pauses, a double tap on the left or right skips 10 s, and **Send to agent** writes the feedback to `cutroom/feedback.md` (or `<name>.feedback.md`) for the agent to read. Reload the page after the agent edits the project: it re-plans when the project file or the story changes. The URL carries a random token and only the project's own media files are served; stop the server with ctrl-c. macOS may ask once to allow incoming connections. 4K footage plays over Wi-Fi, but a weak connection can stutter.

## Shorts

A short is a moment that stands on its own: no word in it points at something outside it. You or your agent choose candidate ranges. CutRoom checks the candidates, plays them on the Shorts tab, and exports the ones you pick. The rules for a good short are in [`core.md`](skills/cutroom/references/core.md#shorts).

- **From a finished cut** (a talking head, an explainer, a vlog): the agent reads the transcript, writes candidates under `shorts` with a title, a reason, a theme, scores and a rank, and checks every edge by ear.
- **From hours of recording that will never be one edit** (a life story in 14 files): link the files into one folder, set `"style": "talking-head"`, and follow [`shorts.md`](skills/cutroom/references/shorts.md): chapter agents with a checker, one judge across all of them, an edge check by ear. The first run turned 4 hours into 83 ranked candidates.
- **From an explainer**: the words are not enough. `cutroom frames <source> S1 S2` shows a grid of frames over each short, the edge checks flag words that need the screen ("right here") or earlier context ("as I mentioned"), and each short is tagged `camera`, `screen` or `mixed` for its vertical version. See [`explainer.md`](skills/cutroom/references/explainer.md).
- **Checks**: each short shows what to check before you pick it: an opening that leans on what came before, an ending cut off mid-sentence, words that need the screen or point to earlier, and a phrase said twice close together. `cutroom review` prints them too.
- **Text**: a short to post gets a headline and calls to action in its `copy`. The Shorts tab shows each text with the words it starts on. Edit it there, approve it (A), and apply the review feedback to the project file before exporting. `cutroom export <source> S6 --text <export.mp4>` then writes the job for the shorts-text skill (OpenMontage, `.agents/skills/shorts-text`), which renders the 9:16 master with the text on it.
- **Out**: `cutroom export <source> S1 S4` writes FCPXML (or `--format mp4`). When the video was made in Screen Studio, `--screenstudio <project>` also writes `<project>-S1.screenstudio`: the project cut down to that short, found by its words, so the time codes of the finished video do not matter (an intro added later, a Final Cut trim, retakes still in the recording). Give `--screenstudio` once per project for a video made from several. The words are matched against what the project's slices play, transcribed as one piece of audio (cached as `<project>.shown.transcript.json`), because Whisper on the whole recording often starts a sentence seconds early, inside the pause before it.

## A vlog from a folder of clips

Clips sit on one timeline in capture order (iPhone creation date, then the file's `creation_time`, then its modified time). The full procedure, with the agent prompts that worked, is in [`skills/cutroom/references/vlog.md`](skills/cutroom/references/vlog.md). In short:

1. brief, 2. `cutroom digest`, 3. a clip log from vision sub-agents reading every contact sheet, 4. the story outline and your approval, 5. sub-agents fill the story's scenes in parallel and judge every moment of their clips "in" or "out" with a reason (the inclusion list), 6. `cutroom candidates --write-selects --story-order`, 7. lead edit and read-through, 8. your review, 9. `cutroom export <folder> vlog S1 ...`.

On the first run (Hack the North, 101 clips, 3.9 h of 4K HEVC): transcription 20 minutes once, contact sheets 5.5 minutes once, every later re-plan seconds; the result was a 12-minute vlog in 8 chapters with 5 short candidates, all CutRoom state in 3.6 MB.

## Steps that need computer use

CutRoom stops at files. These happen in GUI apps, done by a person or a computer-use agent:

| Step | How | What to check |
|---|---|---|
| Review the cut | `open <path>/review.html`, or on a phone `cutroom review <source> --serve` | cuts land between sentences; each retake keeps the full final take; the story flows; shorts stand on their own |
| See a cut Screen Studio project | `open -a "Screen Studio" demo-clean.screenstudio` | protected pauses show the click or typing |
| Check a short's Screen Studio project | `open -a "Screen Studio" e2e-1-S2.screenstudio` | it opens and closes on the short's first and last sentence; zooms and layout came along |
| Export from Screen Studio | Screen Studio's Export button | Screen Studio has no command-line export |
| Import into Final Cut Pro, once | File > Import > XML | media links in place (set Final Cut to leave files in place); mute the clips the agent flagged for room music |
| Import into DaVinci Resolve | File > Import > Timeline | Resolve reads the same FCPXML |

## Limits

- Retakes are matched on their opening words only; a redo that starts differently needs an `edits.cuts` entry.
- Automatic pause removal barely shortens event footage (a crowd is never silent): a vlog's length comes from the story's selects.
- Filler words ("um", "uh") are not removed, and a stumble inside a sentence with no pause is not detected.
- Music playing in the room stays in the audio; mute it in your editor.
- A folder exports FCPXML only (no mp4 render). A Screen Studio project keeps recorded order.
- A short becomes a Screen Studio project only when 90% of its words are in one recording, in recorded order. A short that joins two recordings (an opening from one, an ending from another) stays an FCPXML.
- `cutroom frames` reads video files; a Screen Studio project's picture is only visible in Screen Studio.
- The edge checks read Whisper's words: they are hints. Only listening settles an edge (see `shorts.md`, step 6).
- The review page plays what the browser decodes: on a Mac, Safari and Chromium play H.264 and HEVC; ProRes plays in Safari.
- Protected screen actions keep their pauses, so a click-heavy demo is longer than with `--no-protect-actions`. Mouse movement alone does not protect a pause.
- Silence detection is energy based (`--noise`, default -35 dB). A noisy room may need `--noise -30`.

## Development

To install the CLI from your checkout, run `uv tool install --python 3.11 --editable .`.

```bash
uv sync --python 3.11
uv run pytest
```

The tests generate their own audio and video with ffmpeg and pre-write transcripts, so they need no model download and run in seconds. On a Mac with Final Cut Pro installed, FCPXML output is validated against Final Cut's own DTD. CI runs the suite on Linux, Windows and macOS (ffmpeg 6 and 7+ both covered).
