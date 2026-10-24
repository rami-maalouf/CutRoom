# Reaction

One person watching a video (a YouTube video, a talk, a clip) and commenting on it, usually recorded in Screen Studio: the video plays on screen, the camera shows the reactor, and the reactor pauses the video to comment. There are two voices: the reactor's mic and the video's sound (Screen Studio's system audio, recorded on its own channel).

cutroom defaults for this style: `pacing balanced`, retake detection **on** (on the mic only), and:

- **A pause is only where both voices are quiet.** A mic pause while the video plays is content. Without the style, cutroom cuts the whole video away as silence.
- **A retake cut never removes the video's sound.** A bad take, the video playing on, then the redo: the bad take goes, the video stays.
- **Clicks protect nothing.** In a reaction a click pauses, plays or seeks the video: dead time, not on-screen action.
- The video's words count as speech wherever the cut asks whether a moment has words (cleanup of short fragments, snapping selects), are shown with `video:` in the read-through (`cutroom script`), and are listed as `heardSentences` in the report. The system audio transcript is cached as `<name>.system.transcript.json`.

Set it in the project file: `"style": "reaction"`. A plain video file has one audio track, so its silences already include the video; the style still turns off click protection.

## Several recordings: join them first

A reaction is often recorded in parts. `cutroom join a.screenstudio b.screenstudio --output both.screenstudio` makes one project that plays them in order, as if the recording had been paused and resumed: the later recordings become the next sessions (renamed APFS clones, nothing re-encoded, no extra disk), their slices and zooms move to where their sessions start, and the first project's look and layout are kept. It refuses recordings from another setup (other channels, display or camera size). Then edit the joined project like any other.

Open the joined project with the app's full path, with the shell's sandbox off: `open -a "/Applications/Screen Studio (latest).app" both.screenstudio` (the app's name alone returns 0 and launches nothing). Check that a `Project - <name>` window appears; if it does not, ask the user to open it. Offer per-part projects with the same slices as a fallback.

## Clean-up

As in talking-head.md (read every sentence, add missed retakes to `edits.cuts`, check every decision), with the video's lines read too (the report's `heardSentences`, the read-through). The reactor's retakes are found like a talking head's. What is new is the video being replayed:

- **Rewinds.** The reactor plays a line, rewinds and plays it again (to re-hear it, or to pause at the right word). Keep each line once, in the play that leads into the comment; cut the other plays and the scrubbing.
- **A replay the reactor points at stays.** "This right here." followed by a replay of the line is emphasis, not a retake.
- **Resume with a rewind.** The video stops mid-sentence for a comment; on resume the reactor rewinds a few seconds. Cut from the resume to the point where the first play stopped, so the sentence goes on from there.
- **Scrubs and strays.** The end of an ad before the video starts, a second of the video played by accident in the middle of a comment, the next video starting by itself: cut them.
- **Lines cut off by the pause.** "But back" just before a pause, which then plays again with the rest of the sentence after the comment: cut the first one.

**Do not trust the long transcript at the video's edges.** Whisper drops speech that repeats (a replay can be missing from the transcript altogether), and after a pause its word times can be early by a second or more. On the Hank Green reaction this hid a whole resumed passage, and five edges first landed inside words. So:

- Find hidden audio: stretches where the system audio is loud but the transcript has no words. Transcribe each as a short clip.
- Place edges on the sound, not on word times: a cut edge goes where both voices are quiet, or at the deepest dip between two of the video's words (its speech has almost no silent gaps).
- A replay is the same audio twice, but not sample for sample: align the two plays by their loudness envelopes (5 ms steps) and cut exactly one offset long, from a quiet seam in the first play. The join is then seamless.
- `cutroom check <source>` hears every retake and manual cut: the kept audio on both sides of each join (both voices mixed), transcribed as a short clip of its own. Fix every join that reads wrong. The review page plays the mic alone, so it cannot check a reaction.

## Two versions: the whole video, and the replies

A user often wants both: one that keeps everything the video says (cleaned, each line once), and a tighter one that keeps only what the reactor replies to.

1. Write the whole version: `cutroom project both.screenstudio --yes --output <name>-full.screenstudio`.
2. Make the replies version from it: `<name>-full.cutroom.json` (style `reaction`) holds only the video passages to remove, with the reason as the note; `cutroom project <name>-full.screenstudio --yes --output <name>-replies.screenstudio`. Screen Studio's own edit is respected, so it starts from the whole version.
3. For every comment, keep the video's line it answers, and enough before it to make sense. Remove the video's asides, examples and ads with no reply. Keep the structure the video gives itself ("Number five.") and the end. Cut at sentence gaps, never inside a sentence, and remove a sentence the pause cut off when its end is removed too.
4. `cutroom check` the replies version too, then read it with `cutroom script`: every comment should still have its setup.

Report both lengths, every removal with its reason, and the judgment calls the user may want back (a comment cut as a retake, an unfinished sentence removed).

## The look

Rami's look for a reaction is in taste.md: landscape, no zooms, the face fullscreen on tangents and on most of the reactor's own comments, the camera overlay at 0.5 (top-right over the comment section). Set it in the project's `project.json` (`config.output.aspectRatio`, `config.defaultLayout`, `scenes[].zooms`, `scenes[].layouts`), on the joined source as well, so every version cut from it inherits it.

- A face span is a layout `{"type": "fullscreen-camera", "sourceStartMs", "sourceEndMs", ...}` (copy the fields from a layout Screen Studio wrote). Find each tangent's first and last words in the transcript, and put the switch on the nearest cut when one is within 1.5 s, so the layout changes on a cut. Check that no screen stretch between two face spans is shorter than about 4 s in any version: it flickers.
- A comment zoom is `{"type": "manual", "zoom": 1.2-1.4, "manualTargetPoint": {"x", "y"}}`. Look at the frames first: the page scrolls, so start the zoom after it settles. Keep the target within `0.5 / zoom` of every edge, or the zoom shows empty space.
- The cursor and the video's volume are per slice: `hideCursor` (true on every slice except where the reactor points at something) and `systemAudioVolume` (the video's level against the mic; measure both over the kept cut, with the mic as Screen Studio renders it under its preset, the newest `cache/audio-render/channel-3-microphone-*.m4a`).
- Screen Studio saves its own state over `project.json` when the project is open: write only while it is closed, and back the file up first. An open project has a `Project - <name>` window and holds its video segments open; after it closes, `screen-studio-native` can keep a few `.m4a` handles, so do not wait for zero open files.
- **A `cutout-camera` layout anywhere makes the export depend on a camera matte** (Screen Studio 4.1: `cache/camera-matte/matte-*/`, chunks of 30 frames, `manifest.json` has the frame count). Screen Studio builds it in the background only while the project is open, and only for the frames the cut uses. Export before it is built and the render can stall: "trusted render at ... ms waited 60 s on: stand-in-content(project-camera(channel-4-webcam-1.m3u8, pp-mattingv2-ss9-refined)...)". The reports are in `~/Library/Application Support/Screen Studio/sentry/queue/` (one JSON event per line, with breadcrumbs). Fix: keep the project open until every chunk the cut's slices need exists, then export; or use another layout for the cutout span. On the Hank Green reaction (2026-10-23) the first export failed at 17:59 of 28:05 with part 2's matte 37% built; with the matte built, the export finished (stalls of 10-30 s recovered).

