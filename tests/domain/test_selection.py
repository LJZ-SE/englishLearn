import random

from listening_cloze.domain.models import Category, Difficulty, Question
from listening_cloze.domain.selection import (
    QuestionProgress,
    QuestionSelector,
    selection_weight,
)


def test_selection_weights_prioritize_unseen_then_review_then_mastered() -> None:
    unseen = QuestionProgress()
    wrong = QuestionProgress(first_result=False)
    revealed = QuestionProgress(answer_revealed=True)
    mastered = QuestionProgress(first_result=True)

    assert selection_weight(unseen) > selection_weight(wrong)
    assert selection_weight(unseen) > selection_weight(revealed)
    assert selection_weight(wrong) == selection_weight(revealed)
    assert selection_weight(wrong) > selection_weight(mastered) > 0


def test_selector_is_reproducible_with_an_injected_random_generator() -> None:
    candidates = [_question(index) for index in range(8)]
    history = {
        "q-0-easy": QuestionProgress(first_result=True),
        "q-1-easy": QuestionProgress(first_result=False),
    }
    first = QuestionSelector(rng=random.Random(31), recent_window=2)
    second = QuestionSelector(rng=random.Random(31), recent_window=2)

    first_ids = [first.select(candidates, history).id for _ in range(6)]
    second_ids = [second.select(candidates, history).id for _ in range(6)]

    assert first_ids == second_ids


def test_selector_avoids_a_recent_different_difficulty_of_the_same_sentence() -> None:
    easy = _question(1, difficulty=Difficulty.EASY, source_sentence_id="shared")
    medium = _question(2, difficulty=Difficulty.MEDIUM, source_sentence_id="shared")
    alternative = _question(3, difficulty=Difficulty.MEDIUM, source_sentence_id="other")
    selector = QuestionSelector(rng=random.Random(4), recent_window=3)

    assert selector.select([easy], {}).id == easy.id
    selected = selector.select([medium, alternative], {})

    assert selected.id == alternative.id


def test_selector_falls_back_when_only_recent_source_has_candidates() -> None:
    easy = _question(1, difficulty=Difficulty.EASY, source_sentence_id="shared")
    medium = _question(2, difficulty=Difficulty.MEDIUM, source_sentence_id="shared")
    selector = QuestionSelector(rng=random.Random(5), recent_window=3)

    selector.select([easy], {})

    assert selector.select([medium], {}).id == medium.id


def _question(
    index: int,
    *,
    difficulty: Difficulty = Difficulty.EASY,
    source_sentence_id: str | None = None,
) -> Question:
    source_id = source_sentence_id or f"sentence-{index}"
    return Question(
        id=f"q-{index}-{difficulty.value}",
        source_sentence_id=source_id,
        sentence=f"Example sentence number {index}.",
        category=Category.DAILY,
        difficulty=difficulty,
        canonical_answer="example",
    )
