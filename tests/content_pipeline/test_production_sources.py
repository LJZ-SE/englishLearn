from __future__ import annotations

import bz2
import json
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.content_pipeline import production_sources
from tools.content_pipeline.production_sources import (
    import_all_sources,
    import_legacy_database,
    report_sources,
)
from tools.content_pipeline.work_database import WorkDatabase


def _write_source_fixtures(tmp_path: Path) -> Path:
    downloads = tmp_path / "fixtures"
    downloads.mkdir()
    tatoeba = downloads / "tatoeba.tsv.bz2"
    with bz2.open(tatoeba, "wt", encoding="utf-8") as stream:
        stream.write("1\teng\tThe train arrives at nine.\talice\n")

    convokit = downloads / "movie.zip"
    with zipfile.ZipFile(convokit, "w") as archive:
        archive.writestr(
            "movie-corpus/utterances.jsonl",
            json.dumps({"id": "u1", "text": "I will call you tomorrow.", "speaker": "bob"})
            + "\n",
        )

    wikinews = downloads / "wikinews.json"
    wikinews.write_text(
        json.dumps(
            {
                "query": {
                    "pages": [
                        {
                            "pageid": 7,
                            "fullurl": "https://en.wikinews.org/wiki/Example",
                            "extract": (
                                "Tuesday, July 21, 2026 The city opened a new library today."
                            ),
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    gutenberg = downloads / "11.txt"
    gutenberg.write_text(
        "Author: Lewis Carroll\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK TEST\n"
        "Alice looked at the clock.\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK TEST\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {"key": "tatoeba-eng", "kind": "tatoeba", "url": tatoeba.as_uri()},
                {
                    "key": "cornell-movie-dialogs",
                    "kind": "convokit",
                    "url": convokit.as_uri(),
                },
                {"key": "english-wikinews", "kind": "wikinews", "url": wikinews.as_uri()},
                {
                    "key": "gutenberg-11",
                    "kind": "gutenberg",
                    "url": gutenberg.as_uri(),
                    "ebook_id": 11,
                },
            ]
        ),
        encoding="utf-8",
    )
    return manifest


def test_import_all_downloads_locks_and_resumes_four_source_kinds(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    manifest = _write_source_fixtures(tmp_path)
    lock = tmp_path / "source-lock.json"

    first = import_all_sources(database, manifest, lock)
    second = import_all_sources(database, manifest, lock)

    assert first == {"tatoeba": 1, "convokit": 1, "wikinews": 1, "gutenberg": 1}
    assert second == first
    payload = json.loads(lock.read_text(encoding="utf-8"))
    assert {entry["kind"] for entry in payload["sources"]} == {
        "tatoeba",
        "convokit",
        "wikinews",
        "gutenberg",
    }
    for entry in payload["sources"]:
        assert entry["final_url"]
        assert entry["size_bytes"] > 0
        assert len(entry["sha256"]) == 64
        assert entry["downloaded_at"].endswith("+00:00")
        cached = lock.parent / entry["cache_path"]
        assert cached.stat().st_size == entry["size_bytes"]


def test_import_all_checkpoints_download_lock_before_source_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    manifest = _write_source_fixtures(tmp_path)
    lock = tmp_path / "source-lock.json"

    def interrupt_import(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(production_sources, "_iter_source", interrupt_import)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        import_all_sources(database, manifest, lock)

    payload = json.loads(lock.read_text(encoding="utf-8"))
    assert [entry["key"] for entry in payload["sources"]] == ["tatoeba-eng"]
    cached = lock.parent / payload["sources"][0]["cache_path"]
    assert cached.is_file()


def _write_legacy_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE sentences(
                id TEXT PRIMARY KEY, text TEXT NOT NULL, translation_zh TEXT NOT NULL,
                category TEXT NOT NULL, source_url TEXT NOT NULL, source_name TEXT NOT NULL,
                license_name TEXT NOT NULL, license_url TEXT NOT NULL,
                source_author TEXT NOT NULL, normalized_hash TEXT NOT NULL UNIQUE
            );
            CREATE TABLE question_variants(
                id TEXT PRIMARY KEY, sentence_id TEXT NOT NULL, difficulty TEXT NOT NULL,
                answer_start INTEGER NOT NULL, answer_end INTEGER NOT NULL,
                canonical_answer TEXT NOT NULL, answer_word_count INTEGER NOT NULL,
                difficulty_score REAL NOT NULL, rationale TEXT NOT NULL
            );
            CREATE TABLE aliases(
                id INTEGER PRIMARY KEY, question_variant_id TEXT NOT NULL, alias TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO sentences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "s0001",
                "The train arrives at nine.",
                "火车九点到。",
                "daily",
                "https://example.test/1",
                "example",
                "CC BY 4.0",
                "https://creativecommons.org/licenses/by/4.0/",
                "alice",
                "digest",
            ),
        )
        connection.execute(
            "INSERT INTO question_variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("s0001-easy", "s0001", "easy", 4, 9, "train", 1, 1.0, "test"),
        )
        connection.execute("INSERT INTO aliases VALUES (1, 's0001-easy', 'railway')")


def test_import_legacy_preserves_ids_aliases_but_not_translation(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    _write_legacy_database(legacy)
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()

    assert import_legacy_database(legacy, database, protected=True) == 1
    assert import_legacy_database(legacy, database, protected=True) == 1

    with database.connect() as connection:
        raw = connection.execute(
            "SELECT id, source_name, source_item_id, protected FROM raw_items"
        ).fetchone()
        sentence_map = connection.execute(
            "SELECT sentence_id, normalized_hash FROM legacy_sentences"
        ).fetchone()
        question_map = connection.execute(
            "SELECT question_id, difficulty, canonical_answer FROM legacy_questions"
        ).fetchone()
        aliases = connection.execute("SELECT question_id, alias FROM legacy_aliases").fetchall()
        translated = connection.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage = 'translate'"
        ).fetchone()[0]
    assert raw is not None
    assert raw[1:] == ("legacy-content", "s0001", 1)
    assert sentence_map == ("s0001", "digest")
    assert question_map == ("s0001-easy", "easy", "train")
    assert aliases == [("s0001-easy", "railway")]
    assert translated == 0


def test_source_report_rejects_missing_provenance_and_reports_kinds(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    manifest = _write_source_fixtures(tmp_path)
    import_all_sources(database, manifest, tmp_path / "source-lock.json")

    output = tmp_path / "source-report.json"
    report = report_sources(database, output)

    assert report["source_kind_count"] == 4
    assert report["missing_provenance_count"] == 0
    assert output.is_file()


def test_production_source_cli_exposes_import_and_report_commands(tmp_path: Path) -> None:
    manifest = _write_source_fixtures(tmp_path)
    legacy = tmp_path / "legacy.db"
    _write_legacy_database(legacy)
    database = tmp_path / "work.db"
    lock = tmp_path / "source-lock.json"
    report = tmp_path / "source-report.json"
    command = [sys.executable, "-m", "tools.content_pipeline.cli"]

    imported = subprocess.run(
        [*command, "import-all", str(database), "--manifest", str(manifest), "--lock", str(lock)],
        check=True,
        capture_output=True,
        text=True,
    )
    protected = subprocess.run(
        [*command, "import-legacy", str(legacy), str(database), "--protected"],
        check=True,
        capture_output=True,
        text=True,
    )
    reported = subprocess.run(
        [*command, "report-sources", str(database), "--output", str(report)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(imported.stdout)["source_kinds"] == 4
    assert json.loads(protected.stdout) == {"legacy_sentences": 1}
    assert json.loads(reported.stdout)["source_kind_count"] == 5


def test_installed_content_entrypoint_loads_repository_tools(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from listening_cloze.content_cli import main

    database = tmp_path / "work.db"
    monkeypatch.setattr(sys, "argv", ["listening-cloze-content", "init", str(database)])
    main()

    assert database.is_file()
    assert capsys.readouterr().err == ""
