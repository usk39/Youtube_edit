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
    "background": {"video_scale": 0.72, "video_top": 36, "border": 8, "border_color": "#FFFFFF", "per_chapter": True,
                   "blur": 4, "darken": 0.15},  # ネット写真は少しぼかして暗くし、元動画を目立たせる
    "materials": {"min_duration": 3.0, "max_duration": 7.0, "max_per_minute": 6, "box": [0.30, 0.10, 0.40, 0.42]},
    "expressions": {"height_ratio": 0.46, "margin_x": 10, "bob": True, "motion": True, "head_ratio": 0.6},
    "se": {"volume_db": -6, "min_gap": 2.5},
    "cutin": {"duration": 1.6, "max_count": 8, "min_gap": 25.0, "height_ratio": 0.36},
    "wipe": {"diameter": 240, "border": 8, "position": "top-right", "margin": 30, "video": None},
    # max_chars_per_line は上限。実際は画面幅とキャラの幅から自動計算した文字数との小さい方
    # punctuation: strip_period=行末の「。」を消す / space=「、。」を空白に / keep=そのまま
    "subtitles": {"font_size": 60, "max_chars_per_line": 20, "max_lines": 2, "outline": 6, "margin_v": 30,
                  "punctuation": "strip_period"},
    "popup": {"duration": 7.0, "triggers": ["お願いがあるの", "チャンネル登録"]},
    "shorts": {"length": 45.0},
    # ネットからの素材取得。API キーは環境変数(PIXABAY_API_KEY 等)でも指定できる
    "online": {
        "enabled": True,
        "prefer": "online",  # online=ネット優先(無ければ assets/ の手持ち素材) / local=手持ち優先
        "cache_dir": None,  # 既定: <assets_dir>/_online
        "allowed_licenses": ["cc0", "pdm", "by"],  # 商用・改変OKのみ。"by-sa" を足すことも可
        "max_downloads": 80,
        "pixabay_api_key": None,
        "pexels_api_key": None,
        "freesound_api_key": None,
        "jamendo_client_id": None,
    },
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
