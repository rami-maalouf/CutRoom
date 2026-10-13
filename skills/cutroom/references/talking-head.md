# Talking head

One person, one recording (a talk to camera, a tutorial, a Screen Studio project, a podcast-style video). The words carry the video, so the work is **audio only**: no contact sheets, no frame grabs, no visual log. The picture is the same person throughout; reading it costs tokens and adds nothing. (Screen Studio recordings are the exception for one thing: cutroom protects clicks and keystrokes from silence cuts automatically.)

cutroom defaults for this style: `pacing balanced`, retake detection **on**. A repeated opening here is a mistake, not a story.

## Clean-up ("process my latest video", "remove the silences and repeats")

No story, no gate. Minutes, not hours.

1. **Find the input.** "My latest video" with no path: the newest `.screenstudio` (or video) in the folder the user records to that has no `-clean` sibling. Ask when the folder is unknown.
2. **Plan:** `cutroom review <source> --report /tmp/report.json` (transcribes once, then plans in seconds).
3. **Check the judgment calls.**
   - Read every sentence in the report's `sentences`. The detector only catches a redo that opens with the same words as the bad take: find the others by reading, and add each to `edits.cuts` in the project file (`[start, end, "missed retake"]`, from the start of the bad take to 0.1 s before the kept take).
   - Check every entry in `decisions`: `kept` must be the complete final take. A wrong one goes into `edits.keeps` (`[start, end, "reject R3"]`).
4. **Read-through:** `cutroom script <source>`, then the read-through checklist in core.md (stray first words, anything said twice).
5. **Write it:**
   - Screen Studio: `cutroom project <pkg> --yes` writes `<name>-clean.screenstudio` (no re-encode; open it with `open -a "Screen Studio" <path>`).
   - Video: `cutroom video <file> --yes --export fcpxml` (Final Cut, Resolve) or `--export mp4`.
6. **Report** the before and after duration and every retake decision, including the ones you added. Offer the review page for a check by eye.

## Edit ("make it better", restructure, a talk that should open on its best line)

Story-first, following core.md's order of work. For a talking head:

1. **Brief** (`<name>.brief.md`): who it is for, the point of the video, the target length.
2. **Understand:** `cutroom review <source> --report /tmp/report.json` and read every sentence. Mark the main claim, each supporting point, examples, stories, tangents, missed retakes, and the strongest single line.
3. **Story** (`<name>.story.md`), usually an argument or a journey:
   - **Hook:** the strongest claim, surprising fact, or question, even if it was said in minute 6. Moving it to the front is fine when it stands alone.
   - **Promise:** what the viewer gets by the end.
   - **Points:** each one claim + example or story. Cut the point that repeats another.
   - **Payoff:** the answer, the result, the lesson.
   - **Close:** one line that answers the hook. Cut the "so yeah, that's it" after it.
   - Tangents go unless they are the most human moment of the video.
   - **Talking heads to record** (core.md): a missing transition, a fact said wrong, a promise the recording never made. Store them as `pickups`; once recorded, the new file is edited the same way and joined in the editor.
   Then `cutroom review <source> --open`, point the user to the Story tab, and **stop for approval**.
4. **Selects:** write the approved story as `selects` in play order (`{"id": "V1", "start", "end", "beat", "role", "intent"}`, no `clip`). Times come from the report's sentences; cutroom snaps them to whole words. Without selects, the clean cut plays in recorded order.
5. **Read-through:** `cutroom script <source>`, fix every checklist problem, then hand over the review page.
6. **Write it:** `cutroom video <file> --yes --export fcpxml` follows the selects' order. A Screen Studio project cannot be reordered from outside: `cutroom project` keeps the selects' content in recorded order. For a reordered Screen Studio cut, export the project from Screen Studio first, then edit that video file.

## Shorts from a long recording

Hours of talking head that will never be one edit (a life story, a long podcast): mine the shorts directly, following [shorts.md](shorts.md): parallel agents by chapter with a checker, one judge for the ranking, an edge check by ear.

## Cutting rules

- Retakes: keep the last complete take. Check every decision.
- Silences: `balanced` for most, `tight` for short social cuts, `relaxed` for a calm explainer.
- Keep emphasis pauses before a key line; protect one with `edits.keeps`.
- A select with `"raw": true` plays exactly as recorded (a story told with feeling, a laugh).
