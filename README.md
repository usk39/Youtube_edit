# ytedit — すみれ&あおい 動画編集 自動化ツール

時事ニュース系チャンネル(すみれ&あおい)向けの動画編集を自動化するツールです。
**動画ファイル(.mp4)か URL を渡すと、選んだ項目を自動で編集して書き出します。**
BGM・効果音・素材画像・背景は **ネットから自動で取ってきます**(手持ち素材も使えます)。

## できること(項目ごとに ON/OFF を選べます)

| キー | 項目 | 内容 |
|---|---|---|
| `bgm` | BGM追加 | 話題の雰囲気(落ち着き/明るい/緊迫)に合う曲を**ネットから取得**。ループ＆フェード、声の間は自動で音量ダウン |
| `materials` | 素材挿入 | セリフのキーワードに合う画像を**ネットから取得**してポップ表示 |
| `background` | 背景画像 | 話題に合う背景写真を**ネットから取得**(少しぼかして元動画を目立たせる)。チャプターごとに切替 |
| `expressions` | キャラ表情 | すみれ/あおいの立ち絵を感情に合わせて切替。立ち絵1枚から表情差分(漫符)を自動生成。驚き=ジャンプ、怒り=震え等の動き付き |
| `audio` | 音声調整 | 低音カット・ノイズ除去・コンプレッサー・ラウドネス正規化(-14 LUFS = YouTube 基準) |
| `se` | 効果音 | 驚き/笑い/ポイント/疑問/ツッコミ/場面転換の効果音を**ネットから取得**して挿入(鳴らしすぎ防止付き) |
| `cutin` | カットイン | 山場でキャラ＋キーワードの帯がスライドイン |
| `subtitles` | 字幕(自動改行) | 話者で色分け。**区切りのいい所(文節・句読点)で1行または2行に自動改行**。長いセリフは文の切れ目で次の字幕へ |
| **追加機能** | | |
| `wipe` | 丸顔ワイプ | 話している人の顔を丸ワイプ表示(顔出し動画の丸抜きも可) |
| `silence_cut` | 無音カット | 間延びした無音を詰めてテンポアップ |
| `popup` | 登録呼びかけ | 「…で、ここで、みんなにお願いがあるの。」でチャンネル登録/高評価/コメント/ハイプのバナー |
| `chapters` | チャプター/概要欄 | チャプター・タイトル案・概要欄・タグ・素材クレジットを `description.txt` に |
| `thumbnail` | サムネイル | 一番盛り上がった場面＋煽り文句＋キャラでサムネ自動生成 |
| `shorts` | ショート切り出し | 盛り上がり区間を縦型 9:16 のショート動画に |

いつも自動で作られるもの: `credits.txt`(ネット素材のクレジット)、`review.html`(使った素材を一覧で確認するページ)

プリセット: `standard`(ワイプ・ショート以外すべて・既定) / `requested`(ご依頼の8項目) / `all` / `light`

## セットアップ

```bash
pip install -e ".[full]"            # ffmpeg も自動で入ります
ytedit init-assets                  # 仮素材(ネットが使えないときの予備)を assets/ に作成

# キャラクターの立ち絵を登録 (1枚から9種類の表情差分を自動生成。白背景でも自動で透過)
ytedit add-character aoi    あおい.webp
ytedit add-character sumire すみれ.webp
```

### ネット素材の取得元

| 種類 | 取得元 | API キー |
|---|---|---|
| 画像・背景 | Pixabay(日本語検索可) / Pexels / Openverse | Openverse は不要。Pixabay・Pexels は無料登録で取得 |
| 効果音 | Freesound / Openverse | Openverse は不要。Freesound は無料登録 |
| BGM | Jamendo / Openverse | Openverse は不要。Jamendo は無料登録 |

**キーが無くても Openverse から取得できます**が、Pixabay・Freesound・Jamendo のキーを入れると素材の質と量が上がります。
キーは `config.yaml` の `online:` か環境変数(`PIXABAY_API_KEY` `PEXELS_API_KEY` `FREESOUND_API_KEY` `JAMENDO_CLIENT_ID`)で指定します。

- **商用利用OK・改変OKのライセンスだけ**を使います(非営利限定 NC・改変禁止 ND は除外)。
- CC BY など表記が必要な素材は `credits.txt` と `description.txt` に自動でクレジットを書き出すので、**概要欄に必ず貼ってください**。
- 取得した素材は `assets/_online/` に保存され、次回からは再ダウンロードしません。
- 自動で選んだ素材が内容に合わないこともあります。公開前に `review.html` で確認してください。

## 使い方

```bash
ytedit run 動画.mp4 --script 台本.txt          # 項目の選択メニューが出ます
ytedit run https://www.youtube.com/watch?v=xxxx -f bgm,se,audio,subtitles
ytedit run 動画.mp4 -f standard,-background    # standard から背景だけ外す
ytedit run 動画.mp4 --offline                  # ネットを使わず assets/ の手持ち素材だけで
ytedit gui                                     # ブラウザの操作画面
```

台本(`--script`)を渡すと、話者・字幕・表情の精度が大きく上がります。いつもの「あおい:」「すみれ:」形式のまま使えます。

出力(`output/<動画名>/`): `final.mp4` / `plan.json` / `review.html` / `credits.txt` / `subtitles.srt` / `description.txt` / `thumbnail.png` / `short.mp4`

`plan.json` を手で直して `ytedit render output/<動画名>/plan.json` で再書き出しできます(素材の差し替え・削除、カットインの文字変更など)。

## 精度を上げる

- `ANTHROPIC_API_KEY` を設定すると、Claude がセリフごとの表情・効果音・カットイン、素材の英語検索語、チャプター・タイトル案・概要欄を判断します(無ければキーワード辞書で判断)。
- 本物の表情差分画像があれば、`assets/characters/<sumire|aoi>/<表情>.png` を置き換えるとそちらが使われます。

## 仕組み

```
入力(mp4/URL) → 無音カット → セリフ取得(台本同期/音声認識) → 話者推定 → 内容解析
  → 素材取得(ネット/手持ち) → plan.json → ffmpeg でレンダリング → サムネ/ショート/概要欄/クレジット
```

## テスト

```bash
pip install -e ".[dev]"
pytest
```
