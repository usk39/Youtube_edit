# 素材フォルダ

`ytedit init-assets` でお試し用の仮素材が作られます。本番用の素材に差し替えてください。
(このフォルダの中身は `.gitignore` で Git 管理外にしています)

```
assets/
├─ characters/
│   ├─ sumire/  normal.png smile.png laugh.png surprised.png angry.png sad.png thinking.png doya.png jito.png
│   │   └─ face/  (任意) 丸ワイプ用の顔アップ画像。同じファイル名で置く
│   └─ aoi/     (同上)
├─ bgm/
│   ├─ calm/    落ち着いた曲    ← チャプターごとに Claude が雰囲気を選ぶ
│   ├─ bright/  明るい曲
│   └─ tense/   緊迫感のある曲
├─ se/
│   ├─ surprise/ laugh/ point/ question/ shock/ transition/   ← セリフに応じて
│   ├─ cutin/    カットイン時
│   └─ popup/    登録呼びかけバナー時
├─ materials/   素材画像。ファイル名がタグ (例: 日銀_金利_グラフ.png)
│   └─ tags.yaml (任意) 追加タグ   例) 日銀_金利_グラフ.png: [利上げ, 植田総裁]
├─ backgrounds/ 背景画像。ファイル名がタグ。「default」を含むものが既定の背景
│   └─ tags.yaml (任意)
└─ fonts/       (任意) 字幕・カットイン用フォント (.ttf/.otf/.ttc)
```

- 立ち絵は **背景透過 PNG** にしてください。無い表情は近い表情(→ normal)で代用されます。
- `jito` = ジト目(あおいの毒舌用)、`doya` = ドヤ顔(すみれの解説の決め所用)。
- 音声は mp3 / wav / m4a / ogg / flac が使えます。BGM・効果音は利用規約を確認のうえ配置してください。
