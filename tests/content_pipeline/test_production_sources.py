from __future__ import annotations

import bz2
import json
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
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


def test_labeled_sources_use_archive_cache_suffix_and_normalization_in_fingerprint() -> None:
    clinc = {
        "key": "clinc150",
        "kind": "clinc150",
        "url": "https://example.test/source.zip",
        "normalization_version": 1,
    }
    massive = {
        "key": "massive-1-0",
        "kind": "massive",
        "url": "https://example.test/source.tar.gz",
        "normalization_version": 1,
    }

    assert production_sources._cache_filename("clinc150", clinc["url"]) == "clinc150.zip"
    assert production_sources._cache_filename("massive-1-0", massive["url"]) == "massive-1-0.tar.gz"
    assert production_sources._source_config(clinc, clinc["url"])["normalization_version"] == 1
    before = production_sources._config_fingerprint(clinc, clinc["url"])
    clinc["normalization_version"] = 2
    assert production_sources._config_fingerprint(clinc, clinc["url"]) != before

    legacy_source = {
        "key": "multiwoz-2-2",
        "kind": "multiwoz",
        "url": "https://example.test/source.zip",
    }
    assert "normalization_version" not in production_sources._source_config(
        legacy_source, legacy_source["url"]
    )


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
    assert [entry["key"] for entry in payload["sources"]] == [
        "tatoeba-eng",
        "cornell-movie-dialogs",
        "english-wikinews",
        "gutenberg-11",
    ]
    assert payload["complete"] is False
    cached = lock.parent / payload["sources"][0]["cache_path"]
    assert cached.is_file()
    monkeypatch.undo()

    import_all_sources(database, manifest, lock)

    assert json.loads(lock.read_text(encoding="utf-8"))["complete"] is True


def test_import_all_rejects_manifest_drift_without_refresh(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    manifest = _write_source_fixtures(tmp_path)
    lock = tmp_path / "source-lock.json"
    import_all_sources(database, manifest, lock)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload[0]["max_items"] = 99
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest 已漂移"):
        import_all_sources(database, manifest, lock)


def test_refresh_lock_replaces_rows_when_v2_max_items_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _write_source_fixtures(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    tatoeba_path = Path(urllib.parse.urlparse(payload[0]["url"]).path)
    with bz2.open(tatoeba_path, "wt", encoding="utf-8") as stream:
        stream.write("1\teng\tFirst sentence is here.\talice\n")
        stream.write("2\teng\tSecond sentence is here.\tbob\n")
    payload[0]["max_items"] = 2
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    lock = tmp_path / "source-lock.json"
    import_all_sources(database, manifest, lock)
    payload[0]["max_items"] = 1
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    original_delete = database.delete_raw_source

    def interrupt_before_delete(_identity: str) -> int:
        raise RuntimeError("simulated pre-delete interruption")

    monkeypatch.setattr(database, "delete_raw_source", interrupt_before_delete)
    with pytest.raises(RuntimeError, match="pre-delete interruption"):
        import_all_sources(database, manifest, lock, refresh_lock=True)
    interrupted = json.loads(lock.read_text(encoding="utf-8"))
    assert interrupted["pending_refresh_identities"] == ["Tatoeba"]
    assert interrupted["complete"] is False
    monkeypatch.setattr(database, "delete_raw_source", original_delete)

    import_all_sources(database, manifest, lock)

    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM raw_items WHERE source_name = 'Tatoeba'"
        ).fetchone()[0]
    assert count == 1
    locked = json.loads(lock.read_text(encoding="utf-8"))["sources"][0]
    assert locked["config"]["max_items"] == 1
    assert json.loads(lock.read_text(encoding="utf-8"))["pending_refresh_identities"] == []


def test_refresh_convokit_rebuilds_extracted_cache_from_new_archive(tmp_path: Path) -> None:
    manifest = _write_source_fixtures(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    lock = tmp_path / "source-lock.json"
    import_all_sources(database, manifest, lock)
    replacement = tmp_path / "replacement.zip"
    with zipfile.ZipFile(replacement, "w") as archive:
        archive.writestr(
            "utterances.jsonl",
            json.dumps({"id": "new", "text": "This comes from the new archive.", "speaker": "n"})
            + "\n",
        )
    payload[1]["url"] = replacement.as_uri()
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    import_all_sources(database, manifest, lock, refresh_lock=True)

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT source_item_id, text FROM raw_items WHERE source_name='cornell-movie-dialogs'"
        ).fetchall()
    assert rows == [("new", "This comes from the new archive.")]
    entry = json.loads(lock.read_text(encoding="utf-8"))["sources"][1]
    extracted = lock.parent / "downloads" / "cornell-movie-dialogs-extracted"
    assert (extracted / "archive-sha256.txt").read_text().strip() == entry["sha256"]


def _write_gutenberg_manifest(tmp_path: Path, count: int = 10) -> tuple[Path, list[dict]]:
    sources = []
    for ebook_id in range(80, 80 + count):
        path = tmp_path / f"{ebook_id}.txt"
        path.write_text(
            f"Author: Author {ebook_id}\n"
            "*** START OF THE PROJECT GUTENBERG EBOOK TEST\n"
            f"Original sentence from book {ebook_id}.\n"
            "*** END OF THE PROJECT GUTENBERG EBOOK TEST\n",
            encoding="utf-8",
        )
        sources.append(
            {
                "key": f"gutenberg-{ebook_id}",
                "kind": "gutenberg",
                "url": path.as_uri(),
                "ebook_id": ebook_id,
                "license_name": "terms",
                "license_url": "https://example.test/terms",
            }
        )
    manifest = tmp_path / "gutenberg-manifest.json"
    manifest.write_text(json.dumps(sources), encoding="utf-8")
    return manifest, sources


def test_refresh_one_gutenberg_sibling_reimports_all_ten_books(tmp_path: Path) -> None:
    manifest, sources = _write_gutenberg_manifest(tmp_path)
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    lock = tmp_path / "source-lock.json"
    import_all_sources(database, manifest, lock)
    replacement = tmp_path / "replacement-84.txt"
    replacement.write_text(
        "Author: New Author\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK TEST\n"
        "Updated sentence from book 84.\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK TEST\n",
        encoding="utf-8",
    )
    sources[4]["url"] = replacement.as_uri()
    manifest.write_text(json.dumps(sources), encoding="utf-8")

    import_all_sources(database, manifest, lock, refresh_lock=True)

    with database.connect() as connection:
        rows = connection.execute(
            "SELECT source_item_id, text FROM raw_items WHERE source_name='Project Gutenberg'"
        ).fetchall()
    assert len(rows) == 10
    assert any(item_id.startswith("84:") and text.startswith("Updated") for item_id, text in rows)

    for source in sources:
        source["license_name"] = "updated terms"
    manifest.write_text(json.dumps(sources), encoding="utf-8")
    import_all_sources(database, manifest, lock, refresh_lock=True)
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM raw_items WHERE source_name='Project Gutenberg'"
        ).fetchone()[0] == 10


