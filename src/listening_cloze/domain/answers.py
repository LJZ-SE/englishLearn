from collections.abc import Sequence

from listening_cloze.domain.models import Question

_APOSTROPHE_TRANSLATION = str.maketrans({"‘": "'", "’": "'"})


def normalize_answer(answer: str) -> str:
    normalized_apostrophes = answer.translate(_APOSTROPHE_TRANSLATION)
    return " ".join(normalized_apostrophes.casefold().split())


def combine_answer_inputs(inputs: Sequence[str]) -> str:
    normalized_inputs = (normalize_answer(value) for value in inputs)
    return " ".join(value for value in normalized_inputs if value)


def is_answer_correct(question: Question, inputs: Sequence[str]) -> bool:
    submitted_answer = combine_answer_inputs(inputs)
    accepted_answers = (question.canonical_answer, *question.equivalent_answers)
    return submitted_answer in {normalize_answer(answer) for answer in accepted_answers}
