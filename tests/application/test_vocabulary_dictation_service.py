from __future__ import annotations

import random

import pytest

from listening_cloze.application.vocabulary_dictation import (
    VocabularyDictationService,
)
from listening_cloze.infrastructure.database import UserRepository
from listening_cloze.infrastructure.dictionary import DictionaryEntry


class FakeDictionary:
    def lookup(self, term: str, *, limit: int = 12) -> tuple[DictionaryEntry, ...]:
        if term.casefold() != "sea":
            return ()
        return (
            DictionaryEntry(
                word="sea",
                phonetic="siː",
                definition="a large area of salt water",
                translation="海；海洋",
                pos="n:100",
                collins=3,
                oxford=True,
                tags=(),
                bnc=100,
                frq=100,
                exchange="",
                detail="",
                audio="",
            ),
        )

    def lookup_homophones(
        self,
        term: str,
        *,
        limit: int = 6,
    ) -> tuple[DictionaryEntry, ...]:
        if term.casefold() != "sea":
            return ()
        return (
            DictionaryEntry(
                word="see",
                phonetic="siː",
                definition="notice with the eyes",
                translation="看见；看到",
                pos="v:100",
                collins=3,
                oxford=True,
                tags=(),
                bnc=100,
                frq=100,
                exchange="",
                detail="",
                audio="",
            ),
        )[:limit]


def _service(tmp_path, terms: tuple[str, ...] = ("sea", "take part in")):
    users = UserRepository(tmp_path / "user.db")
    for term in terms:
        users.add_dictionary_vocabulary(term=term)
    service = VocabularyDictationService(
        users,
        FakeDictionary(),  # type: ignore[arg-type]
        rng=random.Random(3),
    )
    return service, users


def test_vocabulary_dictation_runs_each_entry_once_and_restores_without_input(
    tmp_path,
) -> None:
    service, _users = _service(tmp_path)
    service.start(source="new", count=10)
    first_id = service.current_entry.entry_id

    service.submit("definitely wrong")
    assert service.view(page="practice")["wrongCount"] == 1
    assert service.next_item()
    second_id = service.current_entry.entry_id
    assert second_id != first_id

    restored = VocabularyDictationService(
        _users,
        FakeDictionary(),  # type: ignore[arg-type]
        rng=random.Random(4),
    )
    assert restored.resume()
    assert restored.current_entry.entry_id == second_id
    assert restored.view(page="practice")["submitted"] is False


def test_hint_levels_only_two_through_four_prevent_progress(tmp_path) -> None:
    service, _users = _service(tmp_path, ("sea",))
    service.start(source="new", count=10)

    service.request_hint(1)
    service.submit("SEA")

    independent = service.view(page="practice")
    assert independent["outcome"] == "correct"
    assert independent["streak"] == 1

    service.start(source="new", count=10)
    service.request_hint(1)
    service.request_hint(2)
    service.submit("sea")

    hinted = service.view(page="practice")
    assert hinted["outcome"] == "hint"
    assert hinted["streak"] == 1


def test_reveal_and_wrong_reset_mastery_progress(tmp_path) -> None:
    service, users = _service(tmp_path, ("sea",))
    entry = users.list_vocabulary()[0]
    for _ in range(4):
        users.record_vocabulary_dictation_outcome(
            entry.entry_id,
            outcome="independent_correct",
        )

    service.start(source="new", count=10)
    service.request_hint(1)
    service.request_hint(2)
    service.request_hint(3)
    service.request_hint(4)

    view = service.view(page="practice")
    assert view["submitted"] is True
    assert view["term"] == "sea"
    assert view["streak"] == 0
    assert view["wrongCount"] == 1


def test_homophone_disambiguation_is_visible_without_using_hint(tmp_path) -> None:
    service, _users = _service(tmp_path, ("sea",))
    service.start(source="new", count=10)

    view = service.view(page="practice")

    assert view["homophoneMeaning"] == "海；海洋"
    assert view["hintLevel"] == 0
    assert view["term"] == ""


def test_empty_submission_is_blocked_without_changing_progress(tmp_path) -> None:
    service, _users = _service(tmp_path, ("sea",))
    service.start(source="new", count=10)

    with pytest.raises(ValueError, match="请先填写"):
        service.submit("   ")

    assert service.view(page="practice")["submitted"] is False
