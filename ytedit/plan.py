"""編集プラン(タイムライン)の組み立て。

解析結果から「いつ・何を・どこに出すか」を JSON(plan.json)にまとめる。
plan.json は手で直してから `ytedit render plan.json` で再レンダリングできる。
"""

from __future__ import annotations

from pathlib import Path

from .assets import AssetLibrary
from .characters import MOTIONS
from .online import BACKGROUND_FALLBACK_EN, OnlineSource
from .ffmpeg import MediaInfo
from .transcript import Segment

REACTION = {"surprised": "surprised", "laugh": "smile", "sad": "sad", "angry": "jito"}


def _merge(events: list[dict], keys: tuple[str, ...]) -> list[dict]:
    out: list[dict] = []
    for e in events:
        if e["end"] - e["start"] <= 0.01:
            continue
        if out and all(out[-1][k] == e[k] for k in keys) and e["start"] - out[-1]["end"] < 0.05:
            out[-1]["end"] = e["end"]
        else:
            out.append(dict(e))
    return out


def expression_timeline(segments: list[Segment], char: str, duration: float, lib: AssetLibrary) -> list[dict]:
    raw, cur = [], 0.0
    for s in segments:
        if s.start > cur:
            raw.append({"expression": "normal", "start": cur, "end": s.start, "speaking": False})
        if s.speaker == char:
            expr, speaking = s.emotion or "normal", True
        else:
            expr, speaking = REACTION.get(s.emotion, "normal"), False
        raw.append({"expression": expr, "start": max(cur, s.start), "end": s.end, "speaking": speaking})
        cur = max(cur, s.end)
    if duration > cur:
        raw.append({"expression": "normal", "start": cur, "end": duration, "speaking": False})
    for e in raw:
        e["char"] = char
        e["expression"] = lib.resolve_expression(char, e["expression"])
        e["path"] = str(lib.character(char, e["expression"]))
        e["motion"] = MOTIONS.get(e["expression"]) if e["speaking"] or e["expression"] != "normal" else None
    return _merge(raw, ("expression", "speaking"))


def wipe_timeline(segments: list[Segment], duration: float, lib: AssetLibrary, chars: list[str]) -> list[dict]:
    raw, last = [], None
    for i, s in enumerate(segments):
        if s.speaker not in chars:
            continue
        nxt = next((x.start for x in segments[i + 1:] if x.speaker in chars), duration)
        start = 0.0 if last is None else s.start
        expr = lib.resolve_expression(s.speaker, s.emotion or "normal")
        raw.append({"char": s.speaker, "expression": expr, "start": start, "end": nxt})
        last = s
    return _merge(raw, ("char", "expression"))


def _chapter_ranges(chapters: list[dict], duration: float) -> list[tuple[float, float, dict]]:
    if not chapters:
        return [(0.0, duration, {})]
    out = []
    for i, c in enumerate(chapters):
        end = chapters[i + 1]["start"] if i + 1 < len(chapters) else duration
        out.append((0.0 if i == 0 else c["start"], end, c))
    return out


