from types import SimpleNamespace

from cutroom.core import (
    action_windows,
    cleanup_cuts,
    drop_hallucinated_words,
    find_retake_cuts,
    invert_cuts,
    merge_ranges,
    resolve_pacing,
    silence_cuts,
    subtract_cuts,
    subtract_ranges,
    words_to_sentences,
)


def w(start, end, text):
    return {"startMs": start, "endMs": end, "word": text}


def test_silence_cuts_keep_trail_after_speech_and_lead_before_it():
    assert silence_cuts([(5000, 7000)], trail_ms=200, lead_ms=80) == [(5200, 6920)]


def test_silence_cuts_trim_flush_at_recording_edges():
    cuts = silence_cuts([(0, 2000), (8000, 10000)], trail_ms=200, lead_ms=80, total_ms=10000)
    assert cuts == [(0, 1920), (8200, 10000)]


def test_silence_cuts_drop_cuts_shorter_than_200ms():
    assert silence_cuts([(1000, 1400)], trail_ms=200, lead_ms=80) == []


def test_merge_and_invert_ranges():
    assert merge_ranges([(5, 8), (0, 2), (1, 3)]) == [(0, 3), (5, 8)]
    assert invert_cuts([(1000, 2000), (5000, 6000)], 8000) == [(0, 1000), (2000, 5000), (6000, 8000)]


def test_invert_cuts_drops_slivers_shorter_than_min_slice():
    assert invert_cuts([(0, 1000), (1050, 3000)], 3000) == []


def test_subtract_ranges_splits_around_holes_and_drops_short_pieces():
    assert subtract_ranges([(0, 10000)], [(2000, 3000), (9900, 12000)], min_len_ms=200) == [
        (0, 2000), (3000, 9900)]
    assert subtract_ranges([(0, 1000)], [(100, 950)], min_len_ms=200) == []


def test_action_windows_merge_and_clamp():
    assert action_windows([100, 600, 9000], before_ms=500, after_ms=1000, total_ms=9500) == [
        (0.0, 1600), (8500, 9500)]


# speech before and after the cuts, so only the fragment between them is in question
SPEECH = [w(100, 900, "before"), w(5000, 9000, "after")]


def test_cleanup_absorbs_short_wordless_keep():
    cuts, absorbed = cleanup_cuts([(1000, 2000), (2500, 4000)], 10000, words=SPEECH, min_keep_ms=1500)
    assert absorbed == [(2000, 2500)]
    assert cuts == [(1000, 4000)]


def test_cleanup_keeps_fragments_with_words():
    cuts, absorbed = cleanup_cuts([(1000, 2000), (2500, 4000)], 10000,
                                  words=SPEECH + [w(2100, 2400, "hi")], min_keep_ms=1500)
    assert absorbed == []


def test_cleanup_never_absorbs_a_protected_fragment():
    cuts, absorbed = cleanup_cuts([(1000, 2000), (2500, 4000)], 10000, words=SPEECH,
                                  min_keep_ms=1500, protected=[(2200, 2300)])
    assert absorbed == []
    assert cuts == [(1000, 2000), (2500, 4000)]


def test_cleanup_without_transcript_only_absorbs_tiny_fragments():
    cuts, absorbed = cleanup_cuts([(1000, 2000), (2300, 4000), (5000, 6000)], 10000, words=None)
    assert absorbed == [(2000, 2300)]


def test_drop_hallucinated_words_inside_silence():
    kept, dropped = drop_hallucinated_words(
        [w(0, 500, "real"), w(3000, 3400, "LA"), w(4000, 4000, "zero")], [(2000, 5000)])
    assert [x["word"] for x in kept] == ["real"]
    assert [x["word"] for x in dropped] == ["LA", "zero"]


def test_words_to_sentences_split_on_punctuation_and_pauses():
    words = [w(0, 300, "Hello"), w(300, 600, "there."), w(700, 900, "And"),
             w(900, 1100, "then"), w(2500, 2800, "again")]
    assert [s["text"] for s in words_to_sentences(words)] == ["Hello there.", "And then", "again"]


def sentence(start_s, text):
    return {"startMs": start_s * 1000, "endMs": start_s * 1000 + 2000, "text": text}


def test_retake_keeps_the_last_take_of_a_repeated_opening():
    cuts = find_retake_cuts([
        sentence(0, "Today we are going to build an app."),
        sentence(5, "Today we are going to build an app with expo."),
        sentence(10, "Today we are going to build an app with expo router."),
        sentence(20, "First open the terminal."),
    ], pre_roll_ms=100)
    assert len(cuts) == 1
    assert (cuts[0]["startMs"], cuts[0]["endMs"]) == (0, 9900)
    assert cuts[0]["kept"].endswith("expo router.")
    assert len(cuts[0]["removed"]) == 2


def test_retake_ignores_different_openings_and_the_window():
    assert find_retake_cuts([
        sentence(0, "Today we are going to build an app."),
        sentence(5, "First open the terminal and run it."),
    ]) == []
    assert find_retake_cuts([
        sentence(0, "Today we are going to build an app."),
        sentence(90, "Today we are going to build an app."),
    ], window_s=60) == []


def test_restart_phrase_cuts_that_sentence():
    cuts = find_retake_cuts([
        sentence(0, "So the config goes here, scratch that."),
        sentence(5, "The config lives in app json."),
    ])
    assert len(cuts) == 1 and cuts[0]["reason"] == "restart phrase"
    assert (cuts[0]["startMs"], cuts[0]["endMs"]) == (0, 2000)


def test_subtract_cuts_preserves_fields_and_gives_split_pieces_new_ids():
    out = subtract_cuts([{"id": "a", "sourceStartMs": 0, "sourceEndMs": 10000, "speed": 1.5}],
                        [(2000, 3000), (9950, 10000)])
    assert [(s["sourceStartMs"], s["sourceEndMs"]) for s in out] == [(0, 2000), (3000, 9950)]
    assert out[0]["id"] == "a" and out[1]["id"] != "a"
    assert all(s["speed"] == 1.5 for s in out)


def test_explicit_flags_win_over_the_pacing_preset():
    args = SimpleNamespace(pacing="tight", min_silence=None, trail=0.5, lead=None, min_keep=None)
    resolve_pacing(args)
    assert (args.min_silence, args.trail, args.lead, args.min_keep) == (0.35, 0.5, 0.05, 2.0)
