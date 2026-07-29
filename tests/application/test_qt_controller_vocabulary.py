from __future__ import annotations

import random
import wave
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QSignalSpy, QTest

from listening_cloze.application.controller import PracticeController
from listening_cloze.application.practice_engine import PracticeEngine
from listening_cloze.application.vocabulary_dictation import (
    VocabularyDictationService,
)
from listening_cloze.infrastructure.database import (
    SceneMetadata,
    UserRepository,
)
from listening_cloze.infrastructure.tts_service import PrefetchItem


class EmptyContentRepository:
    def list_scenes(self) -> list[SceneMetadata]:
        return [
            SceneMetadata(
                key="daily",
                label="日常生活",
                children=(
                    SceneMetadata(key="daily_home", label="家庭家务"),
                ),
            )
        ]

    def list_questions(self, **_kwargs) -> list[object]:
        return []


class EmptyDictionary:
    def lookup(self, _term: str, *, limit: int = 12) -> tuple[object, ...]:
        return ()

    def lookup_homophones(
        self,
        _term: str,
        *,
        limit: int = 6,
    ) -> tuple[object, ...]:
        return ()


class FakeTtsService:
    def __init__(self) -> None:
        self.windows: list[list[PrefetchItem]] = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def schedule(self, items) -> None:
        self.windows.append(list(items))


def _controller(tmp_path: Path) -> tuple[PracticeController, FakeTtsService]:
    users = UserRepository(tmp_path / "user.db")
    users.add_dictionary_vocabulary(term="take part in")
    vocabulary = VocabularyDictationService(
        users,
        EmptyDictionary(),  # type: ignore[arg-type]
        rng=random.Random(7),
    )
    engine = PracticeEngine(
        EmptyContentRepository(),  # type: ignore[arg-type]
        users,
        rng=random.Random(8),
    )
    controller = PracticeController(engine, vocabulary_dictation=vocabulary)
    tts = FakeTtsService()
    controller.attachTts(tts)  # type: ignore[arg-type]
    return controller, tts


def _silent_wave(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 16)


def test_vocabulary_controller_starts_and_prefetches_current_window(
    tmp_path: Path,
) -> None:
    controller, tts = _controller(tmp_path)

    controller.startVocabularyDictation("new", 10)

    assert controller.currentPage == "vocabulary-dictation"
    assert controller.vocabularyDictationView["total"] == 1
    assert tts.windows
    assert tts.windows[-1][0].sentence == "take part in"
    assert tts.windows[-1][0].playback_rate == 1.0


def test_vocabulary_new_item_automatically_plays_twice(tmp_path: Path) -> None:
    application = QCoreApplication.instance() or QCoreApplication([])
    assert application is not None
    controller, tts = _controller(tmp_path)
    requested = QSignalSpy(controller.audioRequested)
    controller.startVocabularyDictation("new", 10)
    item = tts.windows[-1][0]
    audio_path = tmp_path / "term.wav"
    _silent_wave(audio_path)

    controller.handleTtsReady(item, audio_path)
    QCoreApplication.processEvents()

    assert requested.count() == 1
    QTest.qWait(1_600)
    assert requested.count() == 2


def test_manual_replay_cancels_pending_second_automatic_play(
    tmp_path: Path,
) -> None:
    application = QCoreApplication.instance() or QCoreApplication([])
    assert application is not None
    controller, tts = _controller(tmp_path)
    requested = QSignalSpy(controller.audioRequested)
    controller.startVocabularyDictation("new", 10)
    item = tts.windows[-1][0]
    audio_path = tmp_path / "term.wav"
    _silent_wave(audio_path)
    controller.handleTtsReady(item, audio_path)
    QCoreApplication.processEvents()

    controller.replayVocabularyDictation(1.0)

    assert requested.count() == 2
    QTest.qWait(1_600)
    assert requested.count() == 2


def test_vocabulary_exit_keeps_resume_and_emits_navigation_signal(
    tmp_path: Path,
) -> None:
    controller, _tts = _controller(tmp_path)
    exited = QSignalSpy(controller.vocabularyDictationExited)
    controller.startVocabularyDictation("new", 10)

    controller.exitVocabularyDictation()

    assert controller.currentPage == "home"
    assert exited.count() == 1
    assert controller.vocabularyDictationView["resumeAvailable"] is True
