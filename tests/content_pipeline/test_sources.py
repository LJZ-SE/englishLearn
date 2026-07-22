from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.content_pipeline.clean import clean_sentence, rejection_reason
from tools.content_pipeline.cli import _import_items
from tools.content_pipeline.convokit_source import iter_convokit_utterances
from tools.content_pipeline.gutenberg import iter_gutenberg_text
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.work_database import WorkDatabase


def test_clean_rejects_subtitle_metadata_and_accepts_complete_dialogue() -> None:
    assert rejection_reason("00:01:14,000 --> 00:01:17,000") == "subtitle_metadata"
    assert rejection_reason("[Door slams]") == "stage_direction"
    assert rejection_reason("SPEAKER 2: We need to leave now.") == "speaker_label"
    assert rejection_reason("We need to leave before the last train.") is None
    for prefix in ("WARNING:", "IMPORTANT NOTICE:", "New York:", "Alice:"):
        text = f"{prefix} We need to leave before the last train."
        assert clean_sentence(text) == text


def test_source_manifest_preserves_initial_sources_and_adds_dialogue_sources() -> None:
    manifest_path = Path(__file__).parents[2] / "tools/content_pipeline/source_manifest.json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest[:5] == [
        {
            "key": "tatoeba-eng",
            "kind": "tatoeba",
            "url": (
                "https://downloads.tatoeba.org/exports/per_language/eng/"
                "eng_sentences_detailed.tsv.bz2"
            ),
            "max_items": 150000,
            "license_name": "CC BY 2.0 FR",
            "license_url": "https://creativecommons.org/licenses/by/2.0/fr/",
        },
        {
            "key": "cornell-movie-dialogs",
            "kind": "convokit",
            "download_name": "movie-corpus",
            "license_name": "source terms",
            "license_url": "https://convokit.cornell.edu/documentation/movie.html",
        },
        {
            "key": "switchboard",
            "kind": "convokit",
            "download_name": "switchboard-corpus",
            "license_name": "source terms",
            "license_url": "https://convokit.cornell.edu/documentation/switchboard.html",
        },
        {
            "key": "english-wikinews",
            "kind": "wikinews",
            "url": "https://en.wikinews.org/w/api.php",
            "article_limit": 500,
            "batch_size": 20,
            "snapshot_version": 2,
            "license_name": "per-item license",
            "license_url": "https://en.wikinews.org/wiki/Wikinews:Copyright",
        },
        {
            "key": "gutenberg",
            "kind": "gutenberg",
            "ebook_ids": [11, 74, 76, 84, 98, 1342, 1661, 2701, 345, 174],
            "license_name": "per-item terms",
            "license_url": "https://www.gutenberg.org/policy/license.html",
        },
    ]
    assert [(item["key"], item["kind"]) for item in manifest[5:]] == [
        ("multiwoz-2-2", "multiwoz"),
        ("daily-dialog", "dailydialog"),
        ("mts-dialog", "mts-dialog"),
    ]


