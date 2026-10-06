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

    def erase_eye(self, e: dict, upto: float = 1.0):
        """目を消す。upto<1 なら上から upto の割合だけ消す(半目用)。"""
        m, d = self._mask()
        c, dc = self._mask()
        k, kc = 1.28, 0.9
        # まつ毛が上にはみ出していることが多いので、上側を広めに消す
        box = (e["x"] - e["w"] * k / 2, e["y"] - e["h"] * 0.66, e["x"] + e["w"] * k / 2, e["y"] + e["h"] * 0.6)
        d.ellipse(box, fill=255)
        dc.ellipse((e["x"] - e["w"] * kc / 2, e["y"] - e["h"] * kc / 2, e["x"] + e["w"] * kc / 2, e["y"] + e["h"] * kc / 2),
                   fill=255)
        if upto < 1.0:
            cut = e["y"] - e["h"] * 0.54 + e["h"] * 1.08 * upto
            for dd in (d, dc):
                dd.rectangle((box[0] - 5, cut, box[2] + 5, box[3] + 5), fill=0)
        self._paint_skin(m, c)

    def erase_mouth(self):
        m, d = self._mask()
        w = self.m["w"] * 1.35
        d.ellipse((self.m["x"] - w / 2, self.m["y"] - w * 0.25, self.m["x"] + w / 2, self.m["y"] + w * 0.32), fill=255)
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

    def closed_eyes(self, dr, tilt: float = 0.0):
        """まばたき中の閉じた目 (‿)"""
        for e, sgn in ((self.L, 1), (self.R, -1)):
            w, h = e["w"] * 0.8, e["h"] * 0.35
            t = tilt * e["h"] * sgn
            cy = e["y"] + e["h"] * 0.05 + t * 0.5
            dr.arc(self._s(e["x"] - w / 2, cy - h, e["x"] + w / 2, cy + h * 0.6), 15, 165, fill=self.line,
                   width=int(self.lw * 1.3) * SS)

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

    def mouth(self, dr, kind: str, level: int = 0):
        x, y, w = self.m["x"], self.m["y"], self.m["w"]
        inside, tongue = (150, 50, 65, 255), (235, 120, 130, 255)
        lw = self.lw * SS
        if kind == "open":  # 驚き: 小さく丸く開いた口(level で大きく)
            r = w * (0.32, 0.4, 0.5)[level]
            dr.ellipse(self._s(x - r * 0.8, y - r * 0.6, x + r * 0.8, y + r * 1.0), fill=inside, outline=self.line, width=lw)
        elif kind == "laugh":  # 大笑い: D 型に大きく開いた口(level 1 は少し閉じる)
            k = 0.7 if level == 1 else 1.0
            dr.chord(self._s(x - w * 0.5, y - w * 0.45 * k, x + w * 0.5, y + w * 0.55 * k), 0, 180, fill=inside,
                     outline=self.line, width=lw)
            dr.chord(self._s(x - w * 0.28, y + w * 0.05 * k, x + w * 0.28, y + w * 0.5 * k), 0, 180, fill=tongue)
        elif kind == "frown":  # への字
            dr.arc(self._s(x - w * 0.4, y - w * 0.05, x + w * 0.4, y + w * 0.45), 200, 340, fill=self.line, width=lw)
        elif kind == "flat":  # 一文字
            dr.line(self._s(x - w * 0.3, y, x + w * 0.3, y), fill=self.line, width=lw)
        elif kind == "wavy":  # 考え中: くの字
            dr.line(self._s(x - w * 0.3, y + w * 0.04, x - w * 0.05, y - w * 0.06, x + w * 0.25, y + w * 0.05),
                    fill=self.line, width=lw, joint="curve")
        elif kind == "smirk":  # ニヤリ(片側が上がる)
            dr.arc(self._s(x - w * 0.55, y - w * 0.55, x + w * 0.45, y + w * 0.15), 25, 120, fill=self.line, width=lw)
        elif kind == "talk":  # しゃべっている口(level で開き具合)
            k = 0.55 if level == 1 else 0.9
            dr.ellipse(self._s(x - w * 0.3, y - w * 0.12 * k, x + w * 0.3, y + w * 0.42 * k), fill=inside,
                       outline=self.line, width=lw)
            if level == 2:
                dr.chord(self._s(x - w * 0.18, y + w * 0.1, x + w * 0.18, y + w * 0.36), 0, 180, fill=tongue)
        elif kind == "talk_smile":  # 笑顔でしゃべる口(D 型)
            k = 0.55 if level == 1 else 0.9
            dr.chord(self._s(x - w * 0.38, y - w * 0.3 * k, x + w * 0.38, y + w * 0.5 * k), 0, 180, fill=inside,
                     outline=self.line, width=lw)
        elif kind == "talk_angry":  # 怒ってしゃべる口(歯が見える)
            k = 0.6 if level == 1 else 1.0
            dr.rounded_rectangle(self._s(x - w * 0.42, y - w * 0.12, x + w * 0.42, y + w * 0.12 + w * 0.3 * k),
                                 radius=w * 0.1 * SS, fill=inside, outline=self.line, width=lw)
            dr.rectangle(self._s(x - w * 0.36, y - w * 0.08, x + w * 0.36, y + w * 0.03), fill=(255, 255, 255, 255))
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
    def apply(self, expr: str, mouth: int = 0, blink: bool = False) -> Image.Image:
        """expr の表情に描き換える。mouth=0/1/2 は口パクの開き具合、blink=True はまばたき中(目を閉じる)。"""
        st = STYLES.get(expr, STYLES["normal"])
        eyes = st.get("eyes")
        happy = eyes == "happy"
        if happy or (blink and not happy):
            for e in (self.L, self.R):
                self.erase_eye(e)
        elif eyes:
            for e in (self.L, self.R):
                self.erase_eye(e, eyes[0])
        mouth_kind = st.get("mouth")
        talk = TALK.get(expr, "talk") if mouth else None
        if mouth_kind or talk:
            self.erase_mouth()
        layer, dr = self._overlay()
        if happy:
            self.happy_eyes(dr)
        elif blink:
            self.closed_eyes(dr, eyes[1] if eyes else 0.0)
        elif eyes:
            self.lid_line(dr, eyes[0], eyes[1])
        if st.get("brows"):
            self.brows(dr, st["brows"])
        if talk:
            self.mouth(dr, talk, mouth)
        elif mouth_kind:
            self.mouth(dr, mouth_kind)
        if st.get("blush"):
            self.blush(dr, st["blush"])
        if st.get("tears"):
            self.tears(dr)
        self._commit(layer)
        return Image.fromarray(np.clip(self.arr, 0, 255).astype(np.uint8), "RGBA")


