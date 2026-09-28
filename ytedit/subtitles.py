"""話者ごとに色分けした ASS 字幕の生成。"""

from __future__ import annotations

import re
from pathlib import Path

from .transcript import Segment


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def wrap(text: str, max_chars: int) -> list[str]:
    """句読点を優先して max_chars 以内の行に分ける。"""
    lines, cur = [], ""
    for piece in re.findall(r"[^、。！？!?,，]*[、。！？!?,，]?", text):
        if not piece:
            continue
        while len(piece) > max_chars:
            room = max_chars - len(cur)
            lines.append(cur + piece[:room])
            cur, piece = "", piece[room:]
        if len(cur) + len(piece) > max_chars:
            lines.append(cur)
            cur = piece
        else:
            cur += piece
    if cur:
        lines.append(cur)
    return [l for l in lines if l.strip()]


def build_ass(segments: list[Segment], cfg: dict, font_name: str, side_margin: int) -> str:
    W, H = cfg["output"]["width"], cfg["output"]["height"]
    sc = cfg["subtitles"]
    scale = H / 1080
    size, outline = int(sc["font_size"] * scale), max(1, int(sc["outline"] * scale))
    styles = []
    for cid, c in {**cfg["characters"], "default": {"color": "#333333"}}.items():
        styles.append(
            f"Style: {cid},{font_name},{size},&H00FFFFFF,&H000000FF,{_ass_color(c['color'])},&H64000000,"
            f"-1,0,0,0,100,100,0,0,1,{outline},{max(1, outline // 3)},2,{side_margin},{side_margin},{int(sc['margin_v'] * scale)},1"
        )
    events = []
    for s in segments:
        lines = wrap(s.text, sc["max_chars_per_line"])
        chunks = [lines[i:i + 2] for i in range(0, len(lines), 2)] or [[s.text]]
        total = sum(len("".join(c)) for c in chunks) or 1
        t = s.start
        for c in chunks:
            dur = s.duration * len("".join(c)) / total
            text = r"\N".join(x.replace("{", "｛").replace("}", "｝") for x in c)
            style = s.speaker if s.speaker in cfg["characters"] else "default"
            events.append(f"Dialogue: 0,{_ass_time(t)},{_ass_time(t + dur)},{style},,0,0,0,,{text}")
            t += dur
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
        "MarginV, Encoding",
        *styles, "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *events, "",
    ])


def write_ass(segments: list[Segment], cfg: dict, font_name: str, side_margin: int, out: Path) -> Path:
    out.write_text(build_ass(segments, cfg, font_name, side_margin), encoding="utf-8")
    return out
