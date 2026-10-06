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
    credit_lines = credit_text(plan.get("credits", []))
    if credit_lines:
        lines += ["■ 使用素材(クレジット)", *credit_lines, ""]
    out.write_text("\n".join(lines) or "(解析情報がありません)\n", encoding="utf-8")
    return out


USED_AS = {"background": "背景", "bgm": "BGM", "materials": "画像", "se": "効果音"}


def credit_text(credits: list[dict]) -> list[str]:
    """概要欄に貼れるクレジット表記。表記が必要なもの(CC BY 等)は必ず載せ、不要なものも出典として載せる。"""
    out = []
    for c in sorted(credits, key=lambda c: (not c.get("needs_credit"), c.get("used_as", ""))):
        title = c.get("title") or "無題"
        by = f" by {c['creator']}" if c.get("creator") else ""
        lic = c.get("license", "")
        lic_url = f" ({c['license_url']})" if c.get("license_url") else ""
        out.append(f"[{USED_AS.get(c.get('used_as'), '素材')}] \"{title}\"{by} / {lic}{lic_url} / {c.get('page', '')}")
    return out


def write_credits(plan: dict, out: Path) -> Path | None:
    lines = credit_text(plan.get("credits", []))
    if not lines:
        return None
    head = ["このファイルの内容を YouTube の概要欄に貼ってください(CC BY 素材はクレジット表記が必須です)。", ""]
    out.write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    return out


def write_review(plan: dict, out: Path) -> Path:
    """自動で選ばれた素材を一覧で確認するための HTML(内容に合っているか・問題がないかのチェック用)。"""
    import html

    rows = []
    for key in ("background", "materials", "bgm", "se"):
        for e in plan.get(key, []):
            t = e.get("start", e.get("time", 0))
            src = Path(e["path"]).resolve().as_uri()
            if key in ("background", "materials"):
                media = f'<img src="{src}" loading="lazy">'
            else:
                media = f'<audio controls preload="none" src="{src}"></audio>'
            c = e.get("credit") or {}
            info = html.escape(f"{c.get('license', '手持ち素材')} {c.get('creator', '')}")
            link = f'<a href="{html.escape(c["page"])}">出典</a>' if c.get("page") else ""
            label = html.escape(str(e.get("keyword") or e.get("mood") or e.get("kind") or ""))
            rows.append(f"<tr><td>{_ts(t)}</td><td>{USED_AS[key]}</td><td>{label}</td><td>{media}</td>"
                        f"<td>{info} {link}<br><code>{html.escape(e['path'])}</code></td></tr>")
    doc = f"""<!doctype html><meta charset="utf-8"><title>素材チェック</title>
<style>body{{font-family:sans-serif;margin:16px}}table{{border-collapse:collapse;width:100%}}
td{{border-bottom:1px solid #ddd;padding:6px;vertical-align:middle}}img{{max-width:260px;max-height:150px}}
code{{font-size:11px;color:#666}}</style>
<h1>素材チェック</h1><p>内容に合わない素材は plan.json の該当行の "path" を差し替えるか削除して
<code>ytedit render plan.json</code> で再書き出ししてください。</p>
<table><tr><th>時刻</th><th>種類</th><th>キーワード</th><th>素材</th><th>ライセンス</th></tr>{''.join(rows)}</table>"""
    out.write_text(doc, encoding="utf-8")
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