def test_refresh_download_failure_does_not_delete_gutenberg_siblings(tmp_path: Path) -> None:
    manifest, sources = _write_gutenberg_manifest(tmp_path, count=2)
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    lock = tmp_path / "source-lock.json"
    import_all_sources(database, manifest, lock)
    sources[1]["url"] = (tmp_path / "missing.txt").as_uri()
    manifest.write_text(json.dumps(sources), encoding="utf-8")

    with pytest.raises(urllib.error.URLError):
        import_all_sources(database, manifest, lock, refresh_lock=True)

    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM raw_items WHERE source_name='Project Gutenberg'"
        ).fetchone()[0] == 2


def test_interrupted_identity_import_recovers_all_gutenberg_siblings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, sources = _write_gutenberg_manifest(tmp_path, count=3)
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    lock = tmp_path / "source-lock.json"
    import_all_sources(database, manifest, lock)
    sources[1]["license_name"] = "changed"
    manifest.write_text(json.dumps(sources), encoding="utf-8")
    original_import = production_sources._import_items
    calls = 0

    def interrupt_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated import interruption")
        return original_import(*args, **kwargs)

    monkeypatch.setattr(production_sources, "_import_items", interrupt_second)
    with pytest.raises(RuntimeError, match="simulated import interruption"):
        import_all_sources(database, manifest, lock, refresh_lock=True)
    monkeypatch.undo()

    import_all_sources(database, manifest, lock)

    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM raw_items WHERE source_name='Project Gutenberg'"
        ).fetchone()[0] == 3
    assert json.loads(lock.read_text(encoding="utf-8"))["complete"] is True


@pytest.mark.parametrize("unsafe_key", ["../escape", "Uppercase", "two--dashes"])
def test_import_all_rejects_unsafe_manifest_keys(tmp_path: Path, unsafe_key: str) -> None:
    manifest = _write_source_fixtures(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload[0]["key"] = unsafe_key
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()

    with pytest.raises(ValueError, match="安全 slug"):
        import_all_sources(database, manifest, tmp_path / "source-lock.json")


def test_import_all_rejects_duplicate_expanded_keys(tmp_path: Path) -> None:
    manifest = _write_source_fixtures(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload.append(payload[0])
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()

    with pytest.raises(ValueError, match="重复 expanded key"):
        import_all_sources(database, manifest, tmp_path / "source-lock.json")


def test_locked_source_rejects_changed_upstream_bytes_without_overwriting_lock(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    manifest = _write_source_fixtures(tmp_path)
    lock = tmp_path / "source-lock.json"
    import_all_sources(database, manifest, lock)
    before = lock.read_bytes()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    upstream = Path(urllib.parse.urlparse(payload[0]["url"]).path)
    with bz2.open(upstream, "wt", encoding="utf-8") as stream:
        stream.write("2\teng\tChanged upstream bytes.\tbob\n")
    cached = lock.parent / json.loads(before)["sources"][0]["cache_path"]
    cached.write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="上游来源字节已变化"):
        import_all_sources(database, manifest, lock)

    assert lock.read_bytes() == before


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
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["listening-cloze-content", "init", str(database)])
    main()

    assert database.is_file()
    assert capsys.readouterr().err == ""
