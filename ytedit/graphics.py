"""Pillow による画像パーツの生成(背景・立ち絵・丸ワイプ・素材カード・カットイン帯・登録バナー・サムネ)。

ffmpeg 側では「完成サイズの PNG を指定時刻に重ねるだけ」にしておくと、処理が速く安定する。
"""

from __future__ import annotations

import glob
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/YuGothB.ttc", "C:/Windows/Fonts/meiryob.ttc", "C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/msgothic.ttc",
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc", "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def find_font(configured: str | None = None, assets_dir: str | Path | None = None) -> str | None:
    if configured and Path(configured).exists():
        return str(configured)
    if assets_dir:
        own = sorted(glob.glob(os.path.join(str(assets_dir), "fonts", "*.[ot]t[fc]")))
        if own:
            return own[0]
    for c in FONT_CANDIDATES:
        if Path(c).exists():
            return c
    hits = glob.glob("/usr/share/fonts/**/*CJK*", recursive=True) + glob.glob("/usr/share/fonts/**/*ipa*", recursive=True)
    return hits[0] if hits else None


@lru_cache(maxsize=64)
def font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img, (w, h), Image.LANCZOS)


def save(img: Image.Image, out: str | Path) -> Path:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return Path(out)


def prepare_background(src: str | Path, w: int, h: int, out: str | Path, blur: float = 0, darken: float = 0) -> Path:
    img = cover(Image.open(src).convert("RGB"), w, h)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur * h / 1080))
    if darken:
        img = Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), darken)
    return save(img, out)


def union_bbox(paths: list[str | Path]) -> tuple[int, int, int, int] | None:
    """同じサイズの表情差分画像すべてを覆う範囲(表情が変わっても立ち位置・大きさがずれないように)。"""
    boxes, size = [], None
    for p in paths:
        img = Image.open(p)
        if size is None:
            size = img.size
        elif img.size != size:
            return None
        b = img.convert("RGBA").getbbox()
        if b:
            boxes.append(b)
    if not boxes:
        return None
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def prepare_character(src: str | Path, target_h: int, out: str | Path, mirror: bool = False,
                      box: tuple[int, int, int, int] | None = None) -> Path:
    img = Image.open(src).convert("RGBA")
    bbox = box or img.getbbox()
    if bbox:
        img = img.crop(bbox)
    scale = target_h / img.height
    img = img.resize((max(1, int(img.width * scale)), target_h), Image.LANCZOS)
    if mirror:
        img = ImageOps.mirror(img)
    return save(img, out)


def _head_crop(img: Image.Image) -> Image.Image:
    """立ち絵の上部(頭)を正方形で切り抜く。"""
    img = img.convert("RGBA")
    bbox = img.getbbox() or (0, 0, img.width, img.height)
    bw = bbox[2] - bbox[0]
    side = int(min(bw * 0.8, (bbox[3] - bbox[1]) * 0.5))
    cx = (bbox[0] + bbox[2]) // 2
    left = max(0, cx - side // 2)
    return img.crop((left, bbox[1], left + side, bbox[1] + side))


def make_wipe(char_src: str | Path, face_src: str | Path | None, diameter: int, border: int,
              color: str, out: str | Path, bg: str = "#FFFFFF") -> Path:
    """丸顔ワイプ(枠付き)。"""
    face = Image.open(face_src).convert("RGBA") if face_src else _head_crop(Image.open(char_src))
    inner = diameter - border * 2
    face = ImageOps.fit(face, (inner, inner), Image.LANCZOS, centering=(0.5, 0.35))
    ss = 4  # アンチエイリアス用に拡大して描く
    canvas = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    ring = Image.new("L", (diameter * ss, diameter * ss), 0)
    ImageDraw.Draw(ring).ellipse((0, 0, diameter * ss - 1, diameter * ss - 1), fill=255)
    ring = ring.resize((diameter, diameter), Image.LANCZOS)
    canvas.paste(Image.new("RGBA", (diameter, diameter), rgb(color) + (255,)), (0, 0), ring)
    mask = Image.new("L", (inner * ss, inner * ss), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, inner * ss - 1, inner * ss - 1), fill=255)
    mask = mask.resize((inner, inner), Image.LANCZOS)
    back = Image.new("RGBA", (inner, inner), rgb(bg) + (255,))
    back.alpha_composite(face)
    canvas.paste(back, (border, border), mask)
    return save(canvas, out)


