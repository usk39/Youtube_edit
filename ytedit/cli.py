"""コマンドライン入口。

  ytedit run <動画ファイル or URL> [-f bgm,se,...] [--script 台本.txt]
  ytedit render output/xxx/plan.json      # plan.json を手直しして再レンダリング
  ytedit features                         # 機能一覧
  ytedit add-character aoi あおい.png     # 立ち絵1枚から表情差分を自動生成して登録
  ytedit init-assets                      # お試し用の仮素材を作成
  ytedit gui                              # ブラウザ画面で操作
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .features import FEATURES, PRESETS, interactive_select, parse_features


def _cmd_features(_args) -> int:
    print("機能キー        内容")
    for f in FEATURES:
        tag = "" if f.requested else " (追加機能)"
        print(f"  {f.key:14s}{f.label}{tag}: {f.description}")
    print("\nプリセット:")
    for k, v in PRESETS.items():
        print(f"  {k:14s}{', '.join(v)}")
    print("\n例: -f standard,-wipe   -f bgm,se,audio   -f all")
    return 0


def _cmd_run(args) -> int:
    from .pipeline import run

    cfg = load_config(args.config)
    if args.no_llm:
        cfg["llm"]["enabled"] = False
    if args.offline:
        cfg["online"]["enabled"] = False
    if args.wipe_video:
        cfg["wipe"]["video"] = args.wipe_video
    if args.features:
        features = parse_features(args.features)
    elif args.interactive or sys.stdin.isatty():
        features = interactive_select()
    else:
        features = parse_features(None)
    run(args.input, features, cfg, script=args.script, srt=args.srt, out_dir=args.out, plan_only=args.plan_only)
    return 0


def _cmd_render(args) -> int:
    from .pipeline import render_plan_file

    render_plan_file(args.plan, load_config(args.config))
    return 0


def _cmd_init_assets(args) -> int:
    from .sample_assets import init_assets

    cfg = load_config(args.config)
    root = init_assets(args.dir or cfg["assets_dir"], force=args.force)
    print(f"仮素材を作成しました: {root}")
    return 0


def _cmd_add_character(args) -> int:
    from .characters import add_character

    cfg = load_config(args.config)
    if args.char not in cfg["characters"]:
        raise ValueError(f"キャラ ID は {', '.join(cfg['characters'])} のどれかにしてください")
    written = add_character(args.char, args.image, cfg["assets_dir"], cfg["expressions"]["head_ratio"], args.force,
                            cfg.get("font_path"))
    d = f"{cfg['assets_dir']}/characters/{args.char}"
    if written:
        print(f"{args.char} の表情差分を {len(written)} 枚作成しました: {d}")
        if Path(d, "face_check.png").exists():
            print(f"目と口の位置の確認用画像: {d}/face_check.png (赤丸=目、青枠=口)\n"
                  f"  ずれていたら {d}/face.json の座標を直し、\"manual\": true にして --force で再実行してください")
    else:
        print(f"{d} に手描きの表情差分があるため作成しませんでした(上書きするなら --force)")
    return 0


def _cmd_gui(args) -> int:
    from .gui import launch

    launch(args.config, share=args.share)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ytedit", description="すみれ&あおい 動画編集 自動化ツール")
    ap.add_argument("-c", "--config", help="設定ファイル (既定: ./config.yaml があれば使用)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="動画を自動編集する")
    r.add_argument("input", help="動画ファイル(.mp4 等)または YouTube 等の URL")
    r.add_argument("-f", "--features", help="使う機能(カンマ区切り/プリセット)。省略時は選択メニューを表示")
    r.add_argument("-i", "--interactive", action="store_true", help="機能を選択メニューで選ぶ")
    r.add_argument("--script", help="台本テキスト(「あおい:」「すみれ:」形式)。話者と字幕が正確になる")
    r.add_argument("--srt", help="字幕ファイル(SRT)。「すみれ：」等で始まる行は話者として扱う")
    r.add_argument("--wipe-video", help="丸ワイプに使う顔出し動画")
    r.add_argument("-o", "--out", help="出力フォルダ")
    r.add_argument("--plan-only", action="store_true", help="plan.json だけ作ってレンダリングしない")
    r.add_argument("--no-llm", action="store_true", help="Claude 解析を使わない")
    r.add_argument("--offline", action="store_true", help="ネットから素材を取らず、assets/ の手持ち素材だけを使う")
    r.set_defaults(func=_cmd_run)

    p = sub.add_parser("render", help="plan.json から動画を書き出す")
    p.add_argument("plan")
    p.set_defaults(func=_cmd_render)

    f = sub.add_parser("features", help="機能とプリセットの一覧")
    f.set_defaults(func=_cmd_features)

    ac = sub.add_parser("add-character", help="立ち絵1枚から表情差分(目・口・眉の描き換え＋漫符)を自動生成して登録")
    ac.add_argument("char", help="キャラ ID (sumire / aoi)")
    ac.add_argument("image", help="立ち絵画像 (png/webp/jpg。白背景なら自動で透過)")
    ac.add_argument("--force", action="store_true", help="既存の表情画像も上書きする")
    ac.set_defaults(func=_cmd_add_character)

    a = sub.add_parser("init-assets", help="お試し用の仮素材(立ち絵/BGM/効果音/素材/背景)を作る")
    a.add_argument("--dir")
    a.add_argument("--force", action="store_true")
    a.set_defaults(func=_cmd_init_assets)

    g = sub.add_parser("gui", help="ブラウザの操作画面を起動")
    g.add_argument("--share", action="store_true")
    g.set_defaults(func=_cmd_gui)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n中断しました")
        return 130
    except Exception as e:
        print(f"\n[エラー] {e}", file=sys.stderr)
        return 1
