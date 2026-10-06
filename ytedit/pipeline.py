"""全体の処理の流れ。

入力 → (無音カット) → 文字起こし/台本同期 → 話者推定 → 内容解析 → プラン作成 → レンダリング → 追加出力
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import analyze, extras, llm
from .assets import AssetLibrary
from .ffmpeg import detect_silences, extract_audio, probe
from .ingest import is_url, resolve_input
from .plan import build_plan
from .render import render, silence_cut
from .speakers import assign_by_pitch
from .transcript import (Segment, align_script_with_silence, align_script_with_words, parse_script, parse_srt,
                         transcribe, voiced_intervals, write_srt)


def _slug(src: str) -> str:
    base = src.rstrip("/").split("/")[-1] if is_url(src) else Path(src).stem
    return re.sub(r"[^\w\-]+", "_", base)[:40] or "video"


def _keep_intervals(silences, duration: float, pad: float) -> list[tuple[float, float]]:
    keep = []
    for a, b in voiced_intervals(silences, duration):
        a, b = max(0.0, a - pad), min(duration, b + pad)
        if keep and a <= keep[-1][1]:
            keep[-1] = (keep[-1][0], b)
        else:
            keep.append((a, b))
    return keep


def get_segments(media: Path, audio_wav: Path, duration: float, cfg: dict, script: str | None,
                 srt: str | None) -> list[Segment]:
    chars = cfg["characters"]
    if srt:
        print(f"[字幕] SRT を読み込み: {srt}")
        return parse_srt(srt, chars)
    lines = parse_script(script, chars) if script else None
    if script and not lines:
        raise ValueError("台本から「すみれ:」「あおい:」形式のセリフが見つかりませんでした")
    try:
        print("[文字起こし] faster-whisper で音声認識中 ...")
        segs, words = transcribe(audio_wav, cfg)
        if lines:
            print(f"[台本同期] 台本 {len(lines)} 行を音声に合わせています")
            return align_script_with_words(lines, words)
        return segs
    except RuntimeError as e:
        if not lines:
            raise
        print(f"[台本同期] 音声認識が使えないため、無音区間で同期します ({str(e).splitlines()[0]})")
        voiced = voiced_intervals(detect_silences(media, -40, 0.25), duration)
        return align_script_with_silence(lines, voiced)


def run(src: str, features: list[str], cfg: dict, script: str | None = None, srt: str | None = None,
        out_dir: str | None = None, plan_only: bool = False) -> dict:
    out = Path(out_dir or Path(cfg["output_dir"]) / _slug(src)).resolve()
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    lib = AssetLibrary(cfg["assets_dir"])
    print(f"[開始] 出力先: {out}\n[機能] {', '.join(features) or '(なし)'}")

    media = resolve_input(src, work)
    info = probe(media)
    print(f"[入力] {media.name}  {info.duration:.1f}秒  映像={'あり' if info.has_video else 'なし'}")

    if "silence_cut" in features and info.has_audio:
        sc = cfg["silence_cut"]
        keep = _keep_intervals(detect_silences(media, sc["noise_db"], sc["min_silence"]), info.duration,
                               sc["keep_padding"])
        kept = sum(b - a for a, b in keep)
        if keep and info.duration - kept > 0.5:
            print(f"[無音カット] {info.duration - kept:.1f} 秒をカット")
            media = silence_cut(media, keep, info.has_video, work / ("cut.mp4" if info.has_video else "cut.wav"), work)
            info = probe(media)
            if srt:
                print("[無音カット] 注意: SRT の時刻はカット前の動画基準です。台本(--script)の利用をおすすめします")

    audio_wav = extract_audio(media, work / "audio16k.wav")
    segments = get_segments(media, audio_wav, info.duration, cfg, script, srt)
    if not segments:
        raise RuntimeError("セリフを取得できませんでした")
    assign_by_pitch(segments, audio_wav, list(cfg["characters"]), cfg["speaker"]["higher_pitch"])
    print(f"[セリフ] {len(segments)} 件")

    analyze.analyze_rules(segments, cfg["cutin"]["max_count"], cfg["cutin"]["min_gap"])
    overview: dict = {"chapters": analyze.detect_chapters(segments)}
    if llm.llm_available(cfg):
        try:
            print(f"[解析] Claude ({cfg['llm']['model']}) で内容を解析中 ...")
            overview = llm.analyze_with_claude(segments, cfg, lib.material_tags(), lib.background_tags()) or overview
        except Exception as e:
            print(f"[解析] Claude 解析に失敗したためルールベースで続行: {e}")
    else:
        print("[解析] ルールベースで解析 (ANTHROPIC_API_KEY を設定すると Claude で高精度に解析します)")

    plan = build_plan(segments, info, media, features, cfg, lib, overview, work)
    plan_path = out / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    write_srt(segments, out / "subtitles.srt", cfg["characters"])
    print(f"[プラン] {plan_path}  (素材{len(plan['materials'])} / 効果音{len(plan['se'])} / "
          f"カットイン{len(plan['cutins'])} / 表情切替{len(plan['expressions'])})")
    if plan_only:
        return {"plan": str(plan_path), "out_dir": str(out)}
    return finish(plan, cfg, out)


def finish(plan: dict, cfg: dict, out: Path) -> dict:
    work = out / "work"
    video = render(plan, cfg, work, out / "final.mp4", cfg["assets_dir"])
    result = {"video": str(video), "plan": str(out / "plan.json"), "out_dir": str(out)}
    feats = set(plan["features"])
    credits = extras.write_credits(plan, out / "credits.txt")
    if credits:
        result["credits"] = str(credits)
    result["review"] = str(extras.write_review(plan, out / "review.html"))
    if "chapters" in feats:
        result["description"] = str(extras.write_description(plan, out / "description.txt"))
    if "thumbnail" in feats:
        result["thumbnail"] = str(extras.make_thumbnail(plan, cfg, work, out / "thumbnail.png"))
    if "shorts" in feats:
        result["short"] = str(extras.make_short(plan, cfg, video, out / "short.mp4"))
    print("[完了]")
    for k, v in result.items():
        print(f"  {k:12s}: {v}")
    return result


def render_plan_file(plan_path: str, cfg: dict) -> dict:
    p = Path(plan_path).resolve()
    plan = json.loads(p.read_text(encoding="utf-8"))
    return finish(plan, cfg, p.parent)
