from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import uuid
import wave
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AudioProfile:
    sdk_version: str
    model_revision: str
    voice: str
    voice_sha256: str
    language: str
    steps: int
    synthesis_speed: float
    sample_rate: int

    @classmethod
    def default(cls) -> AudioProfile:
        return cls(
            sdk_version="1.3.1",
            model_revision="724fb5abbf5502583fb520898d45929e62f02c0b",
            voice="F3",
            voice_sha256="bundled-f3",
            language="en",
            steps=8,
            synthesis_speed=1.0,
            sample_rate=44_100,
        )


def normalize_sentence(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", normalized).strip()


class AudioCache:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def cache_key(self, sentence: str, profile: AudioProfile) -> str:
        payload = {
            "sentence": normalize_sentence(sentence),
            "profile": asdict(profile),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def path_for(self, sentence: str, profile: AudioProfile) -> Path:
        return self.directory / f"{self.cache_key(sentence, profile)}.wav"

    def temporary_path(self, target: Path) -> Path:
        return target.with_name(f"{target.stem}.tmp-{uuid.uuid4().hex}.wav")

    def valid_path(self, sentence: str, profile: AudioProfile) -> Path | None:
        target = self.path_for(sentence, profile)
        if not target.is_file():
            return None
        if self._is_valid_wave(target, profile.sample_rate):
            return target
        target.unlink(missing_ok=True)
        return None

    def commit(self, temporary: Path, target: Path) -> None:
        if not self._is_valid_wave(temporary, expected_sample_rate=None):
            temporary.unlink(missing_ok=True)
            raise ValueError(f"生成的音频不是完整 WAV 文件: {temporary}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, target)

    @staticmethod
    def _is_valid_wave(path: Path, expected_sample_rate: int | None) -> bool:
        try:
            with wave.open(str(path), "rb") as source:
                return (
                    source.getnchannels() >= 1
                    and source.getsampwidth() >= 1
                    and source.getnframes() > 0
                    and (
                        expected_sample_rate is None
                        or source.getframerate() == expected_sample_rate
                    )
                )
        except (EOFError, OSError, wave.Error):
            return False
