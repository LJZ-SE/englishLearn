from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from tools.content_pipeline import cli
from tools.content_pipeline.categorize import SceneClassifier
from tools.content_pipeline.classification import (
    ClassificationImportError,
    export_classification_repairs,
    import_classification_repairs,
)
from tools.content_pipeline.scenes import SCENES, SceneDefinition
from tools.content_pipeline.work_database import WorkDatabase


def _ready_item(
    database: WorkDatabase, item_id: str, text: str, *, source_name: str = "fixture"
) -> int:
    row_id = database.upsert_raw(
        source_name=source_name,
        source_item_id=item_id,
        source_url=f"https://example.test/{item_id}",
        source_author=f"author-{item_id}",
        license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        text=text,
    )
    database.mark_stage(row_id, "clean", payload={"clean_text": text})
    database.mark_stage(row_id, "dedupe", payload={"simhash64": "0"})
    return row_id


def test_stage_cli_batch_size_runs_to_completion_and_second_run_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    for index in range(5):
        database.upsert_raw(
            source_name="fixture",
            source_item_id=str(index),
            source_url=f"https://example.test/{index}",
            source_author=f"author-{index}",
            license_name="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            text=f"The hotel reservation number {index} is ready for tonight.",
        )

    monkeypatch.setattr(
        sys,
        "argv",
        ["listening-cloze-content", "clean", str(database_path), "--batch-size", "2"],
    )
    cli.main()
    first = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(
        sys,
        "argv",
        ["listening-cloze-content", "clean", str(database_path), "--batch-size", "2"],
    )
    cli.main()
    second = json.loads(capsys.readouterr().out)

    assert first["processed"] == 5
    assert second["processed"] == 0
    assert database.stage_counts()["clean"] == 5


def test_classification_exchange_is_complete_strict_and_atomic(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first = _ready_item(database, "1", "The thoughtful visitor considered several options.")
    second = _ready_item(database, "2", "Several people carefully considered another proposal.")
    for item_id in (first, second):
        database.mark_stage(
            item_id,
            "classify",
            payload={
                "top_scene": None,
                "sub_scene": None,
                "confidence": 0.1,
                "method": "llm_required",
            },
        )
    export_path = tmp_path / "repairs.jsonl"

    assert export_classification_repairs(database, export_path) == 2
    exported = [json.loads(line) for line in export_path.read_text().splitlines()]
    assert all(row["method"] == "llm_required" for row in exported)
    assert all(len(row["candidate_labels"]) == 32 for row in exported)
    assert exported[0]["text"]

    invalid_path = tmp_path / "invalid.jsonl"
    invalid_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "item_id": first,
                        "top_scene": "daily",
                        "sub_scene": "daily_social",
                        "reason": "social interaction",
                    }
                ),
                json.dumps(
                    {
                        "item_id": second,
                        "top_scene": "daily",
                        "sub_scene": "daily_social",
                        "reason": "social interaction",
                        "extra": True,
                    }
                ),
            )
        )
        + "\n"
    )
    with pytest.raises(ClassificationImportError, match="字段"):
        import_classification_repairs(database, [invalid_path])
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage='classify' "
            "AND json_extract(payload_json, '$.method')='llm_required'"
        ).fetchone()[0] == 2

    valid_path = tmp_path / "valid.jsonl"
    valid_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "item_id": item_id,
                    "top_scene": "daily",
                    "sub_scene": "daily_social",
                    "reason": "social interaction",
                }
            )
            for item_id in (first, second)
        ) + "\n"
    )
    assert import_classification_repairs(database, [valid_path]) == 2
    assert database.pending_classification_repairs() == 0


