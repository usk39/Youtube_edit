"""立ち絵の顔パーツ(目・口)の位置を自動で見つける。

アニメ/SD 絵向けの簡易検出:
  1. 頭の範囲で真っ白な画素(目のハイライト・白目)を探し、左右の目のおおよその位置を出す
  2. その周りで「肌でも髪でも白でもない」画素のかたまり(瞳)を取り出して、目の範囲を決める
  3. 両目の間隔から口のあたりを推定し、赤っぽい線(口)を探して位置を合わせる
自動検出がずれる場合は assets/characters/<id>/face.json を手で直せる。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def _largest_component(mask: np.ndarray) -> np.ndarray | None:
    """mask の中で一番大きいかたまり(細い線で切り離してから探す)。"""
    m = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(5))
    rgb = m.convert("RGB")
    best, best_n, label = None, 0, 1
    while True:
        arr = np.asarray(rgb)
        ys, xs = np.nonzero(np.all(arr == (255, 255, 255), axis=-1))
        if len(xs) == 0 or label > 200:
            break
        color = (label % 250, label // 250 + 1, 7)
        ImageDraw.floodfill(rgb, (int(xs[0]), int(ys[0])), color)
        comp = np.all(np.asarray(rgb) == color, axis=-1)
        n = int(comp.sum())
        if n > best_n:
            best, best_n = comp, n
        label += 1
    if best is None:
        return None
    return np.asarray(Image.fromarray((best * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0


def detect_face(img: Image.Image) -> dict | None:
    a = np.asarray(img.convert("RGBA")).astype(int)
    c, alpha = a[..., :3], a[..., 3]
    ys, xs = np.nonzero(alpha > 200)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    h = y1 - y0
    head_top, head_bottom = y0 + int(h * 0.15), y0 + int(h * 0.65)
    solid = alpha > 200
    skin = (c[..., 0] > 215) & (c[..., 0] - c[..., 2] > 25) & (c[..., 1] > 170) & solid
    white = (c.min(-1) > 238) & solid
    white[:head_top] = False
    white[head_bottom:] = False
    sy, sx = np.nonzero(skin[head_top:head_bottom])
    if len(sx) < 50:
        return None
    face_cx = float(np.median(sx))
    wy, wx = np.nonzero(white)
    left, right = wx < face_cx, wx >= face_cx
    if left.sum() < 10 or right.sum() < 10:
        return None
    guess = [(wx[left].mean(), wy[left].mean()), (wx[right].mean(), wy[right].mean())]
    dist = guess[1][0] - guess[0][0]
    if dist <= 10:
        return None

    top = a[y0 + int(h * 0.04):y0 + int(h * 0.15), int(face_cx - dist * 0.25):int(face_cx + dist * 0.25)]
    top = top[top[..., 3] > 200][:, :3]
    hair = np.median(top, axis=0) if len(top) else np.array([0, 0, 0])
    not_hair = np.sqrt(((c - hair) ** 2).sum(-1)) >= 70
    eye_mask = (~skin) & (~white) & not_hair & solid

    eyes = []
    for gx, gy in guess:
        r = int(dist * 0.34)
        ya, yb = int(gy - dist * 0.25), int(gy + dist * 0.32)
        xa, xb = int(gx - r), int(gx + r)
        sub = eye_mask[ya:yb, xa:xb]
        comp = _largest_component(sub)
        if comp is None or comp.sum() < 30:
            eyes.append({"x": float(gx), "y": float(gy), "w": dist * 0.5, "h": dist * 0.5})
            continue
        cy_, cx_ = np.nonzero(comp)
        bx0, bx1 = np.percentile(cx_, 3) + xa, np.percentile(cx_, 97) + xa
        by0, by1 = np.percentile(cy_, 3) + ya, np.percentile(cy_, 97) + ya
        # 白目・ハイライトも目の範囲に含める
        wsel = (np.abs(wx - (bx0 + bx1) / 2) < dist * 0.35) & (np.abs(wy - (by0 + by1) / 2) < dist * 0.35)
        if wsel.any():
            bx0, bx1 = min(bx0, wx[wsel].min()), max(bx1, wx[wsel].max())
            by0, by1 = min(by0, wy[wsel].min()), max(by1, wy[wsel].max())
        w_, h_ = min(bx1 - bx0, dist * 0.7), min(by1 - by0, dist * 0.7)
        eyes.append({"x": float((bx0 + bx1) / 2), "y": float((by0 + by1) / 2), "w": float(w_), "h": float(h_)})

    ex = (eyes[0]["x"] + eyes[1]["x"]) / 2
    ey = max(e["y"] + e["h"] / 2 for e in eyes)
    d = eyes[1]["x"] - eyes[0]["x"]
    mx, my, mw = ex, ey + d * 0.2, d * 0.28
    # 口の線(赤茶色で少し暗い)を、目の少し下から上へ順に探し、最初に見つかった線を口とする
    ya, yb = int(ey + d * 0.02), int(ey + d * 0.5)
    xa, xb = int(ex - d * 0.25), int(ex + d * 0.25)
    sub = c[ya:yb, xa:xb]
    lum = sub.mean(-1)
    mouth = (sub[..., 0] - sub[..., 2] > 35) & (lum < 175) & (alpha[ya:yb, xa:xb] > 200) & \
        (np.abs(sub[..., 0] - sub[..., 1]) > 25)
    rows = mouth.sum(1)
    hit = np.nonzero(rows >= 3)[0]
    if len(hit):
        r0 = hit[0]
        band = mouth[r0:r0 + int(d * 0.08)]
        by_, bx_ = np.nonzero(band)
        mx, my = float(np.median(bx_) + xa), float(np.median(by_) + ya + r0)
        mw = float(max(d * 0.15, np.percentile(bx_, 97) - np.percentile(bx_, 3)))
    return {"eyes": eyes, "mouth": {"x": float(mx), "y": float(my), "w": float(mw)}, "hair": [int(v) for v in hair]}


# 添付いただいた すみれ/あおい の立ち絵は、目と口の位置を実測したプリセットを使う(画像の見た目のハッシュで判定)
PRESETS = [
    {"name": "あおい(青髪ロング)", "ahash": "e7c38189998181e3", "size": [1148, 1280],
     "eyes": [{"x": 475, "y": 552, "w": 166, "h": 155}, {"x": 781, "y": 557, "w": 147, "h": 155}],
     "mouth": {"x": 629, "y": 700, "w": 82}},
    {"name": "すみれ(茶髪マフラー)", "ahash": "ffc3819199c18383", "size": [897, 1279],
     "eyes": [{"x": 279, "y": 600, "w": 122, "h": 117}, {"x": 545, "y": 605, "w": 150, "h": 130}],
     "mouth": {"x": 409, "y": 709, "w": 92}},
]


def ahash(img: Image.Image) -> str:
    g = Image.new("RGBA", img.size, (255, 255, 255, 255))
    g.alpha_composite(img.convert("RGBA"))
    a = np.asarray(g.convert("L").resize((8, 8), Image.LANCZOS)).astype(float)
    return "%016x" % int("".join("1" if b else "0" for b in (a > a.mean()).flatten()), 2)


def preset_face(img: Image.Image) -> dict | None:
    """プリセットと同じ絵なら(拡大縮小されていても)その顔位置を返す。"""
    h = int(ahash(img), 16)
    for p in PRESETS:
        if bin(h ^ int(p["ahash"], 16)).count("1") > 4:
            continue
        sx, sy = img.width / p["size"][0], img.height / p["size"][1]
        if abs(sx - sy) > 0.02:
            continue
        eyes = [{"x": e["x"] * sx, "y": e["y"] * sy, "w": e["w"] * sx, "h": e["h"] * sy} for e in p["eyes"]]
        m = p["mouth"]
        return {"eyes": eyes, "mouth": {"x": m["x"] * sx, "y": m["y"] * sy, "w": m["w"] * sx}, "preset": p["name"]}
    return None


def find_face(img: Image.Image) -> dict | None:
    return preset_face(img) or detect_face(img)


def transform_face(face: dict, offset: tuple[float, float], scale: float) -> dict:
    """切り抜き(offset)・拡大縮小(scale)後の座標に変換。"""
    ox, oy = offset
    eyes = [{"x": (e["x"] - ox) * scale, "y": (e["y"] - oy) * scale, "w": e["w"] * scale, "h": e["h"] * scale}
            for e in face["eyes"]]
    m = face["mouth"]
    return {**face, "eyes": eyes, "mouth": {"x": (m["x"] - ox) * scale, "y": (m["y"] - oy) * scale, "w": m["w"] * scale}}


def load_face(char_dir: Path) -> dict | None:
    p = char_dir / "face.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def draw_debug(img: Image.Image, face: dict) -> Image.Image:
    """検出結果を枠で描いた確認用画像。"""
    out = Image.new("RGBA", img.size, (255, 255, 255, 255))
    out.alpha_composite(img.convert("RGBA"))
    d = ImageDraw.Draw(out)
    for e in face["eyes"]:
        d.ellipse((e["x"] - e["w"] / 2, e["y"] - e["h"] / 2, e["x"] + e["w"] / 2, e["y"] + e["h"] / 2),
                  outline=(255, 0, 0, 255), width=4)
    m = face["mouth"]
    d.rectangle((m["x"] - m["w"] / 2, m["y"] - 8, m["x"] + m["w"] / 2, m["y"] + 8), outline=(0, 160, 255, 255), width=4)
    return out
