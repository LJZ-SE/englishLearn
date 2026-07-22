from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np


class SupertonicBackend:
    def __init__(
        self,
        model_dir: str | Path,
        *,
        voice: str = "F3",
        steps: int = 8,
        synthesis_speed: float = 1.0,
        target_rms_dbfs: float = -11.0,
        peak_ceiling_dbfs: float = -1.0,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.voice = voice
        self.steps = steps
        self.synthesis_speed = synthesis_speed
        self.target_rms_dbfs = target_rms_dbfs
        self.peak_ceiling_dbfs = peak_ceiling_dbfs
        self._tts: Any | None = None
        self._voice_style: Any | None = None

    @property
    def sample_rate(self) -> int:
        self._ensure_loaded()
        return int(self._tts.sample_rate)

    def synthesize_to_file(
        self,
        text: str,
        target: Path,
        *,
        speed: float | None = None,
    ) -> float:
        self._ensure_loaded()
        target.parent.mkdir(parents=True, exist_ok=True)
        waveform, duration = self._tts.synthesize(
            text=text,
            voice_style=self._voice_style,
            lang="en",
            total_steps=self.steps,
            speed=self.synthesis_speed if speed is None else speed,
            max_chunk_length=300,
            silence_duration=0.3,
            verbose=False,
        )
        waveform = self._normalize_loudness(waveform)
        self._tts.save_audio(waveform, str(target))
        return float(duration[0])

    def _normalize_loudness(self, waveform):
        rms = float(np.sqrt(np.mean(np.square(waveform, dtype=np.float64))))
        if rms == 0:
            return waveform

        target_rms = 10 ** (self.target_rms_dbfs / 20)
        peak_ceiling = 10 ** (self.peak_ceiling_dbfs / 20)

        def limited(gain: float):
            return peak_ceiling * np.tanh(waveform * gain / peak_ceiling)

        lower_gain = 0.0
        upper_gain = max(target_rms / rms, 1e-6)
        for _ in range(20):
            candidate = limited(upper_gain)
            candidate_rms = float(
                np.sqrt(np.mean(np.square(candidate, dtype=np.float64)))
            )
            if candidate_rms >= target_rms:
                break
            upper_gain *= 2

        for _ in range(64):
            middle_gain = (lower_gain + upper_gain) / 2
            candidate = limited(middle_gain)
            candidate_rms = float(
                np.sqrt(np.mean(np.square(candidate, dtype=np.float64)))
            )
            if candidate_rms < target_rms:
                lower_gain = middle_gain
            else:
                upper_gain = middle_gain

        return limited(upper_gain)

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
