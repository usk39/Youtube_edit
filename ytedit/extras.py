"""追加機能: 概要欄/チャプター、サムネイル、ショート動画の切り出し。"""

from __future__ import annotations

from pathlib import Path

from . import graphics as G
from .assets import AssetLibrary
from .ffmpeg import extract_frame, run_ffmpeg
from .transcript import Segment


def _ts(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def write_description(plan: dict, out: Path) -> Path:
    ov = plan.get("overview", {})
    lines = []
    if ov.get("title_ideas"):
        lines += ["■ タイトル案", *[f"・{t}" for t in ov["title_ideas"]], ""]
    if ov.get("description"):
        lines += ["■ 概要欄", ov["description"], ""]
    chapters = plan.get("chapters") or []
    if chapters:
        lines.append("■ チャプター(概要欄に貼るとYouTubeの目次になります)")
        if chapters[0]["start"] > 0:
            chapters = [{"start": 0.0, "title": "オープニング"}, *chapters]
        lines += [f"{_ts(c['start'])} {c['title']}" for c in chapters]
        lines.append("")
    if ov.get("tags"):
        lines += ["■ タグ", ", ".join(ov["tags"]), ""]
    out.write_text("\n".join(lines) or "(解析情報がありません)\n", encoding="utf-8")
    return out


def highlight_segment(plan: dict) -> Segment | None:
    segs = [Segment.from_dict(s) for s in plan.get("segments", [])]
    return max(segs, key=lambda s: (s.emphasis, s.cutin), default=None)


def make_thumbnail(plan: dict, cfg: dict, work: Path, out: Path) -> Path:
    """一番盛り上がったセリフの場面(元映像)を背景に、煽り文句とキャラを載せる。"""
    lib = AssetLibrary(cfg["assets_dir"])
    top = highlight_segment(plan)
    t = top.start + 0.3 if top else plan["duration"] / 3
    frame = None
    if plan.get("has_video"):
        frame = extract_frame(plan["source"], min(t, max(0.0, plan["duration"] - 0.1)), work / "thumb_frame.png")
    text = plan.get("overview", {}).get("thumbnail_text") or (
        (top.cutin_text or (top.keywords[0] if top.keywords else top.text[:10])) if top else "")
    char = "aoi" if "aoi" in cfg["characters"] else next(iter(cfg["characters"]))
    char_img = lib.character(char, "surprised")
    color = cfg["characters"][char]["color"]
    font_path = G.find_font(cfg.get("font_path"), cfg["assets_dir"])
    return G.make_thumbnail(frame, char_img, text, color, font_path, out)


def make_short(plan: dict, cfg: dict, video: Path, out: Path) -> Path | None:
    """強調度の合計が一番高い区間を 9:16 で書き出す。"""
    length = float(cfg["shorts"]["length"])
    D = float(plan["duration"])
    segs = [Segment.from_dict(s) for s in plan.get("segments", [])]
    if D <= length:
        start = 0.0
    else:
        best, start = -1.0, 0.0
        for s in segs:
            if s.start + length > D:
                break
            score = sum(x.emphasis + (0.5 if x.cutin else 0) for x in segs if s.start <= x.start < s.start + length)
            if score > best:
                best, start = score, s.start
    dur = min(length, D - start)
    graph = ("[0:v]split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:2[bg];"
             "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")
    run_ffmpeg(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(video), "-filter_complex", graph,
                "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    return out
