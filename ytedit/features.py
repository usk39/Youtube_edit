"""自動化できる機能の一覧と、選択(プリセット/カンマ区切り)の解釈。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    description: str
    requested: bool  # True = ご依頼の必須項目 / False = 追加提案の機能


FEATURES: list[Feature] = [
    Feature("bgm", "BGM追加", "話題の雰囲気に合うBGMをネットから自動取得。尺に合わせてループし、声の間は音量を下げる(ダッキング)", True),
    Feature("materials", "素材挿入", "セリフのキーワードに合う画像をネットから自動取得してポップ表示", True),
    Feature("background", "背景画像", "話題に合う背景画像をネットから自動取得。元動画を枠付きで配置し、チャプターごとに背景を切替", True),
    Feature("expressions", "キャラ表情", "すみれ/あおいの立ち絵を、セリフの感情に合わせて表情切替(漫符＋動き)", True),
    Feature("audio", "音声調整", "ノイズ除去・低音カット・コンプ・ラウドネス正規化(-14LUFS)", True),
    Feature("se", "効果音", "驚き/笑い/ポイント/疑問/ツッコミ/場面転換などの効果音をネットから自動取得して挿入", True),
    Feature("cutin", "カットイン", "盛り上がる場面でキャラ＋キーワードの帯がスライドイン", True),
    Feature("subtitles", "字幕(自動改行)", "話者で色分けした字幕を、区切りのいい所で1行または2行に自動改行", True),
    Feature("wipe", "丸顔ワイプ", "話している人の顔を丸ワイプ表示(顔出し動画も丸抜き可)", False),
    Feature("silence_cut", "無音カット", "間延びした無音部分を自動でカットしてテンポアップ", False),
    Feature("popup", "登録呼びかけ", "「お願いがあるの」の場面でチャンネル登録/高評価/コメント/ハイプのバナー表示", False),
    Feature("chapters", "チャプター/概要欄", "YouTube用チャプター・タイトル案・概要欄・タグ・素材クレジットを自動生成", False),
    Feature("thumbnail", "サムネイル", "一番盛り上がった場面からサムネイル画像を自動生成", False),
    Feature("shorts", "ショート切り出し", "盛り上がり区間を縦型(9:16)ショート動画として書き出し", False),
]

FEATURE_KEYS = [f.key for f in FEATURES]
FEATURE_MAP = {f.key: f for f in FEATURES}

PRESETS: dict[str, list[str]] = {
    "all": FEATURE_KEYS,
    "requested": [f.key for f in FEATURES if f.requested],
    "standard": [k for k in FEATURE_KEYS if k not in ("shorts", "wipe")],
    "light": ["bgm", "audio", "se", "subtitles"],
}


def parse_features(spec: str | None) -> list[str]:
    """"bgm,se,-wipe" / "standard" / "all,-shorts" のような指定を機能キーのリストに変換する。"""
    if not spec:
        return list(PRESETS["standard"])
    selected: list[str] = []
    for raw in spec.replace(" ", "").split(","):
        if not raw:
            continue
        remove = raw.startswith("-")
        name = raw.lstrip("-+")
        keys = PRESETS.get(name) or ([name] if name in FEATURE_MAP else None)
        if keys is None:
            raise ValueError(f"不明な機能/プリセット: {name}  (使えるもの: {', '.join(FEATURE_KEYS + list(PRESETS))})")
        for k in keys:
            if remove and k in selected:
                selected.remove(k)
            elif not remove and k not in selected:
                selected.append(k)
    return [k for k in FEATURE_KEYS if k in selected]


def interactive_select(default: list[str] | None = None) -> list[str]:
    """ターミナルで番号を入力して機能を選ぶ。"""
    chosen = set(default or PRESETS["standard"])
    while True:
        print("\n=== 自動化する項目を選んでください ===")
        for i, f in enumerate(FEATURES, 1):
            mark = "[x]" if f.key in chosen else "[ ]"
            tag = "" if f.requested else " (追加機能)"
            print(f" {i:2d}. {mark} {f.label}{tag} - {f.description}")
        print("番号(例: 1 3 5)で ON/OFF 切替 / a=全部 / n=全解除 / Enter=決定")
        ans = input("> ").strip().lower()
        if ans == "":
            return [k for k in FEATURE_KEYS if k in chosen]
        if ans == "a":
            chosen = set(FEATURE_KEYS)
            continue
        if ans == "n":
            chosen = set()
            continue
        for tok in ans.replace(",", " ").split():
            if tok.isdigit() and 1 <= int(tok) <= len(FEATURES):
                chosen ^= {FEATURES[int(tok) - 1].key}
