"""ネット素材取得のテスト(実際の通信はせず、各サイトの API 応答を模擬する)。"""

import json

import pytest

from ytedit import online
from ytedit.assets import AssetLibrary
from ytedit.extras import credit_text
from ytedit.ffmpeg import MediaInfo
from ytedit.online import OnlineSource, to_english
from ytedit.plan import build_plan
from ytedit.transcript import Segment

OPENVERSE_IMG = {"results": [
    {"url": "https://ex.org/nc.jpg", "license": "by-nc", "title": "NC", "creator": "x"},
    {"url": "https://ex.org/yen.jpg", "license": "by", "license_version": "4.0", "title": "Yen coins", "creator": "Taro",
     "license_url": "https://creativecommons.org/licenses/by/4.0/", "foreign_landing_url": "https://flickr.com/1",
     "source": "flickr"},
]}
FREESOUND = {"results": [
    {"name": "nc hit", "username": "a", "license": "https://creativecommons.org/licenses/by-nc/4.0/",
     "previews": {"preview-hq-mp3": "https://fs.org/nc.mp3"}, "duration": 1.0, "url": "https://fs.org/s/1"},
    {"name": "whoosh", "username": "b", "license": "http://creativecommons.org/publicdomain/zero/1.0/",
     "previews": {"preview-hq-mp3": "https://fs.org/ok.mp3"}, "duration": 0.8, "url": "https://fs.org/s/2"},
]}
JAMENDO = {"results": [
    {"name": "Calm Song", "artist_name": "Hanako", "audio": "https://jam.org/a.mp3", "audiodownload_allowed": False,
     "license_ccurl": "http://creativecommons.org/licenses/by/3.0/", "shareurl": "https://jam.org/t/1", "duration": 180},
]}
PIXABAY = {"hits": [{"largeImageURL": "https://pix.org/ja.jpg", "tags": "円安", "user": "u", "pageURL": "https://pix.org/1"}]}


@pytest.fixture()
def fake_net(monkeypatch):
    calls = []

    def http_json(url, headers=None):
        calls.append(url)
        if "openverse" in url and "/images/" in url:
            return OPENVERSE_IMG
        if "openverse" in url and "/audio/" in url:
            cat = "music" if "category=music" in url else "se"
            dur = 200000 if cat == "music" else 1500
            return {"results": [{"url": f"https://ov.org/{cat}.mp3", "license": "cc0", "title": cat, "duration": dur}]}
        if "freesound" in url:
            return FREESOUND
        if "jamendo" in url:
            return JAMENDO
        if "pixabay" in url:
            return PIXABAY
        raise AssertionError(url)

    def http_download(url, out, headers=None):
        out.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(".mp3"):
            import shutil

            from ytedit.sample_assets import make_se
            tmp = out.parent / "_gen"
            make_se(tmp)
            shutil.copy(next(tmp.rglob("*.wav")), out)
        else:
            from PIL import Image
            Image.new("RGB", (640, 360), (200, 100, 50)).save(out, "JPEG")
        return out

    monkeypatch.setattr(online, "http_json", http_json)
    monkeypatch.setattr(online, "http_download", http_download)
    return calls


def _cfg(cfg, **keys):
    cfg["online"].update({"enabled": True, **keys})
    return cfg


def test_to_english():
    assert to_english("円安") == "japanese yen"
    assert to_english("円安進行") == "japanese yen"
    assert to_english("AI") == "AI"
    assert to_english("ほげほげ") is None


def test_cc_code_filters_nc_nd():
    assert online._cc_code("https://creativecommons.org/licenses/by/4.0/") == "by"
    assert online._cc_code("https://creativecommons.org/licenses/by-nc/4.0/") is None
    assert online._cc_code("https://creativecommons.org/licenses/by-nd/4.0/") is None
    assert online._cc_code("http://creativecommons.org/publicdomain/zero/1.0/") == "cc0"


def test_openverse_image_skips_noncommercial_and_caches(fake_net, cfg):
    src = OnlineSource(_cfg(cfg))
    path, meta = src.image(["円安"], [])
    assert meta["title"] == "Yen coins" and meta["needs_credit"] and path.exists()
    assert json.loads(path.with_name(path.name + ".json").read_text(encoding="utf-8"))["creator"] == "Taro"
    n = len(fake_net)
    OnlineSource(cfg).image(["円安"], [])  # 2回目は検索結果キャッシュを使う
    assert len(fake_net) == n


def test_pixabay_used_first_with_japanese_query(fake_net, cfg):
    src = OnlineSource(_cfg(cfg, pixabay_api_key="K"))
    path, meta = src.image(["円安"], [])
    assert meta["provider"] == "pixabay" and "q=%E5%86%86%E5%AE%89" in fake_net[0] and "lang=ja" in fake_net[0]


def test_se_and_bgm_providers(fake_net, cfg):
    src = OnlineSource(_cfg(cfg, freesound_api_key="F", jamendo_client_id="J"))
    _, se = src.se("transition")
    assert se["provider"] == "freesound" and se["license"] == "CC0"
    _, bgm = src.bgm("calm")
    assert bgm["provider"] == "jamendo" and bgm["creator"] == "Hanako" and bgm["needs_credit"]


def test_openverse_audio_without_keys(fake_net, cfg):
    src = OnlineSource(_cfg(cfg))
    assert src.se("surprise")[1]["provider"].startswith("openverse")
    assert src.bgm("tense")[1]["duration"] >= 60


def test_provider_failure_falls_back(monkeypatch, cfg):
    def boom(url, headers=None):
        raise OSError("network down")

    monkeypatch.setattr(online, "http_json", boom)
    src = OnlineSource(_cfg(cfg))
    assert src.image(["円安"], ["yen"]) is None
    assert "openverse" in src.failed_providers


def test_plan_uses_online_assets_and_credits(fake_net, cfg, assets, tmp_path):
    _cfg(cfg)
    segs = [Segment(0.0, 3.0, "今日は円安の話題よ。", "sumire", keywords=["円安"], se="point"),
            Segment(3.5, 6.0, "ほげほげ", "aoi", image_query="stock chart")]
    info = MediaInfo(duration=7.0, has_video=True, has_audio=True)
    plan = build_plan(segs, info, tmp_path / "v.mp4", ["bgm", "materials", "background", "se"], cfg,
                      AssetLibrary(assets), {}, tmp_path)
    assert plan["materials"][0]["credit"]["title"] == "Yen coins"
    assert plan["bgm"][0]["credit"]["provider"].startswith("openverse")
    assert plan["se"][0]["credit"] is not None
    assert any(c["needs_credit"] for c in plan["credits"])
    assert any("Taro" in line and "CC BY 4.0" in line for line in credit_text(plan["credits"]))


def test_prefer_local(fake_net, cfg, assets, tmp_path):
    _cfg(cfg, prefer="local")
    segs = [Segment(0.0, 3.0, "物価の話", "sumire", keywords=["物価"])]
    plan = build_plan(segs, MediaInfo(duration=4.0, has_video=True, has_audio=True), tmp_path / "v.mp4",
                      ["materials"], cfg, AssetLibrary(assets), {}, tmp_path)
    assert plan["materials"][0]["credit"] is None and "物価" in plan["materials"][0]["path"]
