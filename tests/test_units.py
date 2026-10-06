import pytest

from ytedit import analyze
from ytedit.config import DEFAULT_CONFIG
from ytedit.features import PRESETS, parse_features
from ytedit.subtitles import build_ass
from ytedit.transcript import (Segment, Word, align_script_with_silence, align_script_with_words, parse_script,
                               parse_srt, split_speaker_prefix, voiced_intervals, write_srt)

CHARS = DEFAULT_CONFIG["characters"]


def test_parse_features():
    assert parse_features("bgm,se") == ["bgm", "se"]
    assert parse_features("all,-shorts,-wipe") == PRESETS["standard"]
    assert set(parse_features("requested")) == {"bgm", "materials", "background", "expressions", "audio", "se", "cutin",
                                                "subtitles"}
    with pytest.raises(ValueError):
        parse_features("unknown")


@pytest.mark.parametrize("text,spk,body", [
    ("あおい:こんにちは", "aoi", "こんにちは"),
    ("すみれ：説明するよ", "sumire", "説明するよ"),
    ("【すみれ】「そうなの」", "sumire", "そうなの"),
    ("ナレーション:ほげ", None, "ナレーション:ほげ"),
])
def test_split_speaker_prefix(text, spk, body):
    assert split_speaker_prefix(text, CHARS) == (spk, body)


def test_parse_script_joins_continuation(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("タイトル：x\nあおい:ねえ\n続きの行\n\nすみれ:うん\n", encoding="utf-8")
    assert parse_script(p, CHARS) == [("aoi", "ねえ続きの行"), ("sumire", "うん")]


def test_align_with_silence_one_to_one():
    lines = [("aoi", "あ"), ("sumire", "い")]
    segs = align_script_with_silence(lines, [(0.0, 1.0), (1.5, 3.0)])
    assert [(s.start, s.end, s.speaker) for s in segs] == [(0.0, 1.0, "aoi"), (1.5, 3.0, "sumire")]


def test_align_with_silence_proportional_snaps_to_gaps():
    lines = [("aoi", "ああああ"), ("sumire", "いいいい"), ("aoi", "うう")]
    voiced = [(0.0, 2.0), (2.5, 3.5), (3.8, 4.5), (5.0, 6.0)]
    segs = align_script_with_silence(lines, voiced)
    assert len(segs) == 3
    assert all(a.end <= b.start for a, b in zip(segs, segs[1:]))
    assert segs[0].end == pytest.approx(2.0)


def test_align_with_words_uses_script_text():
    words = [Word(0.0, 0.5, "ねえ"), Word(0.5, 1.0, "すみれ"), Word(2.0, 2.6, "今日は"), Word(2.6, 3.5, "円安")]
    segs = align_script_with_words([("aoi", "ねえ、すみれ。"), ("sumire", "今日は円安よ。")], words)
    assert segs[0].speaker == "aoi" and segs[0].start < 0.3 and segs[0].end <= segs[1].start
    assert segs[1].text == "今日は円安よ。" and segs[1].start == pytest.approx(1.9, abs=0.2)


def test_srt_roundtrip(tmp_path):
    segs = [Segment(0.0, 1.5, "こんにちは", "aoi"), Segment(1.6, 3.0, "説明するよ", "sumire")]
    p = write_srt(segs, tmp_path / "a.srt", CHARS)
    back = parse_srt(p, CHARS)
    assert [(s.speaker, s.text) for s in back] == [("aoi", "こんにちは"), ("sumire", "説明するよ")]
    assert back[1].start == pytest.approx(1.6)


def test_voiced_intervals():
    assert voiced_intervals([(1.0, 2.0), (3.0, 4.0)], 5.0) == [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]


def test_rule_analysis():
    segs = [Segment(0, 2, "えっ、まじで!? また値上げとか、ふざけとるやろ。", "aoi"),
            Segment(40, 42, "つまり、ポイントは経済の仕組みなの。", "sumire"),
            Segment(80, 82, "今日はいい天気だね", "sumire")]
    analyze.analyze_rules(segs)
    assert segs[0].emotion == "surprised" and segs[0].se == "surprise" and segs[0].cutin
    assert segs[0].cutin_text == "まじで!?"
    assert segs[1].emotion == "doya" and segs[1].se == "point"
    assert segs[2].emotion == "normal" and not segs[2].cutin
    assert "経済" in segs[1].keywords


def test_ass_uses_line_breaks():
    segs = [Segment(0, 2, "テスト{x}", "aoi"), Segment(2, 4, "あおい、今日はね、円安と物価の話題についてよ。", "sumire")]
    ass = build_ass(segs, DEFAULT_CONFIG, "IPAGothic", 300)
    assert "Style: aoi,IPAGothic" in ass and "Dialogue: 0,0:00:00.00,0:00:02.00,aoi" in ass and "{x}" not in ass
    assert ass.rstrip().splitlines()[-1].endswith(",,あおい、今日はね、\\N円安と物価の話題についてよ")
