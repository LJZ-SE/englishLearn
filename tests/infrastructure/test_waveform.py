import math
import wave
from pathlib import Path

import numpy as np

from listening_cloze.infrastructure.waveform import extract_waveform_levels


def test_waveform_levels_are_derived_from_real_pcm_samples(tmp_path: Path) -> None:
    path = tmp_path / "varying.wav"
    samples = np.concatenate(
        [np.full(100, round(30_000 * index / 9), dtype=np.int16) for index in range(10)]
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44_100)
        output.writeframes(samples.tobytes())

    levels = extract_waveform_levels(path, bars=10)

    assert len(levels) == 10
    assert levels[0] == 0.0
    assert math.isclose(levels[-1], 1.0)
    assert levels == sorted(levels)