def build_plan(segments: list[Segment], info: MediaInfo, source: Path, features: list[str], cfg: dict,
               lib: AssetLibrary, overview: dict, work_dir: Path) -> dict:
    D = info.duration
    chars = [c for c in cfg["characters"] if lib.character(c, "normal")]
    plan: dict = {
        "version": 1, "source": str(source), "duration": D, "has_video": info.has_video, "has_audio": info.has_audio,
        "features": features, "segments": [s.to_dict() for s in segments],
        "chapters": overview.get("chapters", []),
        "overview": {k: v for k, v in overview.items() if k != "chapters"},
        "background": [], "bgm": [], "materials": [], "expressions": [], "wipe": [], "wipe_video": None,
        "se": [], "cutins": [], "popups": [],
    }
    ranges = _chapter_ranges(plan["chapters"], D)

    online = OnlineSource(cfg)
    prefer_local = cfg["online"].get("prefer") == "local"

    def pick(local, fetch):
        """手持ち素材とネット素材のどちらを使うか(prefer 設定に従い、無ければもう一方)。"""
        if prefer_local:
            return (str(local), None) if local else _hit(fetch())
        got = _hit(fetch())
        return got if got[0] else ((str(local), None) if local else (None, None))

    if "background" in features:
        default = lib.default_background()
        bgs = []
        for i, (a, b, ch) in enumerate(ranges):
            kws = list(ch.get("background_keywords", [])) + ([ch["title"]] if ch.get("title") else [])
            local = (lib.find_background(kws) if cfg["background"]["per_chapter"] else None) or default
            en = [ch.get("background_query_en", "")] + [BACKGROUND_FALLBACK_EN[i % len(BACKGROUND_FALLBACK_EN)]]
            path, meta = pick(local, lambda: online.image(kws[:2], en, "backgrounds"))
            if path:
                bgs.append({"path": path, "start": a, "end": b, "credit": meta})
            elif bgs:
                bgs.append({**bgs[-1], "start": a, "end": b})
        plan["background"] = _merge(bgs, ("path",))
        if not plan["background"]:
            print("[背景] 背景画像が見つからないためスキップ")

    if "bgm" in features:
        mood_cfg = cfg["bgm"]["mood"]
        items = []
        for a, b, ch in ranges:
            mood = (ch.get("bgm_mood") or "calm") if mood_cfg == "auto" else mood_cfg
            files = lib.bgm_list(mood)
            path, meta = pick(files[0] if files else None, lambda: online.bgm(mood))
            if path:
                items.append({"path": path, "mood": mood, "start": a, "end": b, "credit": meta})
        plan["bgm"] = [{**e, "volume_db": cfg["bgm"]["volume_db"]} for e in _merge(items, ("path",))]
        if not plan["bgm"]:
            print("[BGM] BGM が見つからないためスキップ")

    if "materials" in features:
        mc = cfg["materials"]
        shown: list[dict] = []
        last_end, last_path = -1.0, None
        for s in segments:
            if s.start < last_end or not (s.keywords or s.image_query):
                continue
            if sum(1 for m in shown if m["start"] > s.start - 60) >= mc["max_per_minute"]:
                continue
            path, meta = pick(lib.find_material(s.keywords) if s.keywords else None,
                              lambda: online.image(s.keywords[:2], [s.image_query], "materials"))
            if path is None or (path == last_path and s.start - last_end < 30):
                continue
            end = min(D, s.start + min(mc["max_duration"], max(mc["min_duration"], s.duration)))
            shown.append({"path": path, "start": s.start, "end": end,
                          "keyword": s.keywords[0] if s.keywords else s.image_query, "credit": meta})
            last_end, last_path = end, path
        plan["materials"] = shown

    if "expressions" in features:
        if not chars:
            print("[表情] assets/characters/<sumire|aoi>/normal.png が無いためスキップ")
        for c in chars:
            plan["expressions"] += expression_timeline(segments, c, D, lib)

    if "wipe" in features:
        video = cfg["wipe"].get("video")
        if video:
            plan["wipe_video"] = str(Path(video).resolve())
        elif chars:
            plan["wipe"] = wipe_timeline(segments, D, lib, chars)

    if "cutin" in features:
        cc = cfg["cutin"]
        chosen: list[Segment] = []
        for s in sorted((s for s in segments if s.cutin), key=lambda x: -x.emphasis):
            if len(chosen) < cc["max_count"] and all(abs(s.start - c.start) >= cc["min_gap"] for c in chosen):
                chosen.append(s)
        for s in sorted(chosen, key=lambda x: x.start):
            spk = s.speaker if s.speaker in chars else (chars[0] if chars else None)
            if spk is None:
                continue
            expr = lib.resolve_expression(spk, s.emotion)
            plan["cutins"].append({"char": spk, "expression": expr, "path": str(lib.character(spk, expr)),
                                   "text": s.cutin_text or s.text[:12], "start": s.start,
                                   "duration": min(cc["duration"], max(0.8, D - s.start))})

    if "popup" in features:
        last = -999.0
        for s in segments:
            if any(t in s.text for t in cfg["popup"]["triggers"]) and s.start - last > 90:
                plan["popups"].append({"start": s.start, "end": min(D, s.start + cfg["popup"]["duration"])})
                last = s.start

    if "se" in features:
        sc = cfg["se"]
        events = [(s.start, s.se, i) for i, s in enumerate(segments) if s.se]
        events += [(c["start"], "cutin", 0) for c in plan["cutins"]]
        events += [(p["start"] + 0.1, "popup", 0) for p in plan["popups"]]
        last_t = -999.0
        for t, kind, seed in sorted(events):
            forced = kind in ("cutin", "popup")
            if not forced and t - last_t < sc["min_gap"]:
                continue
            path, meta = pick(lib.se(kind, seed), lambda: online.se(kind, seed))
            if path:
                plan["se"].append({"path": path, "kind": kind, "time": round(t, 3), "volume_db": sc["volume_db"],
                                   "credit": meta})
                last_t = t

    plan["credits"] = collect_credits(plan)
    if online.downloads:
        print(f"[ネット素材] 新たに {online.downloads} 件ダウンロード (キャッシュ: {online.cache})")
    return plan


def _hit(result) -> tuple[str | None, dict | None]:
    if not result:
        return None, None
    path, meta = result
    return str(path), meta


def collect_credits(plan: dict) -> list[dict]:
    """プランで使っているネット素材のクレジット(重複なし)。"""
    seen, out = set(), []
    for key in ("background", "bgm", "materials", "se"):
        for e in plan.get(key, []):
            c = e.get("credit")
            if c and c.get("url") not in seen:
                seen.add(c.get("url"))
                out.append({**c, "used_as": key})
    return out