# 表情ごとの顔の描き方: eyes = "happy"(にっこり) / (上から消す割合, つり上がり) / None(元の目)
STYLES: dict[str, dict] = {
    "normal": {},
    "smile": {"eyes": "happy", "blush": 90},
    "laugh": {"eyes": "happy", "mouth": "laugh", "blush": 120},
    "surprised": {"brows": "surprised", "mouth": "open"},
    "angry": {"eyes": (0.3, 0.12), "brows": "angry", "mouth": "grin"},
    "sad": {"eyes": (0.2, -0.1), "brows": "sad", "mouth": "frown", "tears": True},
    "thinking": {"brows": "think", "mouth": "wavy"},
    "doya": {"eyes": (0.38, 0.0), "mouth": "smirk", "blush": 70},
    "jito": {"eyes": (0.5, 0.0), "mouth": "flat"},
}
# しゃべっているときの口の形
TALK = {"smile": "talk_smile", "doya": "talk_smile", "laugh": "laugh", "surprised": "open", "angry": "talk_angry"}
RECIPES = {k: v for k, v in STYLES.items() if k != "normal"}  # 互換用
CLOSED_EYES = {"smile", "laugh"}  # もともと目を閉じている表情(まばたき不要)


def edit_face(img: Image.Image, face: dict, expr: str, mouth: int = 0, blink: bool = False) -> Image.Image:
    img = img.convert("RGBA")
    if (expr == "normal" or expr not in STYLES) and not mouth and not blink:
        return img
    # 速くするため顔のまわりだけ切り出して描き換え、元の画像に戻す
    eyes = face["eyes"]
    d = abs(eyes[1]["x"] - eyes[0]["x"])
    xs = [e["x"] for e in eyes] + [face["mouth"]["x"]]
    ys = [e["y"] for e in eyes] + [face["mouth"]["y"]]
    x0 = max(0, int(min(xs) - d * 0.8))
    y0 = max(0, int(min(ys) - d * 0.9))
    x1 = min(img.width, int(max(xs) + d * 0.8))
    y1 = min(img.height, int(max(ys) + d * 0.6))
    local = {**face, "eyes": [{**e, "x": e["x"] - x0, "y": e["y"] - y0} for e in eyes],
             "mouth": {**face["mouth"], "x": face["mouth"]["x"] - x0, "y": face["mouth"]["y"] - y0}}
    part = FaceEditor(img.crop((x0, y0, x1, y1)), local).apply(expr if expr in STYLES else "normal", mouth, blink)
    out = img.copy()
    out.paste(part, (x0, y0))
    return out
