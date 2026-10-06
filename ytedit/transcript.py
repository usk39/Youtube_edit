"""セリフ(セグメント)の取得: SRT / 台本テキスト / 音声認識 と、台本と音声のタイミング合わせ。"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None
    emotion: str = "normal"
    emphasis: float = 0.0
    se: str | None = None
    cutin: bool = False
    cutin_text: str = ""
    keywords: list[str] = field(default_factory=list)
    image_query: str = ""  # ネット画像検索用の英語クエリ(Claude 解析時)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Word:
    start: float
    end: float
    text: str


# ---------------------------------------------------------------- 話者名
def _name_table(characters: dict) -> list[tuple[str, str]]:
    table = [(name, cid) for cid, c in characters.items() for name in c["names"]]
    return sorted(table, key=lambda x: -len(x[0]))


def split_speaker_prefix(text: str, characters: dict) -> tuple[str | None, str]:
    """「あおい：こんにちは」→ ("aoi", "こんにちは")"""
    s = text.strip()
    for name, cid in _name_table(characters):
        m = re.match(rf"^[【\[(（]?{re.escape(name)}[】\])）]?\s*[:：「]\s*", s)
        if m:
            body = s[m.end():]
            if s[m.end() - 1] == "「":
                body = body.rstrip("」")
            return cid, body.strip()
    return None, s


# ---------------------------------------------------------------- SRT
def _ts(s: str) -> float:
    h, m, rest = s.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest)


def parse_srt(path: str | Path, characters: dict) -> list[Segment]:
    raw = Path(path).read_text(encoding="utf-8-sig")
    segs = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        a, b = [x.strip() for x in lines[idx].split("-->")]
        text = " ".join(lines[idx + 1:])
        spk, body = split_speaker_prefix(text, characters)
        segs.append(Segment(_ts(a), _ts(b.split()[0]), body, spk))
    return segs


def _fmt_srt(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(segments: list[Segment], path: str | Path, characters: dict) -> Path:
    out = []
    for i, s in enumerate(segments, 1):
        name = characters[s.speaker]["names"][0] + "：" if s.speaker in characters else ""
        out.append(f"{i}\n{_fmt_srt(s.start)} --> {_fmt_srt(s.end)}\n{name}{s.text}\n")
    Path(path).write_text("\n".join(out), encoding="utf-8")
    return Path(path)


# ---------------------------------------------------------------- 台本
def parse_script(path: str | Path, characters: dict) -> list[tuple[str, str]]:
    """「あおい:」「すみれ:」形式の台本からセリフを取り出す。話者の無い行は直前のセリフの続きとみなす。"""
    lines: list[list[str]] = []
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        s = raw.strip()
        if not s:
            continue
        spk, body = split_speaker_prefix(s, characters)
        if spk:
            lines.append([spk, body])
        elif lines and not re.match(r"^[#＃【\[]|^(タイトル|title)\s*[:：]", s, re.I):
            lines[-1][1] += s
    return [(spk, body) for spk, body in lines if body]


# ---------------------------------------------------------------- 音声認識
def transcribe(audio_path: str | Path, cfg: dict) -> tuple[list[Segment], list[Word]]:
    """faster-whisper で文字起こし(単語タイムスタンプ付き)。"""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "音声認識には faster-whisper が必要です: pip install faster-whisper\n"
            "(または --script 台本.txt / --srt 字幕.srt を指定してください)"
        ) from e
    t = cfg["transcribe"]
    model = WhisperModel(t["model"], device=t["device"], compute_type=t["compute_type"])
    it, _ = model.transcribe(str(audio_path), language=t["language"], word_timestamps=True, vad_filter=True)
    segs, words = [], []
    for s in it:
        segs.append(Segment(s.start, s.end, s.text.strip()))
        for w in s.words or []:
            words.append(Word(w.start, w.end, w.word))
    return segs, words


# ---------------------------------------------------------------- 台本と音声の同期
_STRIP = re.compile(r"[\s、。，．,.!！?？「」『』（）()…・ー〜~\-―─♪☆★“”\"'’:：;；]")


def normalize(text: str) -> str:
    return _STRIP.sub("", unicodedata.normalize("NFKC", text)).lower()


def align_script_with_words(lines: list[tuple[str, str]], words: list[Word]) -> list[Segment]:
    """台本の文字列と認識結果の文字列を突き合わせ、台本の各行に時刻を付ける(文字は台本のものを使う)。"""
    w_chars, w_times = [], []
    for w in words:
        n = normalize(w.text)
        for i, ch in enumerate(n):
            w_chars.append(ch)
            w_times.append(w.start + (w.end - w.start) * (i + 0.5) / max(1, len(n)))
    s_chars, s_line = [], []
    for li, (_, text) in enumerate(lines):
        for ch in normalize(text):
            s_chars.append(ch)
            s_line.append(li)

    first: dict[int, float] = {}
    last: dict[int, float] = {}
    sm = difflib.SequenceMatcher(None, "".join(s_chars), "".join(w_chars), autojunk=False)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            li, t = s_line[a + k], w_times[b + k]
            first.setdefault(li, t)
            last[li] = t

    end_all = words[-1].end if words else 0.0
    segs = []
    for li, (spk, text) in enumerate(lines):
        segs.append(Segment(first.get(li, -1.0), last.get(li, -1.0), text, spk))
    _fill_missing_times(segs, end_all)
    for s in segs:  # 文字の中心時刻 → 発話区間に少し広げる
        s.start = max(0.0, s.start - 0.15)
        s.end = s.end + 0.25
    _fix_overlaps(segs)
    return segs


def voiced_intervals(silences: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    out, cur = [], 0.0
    for s, e in sorted(silences):
        if s > cur + 0.05:
            out.append((cur, s))
        cur = max(cur, e)
    if duration > cur + 0.05:
        out.append((cur, duration))
    return out


def align_script_with_silence(lines: list[tuple[str, str]], voiced: list[tuple[float, float]]) -> list[Segment]:
    """音声認識なしでの同期。ゆっくり/VOICEVOX 系のようにセリフ間に無音がある動画向け。"""
    if not lines or not voiced:
        return []
    if len(voiced) == len(lines):
        return [Segment(a, b, t, spk) for (a, b), (spk, t) in zip(voiced, lines)]
    total = sum(b - a for a, b in voiced)

    def at(pos: float) -> float:  # 発話区間だけをつないだ時間軸上の位置 → 実時間
        for a, b in voiced:
            if pos <= b - a:
                return a + pos
            pos -= b - a
        return voiced[-1][1]

    weights = [max(1, len(normalize(t))) for _, t in lines]
    wsum = float(sum(weights))
    gaps = [(voiced[i][1] + voiced[i + 1][0]) / 2 for i in range(len(voiced) - 1)]
    bounds, acc, prev = [], 0.0, 0.0
    for w in weights[:-1]:
        acc += w
        t = at(total * acc / wsum)
        near = [g for g in gaps if g > prev and abs(g - t) < 1.5]
        if near:
            t = min(near, key=lambda g: abs(g - t))
        t = max(t, prev + 0.2)
        bounds.append(t)
        prev = t
    edges = [voiced[0][0], *bounds, voiced[-1][1]]
    segs = [Segment(edges[i], edges[i + 1], t, spk) for i, (spk, t) in enumerate(lines)]
    for s in segs:  # 区間の端の無音を削る
        inside = [(max(a, s.start), min(b, s.end)) for a, b in voiced if b > s.start and a < s.end]
        if inside:
            s.start, s.end = inside[0][0], inside[-1][1]
    return segs


def _fill_missing_times(segs: list[Segment], end_all: float) -> None:
    n = len(segs)
    for i, s in enumerate(segs):
        if s.start >= 0:
            continue
        prev_end = next((segs[j].end for j in range(i - 1, -1, -1) if segs[j].end >= 0), 0.0)
        nxt = next((j for j in range(i + 1, n) if segs[j].start >= 0), None)
        next_start = segs[nxt].start if nxt is not None else end_all
        k = (nxt if nxt is not None else n) - i
        span = max(0.0, next_start - prev_end) / max(1, k)
        s.start = prev_end
        s.end = prev_end + span
    for s in segs:
        if s.end < s.start:
            s.end = s.start + 0.5


def _fix_overlaps(segs: list[Segment]) -> None:
    for a, b in zip(segs, segs[1:]):
        if a.end > b.start:
            a.end = max(a.start + 0.1, b.start)
