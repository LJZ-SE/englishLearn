import pytest

from listening_cloze.domain.answers import (
    combine_answer_inputs,
    is_answer_correct,
    normalize_answer,
)
from listening_cloze.domain.models import Category, Difficulty, Question


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  TAKE   Part IN  ", "take part in"),
        ("DON’T", "don't"),
        ("don‘t", "don't"),
    ],
)
def test_normalize_answer_handles_case_whitespace_and_apostrophes(raw: str, expected: str) -> None:
    assert normalize_answer(raw) == expected


def test_combine_answer_inputs_joins_only_non_empty_boxes_in_order() -> None:
    assert combine_answer_inputs(["  take ", "", " part   in ", "  "]) == "take part in"


def test_answer_accepts_the_canonical_answer_from_multiple_boxes() -> None:
    question = _question("take part in")

    assert is_answer_correct(question, ["take", "part", "in"])


def test_answer_accepts_an_explicit_equivalent_with_a_different_word_count() -> None:
    question = _question("do not", equivalent_answers=("don't",))

    assert is_answer_correct(question, ["DON’T", ""])


def test_answer_does_not_accept_an_unconfigured_approximation() -> None:
    question = _question("through", equivalent_answers=("by means of",))

    assert not is_answer_correct(question, ["thru"])


def _question(canonical_answer: str, *, equivalent_answers: tuple[str, ...] = ()) -> Question:
    return Question(
        id="q-answer",
        source_sentence_id="sentence-answer",
        sentence="This is an example sentence.",
        category=Category.EXAM,
        difficulty=Difficulty.MEDIUM,
        canonical_answer=canonical_answer,
        equivalent_answers=equivalent_answers,
    )
