import threading
import time
import wave
from pathlib import Path

from listening_cloze.infrastructure.audio_cache import AudioCache, AudioProfile
from listening_cloze.infrastructure.tts_service import PrefetchItem, TtsPrefetchService


class RecordingBackend:
    def __init__(self, fail_first_text: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_first_text = fail_first_text
        self._failed = False

    def synthesize_to_file(self, text: str, target: Path) -> float:
        self.calls.append(text)
        if text == self.fail_first_text and not self._failed:
            self._failed = True
            raise RuntimeError("temporary failure")
        with wave.open(str(target), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(44_100)
            output.writeframes(b"\x00\x00" * 32)
        return 0.01


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("等待后台 TTS 任务超时")


def test_prefetch_generates_current_then_next_two_in_priority_order(tmp_path: Path) -> None:
    backend = RecordingBackend()
    service = TtsPrefetchService(backend, AudioCache(tmp_path), AudioProfile.default())
    service.start()
    try:
        service.schedule(
            [
                PrefetchItem("q-1", "Sentence one."),
                PrefetchItem("q-2", "Sentence two."),
                PrefetchItem("q-3", "Sentence three."),
            ]
        )
        _wait_until(lambda: len(backend.calls) == 3)
    finally:
        service.stop()

    assert backend.calls == ["Sentence one.", "Sentence two.", "Sentence three."]


def test_prefetch_merges_same_sentence_for_multiple_question_versions(tmp_path: Path) -> None:
    backend = RecordingBackend()
    ready: list[str] = []
    service = TtsPrefetchService(
        backend,
        AudioCache(tmp_path),
        AudioProfile.default(),
        on_ready=lambda item, _path: ready.append(item.question_id),
    )
    service.start()
    try:
        service.schedule(
            [
                PrefetchItem("easy-1", "Shared sentence."),
                PrefetchItem("medium-1", "Shared sentence."),
                PrefetchItem("q-2", "Another sentence."),
            ]
        )
        _wait_until(lambda: len(ready) == 3)
    finally:
        service.stop()

    assert backend.calls == ["Shared sentence.", "Another sentence."]
    assert ready == ["easy-1", "medium-1", "q-2"]


def test_current_question_retries_once_after_temporary_failure(tmp_path: Path) -> None:
    backend = RecordingBackend(fail_first_text="Current sentence.")
    ready: list[str] = []
    errors: list[str] = []
    service = TtsPrefetchService(
        backend,
        AudioCache(tmp_path),
        AudioProfile.default(),
        on_ready=lambda item, _path: ready.append(item.question_id),
        on_error=lambda item, _error: errors.append(item.question_id),
    )
    service.start()
    try:
        service.schedule([PrefetchItem("current", "Current sentence.")])
        _wait_until(lambda: ready == ["current"])
    finally:
        service.stop()

    assert backend.calls == ["Current sentence.", "Current sentence."]
    assert errors == []
