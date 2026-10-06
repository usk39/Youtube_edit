"""Claude API による内容解析(任意)。ANTHROPIC_API_KEY 等の認証情報があると自動で使う。

セリフごとの感情・効果音・カットイン・素材キーワードに加え、チャプター・タイトル案・概要欄を作る。
失敗・拒否された場合はルールベース解析の結果をそのまま使う。
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel

from .transcript import Segment

Emotion = Literal["normal", "smile", "laugh", "surprised", "angry", "sad", "thinking", "doya", "jito"]
SEKind = Literal["none", "surprise", "laugh", "point", "question", "shock", "transition"]
Mood = Literal["calm", "bright", "tense", "sad", "comical"]


class SegmentTag(BaseModel):
    index: int
    emotion: Emotion
    se: SEKind
    emphasis: float
    cutin: bool
    cutin_text: str
    material_keywords: list[str]
    image_query_en: str


class SegmentTags(BaseModel):
    segments: list[SegmentTag]


class Chapter(BaseModel):
    start_index: int
    title: str
    bgm_mood: Mood
    background_keywords: list[str]
    background_query_en: str


class Scene(BaseModel):
    start_index: int
    mood: Mood
    description: str


class Overview(BaseModel):
    chapters: list[Chapter]
    scenes: list[Scene]
    title_ideas: list[str]
    description: str
    thumbnail_text: str
    tags: list[str]


SYSTEM = """あなたは時事ニュース系YouTubeチャンネルの動画編集ディレクターです。
出演は姉妹の「すみれ」(物知りな説明役)と「あおい」(博多弁の毒舌な聞き役)。
渡されたセリフ一覧を読み、編集の演出指示を JSON で返してください。

- emotion: そのセリフを話しているキャラの表情。jito はジト目(皮肉・呆れ)、doya はドヤ顔(解説の決め所)。
- se: 効果音。多用せず、本当に効果的なセリフだけに付ける(目安: 全体の2〜3割)。それ以外は none。
- emphasis: 0〜1 の盛り上がり度。
- cutin: 動画の山場だけ true(10分あたり最大6個程度)。cutin_text はカットインに大きく出す12文字以内の言葉。
- material_keywords: 画面に出すと理解が深まる画像素材のキーワード。手持ち素材タグに合うものがあれば必ずそのタグ名をそのまま使う。
- image_query_en: そのセリフに合う写真をフリー素材サイトで探すための英語の検索語(2〜4語、例 "japanese yen coins")。
  素材が不要なセリフは空文字。人物の実名やロゴは避け、物や風景で表現する。
"""


def llm_available(cfg: dict) -> bool:
    mode = cfg["llm"]["enabled"]
    if mode is False or mode == "off":
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    if mode is True or mode == "on":
        return True
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.environ.get("ANTHROPIC_PROFILE"))


def _lines(segments: list[Segment], characters: dict) -> str:
    out = []
    for i, s in enumerate(segments):
        name = characters.get(s.speaker, {}).get("names", ["?"])[0]
        out.append(f"[{i}] ({s.start:.1f}s) {name}: {s.text}")
    return "\n".join(out)


def _parse(client, model: str, prompt: str, schema):
    resp = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=schema,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude が応答を拒否しました")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("出力が長すぎて途中で切れました(llm.chunk_size を小さくしてください)")
    return resp.parsed_output


def analyze_with_claude(segments: list[Segment], cfg: dict, material_tags: list[str],
                        background_tags: list[str]) -> dict | None:
    """セグメントを直接更新し、概要(チャプター等)を dict で返す。"""
    import anthropic

    client = anthropic.Anthropic()
    model = cfg["llm"]["model"]
    chars = cfg["characters"]
    tags_note = "手持ち素材タグ: " + (", ".join(sorted(set(material_tags))[:300]) or "(なし)")
    chunk = int(cfg["llm"]["chunk_size"])

    for start in range(0, len(segments), chunk):
        part = segments[start:start + chunk]
        # [番号] は全体での通し番号 (= 返してほしい index)
        prompt = f"{tags_note}\n\n次のセリフすべてに演出を付けてください。\n\n" + "\n".join(
            f"[{start + i}] {chars.get(s.speaker, {}).get('names', ['?'])[0]}: {s.text}" for i, s in enumerate(part))
        result: SegmentTags = _parse(client, model, prompt, SegmentTags)
        for tag in result.segments:
            if not (0 <= tag.index < len(segments)):
                continue
            s = segments[tag.index]
            s.emotion = tag.emotion
            s.se = None if tag.se == "none" else tag.se
            s.emphasis = max(0.0, min(1.0, tag.emphasis))
            s.cutin = tag.cutin
            s.cutin_text = tag.cutin_text[:14]
            if tag.material_keywords:
                s.keywords = tag.material_keywords[:5]
            s.image_query = tag.image_query_en.strip()

    prompt = (
        "背景画像タグ: " + (", ".join(sorted(set(background_tags))) or "(なし)") + "\n\n"
        "以下は動画の全セリフです。シーン(雰囲気のまとまり。BGM と効果音を切り替える単位で、最初は index 0、"
        "1 シーンは目安 30 秒以上。mood は calm=落ち着き/bright=明るい/tense=緊迫・驚き/sad=しんみり/comical=コミカル・ツッコミ)、"
        "チャプター(話題の区切り。最初は index 0。background_query_en は"
        "その話題の背景に使う写真を探す英語の検索語で、文字が少なく落ち着いた風景や街並みにする)、YouTube タイトル案を5つ、"
        "概要欄の文章(チャプターのタイムスタンプは不要)、サムネイル用の短い煽り文句(12文字以内)、タグを作ってください。\n\n"
        + _lines(segments, chars)
    )
    ov: Overview = _parse(client, model, prompt, Overview)
    chapters = []
    for c in sorted(ov.chapters, key=lambda c: c.start_index):
        if 0 <= c.start_index < len(segments):
            chapters.append({"start": 0.0 if not chapters else segments[c.start_index].start, "title": c.title,
                             "bgm_mood": c.bgm_mood, "background_keywords": c.background_keywords,
                             "background_query_en": c.background_query_en})
    scenes = []
    for sc in sorted(ov.scenes, key=lambda c: c.start_index):
        if 0 <= sc.start_index < len(segments):
            start = 0.0 if not scenes else segments[sc.start_index].start
            if scenes:
                scenes[-1]["end"] = start
            scenes.append({"start": start, "end": None, "mood": sc.mood, "label": sc.description})
    return {"chapters": chapters, "scenes": scenes, "title_ideas": ov.title_ideas, "description": ov.description,
            "thumbnail_text": ov.thumbnail_text, "tags": ov.tags}
