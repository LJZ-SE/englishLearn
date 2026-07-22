import sys
import types
import wave
from pathlib import Path

import numpy as np

from listening_cloze.infrastructure.supertonic_backend import SupertonicBackend


class FakeTts:
    constructor: dict[str, object] = {}
    synthesize_options: dict[str, object] = {}

    def __init__(self, **options) -> None:
        type(self).constructor = options
        self.sample_rate = 44_100

    def get_voice_style(self, name: str) -> str:
        return f"style:{name}"

    def synthesize(self, **options):
        type(self).synthesize_options = options
        return np.zeros((1, 32), dtype=np.float32), np.array([0.01])

    def save_audio(self, _waveform, target: str) -> None:
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
