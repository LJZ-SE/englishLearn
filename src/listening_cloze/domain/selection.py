import random
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from listening_cloze.domain.models import Difficulty, Question


@dataclass(frozen=True, slots=True)
class QuestionProgress:
    first_result: bool | None = None
    answer_revealed: bool = False


def selection_weight(progress: QuestionProgress) -> float:
    if progress.first_result is None and not progress.answer_revealed:
        return 9.0
    if progress.first_result is False or progress.answer_revealed:
        return 3.0
    return 0.25


class QuestionSelector:
    def __init__(
        self,
        *,
        rng: random.Random | None = None,
        recent_window: int = 3,
    ) -> None:
        if recent_window < 0:
            raise ValueError("短期去重窗口不能为负数")
        self._rng = rng or random.Random()
        self._recent: deque[tuple[str, Difficulty]] = deque(maxlen=recent_window)

    def select(
        self,
        candidates: Sequence[Question],
        history: Mapping[str, QuestionProgress],
    ) -> Question:
        if not candidates:
            raise ValueError("没有可选择的候选题")

        eligible = [question for question in candidates if not self._is_blocked(question)]
        if not eligible:
            eligible = list(candidates)

        weights = [
            selection_weight(history.get(question.id, QuestionProgress())) for question in eligible
        ]
        selected = self._rng.choices(eligible, weights=weights, k=1)[0]
        self._recent.append((selected.source_sentence_id, selected.difficulty))
        return selected

    def _is_blocked(self, question: Question) -> bool:
        return any(
            source_sentence_id == question.source_sentence_id
            and difficulty is not question.difficulty
            for source_sentence_id, difficulty in self._recent
        )