def make_wipe_ring(diameter: int, border: int, color: str, out: str | Path) -> Path:
    """顔出し動画用: 枠だけの画像。"""
    ss = 4
    big = Image.new("RGBA", (diameter * ss, diameter * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.ellipse((0, 0, diameter * ss - 1, diameter * ss - 1), outline=rgb(color) + (255,), width=border * ss)
    return save(big.resize((diameter, diameter), Image.LANCZOS), out)


def _shadow(img: Image.Image, radius: int = 12, offset: int = 8) -> Image.Image:
    pad = radius * 2 + offset
    canvas = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 150))
    sh.putalpha(Image.eval(img.getchannel("A"), lambda a: a * 150 // 255))
    canvas.alpha_composite(sh, (pad + offset, pad + offset))
    canvas = canvas.filter(ImageFilter.GaussianBlur(radius))
    canvas.alpha_composite(img, (pad, pad))
    return canvas


def make_material_card(src: str | Path, box_w: int, box_h: int, out: str | Path, border: int = 10) -> Path:
    """素材画像を枠内に収め、白フチ・角丸・影を付ける。"""
    img = Image.open(src).convert("RGBA")
    img.thumbnail((box_w - border * 2 - 40, box_h - border * 2 - 40), Image.LANCZOS)
    card = Image.new("RGBA", (img.width + border * 2, img.height + border * 2), (255, 255, 255, 255))
    card.alpha_composite(img, (border, border))
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, card.width - 1, card.height - 1), radius=18, fill=255)
    card.putalpha(mask)
    return save(_shadow(card), out)


def _outlined(draw: ImageDraw.ImageDraw, xy, text: str, fnt, fill, stroke, width: int, anchor="la"):
    draw.text(xy, text, font=fnt, fill=fill, stroke_width=width, stroke_fill=stroke, anchor=anchor)


