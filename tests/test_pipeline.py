import json

from ytedit.assets import AssetLibrary
from ytedit.ffmpeg import MediaInfo, probe
from ytedit.features import parse_features
from ytedit.pipeline import render_plan_file, run
from ytedit.plan import build_plan
from ytedit.render import build_command
from ytedit.transcript import Segment


def _segs():
    return [Segment(0.0, 2.0, "ねえねえ、すみれ。", "aoi", emotion="thinking", se="question"),
            Segment(2.6, 5.1, "実は過去最大の値上げなの！", "sumire", emotion="surprised", se="surprise",
                    emphasis=0.9, cutin=True, cutin_text="過去最大", keywords=["値上げ", "物価"]),
            Segment(5.7, 7.5, "ここで、みんなにお願いがあるの。", "sumire", keywords=["経済"])]


def test_build_plan_and_graph(cfg, assets, tmp_path):
    lib = AssetLibrary(assets)
    info = MediaInfo(duration=8.0, has_video=True, has_audio=True, width=640, height=360)
    plan = build_plan(_segs(), info, tmp_path / "src.mp4", parse_features("all"), cfg, lib, {}, tmp_path)
    assert plan["materials"][0]["path"].endswith("物価_値上げ_円安.png")
    assert {e["char"] for e in plan["expressions"]} == {"sumire", "aoi"}
    assert plan["cutins"][0]["text"] == "過去最大"
    assert plan["popups"] and plan["background"] and plan["bgm"]
    # カットインと同時刻の効果音は、カットイン音を優先して重ねない
    assert [e["kind"] for e in plan["se"]] == ["question", "cutin", "popup"]
    # 表情はすき間なく全体を覆う
    for c in ("sumire", "aoi"):
        ev = [e for e in plan["expressions"] if e["char"] == c]
        assert ev[0]["start"] == 0 and ev[-1]["end"] == 8.0
        assert all(abs(a["end"] - b["start"]) < 1e-6 for a, b in zip(ev, ev[1:]))
    args, graph = build_command(plan, cfg, tmp_path / "work", tmp_path / "o.mp4", assets)
    assert "sidechaincompress" in graph and "loudnorm" in graph and "subtitles=subs.ass" in graph
    assert graph.count("overlay=") >= len(plan["expressions"]) + len(plan["cutins"])


def test_end_to_end(cfg, media, tmp_path):
    res = run(str(media["mp4"]), parse_features("all"), cfg, script=str(media["script"]), out_dir=str(tmp_path / "o"))
    info = probe(res["video"])
    assert info.has_video and info.has_audio and (info.width, info.height) == (640, 360)
    assert abs(info.duration - 10.5) < 0.6  # 無音カット後の長さ
    plan = json.loads(open(res["plan"], encoding="utf-8").read())
    assert [s["speaker"] for s in plan["segments"]] == ["aoi", "sumire", "aoi", "sumire"]
    assert probe(res["short"]).height == 1920
    assert "チャプター" in open(res["description"], encoding="utf-8").read()

    # plan.json を編集して再レンダリング
    plan["cutins"] = []
    plan["features"] = ["bgm", "audio"]
    open(res["plan"], "w", encoding="utf-8").write(json.dumps(plan, ensure_ascii=False))
    again = render_plan_file(res["plan"], cfg)
    assert probe(again["video"]).has_audio


def test_audio_only_input_with_wipe_video(cfg, media, tmp_path):
    cfg["wipe"]["video"] = str(media["mp4"])
    res = run(str(media["wav"]), parse_features("background,expressions,wipe,subtitles,se"), cfg,
              script=str(media["script"]), out_dir=str(tmp_path / "a"))
    info = probe(res["video"])
    assert info.has_video and (info.width, info.height) == (640, 360)


def test_pitch_speaker_detection_without_script(cfg, media, tmp_path):
    from ytedit.speakers import assign_by_pitch

    segs = [Segment(0.0, 2.0, "a"), Segment(2.6, 5.1, "b"), Segment(5.7, 7.5, "c"), Segment(8.1, 10.3, "d")]
    assign_by_pitch(segs, media["wav"], ["sumire", "aoi"], higher="aoi")
    assert [s.speaker for s in segs] == ["aoi", "sumire", "aoi", "sumire"]
