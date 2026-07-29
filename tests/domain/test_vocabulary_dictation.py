from listening_cloze.domain.vocabulary_dictation import (
    is_vocabulary_answer_correct,
    normalize_vocabulary_answer,
)


def test_vocabulary_answer_normalization_only_allows_case_space_and_apostrophe_changes() -> None:
    assert normalize_vocabulary_answer("  DON’T   stop ") == "don't stop"
    assert is_vocabulary_answer_correct(expected="Don't stop", submitted="  don’t   STOP ")


def test_vocabulary_answer_requires_exact_spelling_hyphen_and_word_order() -> None:
    assert not is_vocabulary_answer_correct(expected="colour", submitted="color")
    assert not is_vocabulary_answer_correct(expected="well-known", submitted="well known")
    assert not is_vocabulary_answer_correct(expected="take part in", submitted="take in part")
