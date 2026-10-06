import subprocess
import wave

import numpy as np
import pytest

from ytedit.config import DEFAULT_CONFIG, deep_merge
from ytedit.ffmpeg import ffmpeg_exe
from ytedit.sample_assets import init_assets

SCRIPT = """タイトル：テスト
あおい:ねえねえ、すみれ。今日はどんな話題について話していくと？
すみれ:あおい、今日はね、円安と物価の話題についてよ。実は、なんと過去最大の値上げなの！
あおい:えっ、まじで!? また値上げとか、ふざけとるやろ。
すみれ:つまり、ポイントは経済の仕組みなの。ここで、みんなにお願いがあるの。
"""
# (周波数, 秒)  周波数 0 は無音。あおい=高い声 / すみれ=低い声
VOICE = [(330, 2.0), (0, 0.6), (210, 2.5), (0, 0.6), (330, 1.8), (0, 0.6), (210, 2.2), (0, 0.8)]


def make_voice(path, sr=16000):
    parts = []
    for f, d in VOICE:
        t = np.arange(int(sr * d)) / sr
        parts.append(0.3 * np.sin(2 * np.pi * f * t) * (1 + 0.3 * np.sin(2 * np.pi * 3 * t)) if f else np.zeros_like(t))
    x = np.concatenate(parts)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    return len(x) / sr


@pytest.fixture(scope="session")
def assets(tmp_path_factory):
    return init_assets(tmp_path_factory.mktemp("assets"))


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    wav = d / "voice.wav"
    dur = make_voice(wav)
    mp4 = d / "test.mp4"
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=s=640x360:r=24:d={dur:.2f}",
                    "-i", str(wav), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(mp4)], check=True)
    script = d / "script.txt"
    script.write_text(SCRIPT, encoding="utf-8")
    return {"wav": wav, "mp4": mp4, "script": script, "dir": d}


@pytest.fixture()
def cfg(assets, tmp_path):
    return deep_merge(DEFAULT_CONFIG, {
        "assets_dir": str(assets), "output_dir": str(tmp_path / "out"),
        "output": {"width": 640, "height": 360, "fps": 24, "preset": "ultrafast"},
        "llm": {"enabled": False}, "cutin": {"min_gap": 3},
        "online": {"enabled": False, "cache_dir": str(tmp_path / "online_cache")},
    })
