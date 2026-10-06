"""キャラクターの立ち絵アニメーション(口パク・目パチ・表情の動き)。

動画の 1 フレームごとに、キャラ 2 人を描いた透明な帯画像(画面下部)を作って ffmpeg に流し込む。
- 口パク: 話しているキャラの声の大きさ(音量)に合わせて、口を 閉じ/半開き/全開 で切り替える
- 目パチ: 2〜5 秒おきにランダムでまばたき(たまに 2 回連続)
- 表情: plan.json の expressions(セリフの感情)に合わせて切り替え、驚き=ジャンプ等の動きも付ける
"""

from __future__ import annotations

import math
import random
import wave
from pathlib import Path

import numpy as np
from PIL import Image

from . import graphics as G
from .assets import AssetLibrary
from .ffmpeg import extract_audio


def mouth_levels(wav_path: Path, fps: float, n_frames: int, speaking: np.ndarray, hold: int = 2) -> np.ndarray:
    """フレームごとの口の開き(0=閉,1=半開き,2=全開)。speaking は話している区間(bool 配列)。"""
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    hop = sr / fps
    rms = np.zeros(n_frames, dtype=np.float32)
    for i in range(n_frames):
        a, b = int(i * hop), int((i + 1) * hop)
        if a >= len(x):
            break
        seg = x[a:b]
        rms[i] = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    voiced = rms[speaking & (rms > 0)]
    ref = float(np.percentile(voiced, 90)) if len(voiced) > 10 else (float(rms.max()) or 1.0)
    r = rms / (ref + 1e-9)
    lv = np.where(r < 0.15, 0, np.where(r < 0.55, 1, 2)).astype(np.int8)
    # 母音が伸びて音量が一定でも口が開きっぱなしにならないよう、音量の山と谷で開き具合を揺らす
    win = max(3, int(fps * 0.25)) | 1
    local = np.convolve(rms, np.ones(win) / win, mode="same")
    dip = rms < local * 0.92
    lv = np.where(dip & (lv > 0), lv - 1, lv).astype(np.int8)
    run = 0
    for i in range(n_frames):  # 0.3 秒以上開きっぱなしなら一瞬閉じる
        run = run + 1 if lv[i] > 0 else 0
        if run >= int(fps * 0.3):
            lv[i] = 0
            run = 0
    lv[~speaking] = 0
    # 細かくパクパクしすぎないよう、最低 hold フレームは同じ口を保つ
    out = lv.copy()
    last, count = out[0] if n_frames else 0, 0
    for i in range(n_frames):
        if lv[i] != last and count < hold:
            out[i] = last
            count += 1
        else:
            if lv[i] != last:
                last = lv[i]
                count = 1
            else:
                count += 1
            out[i] = last
    out[~speaking] = 0
    return out


def blink_frames(n_frames: int, fps: float, seed: str) -> np.ndarray:
    rng = random.Random(seed)
    out = np.zeros(n_frames, dtype=bool)
    t = rng.uniform(0.5, 2.5)
    dur = max(2, round(0.11 * fps))
    while t * fps < n_frames:
        i = int(t * fps)
        out[i:i + dur] = True
        if rng.random() < 0.18:  # 2 回連続のまばたき
            j = i + dur + max(2, round(0.12 * fps))
            out[j:j + dur] = True
        t += rng.uniform(2.0, 5.0)
    return out


def motion_offset(ev: dict, t: float, k: float, bob: bool) -> tuple[int, int]:
    """表情イベントの動き(x, y のずれ)。render.py の式版と同じ動き。"""
    a = t - ev["start"]
    dx = dy = 0.0
    motion = ev.get("motion")
    if motion == "jump":
        dy -= 40 * k * abs(math.sin(math.pi * a / 0.22)) * (a < 0.44)
    elif motion == "shake":
        dx += 9 * k * math.sin(2 * math.pi * 16 * a) * (a < 0.6)
    elif motion == "sink":
        dy += 22 * k * min(1.0, a / 0.4)
    elif motion == "bounce" and ev.get("speaking"):
        dy -= 10 * k * abs(math.sin(2 * math.pi * 4 * t))
    if bob and ev.get("speaking") and motion not in ("jump", "bounce"):
        dy -= 6 * k * abs(math.sin(2 * math.pi * 2.4 * t))
    return int(round(dx)), int(round(dy))


