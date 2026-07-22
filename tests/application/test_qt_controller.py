import random
import wave
from pathlib import Path

from PySide6.QtTest import QSignalSpy

from listening_cloze.application.controller import PracticeController
from listening_cloze.application.practice_engine import PracticeEngine
from listening_cloze.infrastructure.database import ContentQuestion, UserRepository
from listening_cloze.infrastructure.tts_service import PrefetchItem


class FakeContentRepository:
    def __init__(self, questions: list[ContentQuestion]) -> None:
        self.questions = questions

    def list_questions(
        self,
        *,
        category: str | None = None,
        difficulty: str | None = None,
    ) -> list[ContentQuestion]:
        return [
            question
            for question in self.questions
            if (category in (None, "all") or question.category == category)
            and (difficulty in (None, "all") or question.difficulty == difficulty)
        ]

    def sample_questions(
        self,
        *,
        top_scene: str | None,
        sub_scene: str | None,
        difficulty: str,
        limit: int,
        exclude_ids: frozenset[str],
        seed: int,
    ) -> list[ContentQuestion]:
        candidates = [
            question
            for question in self.questions
            if (top_scene is None or (question.top_scene or question.category) == top_scene)
            and (sub_scene is None or question.sub_scene == sub_scene)
            and question.difficulty == difficulty
            and question.id not in exclude_ids
        ]
        random.Random(seed).shuffle(candidates)
        return candidates[:limit]

    def get_questions_by_ids(self, ids: list[str] | tuple[str, ...]) -> list[ContentQuestion]:
        by_id = {question.id: question for question in self.questions}
        return [by_id[question_id] for question_id in ids if question_id in by_id]


class FakeTtsService:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.windows: list[list[PrefetchItem]] = []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def schedule(self, items) -> None:
        self.windows.append(list(items))


def test_controller_exposes_multi_blank_question_and_preserves_first_result(
    tmp_path: Path,
) -> None:
    engine = PracticeEngine(
        FakeContentRepository([_question("q1", "take part in")]),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(1),
    )
    controller = PracticeController(engine)

    controller.startQuantitative("daily", "easy", 1)

    assert controller.currentPage == "practice"
    assert controller.sentencePrefix == "You should "
    assert controller.sentenceSuffix == " today."
    assert controller.blankCount == 3
    assert controller.progressText == "第 1 / 1 题"

    controller.submitAnswers(["take", "part", "on"])
    assert controller.feedbackState == "incorrect"
    assert controller.wrongCount == 1
    assert not controller.canAdvance

    controller.submitAnswers(["take", "part", "in"])
    assert controller.feedbackState == "correct"
    assert controller.wrongCount == 1
    assert controller.correctCount == 0
    assert controller.canAdvance

    controller.nextQuestion()
    assert controller.currentPage == "summary"


def test_controller_reveals_answer_and_full_sentence_translation(tmp_path: Path) -> None:
    engine = PracticeEngine(
        FakeContentRepository([_question("q1", "do not", ("don't",), "我不会伤害你。")]),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(2),
    )
    controller = PracticeController(engine)
    controller.startQuantitative("daily", "easy", 1)
    revealed = QSignalSpy(controller.answerRevealed)

    controller.revealAnswer()

    assert revealed.count() == 1
    assert revealed.at(0)[0] == ["do", "not"]
    assert controller.feedbackState == "revealed"
    assert controller.sentenceTranslation == "我不会伤害你。"
    assert controller.viewedAnswerCount == 1
    assert controller.canAdvance


def test_initial_play_does_not_count_as_replay_but_replay_does(tmp_path: Path) -> None:
    engine = PracticeEngine(
        FakeContentRepository([_question("q1", "listen")]),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(3),
    )
    controller = PracticeController(engine)
    controller.startQuantitative("daily", "easy", 1)
    requested = QSignalSpy(controller.audioRequested)

    controller.play()
    controller.replay()

    assert requested.count() == 2
    assert requested.at(0) == ["q1", 1.0]
    assert controller.replayCount == 1


