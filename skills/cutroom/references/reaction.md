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

Screen Studio cannot be opened from an agent's shell, so say so and ask the user to open the joined project (`open -a "Screen Studio (latest)" both.screenstudio`). Offer per-part projects with the same slices as a fallback.

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

Rami's look for a reaction is in taste.md: landscape, no zooms except gentle ones on the comments, the face fullscreen on tangents. Set it in the project's `project.json` (`config.output.aspectRatio`, `config.defaultLayout`, `scenes[].zooms`, `scenes[].layouts`), on the joined source as well, so every version cut from it inherits it.

- A face span is a layout `{"type": "fullscreen-camera", "sourceStartMs", "sourceEndMs", ...}` (copy the fields from a layout Screen Studio wrote). Find each tangent's first and last words in the transcript, and put the switch on the nearest cut when one is within 1.5 s, so the layout changes on a cut. Check that no screen stretch between two face spans is shorter than about 4 s in any version: it flickers.
- A comment zoom is `{"type": "manual", "zoom": 1.2-1.4, "manualTargetPoint": {"x", "y"}}`. Look at the frames first: the page scrolls, so start the zoom after it settles. Keep the target within `0.5 / zoom` of every edge, or the zoom shows empty space.
- Screen Studio saves its own state over `project.json` when the project is open: write only while it is closed, and back the file up first.

## Proven on

The Hank Green reaction (2026-10-22): two Screen Studio recordings, 34:12 and 43:13, joined into one project. The whole version is 49:19 (49 manual cuts and 11 detected retakes); the replies version is 37:19 (34 more removals).
