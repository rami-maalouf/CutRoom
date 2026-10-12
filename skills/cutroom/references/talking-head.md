# Talking head

One person, one recording (a talk to camera, a tutorial, a Screen Studio project, a podcast-style video). The words carry the video, so the work is **audio only**: no contact sheets, no frame grabs, no visual log. The picture is the same person throughout; reading it costs tokens and adds nothing. (Screen Studio recordings are the exception for one thing: cutroom protects clicks and keystrokes from silence cuts automatically.)

cutroom defaults for this style: `pacing balanced`, retake detection **on**. A repeated opening here is a mistake, not a story.

## Understand the material

1. `cutroom review <source> --report /tmp/report.json` (transcribes once, then plans in seconds).
2. Read every sentence in `sentences`. Mark: the main claim, each supporting point, examples, stories, tangents, retakes the detector missed (a redo that starts with different words), and the strongest single line.

## The story

A talking head's story is an argument or a journey. Usually:

- **Hook:** the strongest claim, surprising fact, or question, even if it was said in minute 6. Moving it to the front is fine when it stands alone.
- **Promise:** what the viewer will get by the end.
- **Points:** each one claim + example or story. Cut the point that repeats another.
- **Payoff:** the answer, the result, the lesson.
- **Close:** one line that answers the hook. Cut the "so yeah, that's it" after it.

Tangents go unless they are the most human moment of the video.

## Cutting

- Retakes: keep the last complete take; add misses to `edits.cuts`. Check every `decisions` entry: `kept` must be the full final take.
- Silences: `balanced` for most, `tight` for short social cuts, `relaxed` for a calm explainer.
- Keep emphasis pauses before a key line; use `edits.keeps` to protect one.
- Reordering a single file: express the new order as `selects` (V1, V2, ... with `start`/`end`, no `clip`); without selects the clean cut plays in recorded order.

## Output

- Screen Studio: `cutroom project <pkg> --yes` writes `<name>-clean.screenstudio` (no re-encode; Screen Studio renders it).
- Video: `cutroom video <file> --yes --export fcpxml` (Final Cut, Resolve) or `--export mp4`.