def test_each_new_question_requests_automatic_audio_without_counting_a_replay(
    tmp_path: Path,
) -> None:
    questions = [_question(f"q{index}", "listen") for index in range(8)]
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository(questions),
            UserRepository(tmp_path / "user.db"),
            rng=random.Random(25),
        )
    )
    requested = QSignalSpy(controller.audioRequested)

    controller.startQuantitative("daily", "easy", 5)

    assert requested.count() == 1
    assert controller.replayCount == 0

    controller.submitAnswers(["listen"])
    controller.nextQuestion()

    assert requested.count() == 2
    assert controller.replayCount == 0


def test_automatic_audio_waits_until_local_tts_is_ready(tmp_path: Path) -> None:
    engine = PracticeEngine(
        FakeContentRepository([_question("q1", "listen")]),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(26),
    )
    controller = PracticeController(engine)
    controller.attachTts(FakeTtsService())
    requested = QSignalSpy(controller.audioRequested)

    controller.startQuantitative("daily", "easy", 1)

    assert requested.count() == 0
    audio_file = tmp_path / "automatic.wav"
    with wave.open(str(audio_file), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44_100)
        output.writeframes(b"\x00\x00" * 40)
    controller.handleTtsReady(
        PrefetchItem("q1", engine.current.question.sentence),
        audio_file,
    )

    assert requested.count() == 1
    assert controller.replayCount == 0


def test_controller_schedules_current_and_next_two_and_publishes_ready_audio(
    tmp_path: Path,
) -> None:
    questions = [_question(f"q{index}", f"word{index}") for index in range(5)]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(4),
    )
    controller = PracticeController(engine)
    tts = FakeTtsService()
    controller.attachTts(tts)

    controller.startQuantitative("daily", "easy", 5)

    assert tts.started
    assert len(tts.windows[-1]) == 3
    current_id = controller.currentQuestionId
    audio_file = tmp_path / "current.wav"
    with wave.open(str(audio_file), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(44_100)
        output.writeframes((b"\x00\x00" * 40) + (b"\xff\x3f" * 40))
    controller.handleTtsReady(
        PrefetchItem(current_id, engine.current.question.sentence), audio_file
    )

    assert controller.audioStatus == "ready"
    assert controller.audioSource == audio_file.resolve().as_uri()
    assert len(controller.waveformLevels) == 72
    assert max(controller.waveformLevels) == 1.0
    assert controller.audioDurationMs > 0


def test_playback_rate_reschedules_current_and_next_two_at_selected_speed(
    tmp_path: Path,
) -> None:
    questions = [_question(f"q{index}", f"word{index}") for index in range(5)]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(21),
    )
    controller = PracticeController(engine)
    tts = FakeTtsService()
    controller.attachTts(tts)
    controller.startQuantitative("daily", "easy", 5)

    controller.setPlaybackRate(0.8)

    assert len(tts.windows[-1]) == 3
    assert {item.playback_rate for item in tts.windows[-1]} == {0.8}


def test_startup_asset_issues_open_repair_page(tmp_path: Path) -> None:
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository([]),
            UserRepository(tmp_path / "user.db"),
            rng=random.Random(5),
        )
    )

    controller.setStartupIssues(["缺少题库 content.db", "缺少 Supertonic 模型"])

    assert controller.currentPage == "repair"
    assert controller.repairIssues == ["缺少题库 content.db", "缺少 Supertonic 模型"]


def test_controller_persists_settings_resume_progress_and_audio_skip(tmp_path: Path) -> None:
    questions = [_question(f"q{index}", "listen") for index in range(8)]
    database = tmp_path / "user.db"
    users = UserRepository(database)
    first_engine = PracticeEngine(
        FakeContentRepository(questions),
        users,
        rng=random.Random(14),
    )
    first = PracticeController(first_engine, audio_cache_dir=tmp_path / "cache")
    first.setPlaybackRate(0.8)
    first.setVolume(0.55)
    first.setAnimationsEnabled(False)
    first.startQuantitative("daily", "easy", 5)
    first.submitAnswers(["wrong"])

    second_engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(database),
        rng=random.Random(15),
    )
    second = PracticeController(second_engine, audio_cache_dir=tmp_path / "cache")

    assert second.hasResume
    assert second.playbackRate == 0.8
    assert second.volume == 0.55
    assert not second.animationsEnabled
    second.resumeLatest()
    assert second.currentPage == "practice"
    assert second.progressStates[0] == "wrong"

    failed_id = second.currentQuestionId
    second.handleTtsError(
        PrefetchItem(
            failed_id,
            second_engine.current.question.sentence,
            playback_rate=0.8,
        ),
        RuntimeError("模型故障"),
    )
    assert second.audioStatus == "error"
    second.skipAudioQuestion()
    assert second.currentQuestionId != failed_id
    assert second.wrongCount == 1


