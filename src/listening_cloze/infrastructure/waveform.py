from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def extract_waveform_levels(path: str | Path, *, bars: int = 72) -> list[float]:
    if bars <= 0:
        raise ValueError("波形柱数量必须大于 0")

    with wave.open(str(path), "rb") as audio:
        channels = audio.getnchannels()
        if audio.getsampwidth() != 2:
            raise ValueError("仅支持 16 位 PCM WAV 音频")
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")

    if channels > 1:
        samples = samples.reshape(-1, channels).astype(np.float32).mean(axis=1)
    else:
        samples = samples.astype(np.float32)

    if samples.size == 0:
        return [0.0] * bars

    boundaries = np.linspace(0, samples.size, bars + 1, dtype=int)
    levels: list[float] = []
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=True):
        chunk = samples[start:end]
        levels.append(float(np.max(np.abs(chunk))) if chunk.size else 0.0)

    peak = max(levels)
    if peak == 0:
        return [0.0] * bars
    return [level / peak for level in levels]