def test_convokit_reader_preserves_stable_id_author_and_source_url(tmp_path: Path) -> None:
    payload = tmp_path / "utterances.jsonl"
    payload.write_text(
        json.dumps(
            {
                "id": "movie-utt-17",
                "text": "SPEAKER 2: Please meet me outside after class today.",
                "speaker": {"id": "s-2", "meta": {"name": "Mia"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert list(iter_convokit_utterances(payload, "cornell-movie-dialogs")) == [
        CollectedSentence(
            text="SPEAKER 2: Please meet me outside after class today.",
            source_item_id="movie-utt-17",
            source_author="Mia",
            source_url="https://convokit.cornell.edu/documentation/movie.html",
            source_name="cornell-movie-dialogs",
            license_name="source terms",
            license_url="https://convokit.cornell.edu/documentation/movie.html",
        )
    ]


def test_convokit_uses_speaker_id_without_name_and_skips_missing_speaker(tmp_path: Path) -> None:
    payload = tmp_path / "utterances.jsonl"
    payload.write_text(
        "\n".join(
            json.dumps(item)
            for item in [
                {
                    "id": "movie-utt-with-id",
                    "text": "We should meet outside after class today.",
                    "speaker": "speaker-42",
                },
                {
                    "id": "movie-utt-without-speaker",
                    "text": "We should meet outside after class today.",
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "speakers.json").write_text(
        json.dumps({"speaker-42": {"meta": {}}}), encoding="utf-8"
    )

    items = list(iter_convokit_utterances(payload, "cornell-movie-dialogs"))

    assert [item.source_item_id for item in items] == ["movie-utt-with-id"]
    assert items[0].source_author == "speaker-42"


def test_gutenberg_reader_preserves_stable_id_author_and_source_url(tmp_path: Path) -> None:
    text = tmp_path / "11.txt"
    text.write_text(
        "The Project Gutenberg eBook of Alice's Adventures in Wonderland\n"
        "Title: Alice's Adventures in Wonderland\n"
        "Author: Lewis Carroll\n"
        "Release date: January 1991\n\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK 11 ***\n"
        "Alice was beginning to get very tired of sitting by her sister\n"
        "on the bank, and of having nothing to do.\n\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK 11 ***\n"
        "This text appears after the end marker and must be ignored.\n",
        encoding="utf-8",
    )

    assert list(iter_gutenberg_text(text, 11)) == [
        CollectedSentence(
            text=(
                "Alice was beginning to get very tired of sitting by her sister on the bank, "
                "and of having nothing to do."
            ),
            source_item_id="11:1",
            source_author="Lewis Carroll",
            source_url="https://www.gutenberg.org/ebooks/11",
            source_name="Project Gutenberg",
            license_name="per-item terms",
            license_url="https://www.gutenberg.org/policy/license.html",
        )
    ]


def test_gutenberg_reader_skips_books_without_a_header_author(tmp_path: Path) -> None:
    text = tmp_path / "missing-author.txt"
    text.write_text(
        "Title: Unknown Work\n\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK 99 ***\n"
        "The first complete sentence in this book has no author metadata.\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK 99 ***\n",
        encoding="utf-8",
    )

    assert list(iter_gutenberg_text(text, 99)) == []


def test_cli_rejects_items_with_missing_required_provenance(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    item = CollectedSentence(
        text="The train arrives at nine o'clock.",
        source_name="Example",
        source_item_id="example-1",
        source_url="https://example.test/items/1",
        source_author="",
        license_name="Example terms",
        license_url="https://example.test/license",
    )

    with pytest.raises(ValueError, match="source_author"):
        _import_items(database, [item])

    assert database.stage_counts() == {"raw": 0, "rejected": 0}


def test_wikinews_id_uses_pageid_when_title_changes(tmp_path: Path) -> None:
    from tools.content_pipeline.wikinews import iter_wikinews_extracts

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    for path, title in ((first, "Original title"), (second, "Renamed title")):
        path.write_text(
            json.dumps(
                {
                    "query": {
                        "pages": [
                            {
                                "pageid": 123,
                                "title": title,
                                "fullurl": "https://en.wikinews.org/wiki/Original_title",
                                "extract": "Officials approved the regional transport plan today.",
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

    assert [item.source_item_id for item in iter_wikinews_extracts(first)] == ["123:1"]
    assert [item.source_item_id for item in iter_wikinews_extracts(second)] == ["123:1"]


def test_cli_imports_raw_items_and_clean_records_explicit_rejection(tmp_path: Path) -> None:
    work_db = tmp_path / "work.db"
    utterances = tmp_path / "utterances.jsonl"
    utterances.write_text(
        json.dumps(
            {
                "id": "switchboard-1",
                "text": "[Door slams]",
                "speaker": {"id": "caller-a"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    command = [sys.executable, "-m", "tools.content_pipeline.cli"]

    subprocess.run([*command, "init", str(work_db)], check=True)
    subprocess.run(
        [*command, "import-convokit", str(work_db), str(utterances), "switchboard"],
        check=True,
    )
    subprocess.run([*command, "clean", str(work_db)], check=True)

    database = WorkDatabase(work_db)
    with database.connect() as connection:
        raw_item = connection.execute("SELECT source_item_id FROM raw_items").fetchone()
        rejection = connection.execute("SELECT stage, reason FROM rejections").fetchone()
    assert raw_item == ("switchboard-1",)
    assert rejection == ("clean", "stage_direction")
