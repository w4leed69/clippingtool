from app import captions, tts
from app.pipelines import clipper, story
from app.transcribe import Segment
from app.tts import Word


def W(text, s, e):
    return Word(text, s, e)


def test_estimate_timings_are_monotonic_and_cover_text():
    words = tts.estimate_timings("Hello there, this is a test. Another sentence!")
    assert [w.text for w in words][0] == "Hello"
    assert len(words) == 8
    assert all(a.end <= b.start + 1e-6 for a, b in zip(words, words[1:]))
    scaled = tts.estimate_timings("one two three", total=3.0)
    assert scaled[-1].end <= 3.0


def test_silent_synthesis_produces_audio_and_words(tmp_path):
    sp = tts.synthesize("A quick little sentence.", "silent", tmp_path, "x")
    assert sp.audio.exists() and sp.duration > 0.5
    assert len(sp.words) == 4 and sp.words[-1].end <= sp.duration


def test_unknown_voice_is_rejected(tmp_path):
    import pytest
    with pytest.raises(tts.TTSError):
        tts.synthesize("hi", "nope:voice", tmp_path, "x")


def test_group_words_breaks_on_punctuation_and_size():
    words = [W("I", 0, .1), W("saw", .1, .3), W("it.", .3, .5), W("Then", .6, .8), W("we", .8, .9),
             W("ran", .9, 1.0), W("really", 1.0, 1.2), W("far", 1.2, 1.4)]
    groups = captions.group_words(words, max_words=3)
    assert [[w.text for w in g] for g in groups] == [["I", "saw", "it."], ["Then", "we", "ran"], ["really", "far"]]


def test_build_ass_highlights_each_word(tmp_path):
    words = [W("hello", 0, .4), W("big", .4, .7), W("world", .7, 1.2)]
    out = captions.build_ass(words, tmp_path / "s.ass", "bold", y=0.5)
    text = out.read_text()
    dialogues = [l for l in text.splitlines() if l.startswith("Dialogue:")]
    assert len(dialogues) == 3  # one slice per word
    assert "HELLO" in dialogues[0] and "\\pos(540,960)" in dialogues[0]
    assert "&H001FE8FF" in text  # yellow highlight in BGR
    clean = captions.build_ass(words, tmp_path / "c.ass", "clean").read_text()
    assert len([l for l in clean.splitlines() if l.startswith("Dialogue:")]) == 1


def test_ass_escapes_override_braces(tmp_path):
    out = captions.build_ass([W("{\\evil}", 0, 1)], tmp_path / "s.ass", "clean").read_text()
    assert "{\\evil}" not in out


def test_split_parts():
    body = " ".join(f"Sentence number {i} has some words in it." for i in range(60))
    parts = story.split_parts(body, 60)
    assert len(parts) > 1
    assert " ".join(parts) == body
    assert story.split_parts(body, None) == [body]


def _segments():
    segs, t = [], 0.0
    lines = ["Welcome back to the show.", "Today is a normal day.", "Wait, this is the craziest secret ever!",
             "Nobody believes me but it is true!", "Why would anyone hide this?", "Anyway let's move on.",
             "The weather is fine.", "We talk about lunch.", "Okay that is all for now."]
    for line in lines * 3:
        words, wt = [], t
        for tok in line.split():
            words.append(Word(tok, wt, wt + 0.4))
            wt += 0.45
        segs.append(Segment(t, wt, line, words))
        t = wt + 0.5
    return segs


def test_heuristic_highlights_are_non_overlapping_and_in_range():
    segs = _segments()
    clips = clipper.heuristic_highlights(segs, count=3, min_len=6, max_len=15)
    assert 1 <= len(clips) <= 3
    for c in clips:
        assert 6 <= c["end"] - c["start"] <= 15
        assert 40 <= c["score"] <= 95
    for a, b in zip(clips, clips[1:]):
        assert a["end"] <= b["start"]


def test_sanitize_drops_overlaps_and_clamps():
    clips = [{"start": -3, "end": 20, "title": "a"}, {"start": 10, "end": 30, "title": "b"},
             {"start": 50, "end": 500, "title": "c"}, {"start": 70, "end": 71, "title": "too short"}]
    out = clipper.sanitize(clips, total=100, min_len=10, max_len=30)
    assert [c["title"] for c in out] == ["a", "c"]
    assert out[0]["start"] == 0 and out[1]["end"] == 80
