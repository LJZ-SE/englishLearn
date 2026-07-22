from collections.abc import Sequence
from dataclasses import dataclass

from listening_cloze.domain.answers import is_answer_correct
from listening_cloze.domain.models import Difficulty, Question


@dataclass(frozen=True, slots=True)
class SubmissionFeedback:
    is_correct: bool
    counted_correct: bool


class QuestionAttempt:
    def __init__(self, question: Question) -> None:
        self.question = question
        self.first_result: bool | None = None
        self.submission_count = 0
        self.answer_revealed = False

    def submit(self, inputs: Sequence[str]) -> SubmissionFeedback:
        is_correct = is_answer_correct(self.question, inputs)
        self.submission_count += 1
        if self.first_result is None:
            self.first_result = is_correct
        return SubmissionFeedback(is_correct=is_correct, counted_correct=self.first_result)

    def reveal_answer(self) -> str:
        self.answer_revealed = True
        if self.first_result is None:
            self.first_result = False
        return self.question.canonical_answer


@dataclass(slots=True)
class EndlessDifficultyState:
    difficulty: Difficulty
    correct_streak: int = 0
    incorrect_streak: int = 0

    @classmethod
    def new_session(cls) -> "EndlessDifficultyState":
        return cls(difficulty=Difficulty.EASY)

    def record_outcome(self, *, is_correct: bool) -> None:
        if is_correct:
            self.correct_streak += 1
            self.incorrect_streak = 0
            if self.correct_streak == 5:
                self.difficulty = self.difficulty.next()
                self.correct_streak = 0
            return

        self.incorrect_streak += 1
        self.correct_streak = 0
        if self.incorrect_streak == 5:
            self.difficulty = self.difficulty.previous()
            self.incorrect_streak = 0
