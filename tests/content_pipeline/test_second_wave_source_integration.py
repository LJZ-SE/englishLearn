from __future__ import annotations

from pathlib import Path

import pytest

from tools.content_pipeline import production_sources
from tools.content_pipeline.models import CollectedSentence


@pytest.mark.parametrize(
    ("kind", "key", "expected"),
    [
        ("ami", "ami-manual-v1-6-2", "ami-meeting-corpus-v1.6.2"),
        ("medquad", "medquad", "medquad"),
        ("sciq", "sciq-train", "SciQ"),
    ],
)
def test_second_wave_source_identity_matches_parser_output(
    kind: str, key: str, expected: str
) -> None:
    assert production_sources._raw_source_name({"kind": kind, "key": key}) == expected


@pytest.mark.parametrize(
    ("kind", "reader_name"),
    [
        ("ami", "iter_ami_utterances"),
        ("medquad", "iter_medquad_questions"),
        ("sciq", "iter_sciq_questions"),
    ],
)
def test_second_wave_source_dispatches_to_matching_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    reader_name: str,
) -> None:
    source = tmp_path / "source"
    expected = CollectedSentence(
        text="A complete sentence.",
        source_url="https://example.test/source",
        source_name="test",
        license_name="test",
        license_url="https://example.test/license",
        source_item_id="item-1",
    )
    monkeypatch.setattr(production_sources, reader_name, lambda path: iter([expected]))

    assert list(production_sources._iter_source(kind, source, {"key": kind})) == [expected]
