import sys
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from listening_cloze.infrastructure.supertonic_backend import SupertonicBackend


class FakeTts:
    constructor: dict[str, object] = {}
    synthesize_options: dict[str, object] = {}
    saved_waveform = None

    def __init__(self, **options) -> None:
        type(self).constructor = options
        self.sample_rate = 44_100

    def get_voice_style(self, name: str) -> str:
        return f"style:{name}"

    def synthesize(self, **options):
        type(self).synthesize_options = options
        waveform = np.array([[0.01, -0.05] * 16], dtype=np.float32)
        return waveform, np.array([0.01])

    def save_audio(self, waveform, target: str) -> None:
        type(self).saved_waveform = waveform.copy()
        with wave.open(target, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(self.sample_rate)
            output.writeframes(b"\x00\x00" * 32)


def test_backend_loads_bundled_model_without_download_and_synthesizes_english(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_dir = tmp_path / "supertonic-3"
    (model_dir / "onnx").mkdir(parents=True)
    (model_dir / "voice_styles").mkdir()
    monkeypatch.setitem(sys.modules, "supertonic", types.SimpleNamespace(TTS=FakeTts))
    monkeypatch.setattr(
        "listening_cloze.infrastructure.supertonic_backend.os.cpu_count",
        lambda: 8,
    )
    backend = SupertonicBackend(model_dir, voice="F3", steps=8, synthesis_speed=1.0)
    target = tmp_path / "sentence.wav"

    duration = backend.synthesize_to_file("A sentence for listening.", target)

    assert FakeTts.constructor == {
        "model": "supertonic-3",
        "model_dir": model_dir,
        "auto_download": False,
        "intra_op_num_threads": 7,
        "inter_op_num_threads": 1,
    }
    assert FakeTts.synthesize_options == {
        "text": "A sentence for listening.",
        "voice_style": "style:F3",
        "lang": "en",
        "total_steps": 8,
        "speed": 1.0,
        "max_chunk_length": 300,
        "silence_duration": 0.3,
        "verbose": False,
    }
    assert duration == 0.01
    assert target.is_file()
    output_rms = float(np.sqrt(np.mean(FakeTts.saved_waveform**2)))
    output_rms_dbfs = 20 * np.log10(output_rms)
    assert output_rms_dbfs == pytest.approx(-11.0, abs=0.05)
    assert np.max(np.abs(FakeTts.saved_waveform)) <= 10 ** (-1 / 20)


def test_backend_keeps_silent_waveform_silent(tmp_path: Path) -> None:
    backend = SupertonicBackend(tmp_path)
    silent = np.zeros((1, 32), dtype=np.float32)

    normalized = backend._normalize_loudness(silent)

    np.testing.assert_array_equal(normalized, silent)


def test_backend_accepts_per_request_synthesis_speed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_dir = tmp_path / "supertonic-3"
    (model_dir / "onnx").mkdir(parents=True)
    (model_dir / "voice_styles").mkdir()
    monkeypatch.setitem(sys.modules, "supertonic", types.SimpleNamespace(TTS=FakeTts))
    backend = SupertonicBackend(model_dir, synthesis_speed=1.0)

    backend.synthesize_to_file("Play this slowly.", tmp_path / "slow.wav", speed=0.8)

    assert FakeTts.synthesize_options["speed"] == 0.8
