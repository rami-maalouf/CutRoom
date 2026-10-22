# reactions: someone watching a video and commenting on it. the video's sound
# (screen studio's system audio) is content too: a pause is only where both
# voices are quiet, a retake never cuts the video, and clicks protect nothing

import json

from cutroom import project
from cutroom.cli import main
from conftest import make_screenstudio, needs_ffmpeg, write_transcript

pytestmark = needs_ffmpeg

# me: talk 0-2, quiet while the video plays 2-5, talk 5-7, both quiet 7-9, talk 9-10
MIC = [("tone", 2), ("silence", 3), ("tone", 2), ("silence", 2), ("tone", 1)]
VIDEO = [("silence", 2), ("tone", 3), ("silence", 5)]
MIC_WORDS = [(0.1, 1.9, "first."), (5.1, 6.9, "second."), (9.1, 9.9, "third.")]
VIDEO_WORDS = [(2.1, 3.0, "the"), (3.0, 4.0, "video"), (4.0, 4.9, "talks.")]


def reaction(tmp_path, mic=MIC, video=VIDEO, mic_words=MIC_WORDS, video_words=VIDEO_WORDS,
             style="reaction", clicks=()):
    pkg = make_screenstudio(tmp_path, [mic], clicks=clicks, system=[video])
    write_transcript(pkg.with_suffix(".transcript.json"), mic_words)
    write_transcript(pkg.with_suffix(".system.transcript.json"), video_words)
    project.save(pkg, {"v": 2, "style": style, "edits": {"cuts": [], "keeps": []}})
    return pkg


def cuts(tmp_path, pkg):
    report = tmp_path / "r.json"
    main(["project", str(pkg), "--yes", "--dry-run", "--report", str(report)])
    data = json.loads(report.read_text(encoding="utf-8"))
    return [(round(s, 1), round(e, 1)) for s, e in data["finalCuts"]], data


def test_a_pause_while_the_video_plays_is_kept(tmp_path):
    found, data = cuts(tmp_path, reaction(tmp_path))
    assert len(found) == 1 and 7.0 <= found[0][0] < found[0][1] <= 9.0
    assert [s["text"] for s in data["heardSentences"]] == ["the video talks."]


def test_a_talking_head_cuts_the_same_pause(tmp_path):
    found, _ = cuts(tmp_path, reaction(tmp_path, style="talking-head"))
    assert len(found) == 2 and 2.0 <= found[0][0] < found[0][1] <= 5.0


def test_a_retake_cut_keeps_the_video_that_plays_inside_it(tmp_path):
    # a bad take, the video plays on, then the redo: the bad take goes, the video stays
    mic = [("tone", 2), ("silence", 3), ("tone", 2)]
    video = [("silence", 2), ("tone", 2), ("silence", 3)]
    said = "the point I want to make is this".split()
    take = [(0.1 + i * 0.2, 0.3 + i * 0.2, w) for i, w in enumerate(said)]
    redo = [(5.1 + i * 0.2, 5.3 + i * 0.2, w) for i, w in enumerate(said + ["one."])]
    found, data = cuts(tmp_path, reaction(tmp_path, mic, video, take + redo,
                                          [(2.1, 3.9, "meanwhile.")]))
    assert [d["status"] for d in data["decisions"]] == ["cut"]
    kept = data["keeps"]
    assert any(s <= 2.2 and e >= 3.8 for s, e in kept)       # the video plays
    assert not any(s < 1.5 and e > 0.5 for s, e in kept)     # the bad take does not


def test_clicks_do_not_protect_a_reaction_pause(tmp_path):
    # a click in a pause pauses or seeks the video: dead time, not on-screen action
    found, _ = cuts(tmp_path, reaction(tmp_path, clicks=[8.0]))
    assert len(found) == 1 and found[0][0] < 8.0 < found[0][1]


def test_a_short_video_line_between_cuts_is_not_absorbed(tmp_path):
    # the video says one word between two pauses: it has no mic words, but it is speech
    mic = [("tone", 2), ("silence", 4), ("tone", 2)]
    video = [("silence", 2.6), ("tone", 0.6), ("silence", 4.8)]
    found, data = cuts(tmp_path, reaction(tmp_path, mic, video, [(0.1, 1.9, "first."), (6.1, 7.9, "second.")],
                                          [(2.65, 3.15, "bad.")]))
    assert any(s <= 2.7 and e >= 3.1 for s, e in data["keeps"])


def test_read_through_marks_the_video_lines(tmp_path):
    pkg = reaction(tmp_path)
    main(["script", str(pkg)])
    text = pkg.with_suffix(".script.md").read_text(encoding="utf-8")
    assert "] video: the video talks." in text
    assert "] first." in text


def test_join_window_takes_the_audio_on_both_sides_of_a_cut():
    from cutroom.core import join_window
    keeps = [(0, 2000), (3000, 4000), (7000, 9000)]
    pieces, join = join_window(keeps, 4000, 7000, 2500)
    assert pieces == [(500, 2000), (3000, 4000), (7000, 9000)] and join == 2500
    pieces, join = join_window(keeps, 0, 0, 1000)            # a cut at the very start
    assert pieces[0] == (0, 1000) and join == 0


def test_check_plays_each_cut_with_both_voices(tmp_path, capsys, monkeypatch):
    # the clip around the join mixes the video in: where only the video sounds, the clip is not silent
    import numpy as np
    from cutroom import cli
    pkg = reaction(tmp_path)
    data = json.loads(project.project_path(pkg).read_text(encoding="utf-8"))
    data["edits"]["cuts"] = [[5.0, 7.0, "my second line"]]
    project.save(pkg, data)
    heard = []

    def fake(samples, backend):
        heard.append(samples)
        return [(0.1, 0.5, "before"), (len(samples) / 16000 - 0.5, len(samples) / 16000 - 0.1, "after")]

    monkeypatch.setattr(cli, "transcribe_samples", fake)
    monkeypatch.setattr(cli, "pick_backend", lambda requested=None: "mlx")
    main(["check", str(pkg), "--seconds", "2"])
    out = capsys.readouterr().out
    assert "M1 5.0-7.0s  my second line" in out and "...before || after..." in out
    clip = heard[0]
    assert len(clip) <= 4 * 16000 + 10
    # the first second of the clip is 3.0-4.0 s on the timeline: only the video talks there
    assert np.sqrt((clip[:16000] ** 2).mean()) > 0.01
