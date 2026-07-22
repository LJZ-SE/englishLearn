import random
from pathlib import Path

from listening_cloze.application.practice_engine import PracticeEngine, PracticeMode
from listening_cloze.domain.models import Difficulty
from listening_cloze.domain.session import EndlessDifficultyState
from listening_cloze.infrastructure.database import ContentQuestion, UserRepository


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


def test_quantitative_first_wrong_then_correct_keeps_wrong_statistic(tmp_path: Path) -> None:
    content = FakeContentRepository([_question("q1", "easy", "take part in")])
    users = UserRepository(tmp_path / "user.db")
    engine = PracticeEngine(content, users, rng=random.Random(7))
    engine.start_quantitative(category="daily", difficulty=Difficulty.EASY, count=1)

    first = engine.submit(["take", "part", "on"])
    second = engine.submit(["take", "part", "in"])

    assert not first.is_correct
    assert first.mascot_kind == "incorrect"
    assert second.is_correct
    assert second.mascot_kind == "correct"
    assert second.counted_correct is False
    assert engine.stats.correct == 0
    assert engine.stats.wrong == 1
    assert engine.can_advance
    progress = users.get_question_progress("q1")
    assert progress is not None
    assert progress.first_correct is False
    assert progress.attempt_count == 2


def test_reveal_answer_counts_as_wrong_and_allows_next_question(tmp_path: Path) -> None:
    content = FakeContentRepository([_question("q1", "medium", "do not", ("don't",))])
    users = UserRepository(tmp_path / "user.db")
    engine = PracticeEngine(content, users, rng=random.Random(8))
    engine.start_quantitative(category="daily", difficulty=Difficulty.MEDIUM, count=1)

    answer = engine.reveal_answer()

    assert answer == "do not"
    assert engine.stats.wrong == 1
    assert engine.stats.viewed_answers == 1
    assert engine.can_advance
    assert users.get_question_progress("q1").first_correct is False


def test_endless_five_first_try_correct_answers_upgrade_next_queue_to_medium(
    tmp_path: Path,
) -> None:
    questions = [
        _question(f"easy-{index}", "easy", "word", sentence_id=f"easy-s-{index}")
        for index in range(8)
    ] + [
        _question(f"medium-{index}", "medium", "phrase here", sentence_id=f"medium-s-{index}")
        for index in range(5)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(3),
    )
    engine.start_endless(category="daily")

    for index in range(5):
        result = engine.submit(["word"])
        assert result.is_correct
        if index < 4:
            engine.next_question()

    assert result.difficulty_changed
    assert result.mascot_kind == "level_up"
    assert result.feedback_animation.startswith("level_up_")
    assert engine.endless_state.difficulty is Difficulty.MEDIUM
    engine.next_question()
    assert engine.current.question.difficulty is Difficulty.MEDIUM
    assert all(item.question.difficulty is Difficulty.MEDIUM for item in engine.prefetch_window)


def test_endless_five_first_try_errors_use_level_down_feedback(tmp_path: Path) -> None:
    questions = [
        _question(f"medium-{index}", "medium", "word", sentence_id=f"m-{index}")
        for index in range(8)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(17),
    )
    engine._reset(PracticeMode.ENDLESS, "daily")
    engine.endless_state = EndlessDifficultyState(Difficulty.MEDIUM)
    engine._fill_endless_queue()
    engine._begin_current()

    for index in range(5):
        result = engine.submit(["wrong"])
        engine.reveal_answer()
        if index < 4:
            engine.next_question()

    assert result.difficulty_changed
    assert result.mascot_kind == "level_down"
    assert result.feedback_animation.startswith("level_down_")


def test_quantitative_session_has_fixed_order_and_three_item_prefetch_window(
    tmp_path: Path,
) -> None:
    questions = [
        _question(f"q-{index}", "hard", "answer", sentence_id=f"s-{index}") for index in range(5)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(11),
    )

    engine.start_quantitative(category="daily", difficulty=Difficulty.HARD, count=5)

    assert engine.mode is PracticeMode.QUANTITATIVE
    assert len(engine.prefetch_window) == 3
    assert engine.prefetch_window[0] == engine.current
    assert len({item.question.id for item in engine.items}) == 5


