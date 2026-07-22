import pytest

from listening_cloze.domain.models import Category, Difficulty, Question


def test_difficulty_has_three_ordered_levels() -> None:
    assert [level.value for level in Difficulty] == ["easy", "medium", "hard"]
    assert Difficulty.EASY.next() is Difficulty.MEDIUM
    assert Difficulty.MEDIUM.next() is Difficulty.HARD
    assert Difficulty.HARD.next() is Difficulty.HARD
    assert Difficulty.HARD.previous() is Difficulty.MEDIUM
    assert Difficulty.MEDIUM.previous() is Difficulty.EASY
    assert Difficulty.EASY.previous() is Difficulty.EASY


def test_category_has_the_four_content_groups() -> None:
    assert {category.value for category in Category} == {
        "daily",
        "exam",
        "movies",
        "news_podcasts",
    }


def test_question_exposes_blank_count_from_canonical_answer() -> None:
    question = Question(
        id="q-1-easy",
        source_sentence_id="sentence-1",
        sentence="Everyone can take part in the discussion.",
        category=Category.DAILY,
        difficulty=Difficulty.MEDIUM,
        canonical_answer="take part in",
        equivalent_answers=("participate in",),
    )

    assert question.blank_count == 3


@pytest.mark.parametrize("answer", ["", "   "])
def test_question_rejects_an_empty_canonical_answer(answer: str) -> None:
    with pytest.raises(ValueError, match="规范答案不能为空"):
        Question(
            id="q-1-easy",
            source_sentence_id="sentence-1",
            sentence="A complete sentence.",
            category=Category.EXAM,
            difficulty=Difficulty.EASY,
            canonical_answer=answer,
        )