## When the user edits it further in Screen Studio

The user's own pass is the best taste signal there is: review it, then add what it teaches to taste.md.

1. Diff the slices Screen Studio saved against the ones cutroom wrote (keep the written `project.json` as a backup): every removed block with its words, every range brought back, every speed (`timeScale` below 1 is faster) or volume change.
2. Hear every new join as a short clip (both voices, 5 s each side), exactly as `cutroom check` does. Hand-made cuts in the app look broken in the long transcript far more often than they are: on the Hank Green pass, many joins read wrong there ("So do not" gone, "Not speaking from experience" turned into "speaking from experience"), and heard as short clips almost all were fine.
3. Measure each new edge: louder than -40 dB, it may sit inside a word; louder than about -20 dB, give it to the user to listen to.
4. Read the cut as a viewer (core.md checklist): a "this" whose line went, a half-sentence from the video that now runs into the reactor's line, a numbered list with numbers missing, a plug whose setup was cut.
5. Map the layouts to play time (speed counts): switches inside a sentence, screen stretches under 4 s between face spans, the camera jumping corners.
6. Report in play time (what the user sees in the app), most serious first. Do not edit the project unless asked: the app may still have it open.

## Shorts

Mine them from the finished export, not from the Screen Studio project: the export is one file with both voices mixed, so the review page plays what the viewer hears (on a project it plays the mic alone).

1. Export from Screen Studio. For the review page, make an H.264 copy at 720p (`ffmpeg -hwaccel videotoolbox -i export.mp4 -vf scale=-2:720 -c:v h264_videotoolbox -b:v 3500k -c:a copy -movflags +faststart copy.mp4`): the export is 4K HEVC, which not every browser plays. Same times, same audio.
2. In `<copy>.cutroom.json`: `"style": "reaction"`, every short `"raw": true`, and `edits.keeps` over the whole video, so the page does not propose a second clean-up of a finished cut.
3. Pick candidates verbatim from the read-through. A reaction short is usually the video's line, then the reply; the reactor's tangents (face fullscreen) work like talking-head shorts. "He" is fine while the video's speaker is on screen.
4. Check every edge on the export's audio, transcribed as a short clip: the first and last seconds, and both sides of each join between segments. Long-transcript word times run late or early at the edges: on the Hank Green shorts, 2 of 17 started on a stray word ("to", "to me."), 1 started inside its first word ("Make") and 1 ended before its last word ("fact"). Where the reactor comments inside the video's sentence, measure which voice is speaking (mic or system level at that time) and skip the comment with a second segment.
5. `cutroom review <copy> --serve` and look at the Shorts tab before you hand it over (a short must jump to its start and play).
6. A picked short as its own project: `cutroom export <copy> S2 --screenstudio <project>`. Where both voices talk at once, the word search can fall under 90% and stop (the Hank Green S18, 326 of 461 words). The export plays the project's slices end to end, so map the short's export times through the slices (`timeScale` counts) to recording ranges and cut the package with those keeps (`write_cut_package`); on S7 this gave the same 10 ranges as the word search, within 0.25 s.
7. The vertical look (taste.md, Shorts): in a 3:4 canvas a 16:9 screen fills the frame only at 2.37x or more; below that, the wallpaper shows above and below it.

## Proven on

The Hank Green reaction (2026-10-22): two Screen Studio recordings, 34:12 and 43:13, joined into one project. The whole version is 49:19 (49 manual cuts and 11 detected retakes); the replies version is 37:19 (34 more removals).
