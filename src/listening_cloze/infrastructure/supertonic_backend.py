from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class SupertonicBackend:
    def __init__(
        self,
        model_dir: str | Path,
        *,
        voice: str = "F3",
        steps: int = 8,
        synthesis_speed: float = 1.0,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.voice = voice
        self.steps = steps
        self.synthesis_speed = synthesis_speed
        self._tts: Any | None = None
        self._voice_style: Any | None = None

    @property
    def sample_rate(self) -> int:
        self._ensure_loaded()
        return int(self._tts.sample_rate)

    def synthesize_to_file(self, text: str, target: Path) -> float:
        self._ensure_loaded()
        target.parent.mkdir(parents=True, exist_ok=True)
        waveform, duration = self._tts.synthesize(
            text=text,
            voice_style=self._voice_style,
            lang="en",
            total_steps=self.steps,
            speed=self.synthesis_speed,
            max_chunk_length=300,
            silence_duration=0.3,
            verbose=False,
        )
        self._tts.save_audio(waveform, str(target))
        return float(duration[0])

    def _ensure_loaded(self) -> None:
        if self._tts is not None:
            return
        if not (self.model_dir / "onnx").is_dir():
            raise FileNotFoundError(f"缺少 Supertonic ONNX 目录: {self.model_dir / 'onnx'}")
        if not (self.model_dir / "voice_styles").is_dir():
            raise FileNotFoundError(
                f"缺少 Supertonic 女声资源目录: {self.model_dir / 'voice_styles'}"
            )

        from supertonic import TTS

        self._tts = TTS(
            model="supertonic-3",
            model_dir=self.model_dir,
            auto_download=False,
            intra_op_num_threads=max(1, (os.cpu_count() or 2) - 1),
            inter_op_num_threads=1,
        )
        self._voice_style = self._tts.get_voice_style(self.voice)
