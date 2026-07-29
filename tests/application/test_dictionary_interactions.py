from pathlib import Path

from listening_cloze.application.dictionary_interactions import (
    DictionaryInteractionService,
)
from listening_cloze.infrastructure.database import UserRepository
from listening_cloze.infrastructure.tts_service import PrefetchItem


class FakeTtsService:
    def __init__(self) -> None:
        self.items: list[PrefetchItem] = []
        self.on_ready = None
        self.on_error = None

    def schedule_background(self, items, *, on_ready=None, on_error=None) -> None:
        self.items.extend(items)
        self.on_ready = on_ready
        self.on_error = on_error


def test_dictionary_interaction_adds_term_without_question_context(
    tmp_path: Path,
) -> None:
    repository = UserRepository(tmp_path / "user.db")
    service = DictionaryInteractionService(repository)

    entry = service.add_to_vocabulary("  kind   of  ")

    assert entry.term == "kind of"
    assert entry.source_kind == "dictionary"
    assert entry.source_question_id is None
    assert service.is_saved("KIND OF")


def test_dictionary_interaction_prefetches_pronunciation_in_background(
    tmp_path: Path,
) -> None:
    service = DictionaryInteractionService(UserRepository(tmp_path / "user.db"))
    tts = FakeTtsService()
    service.attach_tts(tts)

    service.prefetch_pronunciation(
        "feature",
        on_ready=lambda _item, _path: None,
        on_error=lambda _item, _error: None,
    )

    assert tts.items == [PrefetchItem("dictionary:feature", "feature")]
