"""お試し用の仮素材を自動生成する(`ytedit init-assets`)。

本番では assets/ 以下を、実際の立ち絵・BGM・効果音・素材画像に差し替えてください。
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import graphics as G

SR = 44100
EXPRESSIONS = ["normal", "smile", "laugh", "surprised", "angry", "sad", "thinking", "doya", "jito"]


# ------------------------------------------------------------------ キャラクター
def draw_character(expr: str, hair: tuple, accent: tuple, size=(600, 900)) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, line = (255, 228, 210, 255), (60, 40, 40, 255)
    # 体・服
    d.rounded_rectangle((150, 520, 450, 900), radius=90, fill=accent + (255,))
    d.polygon([(300, 540), (250, 600), (350, 600)], fill=(255, 255, 255, 255))
    # 後ろ髪
    d.ellipse((100, 60, 500, 560), fill=hair + (255,))
    d.rectangle((100, 300, 500, 620), fill=hair + (255,))
    # 顔
    d.ellipse((150, 140, 450, 480), fill=skin)
    # 前髪
    d.pieslice((120, 70, 480, 380), 180, 360, fill=hair + (255,))
    for x in (170, 240, 310, 380):
        d.polygon([(x - 40, 220), (x + 40, 220), (x, 280)], fill=hair + (255,))
    # 目
    ey, lx, rx = 320, 235, 365
    if expr in ("smile", "laugh", "doya"):
        for x in (lx, rx):
            d.arc((x - 30, ey - 20, x + 30, ey + 25), 200, 340, fill=line, width=8)
    elif expr == "jito":
        for x in (lx, rx):
            d.line((x - 30, ey, x + 30, ey), fill=line, width=8)
            d.ellipse((x - 10, ey, x + 10, ey + 18), fill=line)
    elif expr == "surprised":
        for x in (lx, rx):
            d.ellipse((x - 26, ey - 32, x + 26, ey + 32), fill=(255, 255, 255, 255), outline=line, width=6)
            d.ellipse((x - 9, ey - 9, x + 9, ey + 9), fill=line)
    else:
        for x in (lx, rx):
            d.ellipse((x - 22, ey - 30, x + 22, ey + 30), fill=line)
            d.ellipse((x - 10, ey - 22, x + 4, ey - 8), fill=(255, 255, 255, 255))
    # 眉
    if expr == "angry":
        d.line((lx - 35, ey - 70, lx + 25, ey - 45), fill=line, width=9)
        d.line((rx + 35, ey - 70, rx - 25, ey - 45), fill=line, width=9)
    elif expr in ("sad", "thinking"):
        d.line((lx - 30, ey - 45, lx + 25, ey - 65), fill=line, width=7)
        d.line((rx + 30, ey - 45, rx - 25, ey - 65), fill=line, width=7)
    # 頬
    d.ellipse((190, 370, 240, 395), fill=(255, 170, 170, 160))
    d.ellipse((360, 370, 410, 395), fill=(255, 170, 170, 160))
    # 口
    my = 420
    if expr in ("laugh", "surprised"):
        d.ellipse((270, my - 20, 330, my + 35), fill=(180, 40, 60, 255), outline=line, width=4)
    elif expr in ("smile", "doya"):
        d.arc((255, my - 35, 345, my + 20), 20, 160, fill=line, width=7)
    elif expr in ("sad", "angry", "jito"):
        d.arc((265, my, 335, my + 40), 200, 340, fill=line, width=7)
    elif expr == "thinking":
        d.line((280, my + 5, 325, my - 2), fill=line, width=7)
        d.ellipse((400, 250, 470, 320), outline=(120, 120, 120, 255), width=6)
    else:
        d.line((275, my, 325, my), fill=line, width=7)
    if expr == "doya":
        d.polygon([(470, 180), (500, 120), (520, 190)], fill=(255, 215, 0, 255))
    return img


# ------------------------------------------------------------------ 音
def _write_wav(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    x = np.clip(x, -1, 1)
    data = (x * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def _env(n: int, attack=0.01, release=0.2) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(1, t / attack) * np.exp(-t / release)


def _tone(freq, dur, release=0.2, kind="sine"):
    t = np.arange(int(SR * dur)) / SR
    f = freq(t) if callable(freq) else freq
    phase = 2 * np.pi * np.cumsum(np.broadcast_to(f, t.shape)) / SR
    wave_ = np.sin(phase) if kind == "sine" else np.sign(np.sin(phase)) * 0.5
    return wave_ * _env(len(t), release=release)


def make_se(root: Path) -> None:
    rng = np.random.default_rng(0)
    se = {
        "surprise": _tone(lambda t: 500 + 1400 * t / 0.35, 0.35, 0.3) * 0.7,
        "point": np.concatenate([_tone(1318, 0.12, 0.1), _tone(1760, 0.5, 0.25)]) * 0.6,
        "question": np.concatenate([_tone(660, 0.15, 0.1), _tone(990, 0.3, 0.15)]) * 0.6,
        "shock": (_tone(lambda t: 160 - 100 * t, 0.5, 0.25, "square") + rng.normal(0, 0.2, int(SR * 0.5)) * _env(int(SR * 0.5), release=0.08)) * 0.7,
        "laugh": np.concatenate([_tone(880 + 80 * i, 0.09, 0.05) for i in range(6)]) * 0.5,
        "transition": rng.normal(0, 0.4, int(SR * 0.6)) * np.sin(np.linspace(0, np.pi, int(SR * 0.6))) ** 2,
        "cutin": np.concatenate([rng.normal(0, 0.35, int(SR * 0.25)) * np.linspace(0, 1, int(SR * 0.25)),
                                 _tone(220, 0.4, 0.15, "square") * 0.8]),
        "popup": np.concatenate([_tone(988, 0.08, 0.06), _tone(1319, 0.25, 0.12)]) * 0.6,
    }
    for kind, x in se.items():
        _write_wav(root / "se" / kind / f"sample_{kind}.wav", x)


def make_bgm(root: Path, seconds: float = 16.0) -> None:
    moods = {
        "calm": ([261.6, 329.6, 392.0], [220.0, 261.6, 329.6], 72),
        "bright": ([293.7, 370.0, 440.0], [329.6, 415.3, 493.9], 110),
        "tense": ([220.0, 261.6, 311.1], [207.7, 246.9, 293.7], 96),
    }
    n = int(SR * seconds)
    for mood, (c1, c2, bpm) in moods.items():
        x = np.zeros(n)
        beat = 60 / bpm
        t0 = 0.0
        i = 0
        while t0 < seconds:
            chord = c1 if (i // 4) % 2 == 0 else c2
            s = int(t0 * SR)
            seg = sum(_tone(f, beat * 1.5, beat * 0.8) for f in chord) / len(chord)
            e = min(n, s + len(seg))
            x[s:e] += seg[: e - s] * 0.35
            t0 += beat
            i += 1
        _write_wav(root / "bgm" / mood / f"sample_{mood}.wav", x)


# ------------------------------------------------------------------ 画像
def make_images(root: Path, font_path: str | None) -> None:
    def card(text, c1, c2, size=(1280, 720)):
        img = Image.new("RGB", size, c1)
        d = ImageDraw.Draw(img)
        for y in range(size[1]):
            k = y / size[1]
            d.line((0, y, size[0], y), fill=tuple(int(a * (1 - k) + b * k) for a, b in zip(c1, c2)))
        f = G.font(font_path, 110)
        d.text((size[0] // 2, size[1] // 2), text, font=f, fill=(255, 255, 255), anchor="mm",
               stroke_width=6, stroke_fill=(0, 0, 0))
        return img

    mats = {"経済_株価_グラフ": ((20, 90, 60), (10, 40, 30)), "政治_国会": ((80, 30, 30), (30, 10, 10)),
            "物価_値上げ_円安": ((140, 90, 20), (60, 30, 10)), "AI_人工知能_テクノロジー": ((30, 50, 120), (10, 10, 40)),
            "天気_台風_災害": ((60, 90, 130), (20, 30, 60)), "スマホ_SNS_ネット": ((90, 40, 120), (30, 10, 50))}
    for name, (a, b) in mats.items():
        (root / "materials").mkdir(parents=True, exist_ok=True)
        card(name.split("_")[0], a, b).save(root / "materials" / f"{name}.png")
    bgs = {"default_ニュース": ((230, 235, 250), (180, 190, 230)), "経済_ビジネス": ((220, 240, 225), (150, 200, 170)),
           "政治_社会": ((245, 230, 225), (210, 170, 160))}
    for name, (a, b) in bgs.items():
        (root / "backgrounds").mkdir(parents=True, exist_ok=True)
        img = card("", a, b, (1920, 1080))
        d = ImageDraw.Draw(img)
        for x in range(0, 1920, 80):
            d.line((x, 0, x, 1080), fill=tuple(max(0, c - 12) for c in a), width=2)
        img.save(root / "backgrounds" / f"{name}.png")


def init_assets(root: str | Path, force: bool = False) -> Path:
    root = Path(root)
    font_path = G.find_font(None, root)
    chars = {"sumire": ((120, 80, 200), (230, 220, 255)), "aoi": ((40, 120, 210), (220, 240, 255))}
    for cid, (hair, accent) in chars.items():
        d = root / "characters" / cid
        if d.exists() and not force and not (d / ".placeholder").exists():
            continue  # 本番の立ち絵が登録済み
        d.mkdir(parents=True, exist_ok=True)
        (d / ".placeholder").write_text("仮素材 (ytedit add-character で置き換え)", encoding="utf-8")
        for expr in EXPRESSIONS:
            p = d / f"{expr}.png"
            if force or not p.exists():
                draw_character(expr, hair, accent).save(p)
    if force or not (root / "se").exists():
        make_se(root)
    if force or not (root / "bgm").exists():
        make_bgm(root)
    if force or not (root / "materials").exists():
        make_images(root, font_path)
    return root
