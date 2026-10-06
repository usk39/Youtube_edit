"""字幕の自動改行。区切りのいい所(文節・句読点)で 1 行 または 2 行にする。

- 1 行に収まるなら 1 行のまま。
- 収まらなければ、文節の切れ目のうち「2 行の長さが揃い、読点の後ろなど自然な位置」で 2 行に。
- 2 行にも収まらない長いセリフは、文の切れ目を優先して複数の字幕(ページ)に分ける。
- 行頭に「、」「。」「ー」や小さい「っ」等が来ないようにする(禁則処理)。

文節の判定は BudouX(Google 製の日本語改行ライブラリ)を使い、無ければ簡易ルールで代用する。
"""

from __future__ import annotations

import re
from functools import lru_cache

SENTENCE_END = "。！？!?…"
SOFT_END = "、，,"
NO_LINE_START = set("、。，．,.！？!?）)」』】ー〜ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ…")
PARTICLE_END = ("は", "が", "を", "に", "で", "と", "も", "へ", "や", "から", "まで", "より", "けど", "ので", "って", "ても", "たら", "ながら")


@lru_cache(maxsize=1)
def _budoux():
    try:
        import budoux  # type: ignore

        return budoux.load_default_japanese_parser()
    except Exception:
        return None


def _char_class(ch: str) -> str:
    if re.match(r"[ぁ-ゖ]", ch):
        return "h"
    if re.match(r"[ァ-ヺー]", ch):
        return "k"
    if re.match(r"[一-龥々〆]", ch):
        return "j"
    if re.match(r"[A-Za-z0-9０-９Ａ-Ｚａ-ｚ%％.]", ch):
        return "a"
    return "p"


def _heuristic_phrases(text: str) -> list[str]:
    """簡易文節分割: ひらがな→漢字/カタカナ/英数 の変わり目と、句読点の後ろで切る。"""
    out, cur = [], ""
    for i, ch in enumerate(text):
        if cur:
            prev = text[i - 1]
            boundary = (prev in SENTENCE_END + SOFT_END or prev in " 　") and ch not in NO_LINE_START
            boundary |= _char_class(prev) == "h" and _char_class(ch) in "kja" and ch not in NO_LINE_START
            boundary |= ch in "「（(『【"
            if boundary:
                out.append(cur)
                cur = ""
        cur += ch
    if cur:
        out.append(cur)
    return out


def phrases(text: str) -> list[str]:
    parser = _budoux()
    ps = parser.parse(text) if parser else _heuristic_phrases(text)
    # 禁則: 行頭に来てはいけない文字で始まる文節は、前の文節にくっつける
    merged: list[str] = []
    for p in ps:
        if merged and p and p[0] in NO_LINE_START:
            merged[-1] += p
        elif p:
            merged.append(p)
    return merged


_TRAIL = ""  # 長さを数えるときに無視する行末の文字(句点を消す設定のとき「。」)


def _len(line: str) -> int:
    return len(line.rstrip(_TRAIL)) if _TRAIL else len(line)


def _boundary_bonus(left: str) -> float:
    """left の直後で改行したときの「区切りの良さ」(小さいほど良い)。"""
    if not left:
        return 0
    if left[-1] in SENTENCE_END:
        return -8
    if left[-1] in SOFT_END or left[-1] in " 　":
        return -6
    if left.endswith(PARTICLE_END):
        return -2
    if left.endswith("の"):
        return 3  # 「〇〇の / 話題」は少し不自然
    return 0


def _hard_split(text: str, max_chars: int) -> list[str]:
    """文節が長すぎるとき用: 禁則を守って文字数で切る。"""
    out = []
    while len(text) > max_chars:
        cut = max_chars
        while cut > 1 and text[cut] in NO_LINE_START:
            cut -= 1
        out.append(text[:cut])
        text = text[cut:]
    return out + ([text] if text else [])


def _split_two(ps: list[str], max_chars: int) -> tuple[list[str], float] | None:
    total = "".join(ps).strip()
    if _len(total) <= max_chars:
        return [total], 0.0
    best = None
    for k in range(1, len(ps)):
        a, b = "".join(ps[:k]).strip(), "".join(ps[k:]).strip()
        if _len(a) > max_chars or _len(b) > max_chars:
            continue
        cost = abs(_len(a) - _len(b)) * 0.6 + _boundary_bonus(a)
        if best is None or cost < best[1]:
            best = ([a, b], cost)
    return best


def _units(text: str, max_chars: int) -> list[str]:
    out = []
    for p in phrases(text):
        out += _hard_split(p, max_chars) if len(p) > max_chars else [p]
    return out


def break_text(text: str, max_chars: int, max_lines: int = 2, ignore_trailing: str = "") -> list[list[str]]:
    """テキストを字幕ページのリストに。各ページは 1〜max_lines 行。

    ignore_trailing: 表示時に行末から消す文字(例「。」)。文字数の計算から除く。
    """
    global _TRAIL
    _TRAIL = ignore_trailing
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    if _len(text) <= max_chars:
        return [[text]]
    us = _units(text, max_chars)
    n = len(us)
    cap = max_chars * max_lines
    INF = float("inf")
    dp = [INF] * (n + 1)
    choice: list = [None] * (n + 1)
    dp[0] = 0.0
    for i in range(1, n + 1):
        for j in range(i - 1, -1, -1):
            page = us[j:i]
            if _len("".join(page)) > cap:
                break
            res = _split_two(page, max_chars) if max_lines >= 2 else (
                ([page[0]], 0.0) if len(page) == 1 or len("".join(page)) <= max_chars else None)
            if res is None or dp[j] == INF:
                continue
            lines, cost = res
            if max_lines == 1 and len("".join(page)) > max_chars:
                continue
            last = "".join(page)
            cost += 100  # ページ数は少ないほど良い
            if i < n:
                cost += 0 if last[-1] in SENTENCE_END else (4 if last[-1] in SOFT_END else 18)
                if len(last) < cap * 0.35:
                    cost += 12  # 短すぎるページは避ける
            if dp[j] + cost < dp[i]:
                dp[i] = dp[j] + cost
                choice[i] = (j, lines)
    if dp[n] == INF:  # 念のため
        return [[l] for l in _hard_split(text, max_chars)]
    pages, i = [], n
    while i > 0:
        j, lines = choice[i]
        pages.append(lines)
        i = j
    return pages[::-1]


def tidy(line: str, mode: str = "strip_period") -> str:
    """字幕向けに句読点を整える。strip_period=行末の「。」を消す / space=「、。」を空白に / keep=そのまま"""
    if mode == "strip_period":
        return line.rstrip("。").rstrip() or line
    if mode == "space":
        return re.sub(r"[、。]+", "　", line).strip("　") or line
    return line