def _fit_font(text: str, font_path: str | None, max_w: int, start: int, min_size: int = 24):
    size = start
    while size > min_size:
        f = font(font_path, size)
        if f.getbbox(text, stroke_width=max(2, size // 12))[2] <= max_w:
            return f
        size -= 4
    return font(font_path, min_size)


def make_cutin(char_src: str | Path, text: str, color: str, width: int, band_h: int,
               font_path: str | None, out: str | Path, char_on_left: bool = True) -> Path:
    """斜めストライプの帯 + キャラ + 大きな文字のカットイン画像。"""
    h = int(band_h * 1.25)
    canvas = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    band = Image.new("RGBA", (width, band_h), rgb(color) + (235,))
    d = ImageDraw.Draw(band)
    light = tuple(min(255, c + 45) for c in rgb(color)) + (235,)
    for x in range(-band_h, width, 70):
        d.polygon([(x, band_h), (x + 35, band_h), (x + 35 + band_h, 0), (x + band_h, 0)], fill=light)
    d.rectangle((0, 0, width, 10), fill=(255, 255, 255, 255))
    d.rectangle((0, band_h - 10, width, band_h), fill=(255, 255, 255, 255))
    canvas.alpha_composite(band, (0, (h - band_h) // 2))

    char = Image.open(char_src).convert("RGBA")
    bbox = char.getbbox()
    if bbox:
        char = char.crop(bbox)
    ch = h
    k = 1 / 0.72  # 上から 72% (SDキャラの頭〜肩) を帯に収める
    char = char.resize((int(char.width * ch * k / char.height), int(ch * k)), Image.LANCZOS).crop(
        (0, 0, int(char.width * ch * k / char.height), ch))
    # 下端をフェードさせて、切り抜きの境目を目立たなくする
    fade = Image.linear_gradient("L").resize((char.width, int(ch * 0.12)))
    fade = Image.eval(fade, lambda v: 255 - v)
    alpha = char.getchannel("A")
    bottom = alpha.crop((0, ch - fade.height, char.width, ch))
    alpha.paste(Image.fromarray((np.asarray(bottom, dtype=np.uint16) * np.asarray(fade, dtype=np.uint16) // 255)
                                .astype(np.uint8)), (0, ch - fade.height))
    char.putalpha(alpha)
    cx = int(width * 0.05) if char_on_left else width - char.width - int(width * 0.05)
    canvas.alpha_composite(char, (cx, 0))

    text_area_x = cx + char.width + 40 if char_on_left else 60
    text_area_w = (width - text_area_x - 60) if char_on_left else (cx - 100)
    f = _fit_font(text, font_path, text_area_w, int(band_h * 0.62))
    td = ImageDraw.Draw(canvas)
    _outlined(td, (text_area_x + text_area_w // 2, h // 2), text, f, (255, 255, 255), (30, 30, 30),
              max(4, f.size // 10), anchor="mm")
    return save(canvas, out)


def make_popup(width: int, height: int, font_path: str | None, out: str | Path) -> Path:
    """チャンネル登録・高評価・コメント・ハイプの呼びかけバナー。"""
    items = [("チャンネル登録", "#FF0033"), ("高評価", "#1E88E5"), ("コメント", "#43A047"), ("ハイプ", "#FB8C00")]
    k = height / 1080
    f = font(font_path, max(12, int(44 * k)))
    pad, gap = int(34 * k), int(22 * k)
    widths = [int(f.getlength(t)) + pad * 2 for t, _ in items]
    total = sum(widths) + gap * (len(items) - 1)
    h = int(100 * k)
    canvas = Image.new("RGBA", (total + 40, h + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    x = 20
    for (label, c), w in zip(items, widths):
        d.rounded_rectangle((x, 20, x + w, 20 + h), radius=h // 2, fill=rgb(c) + (255,), outline=(255, 255, 255, 255),
                            width=max(2, int(5 * k)))
        _outlined(d, (x + w // 2, 20 + h // 2), label, f, (255, 255, 255), (0, 0, 0), 3, anchor="mm")
        x += w + gap
    scale = min(1.0, (width * 0.9) / canvas.width)
    if scale < 1.0:
        canvas = canvas.resize((int(canvas.width * scale), int(canvas.height * scale)), Image.LANCZOS)
    return save(_shadow(canvas, radius=8, offset=5), out)


def make_thumbnail(frame: str | Path | None, char_src: str | Path | None, text: str, color: str,
                   font_path: str | None, out: str | Path, size=(1280, 720)) -> Path:
    w, h = size
    base = cover(Image.open(frame).convert("RGB"), w, h) if frame else Image.new("RGB", size, (30, 30, 50))
    base = base.filter(ImageFilter.GaussianBlur(2)).convert("RGBA")
    shade = Image.new("RGBA", size, (0, 0, 0, 90))
    base.alpha_composite(shade)
    if char_src:
        ch = Image.open(char_src).convert("RGBA")
        bbox = ch.getbbox()
        if bbox:
            ch = ch.crop(bbox)
        ch = ch.resize((int(ch.width * h * 1.05 / ch.height), int(h * 1.05)), Image.LANCZOS)
        base.alpha_composite(ch, (w - ch.width + 20, h - ch.height + 40))
    d = ImageDraw.Draw(base)
    lines = [text[i:i + 7] for i in range(0, len(text), 7)][:3] or [""]
    f = _fit_font(max(lines, key=len), font_path, int(w * 0.62), 170, 60)
    y = h // 2 - (len(lines) * f.size * 1.1) / 2
    for line in lines:
        _outlined(d, (50, y), line, f, (255, 240, 60), rgb(color), max(8, f.size // 9))
        y += f.size * 1.1
    return save(base.convert("RGB"), out)
