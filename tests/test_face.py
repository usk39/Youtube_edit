import numpy as np
from PIL import Image

from ytedit import face as F
from ytedit.face import detect_face, preset_face, transform_face
from ytedit.face_edit import RECIPES, edit_face
from ytedit.sample_assets import draw_character


def _char():
    return draw_character("normal", (40, 120, 210), (220, 240, 255))


def test_detect_face_on_sample_character():
    f = detect_face(_char())
    assert f is not None
    left, right = sorted(f["eyes"], key=lambda e: e["x"])
    # sample_assets の目は (235,320) と (365,320)、口は (300,420)
    assert abs(left["x"] - 235) < 25 and abs(right["x"] - 365) < 25 and abs(left["y"] - 320) < 30
    assert abs(f["mouth"]["x"] - 300) < 30


def test_preset_matches_scaled_copy(monkeypatch):
    img = _char()
    preset = {"name": "テスト", "ahash": F.ahash(img), "size": list(img.size),
              "eyes": [{"x": 235, "y": 320, "w": 50, "h": 60}, {"x": 365, "y": 320, "w": 50, "h": 60}],
              "mouth": {"x": 300, "y": 420, "w": 50}}
    monkeypatch.setattr(F, "PRESETS", [preset])
    half = img.resize((img.width // 2, img.height // 2))
    got = preset_face(half)
    assert got["preset"] == "テスト" and abs(got["eyes"][0]["x"] - 117.5) < 1
    assert preset_face(Image.new("RGBA", (600, 900), (255, 0, 0, 255))) is None


def test_transform_face():
    f = {"eyes": [{"x": 110, "y": 60, "w": 20, "h": 20}] * 2, "mouth": {"x": 110, "y": 100, "w": 30}}
    t = transform_face(f, (10, 20), 0.5)
    assert t["eyes"][0] == {"x": 50, "y": 20, "w": 10, "h": 10} and t["mouth"]["y"] == 40


def test_every_expression_changes_the_face():
    img = _char()
    face = {"eyes": [{"x": 235, "y": 320, "w": 60, "h": 70}, {"x": 365, "y": 320, "w": 60, "h": 70}],
            "mouth": {"x": 300, "y": 420, "w": 60}}
    base = np.asarray(img).astype(int)
    assert np.array_equal(np.asarray(edit_face(img, face, "normal")), np.asarray(img))
    for expr in RECIPES:
        out = np.asarray(edit_face(img, face, expr)).astype(int)
        changed = np.abs(out - base).sum(-1) > 30
        assert changed[250:460, 180:420].sum() > 200, expr  # 顔のあたりが描き換わっている
        assert changed[600:, :].sum() == 0, expr  # 体は変わらない
