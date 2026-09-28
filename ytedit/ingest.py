"""入力(URL または動画/音声ファイル)の受け取り。"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

URL_RE = re.compile(r"^https?://", re.I)


def is_url(s: str) -> bool:
    return bool(URL_RE.match(s.strip()))


def download(url: str, dest_dir: Path) -> Path:
    """yt-dlp で動画をダウンロードして mp4 のパスを返す。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    template = str(dest_dir / "source.%(ext)s")
    fmt = "bv*[height<=1080]+ba/b[height<=1080]/b"
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        yt_dlp = None
    if yt_dlp is not None:
        from .ffmpeg import ffmpeg_exe

        opts = {"outtmpl": template, "format": fmt, "merge_output_format": "mp4",
                "ffmpeg_location": ffmpeg_exe(), "quiet": True, "noprogress": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    elif shutil.which("yt-dlp"):
        subprocess.run(["yt-dlp", "-f", fmt, "--merge-output-format", "mp4", "-o", template, url], check=True)
    else:
        raise RuntimeError("URL から取得するには yt-dlp が必要です: pip install yt-dlp")
    files = sorted(dest_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        raise RuntimeError(f"ダウンロードに失敗しました: {url}")
    return files[0]


def resolve_input(src: str, work_dir: Path) -> Path:
    if is_url(src):
        print(f"[入力] URL からダウンロード中: {src}")
        return download(src, work_dir)
    p = Path(src).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {p}")
    return p.resolve()
