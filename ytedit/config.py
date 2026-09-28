"""設定の既定値と YAML 読み込み。config.yaml に書いた値だけが既定値を上書きする。"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "assets_dir": "assets",
    "output_dir": "output",
    "font_path": None,  # 未指定なら日本語フォントを自動検出
    "output": {"width": 1920, "height": 1080, "fps": 30, "crf": 20, "preset": "medium", "audio_bitrate": "192k"},
    "characters": {
        "sumire": {"names": ["すみれ", "スミレ", "sumire"], "color": "#8E5CF7", "side": "right"},
        "aoi": {"names": ["あおい", "アオイ", "葵", "aoi"], "color": "#1E9BE8", "side": "left"},
    },
    "transcribe": {"model": "small", "language": "ja", "device": "auto", "compute_type": "auto"},
    # 台本も SRT も無いとき、声の高さで話者を推定する。高い声の方をこのキャラにする
    "speaker": {"higher_pitch": "aoi"},
    "llm": {"enabled": "auto", "model": "claude-opus-5", "chunk_size": 80},
    "silence_cut": {"noise_db": -38, "min_silence": 0.7, "keep_padding": 0.18},
    "audio": {"target_lufs": -14, "true_peak": -1.5, "highpass_hz": 80, "denoise": True, "compressor": True},
    "bgm": {"volume_db": -24, "ducking": True, "fade_in": 2.0, "fade_out": 3.0, "mood": "auto"},
    "background": {"video_scale": 0.72, "video_top": 36, "border": 8, "border_color": "#FFFFFF", "per_chapter": True},
    "materials": {"min_duration": 3.0, "max_duration": 7.0, "max_per_minute": 6, "box": [0.30, 0.10, 0.40, 0.42]},
    "expressions": {"height_ratio": 0.50, "margin_x": 10, "bob": True},
    "se": {"volume_db": -6, "min_gap": 2.5},
    "cutin": {"duration": 1.6, "max_count": 8, "min_gap": 25.0, "height_ratio": 0.36},
    "wipe": {"diameter": 240, "border": 8, "position": "top-right", "margin": 30, "video": None},
    "subtitles": {"font_size": 60, "max_chars_per_line": 22, "outline": 6, "margin_v": 30},
    "popup": {"duration": 7.0, "triggers": ["お願いがあるの", "チャンネル登録"]},
    "shorts": {"length": 45.0},
    "pexels_api_key": None,  # 設定すると、手持ち素材に無いキーワードを Pexels から自動取得
}


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    candidates = [Path(path)] if path else [Path("config.yaml")]
    for p in candidates:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                cfg = deep_merge(cfg, yaml.safe_load(f) or {})
        elif path:
            raise FileNotFoundError(f"設定ファイルが見つかりません: {p}")
    return cfg


def character_ids(cfg: dict) -> list[str]:
    return list(cfg["characters"].keys())


def display_name(cfg: dict, char_id: str) -> str:
    return cfg["characters"][char_id]["names"][0]
