from __future__ import annotations

from listening_cloze.application.dictionary_models import DictionaryViewModel
from listening_cloze.infrastructure.dictionary import DictionaryEntry


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