def test_returning_home_and_resuming_keeps_the_live_practice_state(tmp_path: Path) -> None:
    questions = [_question(f"q{index}", "listen") for index in range(8)]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(23),
    )
    controller = PracticeController(engine)
    controller.startQuantitative("daily", "easy", 5)
    controller.submitAnswers(["wrong"])
    current_question_id = controller.currentQuestionId

    controller.goHome()

    assert controller.currentPage == "home"
    assert controller.hasResume

    controller.resumeLatest()

    assert controller.currentPage == "practice"
    assert controller.currentQuestionId == current_question_id
    assert controller.feedbackState == "incorrect"
    assert controller.wrongCount == 1


def test_closing_settings_returns_to_the_page_that_opened_it(tmp_path: Path) -> None:
    questions = [_question(f"q{index}", "listen") for index in range(8)]
    controller = PracticeController(
        PracticeEngine(
            FakeContentRepository(questions),
            UserRepository(tmp_path / "user.db"),
            rng=random.Random(24),
        )
    )
    controller.startQuantitative("daily", "easy", 5)
    controller.submitAnswers(["wrong"])

    controller.openSettings()
    assert controller.currentPage == "settings"

    controller.closeSettings()
    assert controller.currentPage == "practice"
    assert controller.feedbackState == "incorrect"

    controller.goHome()
    controller.openSettings()
    controller.closeSettings()
    assert controller.currentPage == "home"


def test_reset_learning_records_requires_explicit_confirmation(tmp_path: Path) -> None:
    users = UserRepository(tmp_path / "user.db")
    users.record_attempt("q1", is_correct=False)
    engine = PracticeEngine(
        FakeContentRepository([_question("q1", "listen")]),
        users,
        rng=random.Random(16),
    )
    controller = PracticeController(engine)

    controller.resetLearningRecords(False)
    assert users.get_question_progress("q1") is not None

    controller.resetLearningRecords(True)
    assert users.get_question_progress("q1") is None


def test_endless_summary_exposes_adaptive_session_metrics(tmp_path: Path) -> None:
    engine = PracticeEngine(
        FakeContentRepository([_question(f"q{index}", "listen") for index in range(8)]),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(19),
    )
    controller = PracticeController(engine)
    controller.startEndless("daily")
    controller.submitAnswers(["listen"])

    controller.endSession()

    assert controller.currentPage == "summary"
    assert controller.isEndlessSummary
    assert controller.completedCount == 1
    assert controller.accuracyText == "100%"
    assert controller.highestDifficultyLabel == "简单"
    assert controller.endingDifficultyLabel == "简单"
    assert controller.longestStreak == 1


def _question(
    question_id: str,
    answer: str,
    aliases: tuple[str, ...] = (),
    translation_zh: str = "",
) -> ContentQuestion:
    sentence = f"You should {answer} today."
    start = sentence.index(answer)
    return ContentQuestion(
        id=question_id,
        sentence_id=f"sentence-{question_id}",
        sentence_text=sentence,
        translation_zh=translation_zh,
        category="daily",
        source_url="https://example.test",
        normalized_hash=f"hash-{question_id}",
        difficulty="easy",
        answer_start=start,
        answer_end=start + len(answer),
        canonical_answer=answer,
        answer_word_count=len(answer.split()),
        difficulty_score=1.0,
        rationale="测试数据",
        aliases=aliases,
    )
