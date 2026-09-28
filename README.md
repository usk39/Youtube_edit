# ytedit — すみれ&あおい 動画編集 自動化ツール

時事ニュース系チャンネル(すみれ&あおい)向けの動画編集を自動化するツールです。
**動画ファイル(.mp4)か URL を渡すと、選んだ項目を自動で編集して書き出します。**

## できること(項目ごとに ON/OFF を選べます)

| キー | 項目 | 内容 |
|---|---|---|
| `bgm` | BGM追加 | 尺に合わせてループ＆フェード。声が出ている間は自動で音量を下げる(ダッキング)。チャプターごとに曲の雰囲気を切替 |
| `materials` | 素材挿入 | セリフのキーワードに合う画像素材をポップ表示 |
| `background` | 背景画像 | 背景画像を敷き、元動画を白枠付きで配置。チャプターごとに背景を切替 |
| `expressions` | キャラ表情 | すみれ/あおいの立ち絵を、セリフの感情に合わせて表情切替。話している方は小さく揺れる |
| `audio` | 音声調整 | 低音カット・ノイズ除去・コンプレッサー・ラウドネス正規化(-14 LUFS = YouTube 基準) |
| `se` | 効果音 | 驚き/笑い/ポイント/疑問/ツッコミ/場面転換を自動挿入(間隔を空けて鳴らしすぎ防止) |
| `cutin` | カットイン | 山場でキャラ＋キーワードの帯がスライドイン |
| `wipe` | 丸顔ワイプ | 話している人の顔を丸ワイプ表示。顔出し動画を丸抜きすることも可 |
| **追加機能** | | |
| `subtitles` | 自動字幕 | 話者ごとに色分けしたテロップ。`subtitles.srt` も出力 |
| `silence_cut` | 無音カット | 間延びした無音を詰めてテンポアップ |
| `popup` | 登録呼びかけ | すみれの「…で、ここで、みんなにお願いがあるの。」でチャンネル登録/高評価/コメント/ハイプのバナー |
| `chapters` | チャプター/概要欄 | YouTube チャプター・タイトル案・概要欄・タグを `description.txt` に出力 |
| `thumbnail` | サムネイル | 一番盛り上がった場面＋煽り文句＋キャラでサムネを自動生成 |
| `shorts` | ショート切り出し | 盛り上がり区間を縦型 9:16 のショート動画に |

プリセット: `standard`(ショート以外すべて・既定) / `all` / `requested`(ご依頼の8項目) / `light`(BGM・音声・効果音・字幕)

## セットアップ

```bash
pip install -e .            # 最小構成 (ffmpeg も自動で入ります)
pip install -e ".[full]"    # 音声認識・Claude解析・URL取得・GUI も全部入り
ytedit init-assets          # お試し用の仮素材(立ち絵・BGM・効果音・素材・背景)を assets/ に作成
cp config.example.yaml config.yaml   # 必要なら設定を編集
```

素材は `assets/` に置きます。置き方は [assets/README.md](assets/README.md) を参照してください。

## 使い方

```bash
# 選択メニューで項目を選んで開始
ytedit run 動画.mp4

# 項目を指定して開始 (URL も OK)
ytedit run https://www.youtube.com/watch?v=xxxx -f bgm,se,audio,expressions
ytedit run 動画.mp4 -f standard,-wipe          # standard から丸ワイプだけ外す

# 台本を渡すと、話者・字幕・表情の精度がぐっと上がります(おすすめ)
ytedit run 動画.mp4 --script 台本.txt

# 丸ワイプに顔出し動画を使う
ytedit run 動画.mp4 --wipe-video face.mp4

# ブラウザの操作画面で使う
ytedit gui
```

出力(`output/<動画名>/`):

- `final.mp4` … 完成動画
- `plan.json` … 編集プラン(いつ何を出すか)。手で直して `ytedit render output/<動画名>/plan.json` で再書き出しできます
- `subtitles.srt` / `description.txt` / `thumbnail.png` / `short.mp4`

### 台本の書式

これまでの台本フォーマットのまま使えます。話者名の無い行は直前のセリフの続きとして扱います。

```
あおい:ねえねえ、すみれ。今日はどんな話題について話していくと?
すみれ:あおい、今日はね、〇〇の話題についてよ。
```

## 仕組み

```
入力(mp4/URL) → 無音カット → セリフ取得 → 話者推定 → 内容解析 → plan.json → ffmpeg でレンダリング → サムネ/ショート/概要欄
```

- **セリフ取得**: `--script` の台本を音声に同期(faster-whisper があれば認識結果と文字単位で突き合わせ、無ければセリフ間の無音で同期)。台本なしなら faster-whisper で文字起こし、`--srt` も可。
- **話者推定**: 台本が無いときは声の高さで2人を振り分け(`speaker.higher_pitch`)。
- **内容解析**: キーワード辞書によるルールベース(博多弁の毒舌も考慮)。`ANTHROPIC_API_KEY` を設定すると Claude がセリフごとの表情・効果音・カットイン・素材キーワード、チャプター・タイトル案・概要欄を判断します(失敗時はルールベースで続行)。
- **レンダリング**: 立ち絵・ワイプ・カットイン等は Pillow で完成サイズの PNG にしてから ffmpeg で重ねるので高速です。

## テスト

```bash
pip install -e ".[dev]"
pytest
```
