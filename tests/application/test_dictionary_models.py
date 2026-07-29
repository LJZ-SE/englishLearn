from __future__ import annotations

from pathlib import Path

from listening_cloze.application.dictionary_models import DictionaryViewModel
from listening_cloze.infrastructure.dictionary import DictionaryEntry
from listening_cloze.infrastructure.tts_service import PrefetchItem


class FakeDictionaryRepository:
    def lookup(self, term: str, *, limit: int = 12) -> tuple[DictionaryEntry, ...]:
        if term.casefold() != "listen":
            return ()
        return (
            DictionaryEntry(
                word="listen",
                phonetic="lisn",
                definition="give attention to sound",
                translation="听；倾听",
                pos="v:100",
                collins=4,
                oxford=True,
                tags=("zk", "gk", "cet4"),
                bnc=900,
                frq=700,
                exchange="p:listened/d:listened/i:listening/3:listens",
                detail="",
                audio="",
            ),
        )


class FakeDictionaryInteractions:
    def __init__(self) -> None:
        self.saved_terms: set[str] = set()
        self.prefetched_terms: list[str] = []

    def is_saved(self, term: str) -> bool:
        return term.casefold() in self.saved_terms

    def add_to_vocabulary(self, term: str):
        self.saved_terms.add(term.casefold())

    def prefetch_pronunciation(self, term: str, *, on_ready, on_error) -> None:
        del on_ready, on_error
        self.prefetched_terms.append(term)


def test_dictionary_view_model_maps_entry_for_qml() -> None:
    model = DictionaryViewModel(FakeDictionaryRepository())

    model.lookup("listen")

    assert model.visible
    assert model.query == "listen"
    assert model.resultText == "找到 1 个词条"
    assert model.entries[0]["word"] == "listen"
    assert model.entries[0]["tagLabels"] == ["高考", "CET-4", "中考"]
    assert model.entries[0]["exchangeText"] == (
        "过去式 listened · 过去分词 listened · 现在分词 listening · 第三人称 listens"
    )
    model.close()
    assert not model.visible


def test_dictionary_view_model_reports_missing_entry_without_failing() -> None:
    model = DictionaryViewModel(FakeDictionaryRepository())

    model.lookup("missing")

    assert model.visible
    assert model.entries == []
    assert model.resultText == "没有找到该词条"


def test_dictionary_view_model_prefetches_first_result_and_marks_saved_entry() -> None:
    interactions = FakeDictionaryInteractions()
    model = DictionaryViewModel(
        FakeDictionaryRepository(),
        interactions=interactions,
    )

    model.lookup("listen")

    assert interactions.prefetched_terms == ["listen"]
    assert model.entries[0]["pronunciationState"] == "generating"
    assert model.entries[0]["isSaved"] is False

    model.addToVocabulary("listen")

    assert model.entries[0]["isSaved"] is True
    assert model.entries[0]["saveError"] == ""


def test_dictionary_view_model_plays_ready_pronunciation() -> None:
    interactions = FakeDictionaryInteractions()
    model = DictionaryViewModel(
        FakeDictionaryRepository(),
        interactions=interactions,
    )
    requested: list[tuple[str, str]] = []
    model.playbackRequested.connect(lambda term, source: requested.append((term, source)))
    model.lookup("listen")
    model.handlePronunciationReady(
        PrefetchItem("dictionary:listen", "listen"),
        Path("/tmp/listen.wav"),
    )

    model.playPronunciation("listen")

    assert requested == [("listen", Path("/tmp/listen.wav").resolve().as_uri())]
    assert model.entries[0]["pronunciationState"] == "playing"
