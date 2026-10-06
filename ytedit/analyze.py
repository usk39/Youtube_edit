"""セリフの内容解析(ルールベース)。感情・強調度・効果音・カットイン・素材キーワードを付ける。

ANTHROPIC_API_KEY があれば llm.py の Claude 解析で上書きされ、精度が上がる。
"""

from __future__ import annotations

import re

from .transcript import Segment

EMOTIONS = ["normal", "smile", "laugh", "surprised", "angry", "sad", "thinking", "doya", "jito"]
SE_KINDS = ["surprise", "laugh", "point", "question", "shock", "transition"]

# 感情ごとのキーワード(博多弁のあおいも考慮)
EMOTION_RULES: list[tuple[str, list[str]]] = [
    ("surprised", ["えっ", "えー", "ええ", "まじ", "マジ", "本当", "ほんと", "驚", "びっくり", "うそ", "嘘", "なんと", "衝撃", "!?", "！？", "すごか", "すごい"]),
    ("angry", ["ふざけ", "許せ", "怒", "ひどか", "ひどい", "最悪", "むかつ", "腹立", "なんしよ", "おかしか", "おかしい", "ありえん", "ありえない"]),
    ("jito", ["どうせ", "結局", "言い訳", "意味なか", "意味ない", "口だけ", "毎回", "また", "いつも"]),
    ("laugh", ["笑", "www", "ははは", "あはは", "面白", "おもしろ", "ウケる"]),
    ("sad", ["悲し", "残念", "つら", "辛い", "心配", "不安", "かわいそう", "厳しい", "きつか"]),
    ("doya", ["つまり", "ポイント", "実は", "結論", "重要", "大事", "要する", "というのも", "解説"]),
    ("thinking", ["うーん", "どういう", "なぜ", "なんで", "どうして", "考え", "とやろ", "と?", "と？", "ってこと"]),
    ("smile", ["よかった", "嬉し", "うれし", "楽し", "ありがと", "いいね", "なるほど", "へえ", "へー"]),
]

SE_RULES: list[tuple[str, list[str]]] = [
    ("surprise", ["えっ", "えー", "まじ", "マジ", "うそ", "嘘", "なんと", "!?", "！？", "衝撃"]),
    ("shock", ["ふざけ", "最悪", "ありえ", "許せ", "ひど", "なんしよ"]),
    ("laugh", ["笑", "www", "ははは", "あはは"]),
    ("point", ["ポイント", "つまり", "実は", "結論", "重要", "要する"]),
    ("transition", ["次は", "続いて", "さて", "ところで", "話を戻"]),
    ("question", ["どういう", "なぜ", "なんで", "どうして", "と?", "と？"]),
]

EMPHASIS_WORDS = ["実は", "なんと", "衝撃", "史上", "初", "過去最", "最大", "最悪", "異例", "緊急", "速報", "ついに", "まさか"]
STOPWORDS = set("今日 今回 話題 感じ 場合 部分 自分 本当 ところ こと もの 問題 大丈夫 みんな 一番 意味 理由 最近 全然 結局 普通 必要 可能 状態 以上 以下".split())
KEYWORD_RE = re.compile(r"[一-龥々]{2,}|[ァ-ヴー]{3,}|[A-Za-z][A-Za-z0-9]{1,}")


def extract_keywords(text: str, limit: int = 5) -> list[str]:
    seen, out = set(), []
    for w in KEYWORD_RE.findall(text):
        if w in STOPWORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return sorted(out, key=len, reverse=True)[:limit]


def classify_emotion(text: str) -> str:
    for emo, words in EMOTION_RULES:
        if any(w in text for w in words):
            return emo
    if text.endswith(("！", "!")):
        return "surprised"
    if text.endswith(("？", "?")):
        return "thinking"
    return "normal"


def classify_se(text: str) -> str | None:
    for kind, words in SE_RULES:
        if any(w in text for w in words):
            return kind
    return None


def emphasis_score(text: str) -> float:
    score = 0.0
    score += 0.25 * sum(w in text for w in EMPHASIS_WORDS)
    score += 0.15 * min(3, text.count("！") + text.count("!"))
    score += 0.15 * len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|％|億|兆|万|倍|人|円|ドル)", text))
    if classify_emotion(text) in ("surprised", "angry"):
        score += 0.25
    return min(1.0, score)


def analyze_rules(segments: list[Segment], max_cutins: int = 8, cutin_gap: float = 25.0) -> None:
    for s in segments:
        s.emotion = classify_emotion(s.text)
        s.se = classify_se(s.text)
        s.emphasis = emphasis_score(s.text)
        s.keywords = extract_keywords(s.text)
        s.cutin = False
        s.cutin_text = ""
    pick_cutins(segments, max_cutins, cutin_gap)


