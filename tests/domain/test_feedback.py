import random

from listening_cloze.domain.feedback import (
    DEFAULT_FEEDBACK_POOLS,
    FeedbackKind,
    FeedbackPool,
    FeedbackSelector,
)


def test_default_feedback_covers_answer_and_difficulty_events() -> None:
    assert set(DEFAULT_FEEDBACK_POOLS) == set(FeedbackKind)
    assert all(
        len(pool.texts) >= 2 and len(pool.animations) >= 2
        for pool in DEFAULT_FEEDBACK_POOLS.values()
    )


def test_feedback_text_and_animation_never_repeat_consecutively() -> None:
    selector = FeedbackSelector(
        pools={
            FeedbackKind.CORRECT: FeedbackPool(
                texts=("太棒了！", "完全正确！", "继续保持！"),
                animations=("bounce", "clap", "spin"),
            )
        },
        rng=random.Random(9),
    )

    choices = [selector.next(FeedbackKind.CORRECT) for _ in range(30)]

    assert all(
        current.text != following.text and current.animation != following.animation
        for current, following in zip(choices, choices[1:], strict=False)
    )


def test_feedback_selection_is_reproducible_with_an_injected_random_generator() -> None:
    pool = FeedbackPool(
        texts=("再试试！", "差一点！"),
        animations=("droop", "shake"),
    )
    first = FeedbackSelector(pools={FeedbackKind.INCORRECT: pool}, rng=random.Random(17))
    second = FeedbackSelector(pools={FeedbackKind.INCORRECT: pool}, rng=random.Random(17))

    first_sequence = [first.next(FeedbackKind.INCORRECT) for _ in range(8)]
    second_sequence = [second.next(FeedbackKind.INCORRECT) for _ in range(8)]

    assert first_sequence == second_sequence
