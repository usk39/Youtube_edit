"""ブラウザ操作画面 (Gradio)。`pip install gradio` の上で `ytedit gui`。"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

from .config import load_config
from .features import FEATURES, PRESETS


def launch(config_path: str | None = None, share: bool = False) -> None:
    try:
        import gradio as gr  # type: ignore
    except ImportError as e:
        raise RuntimeError("GUI には gradio が必要です: pip install gradio") from e
    from .pipeline import run

    labels = {f"{f.label}" + ("" if f.requested else " ★追加"): f.key for f in FEATURES}
    default_labels = [l for l, k in labels.items() if k in PRESETS["standard"]]

    def process(url, video, script, srt, wipe, chosen, use_llm, use_online):
        cfg = load_config(config_path)
        cfg["llm"]["enabled"] = "auto" if use_llm else False
        cfg["online"]["enabled"] = bool(use_online)
        if wipe is not None:
            cfg["wipe"]["video"] = wipe if isinstance(wipe, str) else wipe.name
        src = (url or "").strip() or (video if isinstance(video, str) else getattr(video, "name", None))
        if not src:
            raise gr.Error("動画ファイルか URL を指定してください")
        path = lambda x: None if x is None else (x if isinstance(x, str) else x.name)  # noqa: E731
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            res = run(src, [labels[c] for c in chosen], cfg, script=path(script), srt=path(srt))
        desc = Path(res["description"]).read_text(encoding="utf-8") if res.get("description") else ""
        return res.get("video"), res.get("thumbnail"), res.get("short"), desc, log.getvalue()

    with gr.Blocks(title="すみれ&あおい 自動編集") as app:
        gr.Markdown("## すみれ&あおい 動画編集 自動化ツール\n動画ファイルか URL を渡して、自動化したい項目を選んでください。")
        with gr.Row():
            with gr.Column():
                url = gr.Textbox(label="動画 URL (YouTube など)")
                video = gr.File(label="または動画ファイル (.mp4)", file_types=["video", "audio"])
                script = gr.File(label="台本 (任意・「あおい:」「すみれ:」形式の .txt)", file_types=[".txt"])
                srt = gr.File(label="字幕 SRT (任意)", file_types=[".srt"])
                wipe = gr.File(label="丸ワイプ用の顔出し動画 (任意)", file_types=["video"])
                chosen = gr.CheckboxGroup(list(labels), value=default_labels, label="自動化する項目")
                use_llm = gr.Checkbox(value=True, label="Claude で内容解析 (ANTHROPIC_API_KEY がある場合)")
                use_online = gr.Checkbox(value=True, label="BGM・効果音・画像をネットから自動取得")
                btn = gr.Button("編集スタート", variant="primary")
            with gr.Column():
                out_video = gr.Video(label="完成動画")
                out_thumb = gr.Image(label="サムネイル")
                out_short = gr.Video(label="ショート")
                out_desc = gr.Textbox(label="タイトル案・概要欄・チャプター", lines=10)
                out_log = gr.Textbox(label="ログ", lines=10)
        btn.click(process, [url, video, script, srt, wipe, chosen, use_llm, use_online],
                  [out_video, out_thumb, out_short, out_desc, out_log])
    app.launch(share=share)