def test_session_resume_restores_order_stats_attempt_and_endless_streak(tmp_path: Path) -> None:
    questions = [
        _question(f"q-{index}", "easy", "word", sentence_id=f"s-{index}") for index in range(8)
    ]
    database = tmp_path / "user.db"
    users = UserRepository(database)
    first = PracticeEngine(FakeContentRepository(questions), users, rng=random.Random(12))
    first.start_endless(category="daily")
    original_order = [item.question.id for item in first.items]
    first.submit(["wrong"])

    resumed = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(database),
        rng=random.Random(99),
    )

    assert resumed.has_unfinished_session
    assert resumed.resume_latest()
    assert [item.question.id for item in resumed.items] == original_order
    assert resumed.stats.wrong == 1
    assert resumed.endless_state is not None
    assert resumed.endless_state.incorrect_streak == 1
    assert resumed.progress_states == ["wrong"]

    corrected = resumed.submit(["word"])
    assert corrected.is_correct
    assert not corrected.counted_correct
    assert resumed.stats.wrong == 1


def test_quantitative_progress_states_and_audio_skip_replacement_do_not_change_stats(
    tmp_path: Path,
) -> None:
    questions = [
        _question(f"q-{index}", "easy", "word", sentence_id=f"s-{index}") for index in range(8)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(13),
    )
    engine.start_quantitative(category="daily", difficulty=Difficulty.EASY, count=5)
    failed_id = engine.current.question.id

    engine.skip_current_for_audio_error()

    assert engine.current.question.id != failed_id
    assert len(engine.items) == 5
    assert engine.stats.completed == 0
    assert engine.progress_states == ["current", "pending", "pending", "pending", "pending"]

    engine.submit(["wrong"])
    assert engine.progress_states == ["wrong", "pending", "pending", "pending", "pending"]


def test_persisted_question_history_is_used_by_selector(tmp_path: Path) -> None:
    questions = [
        _question("mastered", "easy", "word", sentence_id="mastered-s"),
        _question("unseen", "easy", "word", sentence_id="unseen-s"),
    ]
    users = UserRepository(tmp_path / "user.db")
    users.record_attempt("mastered", is_correct=True)
    engine = PracticeEngine(
        FakeContentRepository(questions),
        users,
        rng=random.Random(1),
    )

    engine.start_quantitative(category="daily", difficulty=Difficulty.EASY, count=1)

    assert engine.current.question.id == "unseen"


def test_quantitative_wrong_questions_can_start_immediate_review(tmp_path: Path) -> None:
    questions = [
        _question(f"q-{index}", "easy", "word", sentence_id=f"s-{index}") for index in range(5)
    ]
    engine = PracticeEngine(
        FakeContentRepository(questions),
        UserRepository(tmp_path / "user.db"),
        rng=random.Random(18),
    )
    engine.start_quantitative(category="daily", difficulty=Difficulty.EASY, count=5)
    wrong_id = engine.current.question.id
    engine.submit(["wrong"])
    engine.reveal_answer()
    for _index in range(4):
        assert engine.next_question()
        engine.submit(["word"])

    assert engine.has_review_items
    engine.start_review()

    assert engine.mode is PracticeMode.QUANTITATIVE
    assert len(engine.items) == 1
    assert engine.current.question.id == wrong_id
    assert engine.stats.completed == 0


def _question(
    question_id: str,
    difficulty: str,
    answer: str,
    aliases: tuple[str, ...] = (),
    *,
    sentence_id: str | None = None,
) -> ContentQuestion:
    sentence = f"You should {answer} today."
    start = sentence.index(answer)
    return ContentQuestion(
        id=question_id,
        sentence_id=sentence_id or f"sentence-{question_id}",
        sentence_text=sentence,
        category="daily",
        source_url=f"https://example.test/{question_id}",
        normalized_hash=f"hash-{question_id}",
        difficulty=difficulty,
        answer_start=start,
        answer_end=start + len(answer),
        canonical_answer=answer,
        answer_word_count=len(answer.split()),
        difficulty_score=1.0,
        rationale="测试数据",
        aliases=aliases,
    )
