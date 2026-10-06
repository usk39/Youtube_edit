"""plan.json から ffmpeg のフィルタグラフを組み立てて最終動画を書き出す。

画像パーツは graphics.py で完成サイズの PNG にしておき、ffmpeg では
「1枚画像を overlay + enable で指定時間だけ表示」する方式にしている(軽くて速い)。
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from . import graphics as G
from .assets import AssetLibrary
from .ffmpeg import ffmpeg_exe, run_ffmpeg
from .subtitles import write_ass
from .transcript import Segment


class Graph:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []
        self.filters: list[str] = []
        self._n = 0
        self._images: dict[str, int] = {}
        self._image_uses: dict[str, list[str]] = {}

    def add_input(self, args: list[str]) -> int:
        self.inputs.append([str(a) for a in args])
        return len(self.inputs) - 1

    def label(self, prefix: str = "l") -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def image(self, path: str | Path) -> str:
        """1枚画像を入力に追加(同じ画像は1回だけ読み、使う回数分 split する)。"""
        key = str(Path(path).resolve())
        if key not in self._images:
            self._images[key] = self.add_input(["-i", key])
            self._image_uses[key] = []
        lab = self.label("img")
        self._image_uses[key].append(lab)
        return lab

    def finalize_images(self) -> None:
        for key, labels in self._image_uses.items():
            idx = self._images[key]
            if len(labels) == 1:
                self.filters.insert(0, f"[{idx}:v]format=rgba[{labels[0]}]")
            else:
                outs = "".join(f"[{l}]" for l in labels)
                self.filters.insert(0, f"[{idx}:v]format=rgba,split={len(labels)}{outs}")

    def overlay(self, base: str, top: str, x: str, y: str, start: float | None = None,
                end: float | None = None, eof: str = "repeat") -> str:
        out = self.label("v")
        enable = f":enable='between(t,{start:.3f},{end:.3f})'" if start is not None else ""
        self.filters.append(f"[{base}][{top}]overlay=x='{x}':y='{y}':eof_action={eof}{enable}[{out}]")
        return out


def _gfx_name(work: Path, kind: str, *parts) -> Path:
    h = hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:12]
    return work / "gfx" / f"{kind}_{h}.png"


def _ffmpeg_major() -> int:
    try:
        out = subprocess.run([ffmpeg_exe(), "-version"], capture_output=True, text=True).stdout
        m = re.search(r"ffmpeg version n?(\d+)\.", out)
        return int(m[1]) if m else 0
    except Exception:
        return 0


def _char_motion(e: dict, side: str, ec: dict, H: int) -> tuple[str, str]:
    """立ち絵の位置の式。話している間の揺れと、表情ごとの動き(ジャンプ/震え/沈む)。"""
    x = str(ec["margin_x"]) if side == "left" else f"W-w-{ec['margin_x']}"
    y = "H-h+10"
    a = f"(t-{e['start']:.3f})"
    motion = e.get("motion") if ec.get("motion", True) else None
    k = H / 1080
    if motion == "jump":  # 驚き: ぴょんぴょんと2回跳ねる
        y += f"-{40 * k:.1f}*abs(sin(PI*{a}/0.22))*lt({a},0.44)"
    elif motion == "shake":  # 怒り: ぶるぶる震える
        x += f"+{9 * k:.1f}*sin(2*PI*16*{a})*lt({a},0.6)"
    elif motion == "sink":  # 落ち込み・ジト目: 少し沈む
        y += f"+{22 * k:.1f}*min(1,{a}/0.4)"
    elif motion == "bounce" and e.get("speaking"):  # 笑い: 小刻みに弾む
        y += f"-{10 * k:.1f}*abs(sin(2*PI*4*t))"
    if e.get("speaking") and ec["bob"] and motion not in ("jump", "bounce"):
        y += f"-{6 * k:.1f}*abs(sin(2*PI*2.4*t))"
    return x, y


def build_command(plan: dict, cfg: dict, work: Path, out_path: Path, assets_dir: str | Path) -> tuple[list[str], str]:
    """ffmpeg 引数とフィルタグラフ文字列を返す(グラフはファイル経由で渡す)。"""
    oc = cfg["output"]
    W, H, FPS, D = oc["width"], oc["height"], oc["fps"], float(plan["duration"])
    feats = set(plan["features"])
    font_path = G.find_font(cfg.get("font_path"), assets_dir)
    chars_cfg = cfg["characters"]
    g = Graph()
    src = g.add_input(["-i", plan["source"]])

    # ------------------------------------------------------------ 映像: 土台と背景
    bg_events = plan.get("background") or []
    if bg_events or not plan["has_video"]:
        base_in = g.add_input(["-f", "lavfi", "-i", f"color=c=0x202030:s={W}x{H}:r={FPS}:d={D:.3f}"])
        cur = g.label("v")
        g.filters.append(f"[{base_in}:v]setsar=1,format=yuv420p[{cur}]")
        for e in bg_events:
            bc = cfg["background"]
            p = G.prepare_background(e["path"], W, H, _gfx_name(work, "bg", e["path"], W, H, bc["blur"], bc["darken"]),
                                     bc["blur"], bc["darken"])
            cur = g.overlay(cur, g.image(p), "0", "0", e["start"], e["end"])
        if plan["has_video"]:
            bc = cfg["background"]
            vw = int(W * bc["video_scale"]) // 2 * 2
            b = int(bc["border"])
            col = bc["border_color"].lstrip("#")
            sv = g.label("src")
            g.filters.append(
                f"[{src}:v]fps={FPS},scale={vw}:-2,setsar=1,pad=iw+{2 * b}:ih+{2 * b}:{b}:{b}:0x{col}[{sv}]")
            cur = g.overlay(cur, sv, "(W-w)/2", str(int(bc["video_top"] * H / 1080)), eof="pass")
    else:
        cur = g.label("v")
        g.filters.append(
            f"[{src}:v]fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[{cur}]")

    # ------------------------------------------------------------ 素材(ポップ表示)
    bx, by, bw, bh = cfg["materials"]["box"]
    for m in plan.get("materials", []):
        card = G.make_material_card(m["path"], int(W * bw), int(H * bh), _gfx_name(work, "mat", m["path"], W, bw, bh))
        cx, cy = int(W * (bx + bw / 2)), int(H * (by + bh / 2))
        a = m["start"]
        cur = g.overlay(cur, g.image(card), f"{cx}-w/2", f"{cy}-h/2+50*max(0,1-(t-{a:.3f})/0.25)", a, m["end"])

    # ------------------------------------------------------------ キャラクター立ち絵
    ec = cfg["expressions"]
    char_h = int(H * ec["height_ratio"])
    char_w_max = 0
    lib = AssetLibrary(assets_dir)
    boxes: dict[str, tuple | None] = {}
    for e in plan.get("expressions", []):
        c = e["char"]
        if c not in boxes:
            files = [lib.character(c, x) for x in lib.expressions(c)]
            boxes[c] = G.union_bbox([f for f in files if f])
        side = chars_cfg.get(c, {}).get("side", "left")
        p = G.prepare_character(e["path"], char_h, _gfx_name(work, "chr", e["path"], char_h, boxes[c]), box=boxes[c])
        char_w_max = max(char_w_max, Image.open(p).width)
        x, y = _char_motion(e, side, ec, H)
        cur = g.overlay(cur, g.image(p), x, y, e["start"], e["end"])

    # ------------------------------------------------------------ 丸顔ワイプ
    wc = cfg["wipe"]
    dia = int(wc["diameter"] * H / 1080)
    mg = int(wc["margin"] * H / 1080)
    pos = wc["position"]
    wx = f"W-w-{mg}" if "right" in pos else str(mg)
    wy = str(mg) if "top" in pos else f"H-h-{mg}"
    if plan.get("wipe_video"):
        wv_in = g.add_input(["-stream_loop", "-1", "-i", plan["wipe_video"]])
        wv = g.label("wv")
        inner = dia - 2 * int(wc["border"])
        g.filters.append(
            f"[{wv_in}:v]fps={FPS},scale={inner}:{inner}:force_original_aspect_ratio=increase,crop={inner}:{inner},"
            f"format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lte(hypot(X-W/2,Y-H/2),W/2-1),255,0)'[{wv}]")
        off = int(wc["border"])
        wx_in = f"W-{dia}-{mg}+{off}" if "right" in pos else str(mg + off)
        wy_in = str(mg + off) if "top" in pos else f"H-{dia}-{mg}+{off}"
        cur = g.overlay(cur, wv, wx_in, wy_in, 0.0, D, eof="pass")
        ring = G.make_wipe_ring(dia, int(wc["border"]), "#FFFFFF", _gfx_name(work, "ring", dia))
        cur = g.overlay(cur, g.image(ring), wx, wy)
    for e in plan.get("wipe", []):
        color = chars_cfg.get(e["char"], {}).get("color", "#FFFFFF")
        body = lib.character(e["char"], e["expression"])
        face = lib.character_face(e["char"], e["expression"])
        if body is None:
            continue
        p = G.make_wipe(body, face, dia, int(wc["border"]), color, _gfx_name(work, "wipe", body, face, dia, color))
        cur = g.overlay(cur, g.image(p), wx, wy, e["start"], e["end"])

    # ------------------------------------------------------------ カットイン
    band_h = int(H * cfg["cutin"]["height_ratio"])
    for c in plan.get("cutins", []):
        color = chars_cfg.get(c["char"], {}).get("color", "#FF4081")
        left = chars_cfg.get(c["char"], {}).get("side", "left") == "left"
        p = G.make_cutin(c["path"], c["text"], color, W, band_h, font_path,
                         _gfx_name(work, "cut", c["path"], c["text"], color, W, band_h), char_on_left=left)
        a, d = c["start"], c["duration"]
        k = 0.22
        x = (f"if(lt(t-{a:.3f},{k}),W*(1-(t-{a:.3f})/{k}),"
             f"if(gt(t-{a:.3f},{d - k:.3f}),-W*(t-{a:.3f}-{d - k:.3f})/{k},0))")
        cur = g.overlay(cur, g.image(p), x, "(H-h)/2", a, a + d)

    # ------------------------------------------------------------ 登録呼びかけバナー
    for pu in plan.get("popups", []):
        p = G.make_popup(W, H, font_path, _gfx_name(work, "popup", W, H))
        a = pu["start"]
        # 字幕の少し上に、下からスライドインさせる
        cur = g.overlay(cur, g.image(p), "(W-w)/2", f"H*0.72-h+(H*0.3)*max(0,1-(t-{a:.3f})/0.3)", a, pu["end"])

    # ------------------------------------------------------------ 字幕
    if "subtitles" in feats and plan.get("segments"):
        fonts_dir = work / "fonts"
        fonts_dir.mkdir(parents=True, exist_ok=True)
        font_name = "sans-serif"
        if font_path:
            shutil.copy(font_path, fonts_dir / Path(font_path).name)
            font_name = G.font(font_path, 20).getname()[0]
        side = char_w_max + 20 if char_w_max else int(W * 0.08)
        segs = [Segment.from_dict(s) for s in plan["segments"]]
        write_ass(segs, cfg, font_name, side, work / "subs.ass")
        out = g.label("v")
        g.filters.append(f"[{cur}]subtitles=subs.ass:fontsdir=fonts[{out}]")
        cur = out

    g.filters.append(f"[{cur}]format=yuv420p[vout]")

    # ------------------------------------------------------------ 音声
    ac = cfg["audio"]
    mix: list[str] = []
    if plan["has_audio"]:
        chain = ["aresample=48000", "aformat=channel_layouts=stereo"]
        if "audio" in feats:
            chain.append(f"highpass=f={ac['highpass_hz']}")
            if ac["denoise"]:
                chain.append("afftdn=nf=-25")
            if ac["compressor"]:
                chain.append("acompressor=threshold=-20dB:ratio=3:attack=5:release=120:makeup=2")
            chain += [f"loudnorm=I={ac['target_lufs']}:TP={ac['true_peak']}:LRA=11", "aresample=48000"]
        g.filters.append(f"[{src}:a]{','.join(chain)}[voice]")
    else:
        sil = g.add_input(["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={D:.3f}"])
        g.filters.append(f"[{sil}:a]anull[voice]")

    bgm_events = plan.get("bgm") or []
    duck = cfg["bgm"]["ducking"] and plan["has_audio"] and bgm_events
    if duck:
        g.filters.append("[voice]asplit=2[voicemix][voicesc]")
        mix.append("[voicemix]")
    else:
        mix.append("[voice]")

    if bgm_events:
        parts = []
        fi, fo = cfg["bgm"]["fade_in"], cfg["bgm"]["fade_out"]
        for e in bgm_events:
            idx = g.add_input(["-stream_loop", "-1", "-i", e["path"]])
            length = max(0.1, e["end"] - e["start"])
            lab = g.label("bgm")
            ms = int(e["start"] * 1000)
            g.filters.append(
                f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{length:.3f},asetpts=PTS-STARTPTS,"
                f"volume={e['volume_db']}dB,afade=t=in:st=0:d={min(fi, length / 3):.2f},"
                f"afade=t=out:st={max(0, length - min(fo, length / 3)):.3f}:d={min(fo, length / 3):.2f},"
                f"adelay={ms}:all=1[{lab}]")
            parts.append(f"[{lab}]")
        bus = "bgmbus"
        if len(parts) > 1:
            g.filters.append(f"{''.join(parts)}amix=inputs={len(parts)}:duration=longest:normalize=0[{bus}]")
        else:
            g.filters.append(f"{parts[0]}anull[{bus}]")
        if duck:
            g.filters.append(f"[{bus}][voicesc]sidechaincompress=threshold=0.02:ratio=8:attack=30:release=500[bgmduck]")
            mix.append("[bgmduck]")
        else:
            mix.append(f"[{bus}]")

    se_files: dict[str, list[dict]] = {}
    for e in plan.get("se", []):
        se_files.setdefault(str(Path(e["path"]).resolve()), []).append(e)
    for path, events in se_files.items():
        idx = g.add_input(["-i", path])
        labs = [g.label("se") for _ in events]
        g.filters.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,asplit={len(labs)}"
                         + "".join(f"[{l}]" for l in labs))
        for l, e in zip(labs, events):
            out = g.label("sed")
            g.filters.append(f"[{l}]volume={e['volume_db']}dB,adelay={int(e['time'] * 1000)}:all=1[{out}]")
            mix.append(f"[{out}]")

    if len(mix) > 1:
        g.filters.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0,"
                         f"alimiter=limit=0.95[aout]")
    else:
        g.filters.append(f"{mix[0]}anull[aout]")

    g.finalize_images()
    graph = ";\n".join(g.filters)
    graph_file = work / "graph.txt"
    graph_file.write_text(graph, encoding="utf-8")
    graph_opt = ["-/filter_complex", graph_file.name] if _ffmpeg_major() >= 7 else ["-filter_complex_script", graph_file.name]

    args = [a for inp in g.inputs for a in inp]
    args += [*graph_opt, "-map", "[vout]", "-map", "[aout]",
             "-c:v", "libx264", "-preset", oc["preset"], "-crf", str(oc["crf"]), "-r", str(FPS),
             "-c:a", "aac", "-b:a", oc["audio_bitrate"], "-t", f"{D:.3f}", "-movflags", "+faststart",
             str(out_path.resolve())]
    return args, graph


def render(plan: dict, cfg: dict, work: Path, out_path: Path, assets_dir: str | Path) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    args, _ = build_command(plan, cfg, work, out_path, assets_dir)
    print(f"[レンダリング] {out_path.name} を書き出し中 ... (動画の長さ {plan['duration']:.0f} 秒)")
    run_ffmpeg(args, cwd=work)
    return out_path


def silence_cut(src: Path, keep: list[tuple[float, float]], has_video: bool, out: Path, work: Path) -> Path:
    """keep 区間だけをつなげた動画を作る(無音カット)。"""
    expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in keep)
    parts = [f"[0:a]aselect='{expr}',asetpts=N/SR/TB[a]"]
    maps = ["-map", "[a]"]
    if has_video:
        parts.insert(0, f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v]")
        maps = ["-map", "[v]", *maps]
    gf = work / "cut_graph.txt"
    gf.write_text(";".join(parts), encoding="utf-8")
    graph_opt = ["-/filter_complex", gf.name] if _ffmpeg_major() >= 7 else ["-filter_complex_script", gf.name]
    codec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16"] if has_video else []
    run_ffmpeg(["-i", str(src.resolve()), *graph_opt, *maps, *codec, "-c:a", "pcm_s16le" if not has_video else "aac",
                "-b:a", "256k", str(out.resolve())], cwd=work)
    return out
