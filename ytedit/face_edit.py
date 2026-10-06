"""立ち絵の顔(目・口・眉)を描き換えて表情を作る。

元の絵の目や口を肌の色で消してから、表情に合わせた目(にっこり・半目・ジト目・怒り目)、
口(開いた口・への字・ニヤリ)、眉(怒り眉・困り眉・驚き眉)、涙や頬の赤みを描き足す。
前髪など髪の毛の部分は消さないので、前髪が目にかかっている絵でも自然に見える。
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SS = 3  # 線をなめらかにするための拡大描画倍率


class FaceEditor:
    def __init__(self, img: Image.Image, face: dict):
        self.img = img.convert("RGBA")
        self.face = face
        self.L, self.R = sorted(face["eyes"], key=lambda e: e["x"])
        self.m = face["mouth"]
        self.d = self.R["x"] - self.L["x"]  # 両目の間隔(線の太さなどの基準)
        a = np.asarray(self.img).astype(int)
        self.arr = a
        self.skin = self._skin_color()
        self.hair = np.array(face.get("hair") or self._hair_color())
        self.line = self._line_color()
        self.lw = max(3, int(self.d * 0.028))

    # ---------------------------------------------------- 色の取得
    def _median(self, x0, y0, x1, y1, cond) -> np.ndarray | None:
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        sub = self.arr[y0:int(y1), x0:int(x1)].reshape(-1, 4)
        sub = sub[(sub[:, 3] > 200)]
        sel = sub[cond(sub[:, :3])] if len(sub) else sub
        return np.median(sel[:, :3], axis=0) if len(sel) > 10 else None

    def _skin_color(self) -> np.ndarray:
        cy = (max(self.L["y"] + self.L["h"] / 2, self.R["y"] + self.R["h"] / 2) + self.m["y"]) / 2
        cx = self.m["x"]
        c = self._median(cx - self.d * 0.12, cy - self.d * 0.06, cx + self.d * 0.12, cy + self.d * 0.06,
                         lambda c: (c[:, 0] > 200) & (c[:, 0] - c[:, 2] > 15))
        return c if c is not None else np.array([250, 228, 210])

    def _hair_color(self) -> np.ndarray:
        e = self.L
        c = self._median(e["x"] - e["w"] / 2, e["y"] - e["h"] * 1.3, self.R["x"] + self.R["w"] / 2, e["y"] - e["h"] * 0.8,
                         lambda c: np.abs(c - self.skin).sum(1) > 90)
        return c if c is not None else np.array([60, 50, 50])

    def _line_color(self) -> tuple[int, int, int, int]:
        e = self.L
        sub = self.arr[int(e["y"] - e["h"] / 2):int(e["y"] - e["h"] / 4), int(e["x"] - e["w"] / 3):int(e["x"] + e["w"] / 3)]
        sub = sub[sub[..., 3] > 200][:, :3] if sub.size else np.zeros((0, 3))
        if len(sub) > 10:
            lum = sub.mean(1)
            dark = sub[lum <= np.percentile(lum, 10)]
            c = np.median(dark, axis=0) * 0.9
        else:
            c = np.array([60, 40, 45])
        return int(c[0]), int(c[1]), int(c[2]), 255

    # ---------------------------------------------------- 消す
    def _paint_skin(self, mask: Image.Image, core: Image.Image | None = None):
        """mask の範囲を肌色で塗る。core(目の中心部)以外では髪の毛の画素を残す(前髪を消さない)。"""
        m = np.asarray(mask.filter(ImageFilter.GaussianBlur(max(1, self.d * 0.006)))).astype(float) / 255
        rgb = self.arr[..., :3].astype(float)
        if core is not None:
            hair_like = np.sqrt(((rgb - self.hair) ** 2).sum(-1)) < 45
            inner = np.asarray(core) > 0
            m = m * (~(hair_like & ~inner))
        m = m * (self.arr[..., 3] > 0)
        out = rgb * (1 - m[..., None]) + self.skin[None, None, :] * m[..., None]
        self.arr = np.concatenate([out, self.arr[..., 3:4]], axis=-1).astype(int)

    def _mask(self) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        m = Image.new("L", self.img.size, 0)
        return m, ImageDraw.Draw(m)

    def erase_eye(self, e: dict, keep_from: float = 1.0):
        """目を消す。keep_from<1 なら上側だけ消す(半目用: 0=全部消す … 1=消さない ではなく、消す割合)。"""
        m, d = self._mask()
        c, dc = self._mask()
        k, kc = 1.28, 0.9
        # まつ毛が上にはみ出していることが多いので、上側を広めに消す
        box = (e["x"] - e["w"] * k / 2, e["y"] - e["h"] * 0.66, e["x"] + e["w"] * k / 2, e["y"] + e["h"] * 0.6)
        d.ellipse(box, fill=255)
        dc.ellipse((e["x"] - e["w"] * kc / 2, e["y"] - e["h"] * kc / 2, e["x"] + e["w"] * kc / 2, e["y"] + e["h"] * kc / 2),
                   fill=255)
        if keep_from < 1.0:
            cut = e["y"] - e["h"] * 0.54 + e["h"] * 1.08 * keep_from
            for dd in (d, dc):
                dd.rectangle((box[0] - 5, cut, box[2] + 5, box[3] + 5), fill=0)
        self._paint_skin(m, c)

    def erase_mouth(self):
        m, d = self._mask()
        w = self.m["w"] * 1.35
        d.ellipse((self.m["x"] - w / 2, self.m["y"] - w * 0.25, self.m["x"] + w / 2, self.m["y"] + w * 0.28), fill=255)
        self._paint_skin(m)

    # ---------------------------------------------------- 描く
    def _overlay(self):
        """描き込み用のレイヤー(拡大サイズ)を返す。"""
        layer = Image.new("RGBA", (self.img.width * SS, self.img.height * SS), (0, 0, 0, 0))
        return layer, ImageDraw.Draw(layer)

    def _commit(self, layer: Image.Image):
        base = Image.fromarray(np.clip(self.arr, 0, 255).astype(np.uint8), "RGBA")
        small = layer.resize(base.size, Image.LANCZOS)
        base.alpha_composite(small)
        self.arr = np.asarray(base).astype(int)

    @staticmethod
    def _s(*v):
        return [x * SS for x in v]

    def happy_eyes(self, dr):
        """にっこり目 (^ ^)"""
        for e in (self.L, self.R):
            w, h = e["w"] * 0.8, e["h"] * 0.55
            dr.arc(self._s(e["x"] - w / 2, e["y"] - h / 2, e["x"] + w / 2, e["y"] + h * 0.9), 200, 340,
                   fill=self.line, width=self.lw * SS)

    def lid_line(self, dr, frac: float, tilt: float = 0.0):
        """半目の上まぶたの線。tilt>0 で目尻が上がる(怒り目)、<0 で下がる。"""
        for e, sgn in ((self.L, 1), (self.R, -1)):
            k = 1.08
            top = e["y"] - e["h"] * k / 2
            y = top + e["h"] * k * frac
            x0, x1 = e["x"] - e["w"] * 0.5, e["x"] + e["w"] * 0.5
            t = tilt * e["h"] * sgn
            dr.line(self._s(x0, y - t, x1, y + t), fill=self.line, width=int(self.lw * 1.4) * SS)

    def brows(self, dr, kind: str):
        color = tuple(int(v) for v in np.clip(self.hair * 0.55, 0, 255)) + (255,)
        for e, sgn in ((self.L, 1), (self.R, -1)):
            y = e["y"] - e["h"] * 0.72
            x_out, x_in = e["x"] - sgn * e["w"] * 0.42, e["x"] + sgn * e["w"] * 0.38
            if kind == "angry":  # 内側が下がる
                pts = (x_out, y - e["h"] * 0.12, x_in, y + e["h"] * 0.12)
            elif kind == "sad":  # 内側が上がる(ハの字)
                pts = (x_out, y + e["h"] * 0.1, x_in, y - e["h"] * 0.12)
            elif kind == "think":  # 片方だけ上がる
                if sgn > 0:
                    continue
                pts = (x_out, y - e["h"] * 0.2, x_in, y - e["h"] * 0.05)
            else:  # surprised: 高く上がる
                pts = (x_out, y - e["h"] * 0.12, x_in, y - e["h"] * 0.18)
            dr.line(self._s(*pts), fill=color, width=int(self.lw * 2.0) * SS)

    def mouth(self, dr, kind: str):
        x, y, w = self.m["x"], self.m["y"], self.m["w"]
        inside, tongue = (150, 50, 65, 255), (235, 120, 130, 255)
        lw = self.lw * SS
        if kind == "open":  # 驚き: 小さく丸く開いた口
            r = w * 0.32
            dr.ellipse(self._s(x - r * 0.8, y - r * 0.6, x + r * 0.8, y + r * 1.0), fill=inside, outline=self.line, width=lw)
        elif kind == "laugh":  # 大笑い: D 型に大きく開いた口
            dr.chord(self._s(x - w * 0.5, y - w * 0.45, x + w * 0.5, y + w * 0.55), 0, 180, fill=inside,
                     outline=self.line, width=lw)
            dr.chord(self._s(x - w * 0.28, y + w * 0.05, x + w * 0.28, y + w * 0.5), 0, 180, fill=tongue)
        elif kind == "frown":  # への字
            dr.arc(self._s(x - w * 0.4, y - w * 0.05, x + w * 0.4, y + w * 0.45), 200, 340, fill=self.line, width=lw)
        elif kind == "flat":  # 一文字
            dr.line(self._s(x - w * 0.3, y, x + w * 0.3, y), fill=self.line, width=lw)
        elif kind == "wavy":  # 考え中: くの字
            dr.line(self._s(x - w * 0.3, y + w * 0.04, x - w * 0.05, y - w * 0.06, x + w * 0.25, y + w * 0.05),
                    fill=self.line, width=lw, joint="curve")
        elif kind == "smirk":  # ニヤリ(片側が上がる)
            dr.arc(self._s(x - w * 0.55, y - w * 0.55, x + w * 0.45, y + w * 0.15), 25, 120, fill=self.line, width=lw)
        elif kind == "grin":  # 怒り: 歯を見せた口
            dr.rounded_rectangle(self._s(x - w * 0.42, y - w * 0.12, x + w * 0.42, y + w * 0.2), radius=w * 0.1 * SS,
                                 fill=(255, 255, 255, 255), outline=self.line, width=lw)
            dr.line(self._s(x - w * 0.4, y + w * 0.04, x + w * 0.4, y + w * 0.04), fill=self.line, width=max(2, lw // 2))

    def tears(self, dr):
        for e, sgn in ((self.L, -1), (self.R, 1)):
            x = e["x"] + sgn * e["w"] * 0.3
            y = e["y"] + e["h"] * 0.5
            r = self.d * 0.035
            dr.polygon(self._s(x, y - r * 1.6, x - r, y, x + r, y), fill=(140, 200, 255, 230))
            dr.ellipse(self._s(x - r, y - r, x + r, y + r), fill=(140, 200, 255, 230), outline=(60, 120, 200, 255),
                       width=max(2, self.lw // 2) * SS)

    def blush(self, dr, strength: int = 110):
        for e in (self.L, self.R):
            x, y = e["x"], e["y"] + e["h"] * 0.72
            w, h = e["w"] * 0.5, e["h"] * 0.16
            dr.ellipse(self._s(x - w / 2, y - h / 2, x + w / 2, y + h / 2), fill=(255, 120, 140, strength))

    # ---------------------------------------------------- 表情
    def apply(self, expr: str) -> Image.Image:
        recipe = RECIPES.get(expr)
        if recipe:
            recipe(self)
        return Image.fromarray(np.clip(self.arr, 0, 255).astype(np.uint8), "RGBA")


def _smile(f: FaceEditor):
    for e in (f.L, f.R):
        f.erase_eye(e)
    layer, dr = f._overlay()
    f.happy_eyes(dr)
    f.blush(dr, 90)
    f._commit(layer)


def _laugh(f: FaceEditor):
    for e in (f.L, f.R):
        f.erase_eye(e)
    f.erase_mouth()
    layer, dr = f._overlay()
    f.happy_eyes(dr)
    f.mouth(dr, "laugh")
    f.blush(dr, 120)
    f._commit(layer)


def _surprised(f: FaceEditor):
    f.erase_mouth()
    layer, dr = f._overlay()
    f.brows(dr, "surprised")
    f.mouth(dr, "open")
    f._commit(layer)


def _angry(f: FaceEditor):
    for e in (f.L, f.R):
        f.erase_eye(e, keep_from=0.3)
    f.erase_mouth()
    layer, dr = f._overlay()
    f.lid_line(dr, 0.3, tilt=0.12)
    f.brows(dr, "angry")
    f.mouth(dr, "grin")
    f._commit(layer)


def _sad(f: FaceEditor):
    for e in (f.L, f.R):
        f.erase_eye(e, keep_from=0.2)
    f.erase_mouth()
    layer, dr = f._overlay()
    f.lid_line(dr, 0.2, tilt=-0.1)
    f.brows(dr, "sad")
    f.mouth(dr, "frown")
    f.tears(dr)
    f._commit(layer)


def _thinking(f: FaceEditor):
    f.erase_mouth()
    layer, dr = f._overlay()
    f.brows(dr, "think")
    f.mouth(dr, "wavy")
    f._commit(layer)


def _doya(f: FaceEditor):
    for e in (f.L, f.R):
        f.erase_eye(e, keep_from=0.38)
    f.erase_mouth()
    layer, dr = f._overlay()
    f.lid_line(dr, 0.38)
    f.mouth(dr, "smirk")
    f.blush(dr, 70)
    f._commit(layer)


def _jito(f: FaceEditor):
    for e in (f.L, f.R):
        f.erase_eye(e, keep_from=0.5)
    f.erase_mouth()
    layer, dr = f._overlay()
    f.lid_line(dr, 0.5)
    f.mouth(dr, "flat")
    f._commit(layer)


RECIPES = {"smile": _smile, "laugh": _laugh, "surprised": _surprised, "angry": _angry, "sad": _sad,
           "thinking": _thinking, "doya": _doya, "jito": _jito}


def edit_face(img: Image.Image, face: dict, expr: str) -> Image.Image:
    if expr == "normal" or expr not in RECIPES:
        return img.convert("RGBA")
    return FaceEditor(img, face).apply(expr)
