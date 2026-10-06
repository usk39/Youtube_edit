"""立ち絵 1 枚から表情差分を自動で作る(`ytedit add-character`)。

1. 目と口の位置を見つける(添付の すみれ/あおい はプリセット、それ以外は自動検出。face.json で手直し可)
2. 顔そのもの(目・口・眉)を表情に合わせて描き換える (face_edit.py)
3. 漫符(びっくりマーク・怒りマーク・汗・はてな・キラキラ等)を足す
動画では表情ごとの動き(驚き=ジャンプ、怒り=震え、落ち込み=沈む)も付く。
本物の表情差分画像があれば、同じファイル名で置き換えるとそちらが使われる。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import graphics as G
from .face import draw_debug, find_face, transform_face
from .face_edit import edit_face

EXPRESSIONS = ["normal", "smile", "laugh", "surprised", "angry", "sad", "thinking", "doya", "jito"]
# 表情ごとの動き (render.py で使用)
MOTIONS = {"surprised": "jump", "angry": "shake", "sad": "sink", "jito": "sink", "laugh": "bounce"}

PAD_X, PAD_TOP = 0.2, 0.16  # 漫符がはみ出せるよう、全表情で共通の余白を付ける


# ------------------------------------------------------------------ 背景透過
def ensure_transparent(img: Image.Image, threshold: int = 238) -> Image.Image:
    """背景が透過されていなければ、外周とつながった白っぽい部分を透明にする。"""
    img = img.convert("RGBA")
    alpha = np.asarray(img.getchannel("A"))
    if (alpha < 16).mean() > 0.03:  # すでに透過あり
        return img
    rgb = img.convert("RGB")
    marker = (255, 0, 255)
    w, h = rgb.size
    arr = np.asarray(rgb)
    seeds = [(x, 0) for x in range(0, w, 8)] + [(x, h - 1) for x in range(0, w, 8)] + \
            [(0, y) for y in range(0, h, 8)] + [(w - 1, y) for y in range(0, h, 8)]
    for x, y in seeds:
        px = arr[y, x] if y < arr.shape[0] and x < arr.shape[1] else (0, 0, 0)
        if min(px) >= threshold and rgb.getpixel((x, y)) != marker:
            ImageDraw.floodfill(rgb, (x, y), marker, thresh=40)
            arr = np.asarray(rgb)
    bg = np.all(np.asarray(rgb) == marker, axis=-1)
    mask = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1))  # フチを少しなじませる
    img.putalpha(mask)
    return img


# ------------------------------------------------------------------ 漫符
class Face:
    """立ち絵の中の「頭」のおおよその位置(SD キャラ想定: 上から約 6 割が頭)。"""

    def __init__(self, img: Image.Image, head_ratio: float):
        x0, y0, x1, y1 = img.getbbox() or (0, 0, img.width, img.height)
        self.x0, self.y0, self.x1 = x0, y0, x1
        self.w = x1 - x0
        self.h = (y1 - y0) * head_ratio
        self.cx = (x0 + x1) / 2
        self.s = self.w / 520  # 漫符の大きさの基準

    def at(self, rx: float, ry: float) -> tuple[float, float]:
        """頭の箱に対する相対座標 → 画像座標 (rx: 0=左端 1=右端, ry: 0=頭頂 1=あご)"""
        return self.x0 + self.w * rx, self.y0 + self.h * ry


def _outline_poly(d: ImageDraw.ImageDraw, pts, fill, outline=(40, 30, 30, 255), width=6):
    d.polygon(pts, fill=fill, outline=outline, width=width)


def _exclamation(d, x, y, s, color=(255, 70, 70, 255)):
    for dx, tilt in ((-s * 38, -6), (s * 38, 10)):
        t = math.radians(tilt)
        def rot(px, py):
            return (x + dx + px * math.cos(t) - py * math.sin(t), y + px * math.sin(t) + py * math.cos(t))
        bar = [rot(-22 * s, -120 * s), rot(22 * s, -120 * s), rot(10 * s, 20 * s), rot(-10 * s, 20 * s)]
        _outline_poly(d, bar, color, width=max(3, int(6 * s)))
        cx, cy = rot(0, 55 * s)
        r = 16 * s
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color, outline=(40, 30, 30, 255), width=max(3, int(6 * s)))


def _impact_lines(d, cx, cy, r, s, n=5, start=200, end=340):
    for i in range(n):
        a = math.radians(start + (end - start) * i / max(1, n - 1))
        p1 = (cx + math.cos(a) * r, cy + math.sin(a) * r)
        p2 = (cx + math.cos(a) * (r + 60 * s), cy + math.sin(a) * (r + 60 * s))
        d.line((p1, p2), fill=(40, 30, 30, 255), width=max(3, int(8 * s)))


def _anger(d, x, y, s):
    r = 34 * s
    off = r * 1.15
    w = max(4, int(12 * s))
    for (ox, oy, a0, a1) in ((-off, -off, 0, 90), (off, -off, 90, 180), (off, off, 180, 270), (-off, off, 270, 360)):
        box = (x + ox - r, y + oy - r, x + ox + r, y + oy + r)
        d.arc(box, a0 - 8, a1 + 8, fill=(90, 0, 0, 255), width=w + max(3, int(5 * s)))
        d.arc(box, a0, a1, fill=(235, 40, 40, 255), width=w)


def _sweat(d, x, y, s, scale=1.0):
    k = s * scale
    pts = [(x, y - 60 * k), (x - 26 * k, y), (x + 26 * k, y)]
    d.polygon(pts, fill=(150, 210, 255, 235))
    d.ellipse((x - 27 * k, y - 25 * k, x + 27 * k, y + 28 * k), fill=(150, 210, 255, 235), outline=(40, 90, 170, 255),
              width=max(2, int(4 * k)))
    d.line(((x, y - 60 * k), (x - 26 * k, y - 4 * k)), fill=(40, 90, 170, 255), width=max(2, int(4 * k)))
    d.line(((x, y - 60 * k), (x + 26 * k, y - 4 * k)), fill=(40, 90, 170, 255), width=max(2, int(4 * k)))
    d.ellipse((x - 12 * k, y - 10 * k, x - 2 * k, y + 6 * k), fill=(255, 255, 255, 230))


def _sparkle(d, x, y, r, color=(255, 215, 60, 255)):
    pts = []
    for i in range(8):
        a = math.radians(i * 45 - 90)
        rr = r if i % 2 == 0 else r * 0.28
        pts.append((x + math.cos(a) * rr, y + math.sin(a) * rr))
    d.polygon(pts, fill=color, outline=(255, 255, 255, 255))


def _note(d, x, y, s, color=(255, 110, 160, 255)):
    r = 18 * s
    w = max(3, int(7 * s))
    d.ellipse((x - r * 1.3, y - r, x + r * 1.3, y + r), fill=color)
    d.line(((x + r * 1.2, y), (x + r * 1.2, y - 80 * s)), fill=color, width=w)
    d.line(((x + r * 1.2, y - 80 * s), (x + r * 2.6, y - 55 * s)), fill=color, width=w)


def _question(d, x, y, s, font_path):
    f = G.font(font_path, max(20, int(150 * s)))
    d.text((x, y), "?", font=f, fill=(70, 120, 255, 255), stroke_width=max(3, int(8 * s)),
           stroke_fill=(255, 255, 255, 255), anchor="mm")
    for i in range(3):
        r = 8 * s
        cx = x - 120 * s + i * 34 * s
        d.ellipse((cx - r, y + 60 * s - r, cx + r, y + 60 * s + r), fill=(90, 90, 110, 255))


def _gloom(layer: Image.Image, face: Face, color, strength: int, lines: bool):
    """顔の上半分を暗くする(ガーン/ジト目)。"""
    w, h = layer.size
    grad = Image.new("L", (w, h), 0)
    gd = ImageDraw.Draw(grad)
    top, peak, bottom = face.y0 + face.h * 0.12, face.y0 + face.h * 0.3, face.y0 + face.h * 0.62
    for y in range(int(top), int(bottom)):
        k = (y - top) / (peak - top) if y < peak else 1 - (y - peak) / (bottom - peak)
        a = int(strength * max(0.0, min(1.0, k)))
        gd.line(((face.x0, y), (face.x0 + face.w, y)), fill=a)
    tint = Image.new("RGBA", (w, h), color + (255,))
    mask = Image.fromarray(np.minimum(np.asarray(grad, dtype=np.uint16), np.asarray(layer.getchannel("A"), dtype=np.uint16))
                           .astype(np.uint8))
    layer.paste(tint, (0, 0), mask)
    if lines:
        d = ImageDraw.Draw(layer)
        for i in range(7):
            x = face.x0 + face.w * (0.25 + i * 0.08)
            y0 = face.y0 + face.h * 0.28
            d.line(((x, y0), (x, y0 + face.h * (0.12 + 0.05 * (i % 3)))), fill=color + (200,),
                   width=max(2, int(6 * face.s)))


def make_expression(base: Image.Image, expr: str, head_ratio: float = 0.6, font_path: str | None = None,
                    face: dict | None = None) -> Image.Image:
    """余白付きの共通キャンバスに、表情を描き込んだ画像を返す。

    face(目と口の位置)があれば顔そのもの(目・口・眉)を描き換え、さらに漫符を足す。
    """
    if face:
        base = edit_face(base, face, expr)
    pw, pt = int(base.width * PAD_X), int(base.height * PAD_TOP)
    canvas = Image.new("RGBA", (base.width + pw * 2, base.height + pt), (0, 0, 0, 0))
    canvas.alpha_composite(base, (pw, pt))
    face = Face(canvas, head_ratio)
    d = ImageDraw.Draw(canvas)
    s = face.s
    if expr == "surprised":
        _exclamation(d, *face.at(0.98, 0.16), s)
        _impact_lines(d, *face.at(0.5, 0.45), face.w * 0.55, s)
    elif expr == "angry":
        _anger(d, *face.at(0.9, 0.12), s * 1.2)
        _anger(d, *face.at(0.12, 0.2), s * 0.7)
    elif expr == "sad":
        _gloom(canvas, face, (60, 70, 160), 150, lines=True)
        d = ImageDraw.Draw(canvas)
        _sweat(d, *face.at(0.88, 0.35), s * 1.1)
    elif expr == "jito":
        _gloom(canvas, face, (70, 60, 90), 120, lines=False)
        d = ImageDraw.Draw(canvas)
        _sweat(d, *face.at(0.95, 0.25), s * 1.3)
    elif expr == "thinking":
        _question(d, *face.at(1.0, 0.1), s, font_path)
    elif expr == "laugh":
        _note(d, *face.at(1.0, 0.2), s * 1.2)
        _note(d, *face.at(-0.02, 0.28), s, (255, 170, 60, 255))
        _impact_lines(d, *face.at(0.5, 0.5), face.w * 0.56, s * 0.8, n=4, start=300, end=360)
    elif expr == "smile":
        _sparkle(d, *face.at(0.98, 0.18), 38 * s, (255, 150, 190, 255))
        _sparkle(d, *face.at(1.06, 0.36), 24 * s, (255, 200, 80, 255))
    elif expr == "doya":
        _sparkle(d, *face.at(1.0, 0.12), 60 * s)
        _sparkle(d, *face.at(1.1, 0.32), 34 * s)
        _sparkle(d, *face.at(-0.05, 0.18), 28 * s)
    return canvas


def add_character(char_id: str, src: str | Path, assets_dir: str | Path, head_ratio: float = 0.6,
                  force: bool = False, font_path: str | None = None) -> list[Path]:
    """立ち絵を登録し、表情差分を assets/characters/<id>/ に書き出す。"""
    original = ensure_transparent(Image.open(src))
    out_dir = Path(assets_dir) / "characters" / char_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # 目と口の位置: 手で直した face.json > 添付キャラのプリセット > 自動検出
    face_file = out_dir / "face.json"
    face = None
    if face_file.exists():
        saved = json.loads(face_file.read_text(encoding="utf-8"))
        if saved.get("manual"):
            face = saved
    face = face or find_face(original)
    if face:
        face_file.write_text(json.dumps({"manual": False, **face, "source": Path(src).name}, ensure_ascii=False,
                                        indent=1), encoding="utf-8")
        draw_debug(original, face).save(out_dir / "face_check.png")
    else:
        print(f"[表情] {char_id}: 目と口の位置が見つからないため、漫符だけで表情を付けます")

    base = original
    bbox = base.getbbox() or (0, 0, base.width, base.height)
    base = base.crop(bbox)
    scale = 1.0
    if base.height > 1400:  # 大きすぎる画像は縮小(画質は十分)
        scale = 1400 / base.height
        base = base.resize((int(base.width * scale), 1400), Image.LANCZOS)
    face_local = transform_face(face, (bbox[0], bbox[1]), scale) if face else None
    font_path = font_path or G.find_font(None, assets_dir)
    written = []
    replaceable = force or (out_dir / ".generated").exists() or (out_dir / ".placeholder").exists()
    for expr in EXPRESSIONS:
        p = out_dir / f"{expr}.png"
        if p.exists() and not replaceable:
            continue  # 手描きの表情差分を上書きしない
        make_expression(base, expr, head_ratio, font_path, face_local).save(p)
        written.append(p)
    (out_dir / ".placeholder").unlink(missing_ok=True)
    (out_dir / ".generated").write_text("ytedit add-character で自動生成", encoding="utf-8")
    return written
