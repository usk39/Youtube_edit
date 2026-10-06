"""ffmpeg の実行・メディア情報の取得・無音検出。

ffmpeg が PATH に無い場合は imageio-ffmpeg 同梱のバイナリを使うので、別途インストール不要。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError as e:  # pragma: no cover
        raise FFmpegError("ffmpeg が見つかりません。`pip install imageio-ffmpeg` か ffmpeg をインストールしてください") from e
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str], cwd: str | Path | None = None, quiet: bool = True) -> str:
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", *[str(a) for a in args]]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-25:])
        raise FFmpegError(f"ffmpeg 失敗 (exit {proc.returncode}):\n{tail}")
    if not quiet:
        print(proc.stderr)
    return proc.stderr


def run_ffmpeg_with_frames(args: list[str], frames, cwd: str | Path | None = None) -> None:
    """標準入力(pipe:0)に生フレームを流し込みながら ffmpeg を実行する。"""
    import tempfile

    cmd = [ffmpeg_exe(), "-hide_banner", "-y", *[str(a) for a in args]]
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err)
        try:
            for buf in frames:
                proc.stdin.write(buf)
        except (BrokenPipeError, OSError):
            pass  # ffmpeg が先に終わった(長さ指定 -t に達した or エラー)
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
        code = proc.wait()
        if code != 0:
            err.seek(0)
            tail = "\n".join(err.read().decode("utf-8", "replace").strip().splitlines()[-25:])
            raise FFmpegError(f"ffmpeg 失敗 (exit {code}):\n{tail}")


@dataclass
class MediaInfo:
    duration: float
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0
    fps: float = 30.0


def probe(path: str | Path) -> MediaInfo:
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-nostdin", "-i", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    err = proc.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    if not m:
        raise FFmpegError(f"メディアを読み込めません: {path}\n{err[-800:]}")
    duration = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    info = MediaInfo(duration=duration, has_video=False, has_audio=False)
    for line in err.splitlines():
        if "Stream #" not in line:
            continue
        if "Video:" in line and "attached pic" not in line and not info.has_video:
            info.has_video = True
            size = re.search(r"\b(\d{2,5})x(\d{2,5})\b", line)
            if size:
                info.width, info.height = int(size[1]), int(size[2])
            fps = re.search(r"([\d.]+) fps", line) or re.search(r"([\d.]+) tbr", line)
            if fps:
                info.fps = float(fps[1])
        elif "Audio:" in line:
            info.has_audio = True
    return info


def detect_silences(path: str | Path, noise_db: float = -38, min_silence: float = 0.5) -> list[tuple[float, float]]:
    err = run_ffmpeg(["-i", path, "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", err)]
    duration = probe(path).duration
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else duration
        out.append((max(0.0, s), e))
    return out


def extract_audio(path: str | Path, out: str | Path, sample_rate: int = 16000) -> Path:
    run_ffmpeg(["-i", path, "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", out])
    return Path(out)


def extract_frame(path: str | Path, t: float, out: str | Path) -> Path:
    run_ffmpeg(["-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", out])
    return Path(out)
