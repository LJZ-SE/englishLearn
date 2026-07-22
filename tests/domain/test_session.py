from listening_cloze.domain.models import Category, Difficulty, Question
from listening_cloze.domain.session import EndlessDifficultyState, QuestionAttempt


def test_first_wrong_submission_remains_wrong_in_statistics_after_later_success() -> None:
    attempt = QuestionAttempt(_question())

    first_feedback = attempt.submit(["wrong"])
    second_feedback = attempt.submit(["correct", "answer"])

    assert not first_feedback.is_correct
    assert first_feedback.counted_correct is False
    assert second_feedback.is_correct
    assert second_feedback.counted_correct is False
    assert attempt.first_result is False
    assert attempt.submission_count == 2


def test_first_correct_submission_is_fixed_as_correct() -> None:
    attempt = QuestionAttempt(_question())

    feedback = attempt.submit(["CORRECT", "answer"])

    assert feedback.is_correct
    assert feedback.counted_correct is True
    assert attempt.first_result is True


def test_revealing_the_answer_before_submission_counts_as_wrong() -> None:
    attempt = QuestionAttempt(_question())

    revealed_answer = attempt.reveal_answer()
    later_feedback = attempt.submit(["correct answer"])

    assert revealed_answer == "correct answer"
    assert attempt.answer_revealed
    assert attempt.first_result is False
    assert later_feedback.is_correct
    assert later_feedback.counted_correct is False


def test_new_endless_session_starts_at_easy_with_empty_streaks() -> None:
    state = EndlessDifficultyState.new_session()

    assert state.difficulty is Difficulty.EASY
    assert state.correct_streak == 0
    assert state.incorrect_streak == 0


def test_five_correct_answers_upgrade_easy_to_medium_and_clear_streak() -> None:
    state = EndlessDifficultyState.new_session()

    for _ in range(5):
        state.record_outcome(is_correct=True)

    assert state.difficulty is Difficulty.MEDIUM
    assert state.correct_streak == 0
    assert state.incorrect_streak == 0


def test_five_correct_answers_upgrade_medium_to_hard() -> None:
    state = EndlessDifficultyState(difficulty=Difficulty.MEDIUM)

    for _ in range(5):
        state.record_outcome(is_correct=True)

    assert state.difficulty is Difficulty.HARD
    assert state.correct_streak == 0


def test_five_wrong_answers_downgrade_hard_to_medium() -> None:
    state = EndlessDifficultyState(difficulty=Difficulty.HARD)

    for _ in range(5):
        state.record_outcome(is_correct=False)

    assert state.difficulty is Difficulty.MEDIUM
    assert state.incorrect_streak == 0


def test_five_wrong_answers_downgrade_medium_to_easy() -> None:
    state = EndlessDifficultyState(difficulty=Difficulty.MEDIUM)

    for _ in range(5):
        state.record_outcome(is_correct=False)

    assert state.difficulty is Difficulty.EASY
    assert state.incorrect_streak == 0


def test_opposite_outcome_clears_the_other_streak() -> None:
    state = EndlessDifficultyState.new_session()

    for _ in range(4):
        state.record_outcome(is_correct=True)
    state.record_outcome(is_correct=False)

    assert state.correct_streak == 0
    assert state.incorrect_streak == 1

    state.record_outcome(is_correct=True)

    assert state.correct_streak == 1
    assert state.incorrect_streak == 0


def test_five_correct_answers_at_hard_keep_boundary_and_clear_streak() -> None:
    state = EndlessDifficultyState(difficulty=Difficulty.HARD)

    for _ in range(5):
        state.record_outcome(is_correct=True)

    assert state.difficulty is Difficulty.HARD
    assert state.correct_streak == 0


def test_five_wrong_answers_at_easy_keep_boundary_and_clear_streak() -> None:
    state = EndlessDifficultyState.new_session()

    for _ in range(5):
        state.record_outcome(is_correct=False)

    assert state.difficulty is Difficulty.EASY
    assert state.incorrect_streak == 0


def _question() -> Question:
    return Question(
        id="q-session",
        source_sentence_id="sentence-session",
        sentence="This is the correct answer.",
        category=Category.DAILY,
        difficulty=Difficulty.EASY,
        canonical_answer="correct answer",
    )