class CharacterStrip:
    """キャラクターの帯レイヤー(W x strip_h, RGBA)をフレームごとに作る。"""

    def __init__(self, plan: dict, cfg: dict, lib: AssetLibrary, work: Path):
        oc = cfg["output"]
        self.W, self.H, self.fps = oc["width"], oc["height"], oc["fps"]
        self.D = float(plan["duration"])
        self.n = int(math.ceil(self.D * self.fps)) + 1
        self.cfg, self.lib, self.work = cfg, lib, work
        ec = cfg["expressions"]
        self.ec = ec
        self.k = self.H / 1080
        self.char_h = int(self.H * ec["height_ratio"])
        self.top_margin = int(50 * self.k)
        self.strip_h = min(self.H, self.char_h + self.top_margin)
        self.events: dict[str, list[dict]] = {}
        for e in plan.get("expressions", []):
            self.events.setdefault(e["char"], []).append(e)
        for evs in self.events.values():
            evs.sort(key=lambda e: e["start"])
        self.chars = list(self.events)
        self._sprites: dict[tuple, np.ndarray] = {}
        self._boxes: dict[str, tuple | None] = {}
        self.lipsync = ec.get("lipsync", True) and plan.get("has_audio")
        self.blink = ec.get("blink", True)
        self.mouth: dict[str, np.ndarray] = {}
        self.blinks: dict[str, np.ndarray] = {}
        self.plan = plan

    # ---------------------------------------------------- タイミング
    def _prepare_timing(self, plan: dict) -> None:
        segs = plan.get("segments", [])
        wav = None
        if self.lipsync:
            wav = self.work / "lipsync.wav"
            if not wav.exists():
                extract_audio(plan["source"], wav)
        for c in self.chars:
            speaking = np.zeros(self.n, dtype=bool)
            for s in segs:
                if s.get("speaker") == c:
                    speaking[int(s["start"] * self.fps):int(math.ceil(s["end"] * self.fps))] = True
            self.mouth[c] = mouth_levels(wav, self.fps, self.n, speaking) if wav else np.zeros(self.n, dtype=np.int8)
            self.blinks[c] = blink_frames(self.n, self.fps, c) if self.blink else np.zeros(self.n, dtype=bool)

    # ---------------------------------------------------- 画像
    def _box(self, char: str):
        if char not in self._boxes:
            d = self.lib.root / "characters" / char
            files = sorted(p for p in d.glob("*.png")) if d.exists() else []
            self._boxes[char] = G.union_bbox(files) if files else None
        return self._boxes[char]

    def sprite(self, char: str, expr: str, mouth: int, blink: bool) -> np.ndarray:
        key = (char, expr, mouth, blink)
        if key not in self._sprites:
            path = self.lib.sprite(char, expr, mouth, blink) or self.lib.character(char, "normal")
            img = Image.open(path).convert("RGBA")
            box = self._box(char)
            if box and img.size == Image.open(self.lib.character(char, "normal")).size:
                img = img.crop(box)
            elif img.getbbox():
                img = img.crop(img.getbbox())
            w = max(1, int(img.width * self.char_h / img.height))
            self._sprites[key] = np.asarray(img.resize((w, self.char_h), Image.LANCZOS))
        return self._sprites[key]

    def max_width(self) -> int:
        return max((self.sprite(c, "normal", 0, False).shape[1] for c in self.chars), default=0)

    # ---------------------------------------------------- フレーム
    def _event_at(self, char: str, t: float, idx: dict) -> dict | None:
        evs = self.events[char]
        i = idx.get(char, 0)
        while i + 1 < len(evs) and evs[i + 1]["start"] <= t:
            i += 1
        idx[char] = i
        ev = evs[i]
        return ev if ev["start"] <= t < ev["end"] + 1e-6 else None

    def frames(self):
        """RGBA の生フレーム(bytes)を順に返す。"""
        if not self.mouth:
            self._prepare_timing(self.plan)
        canvas = np.zeros((self.strip_h, self.W, 4), dtype=np.uint8)
        idx: dict[str, int] = {}
        last_key = None
        sides = {c: self.cfg["characters"].get(c, {}).get("side", "left") for c in self.chars}
        for f in range(self.n):
            t = f / self.fps
            parts = []
            for c in self.chars:
                ev = self._event_at(c, t, idx)
                if ev is None:
                    continue
                m = int(self.mouth[c][f]) if ev.get("speaking") else 0
                b = bool(self.blinks[c][f])
                dx, dy = motion_offset(ev, t, self.k, self.ec["bob"]) if self.ec.get("motion", True) else (0, 0)
                parts.append((c, ev["expression"], m, b, dx, dy))
            key = tuple(parts)
            if key != last_key:
                canvas[:] = 0
                for c, expr, m, b, dx, dy in parts:
                    spr = self.sprite(c, expr, m, b)
                    h, w = spr.shape[:2]
                    mx = int(self.ec["margin_x"])
                    x = mx if sides[c] == "left" else self.W - w - mx
                    y = self.strip_h - h + int(10 * self.k)
                    _blit(canvas, spr, x + dx, y + dy)
                last_key = key
            yield canvas.tobytes()


def _blit(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
    """はみ出しを切り取りつつ src を dst に重ねる(アルファ合成)。"""
    H, W = dst.shape[:2]
    h, w = src.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    s = src[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    d = dst[y0:y1, x0:x1].astype(np.float32)
    sa = s[..., 3:4] / 255.0
    da = d[..., 3:4] / 255.0
    oa = sa + da * (1 - sa)
    rgb = (s[..., :3] * sa + d[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6)
    dst[y0:y1, x0:x1, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    dst[y0:y1, x0:x1, 3:4] = np.clip(oa * 255, 0, 255).astype(np.uint8)