def test_classification_import_rejects_missing_duplicate_unknown_and_invalid_scene(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first = _ready_item(database, "1", "The thoughtful visitor considered several options.")
    second = _ready_item(database, "2", "Several people carefully considered another proposal.")
    for item_id in (first, second):
        database.mark_stage(
            item_id,
            "classify",
            payload={"method": "llm_required", "top_scene": None, "sub_scene": None},
        )

    cases = {
        "missing": [
            {"item_id": first, "top_scene": "daily", "sub_scene": "daily_social", "reason": "x"}
        ],
        "duplicate": [
            {"item_id": first, "top_scene": "daily", "sub_scene": "daily_social", "reason": "x"},
            {"item_id": first, "top_scene": "daily", "sub_scene": "daily_social", "reason": "x"},
        ],
        "unknown": [
            {"item_id": first, "top_scene": "daily", "sub_scene": "daily_social", "reason": "x"},
            {"item_id": 999999, "top_scene": "daily", "sub_scene": "daily_social", "reason": "x"},
        ],
        "invalid": [
            {"item_id": first, "top_scene": "daily", "sub_scene": "daily_social", "reason": "x"},
            {"item_id": second, "top_scene": "travel", "sub_scene": "daily_social", "reason": "x"},
        ],
    }
    for name, rows in cases.items():
        path = tmp_path / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        with pytest.raises(ClassificationImportError):
            import_classification_repairs(database, [path])
    assert database.pending_classification_repairs() == 2


def test_classification_import_rejects_result_file_larger_than_500(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    path = tmp_path / "oversized.jsonl"
    row = {
        "item_id": 1,
        "top_scene": "daily",
        "sub_scene": "daily_social",
        "reason": "fixture",
    }
    path.write_text("\n".join(json.dumps(row) for _ in range(501)) + "\n")

    with pytest.raises(ClassificationImportError, match="500"):
        import_classification_repairs(database, [path])


def test_dedupe_uses_persistent_index_without_loading_all_stage_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    for index, text in enumerate(
        (
            "The train leaves the station at nine o'clock.",
            "The train leaves this station at nine o'clock.",
            "Please send the revised report before Friday.",
        )
    ):
        item_id = database.upsert_raw(
            source_name="fixture",
            source_item_id=str(index),
            source_url=f"https://example.test/{index}",
            source_author=f"author-{index}",
            license_name="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            text=text,
        )
        database.mark_stage(item_id, "clean", payload={"clean_text": text})
    monkeypatch.setattr(
        database,
        "stage_inputs",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unbounded load")),
    )

    summary = cli._dedupe_items(database, 2, run_to_completion=True)

    assert summary["processed"] == 3
    assert summary["near_duplicate"] == 1
    assert database.stage_counts()["dedupe"] == 2
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM dedupe_fingerprints").fetchone()[0] == 2


def test_scene_catalog_still_has_exactly_32_labels() -> None:
    assert len(SCENES) == 32


def test_candidate_pool_keeps_unmatched_rows_auditable_and_protected_rows_pending() -> None:
    classifier = SceneClassifier()
    text = "The thoughtful visitor considered several options."

    regular = classifier.classify_candidate(text)
    protected = classifier.classify_candidate(text, protected=True)

    assert regular.method == "out_of_candidate_pool"
    assert regular.sub_scene is None
    assert protected.method == "llm_required"


def test_candidate_pool_uses_wikinews_fallback_without_restoring_broad_keywords() -> None:
    classifier = SceneClassifier()

    directions = classifier.classify_candidate("This is always the way it has been.")
    current = classifier.classify_candidate("The whole world was quiet yesterday.")
    wikinews = classifier.classify_candidate(
        "Further details emerged after a scheduled briefing.",
        source_name="English Wikinews",
    )

    assert directions.method == "out_of_candidate_pool"
    assert directions.sub_scene is None
    assert current.method == "out_of_candidate_pool"
    assert current.sub_scene is None
    assert (wikinews.method, wikinews.sub_scene) == ("candidate_source", "news_current")


def test_clean_stage_preserves_protected_legacy_even_when_normal_filter_rejects(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    item_id = database.upsert_raw(
        source_name="legacy-content",
        source_item_id="s0001",
        source_url="https://example.test/legacy/s0001",
        source_author="legacy-author",
        license_name="legacy",
        license_url="https://example.test/license",
        text="Too short.",
        protected=True,
    )

    summary = cli._clean_items(database, 10)

    assert summary == {"processed": 1, "accepted": 1, "rejected": 0}
    assert database.claim_batch("dedupe", 10)[0].id == item_id


def test_bounded_exact_selection_does_not_use_unbounded_stage_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    scene = SceneDefinition("travel", "出行旅行", "travel_hotel", "酒店住宿", 5)
    monkeypatch.setattr(cli, "SCENES", (scene,))
    for index in range(20):
        item_id = _ready_item(
            database,
            str(index),
            f"The hotel reservation fixture number {index} is confirmed tonight.",
            source_name=f"fixture-{index % 4}",
        )
        database.mark_stage(
            item_id,
            "classify",
            payload={
                "top_scene": "travel",
                "sub_scene": "travel_hotel",
                "confidence": 0.8,
                "method": "keyword",
            },
        )
    monkeypatch.setattr(
        database,
        "stage_inputs",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unbounded load")),
    )

    summary = cli._select_items(database, bounded=True)

    assert summary is not None and summary["selected"] == 5
    assert database.stage_counts()["select"] == 5


def test_bounded_selection_failure_preserves_previous_atomic_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    item_id = _ready_item(
        database,
        "only",
        "The hotel reservation is confirmed for the visiting guest tonight.",
    )
    database.mark_stage(
        item_id,
        "classify",
        payload={
            "top_scene": "travel",
            "sub_scene": "travel_hotel",
            "confidence": 0.9,
            "method": "keyword",
        },
    )
    database.replace_stage(
        "select",
        [(item_id, {"top_scene": "travel", "sub_scene": "travel_hotel"})],
    )
    monkeypatch.setattr(
        cli,
        "SCENES",
        (SceneDefinition("travel", "出行旅行", "travel_hotel", "酒店住宿", 5),),
    )

    with pytest.raises(ValueError, match="场景配额差额"):
        cli._select_items(database, bounded=True)

    with database.connect() as connection:
        selected_ids = connection.execute(
            "SELECT item_id FROM stage_results WHERE stage='select'"
        ).fetchall()
    assert selected_ids == [(item_id,)]
