import wave

import numpy as np

from ytedit.analyze import detect_scenes
from ytedit.animate import CharacterStrip, blink_frames, mouth_levels, motion_offset
from ytedit.assets import AssetLibrary
from ytedit.characters import add_character, variant_name
from ytedit.ffmpeg import MediaInfo
from ytedit.plan import build_plan
from ytedit.sample_assets import draw_character
from ytedit.transcript import Segment


def _wav(path, sr=16000):
    t = np.arange(sr * 2) / sr
    x = np.where(t < 1.0, 0.4 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t)), 0.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    return path


def test_mouth_moves_only_while_speaking(tmp_path):
    lv = mouth_levels(_wav(tmp_path / "a.wav"), 24, 48, np.array([True] * 24 + [False] * 24))
    assert set(lv[:24]) >= {0, 1, 2} or set(lv[:24]) >= {1, 2}  # 声の間はパクパクする
    assert (lv[:24] > 0).sum() > 8
    assert (lv[24:] == 0).all()  # 話していない間は閉じている


def test_blinks_are_periodic():
    b = blink_frames(30 * 20, 30, "aoi")
    starts = np.nonzero(b[1:] & ~b[:-1])[0]
    assert 4 <= len(starts) <= 14  # 20 秒で数回
    assert not np.array_equal(b, blink_frames(30 * 20, 30, "sumire"))  # 2 人でタイミングが違う


def test_motion_offsets():
    assert motion_offset({"start": 0, "motion": "jump"}, 0.11, 1.0, False)[1] < -30
    assert motion_offset({"start": 0, "motion": "shake"}, 0.015, 1.0, False)[0] != 0
    assert motion_offset({"start": 0, "motion": None}, 1.0, 1.0, False) == (0, 0)


def test_add_character_makes_lipsync_and_blink_variants(tmp_path):
    src = tmp_path / "c.png"
    draw_character("normal", (40, 120, 210), (220, 240, 255)).save(src)
    add_character("aoi", src, tmp_path / "assets")
    d = tmp_path / "assets/characters/aoi"
    for name in ("normal", "normal__m1", "normal__m2", "normal__b", "angry__b_m2", "smile__m1"):
        assert (d / f"{name}.png").exists(), name
    assert not (d / "smile__b.png").exists()  # にっこり目はまばたき不要
    lib = AssetLibrary(tmp_path / "assets")
    assert lib.expressions("aoi")[0] == "angry" and "normal__m1" not in lib.expressions("aoi")
    assert lib.sprite("aoi", "smile", 2, True).name == "smile__m2.png"
    assert variant_name("sad", 1, True) == "sad__b_m1"


def test_character_strip_frames(tmp_path, assets, cfg):
    segs = [Segment(0.0, 0.9, "ねえ", "aoi"), Segment(1.0, 1.9, "うん", "sumire")]
    wav = _wav(tmp_path / "v.wav")
    plan = build_plan(segs, MediaInfo(duration=2.0, has_video=False, has_audio=True), wav, ["expressions"], cfg,
                      AssetLibrary(assets), {}, tmp_path)
    strip = CharacterStrip(plan, cfg, AssetLibrary(assets), tmp_path)
    frames = list(strip.frames())
    assert len(frames) == strip.n and len(frames[0]) == cfg["output"]["width"] * strip.strip_h * 4
    arr = np.frombuffer(frames[5], dtype=np.uint8).reshape(strip.strip_h, -1, 4)
    assert arr[..., 3].max() == 255  # キャラが描かれている


def test_scenes_and_bgm_crossfade(cfg, assets, tmp_path):
    segs = [Segment(i * 10.0, i * 10.0 + 8, "t", "aoi" if i % 2 else "sumire",
                    emotion=("normal" if i < 4 else "angry")) for i in range(8)]
    scenes = detect_scenes(segs, 80.0, min_len=20)
    assert [s["mood"] for s in scenes] == ["calm", "tense"] and scenes[0]["start"] == 0 and scenes[-1]["end"] == 80
    segs[5].se = "surprise"
    plan = build_plan(segs, MediaInfo(duration=80.0, has_video=True, has_audio=True), tmp_path / "v.mp4",
                      ["bgm", "se"], cfg, AssetLibrary(assets), {}, tmp_path)
    a, b = plan["bgm"]
    assert a["mood"] == "calm" and b["mood"] == "tense" and a["end"] > b["start"]  # 重なってクロスフェード
    assert a["fade_out"] == b["fade_in"] == cfg["bgm"]["crossfade"]
    kinds = [(e["kind"], e["mood"]) for e in plan["se"]]
    assert ("transition", "tense") in kinds and ("surprise", "tense") in kinds