def pick_cutins(segments: list[Segment], max_count: int = 8, min_gap: float = 25.0) -> None:
    """強調度の高い順に、一定間隔を空けてカットイン候補を選ぶ。"""
    chosen: list[Segment] = []
    for s in sorted(segments, key=lambda x: -x.emphasis):
        if s.emphasis < 0.4 or len(chosen) >= max_count:
            break
        if all(abs(s.start - c.start) >= min_gap for c in chosen):
            chosen.append(s)
    for s in chosen:
        s.cutin = True
        s.cutin_text = s.cutin_text or make_cutin_text(s)


def make_cutin_text(s: Segment) -> str:
    """カットインに出す短い言葉。強調語を含む短いフレーズ > 「!」付きの短いフレーズ > キーワード の順。"""
    phrases = re.findall(r"[^、。\s　]+", s.text)
    short = [p for p in phrases if 4 <= len(p) <= 12]
    for p in short:
        if any(w in p for w in EMPHASIS_WORDS):
            return p
    for p in short:
        if re.search(r"[!！]", p):
            return p
    kws = s.keywords or extract_keywords(s.text)
    if kws:
        return kws[0][:12]
    return (phrases[0] if phrases else s.text)[:12]


def detect_chapters(segments: list[Segment], min_len: float = 60.0) -> list[dict]:
    """話題転換の言葉からチャプターを推定(Claude 解析が無いときの簡易版)。"""
    if not segments:
        return []
    chapters = [{"start": 0.0, "title": "オープニング"}]
    for s in segments[1:]:
        if any(w in s.text for w in ["次は", "続いて", "さて", "ところで", "まず", "ここで", "最後に", "まとめ"]):
            if s.start - chapters[-1]["start"] >= min_len:
                title = (s.keywords[0] if s.keywords else s.text[:14])
                if "まとめ" in s.text or "最後" in s.text:
                    title = "まとめ"
                chapters.append({"start": s.start, "title": title})
    return chapters


# ---------------------------------------------------------------- シーン
SCENE_MOODS = ["calm", "bright", "tense", "sad", "comical"]
SCENE_LABELS = {"calm": "落ち着き", "bright": "明るい", "tense": "緊迫", "sad": "しんみり", "comical": "コミカル"}
EMOTION_MOOD = {"angry": "tense", "surprised": "tense", "laugh": "comical", "jito": "comical", "smile": "bright",
                "doya": "bright", "sad": "sad", "normal": "calm", "thinking": "calm"}


def detect_scenes(segments: list[Segment], duration: float, chapters: list[dict] | None = None,
                  min_len: float = 25.0, window: float = 20.0) -> list[dict]:
    """セリフの感情から「シーン(雰囲気のまとまり)」を作る。BGM と効果音の選択に使う。"""
    if not segments:
        return [{"start": 0.0, "end": duration, "mood": "calm"}]
    # 各セリフの前後 window 秒の感情を集計して、そのあたりの雰囲気を決める
    moods = []
    for s in segments:
        score = {m: 0.0 for m in SCENE_MOODS}
        for o in segments:
            if abs(o.start - s.start) <= window:
                m = EMOTION_MOOD.get(o.emotion, "calm")
                score[m] += max(0.5, o.duration) * (0.6 if m == "calm" else 1.0) * (1 + o.emphasis)
        moods.append(max(score, key=score.get))
    bounds = {round(c["start"], 2) for c in (chapters or []) if c.get("start", 0) > 0}
    scenes: list[dict] = []
    for s, m in zip(segments, moods):
        start = 0.0 if not scenes else s.start
        if scenes and scenes[-1]["mood"] == m and round(s.start, 2) not in bounds:
            continue
        if scenes:
            scenes[-1]["end"] = start
        scenes.append({"start": start, "end": duration, "mood": m})
    # 短すぎるシーンは隣のシーンにまとめる
    changed = True
    while changed and len(scenes) > 1:
        changed = False
        for i, sc in enumerate(scenes):
            if sc["end"] - sc["start"] >= min_len:
                continue
            j = i - 1 if i > 0 and (i == len(scenes) - 1 or scenes[i - 1]["end"] - scenes[i - 1]["start"] >=
                                    scenes[i + 1]["end"] - scenes[i + 1]["start"]) else i + 1
            a, b = sorted((i, j))
            keep = scenes[j]["mood"]
            scenes[a] = {"start": scenes[a]["start"], "end": scenes[b]["end"], "mood": keep}
            del scenes[b]
            changed = True
            break
    # 同じ雰囲気が続いたらつなげる
    merged: list[dict] = []
    for sc in scenes:
        if merged and merged[-1]["mood"] == sc["mood"]:
            merged[-1]["end"] = sc["end"]
        else:
            merged.append(dict(sc))
    for sc in merged:
        sc["label"] = SCENE_LABELS[sc["mood"]]
    return merged
