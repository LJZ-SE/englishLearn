from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.content_pipeline.work_database import WorkDatabase


def add_raw_item(database: WorkDatabase, *, source_item_id: str = "42") -> int:
    return database.upsert_raw(
        source_name="Tatoeba",
        source_item_id=source_item_id,
        source_url=f"https://tatoeba.org/en/sentences/show/{source_item_id}",
        source_author="alice",
        license_name="CC BY 2.0 FR",
        license_url="https://creativecommons.org/licenses/by/2.0/fr/",
        text="The train arrives at nine o'clock.",
    )


def test_work_database_is_idempotent_and_resumes_pending_rows(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first_id = add_raw_item(database)
    second_id = add_raw_item(database)

    assert first_id == second_id
    assert database.claim_batch("dedupe", limit=10) == []
    batch = database.claim_batch("clean", limit=10)
    assert [row.id for row in batch] == [first_id]
    database.mark_stage(first_id, "clean", payload={"clean_text": "The train arrives."})
    assert database.claim_batch("clean", limit=10) == []
    assert [row.id for row in database.claim_batch("dedupe", limit=10)] == [first_id]


def test_work_database_preserves_provenance_and_excludes_rejected_rows(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    item_id = database.upsert_raw(
        source_name="Wikinews",
        source_item_id="story-7",
        source_url="https://example.test/story-7",
        source_author="reporter",
        license_name="CC BY 2.5",
        license_url="https://creativecommons.org/licenses/by/2.5/",
        text="The library opened its doors today.",
        protected=True,
    )

    [item] = database.claim_batch("clean", limit=1)
    assert item.id == item_id
    assert item.source_author == "reporter"
    assert item.license_name == "CC BY 2.5"
    assert item.protected is True

    database.record_rejection(item_id, "clean", "sensitive")

    assert database.claim_batch("clean", limit=10) == []
    assert database.stage_counts() == {"raw": 1, "rejected": 1}


def test_work_database_upserts_stage_payload_and_reports_counts(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    item_id = add_raw_item(database)

    database.mark_stage(item_id, "clean", payload={"clean_text": "First result"})
    database.mark_stage(
        item_id,
        "clean",
        payload={"clean_text": "Replacement result"},
        model_version="clean-v2",
    )

    assert database.stage_counts() == {"raw": 1, "clean": 1, "rejected": 0}
    with database.connect() as connection:
        row = connection.execute(
            "SELECT payload_json, model_version FROM stage_results WHERE item_id = ? AND stage = ?",
            (item_id, "clean"),
        ).fetchone()
    assert row == (json.dumps({"clean_text": "Replacement result"}, ensure_ascii=False), "clean-v2")


def test_content_cli_initializes_and_reports_status(tmp_path: Path) -> None:
    database_path = tmp_path / "work.db"
    command = [sys.executable, "-m", "tools.content_pipeline.cli"]

    initialized = subprocess.run(
        [*command, "init", str(database_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    status = subprocess.run(
        [*command, "status", str(database_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert initialized.stdout == ""
    assert json.loads(status.stdout) == {"raw": 0, "rejected": 0}
