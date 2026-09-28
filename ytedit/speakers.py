"""話者の推定。台本/SRT に話者が無いときに、声の高さ(基本周波数)で すみれ/あおい を振り分ける。"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .transcript import Segment


def load_wav(path: str | Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data, sr


def median_pitch(x: np.ndarray, sr: int, fmin: float = 70, fmax: float = 500) -> float | None:
    frame, hop = 1024, 512
    if len(x) < frame:
        return None
    lo, hi = int(sr / fmax), int(sr / fmin)
    rms_all = np.sqrt(np.mean(x ** 2)) + 1e-9
    f0s = []
    for i in range(0, len(x) - frame, hop):
        f = x[i:i + frame]
        if np.sqrt(np.mean(f ** 2)) < rms_all * 0.6:
            continue
        f = f - f.mean()
        spec = np.fft.rfft(f, n=2 * frame)
        ac = np.fft.irfft(spec * np.conj(spec))[:frame]
        if ac[0] <= 0:
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / ac[0] > 0.3:
            f0s.append(sr / lag)
    return float(np.median(f0s)) if f0s else None


def assign_by_pitch(segments: list[Segment], wav_path: str | Path, char_ids: list[str], higher: str) -> None:
    """話者未設定のセグメントに、声の高さで2人を割り当てる。"""
    todo = [s for s in segments if s.speaker is None]
    if not todo:
        return
    lower = next(c for c in char_ids if c != higher) if len(char_ids) > 1 else higher
    x, sr = load_wav(wav_path)
    pitches = [median_pitch(x[int(s.start * sr):int(s.end * sr)], sr) for s in todo]
    valid = np.array([p for p in pitches if p])
    if len(valid) < 2:
        for i, s in enumerate(todo):  # 推定できなければ交互に
            s.speaker = char_ids[i % len(char_ids)]
        return
    # 1次元 k-means (k=2)
    c = np.array([valid.min(), valid.max()])
    for _ in range(20):
        lab = np.abs(valid[:, None] - c[None, :]).argmin(axis=1)
        new = np.array([valid[lab == k].mean() if (lab == k).any() else c[k] for k in range(2)])
        if np.allclose(new, c):
            break
        c = new
    threshold = c.mean()
    prev = None
    for s, p in zip(todo, pitches):
        if p is None:
            s.speaker = prev or higher
        else:
            s.speaker = higher if p >= threshold else lower
        prev = s.speaker
