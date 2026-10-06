import sys
import types

from ytedit import llm
from ytedit.transcript import Segment


class _Resp:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    def parse(self, model, max_tokens, system, messages, output_format):
        if output_format is llm.SegmentTags:
            return _Resp(llm.SegmentTags(segments=[
                llm.SegmentTag(index=1, emotion="jito", se="shock", emphasis=0.8, cutin=True,
                               cutin_text="口だけやん", material_keywords=["国会"], image_query_en="parliament building"),
                llm.SegmentTag(index=99, emotion="normal", se="none", emphasis=0, cutin=False,
                               cutin_text="", material_keywords=[], image_query_en=""),
            ]))
        return _Resp(llm.Overview(
            chapters=[llm.Chapter(start_index=0, title="導入", bgm_mood="calm", background_keywords=[], background_query_en="city"),
                      llm.Chapter(start_index=1, title="本題", bgm_mood="tense", background_keywords=["政治"], background_query_en="parliament")],
            scenes=[llm.Scene(start_index=0, mood="calm", description="導入"),
                    llm.Scene(start_index=1, mood="comical", description="ツッコミ")],
            title_ideas=["タイトル"], description="説明", thumbnail_text="ヤバい", tags=["ニュース"]))


def test_analyze_with_claude_applies_tags(monkeypatch, cfg):
    fake = types.SimpleNamespace(Anthropic=lambda: types.SimpleNamespace(messages=_FakeMessages()))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    segs = [Segment(0, 1, "ねえ", "aoi"), Segment(5, 6, "政治家はまた言い訳しとる", "aoi")]
    ov = llm.analyze_with_claude(segs, cfg, ["国会"], ["政治"])
    assert segs[1].emotion == "jito" and segs[1].se == "shock" and segs[1].cutin_text == "口だけやん"
    assert segs[1].keywords == ["国会"] and segs[1].image_query == "parliament building"
    assert [c["start"] for c in ov["chapters"]] == [0.0, 5]
    assert ov["chapters"][1]["bgm_mood"] == "tense" and ov["thumbnail_text"] == "ヤバい"
    assert ov["chapters"][1]["background_query_en"] == "parliament"
    assert [(x["start"], x["mood"]) for x in ov["scenes"]] == [(0.0, "calm"), (5, "comical")]


def test_llm_available_respects_off(cfg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    cfg["llm"]["enabled"] = False
    assert not llm.llm_available(cfg)
