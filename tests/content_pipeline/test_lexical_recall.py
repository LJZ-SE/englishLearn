from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tools.content_pipeline import cli
from tools.content_pipeline import lexical_recall as recall_module
from tools.content_pipeline.lexical_recall import run_lexical_conflict_recall
from tools.content_pipeline.work_database import WorkDatabase


def _out_of_pool_item(
    database: WorkDatabase,
    index: int,
    text: str,
    *,
    source_name: str = "available-source",
) -> int:
    item_id = database.upsert_raw(
        source_name=source_name,
        source_item_id=str(index),
        source_url=f"https://example.test/{index}",
        source_author=f"author-{index}",
        license_name="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        text=text,
    )
    database.mark_stage(item_id, "clean", payload={"clean_text": text})
    database.mark_stage(item_id, "dedupe", payload={"simhash64": str(index)})
    database.mark_stage(
        item_id,
        "classify",
        payload={
            "top_scene": None,
            "sub_scene": None,
            "confidence": 0.0,
            "method": "out_of_candidate_pool",
        },
    )
    return item_id


def test_lexical_conflict_recall_requires_registered_strong_signal_and_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    conflict = _out_of_pool_item(
        database,
        1,
        "The airport shuttle took us to the hotel.",
    )
    _out_of_pool_item(database, 2, "They stayed cold all night.")
    _out_of_pool_item(database, 3, "The hotel opened yesterday.")
    excluded = _out_of_pool_item(
        database,
        4,
        "The airport is next to the hotel.",
    )

    class CapacityFixture:
        def allows(self, source_name: str, source_author: str) -> bool:
            return True

    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: CapacityFixture(),
    )
    output = tmp_path / "hotel.jsonl"

    summary = run_lexical_conflict_recall(
        database,
        sub_scene="travel_hotel",
        keywords=("hotel",),
        phrases=("hotel room",),
        output_path=output,
        exclude_ids={excluded},
        top_k=100,
    )
    rows = [json.loads(line) for line in output.read_text().splitlines()]

    assert summary == {"matched": 1, "selected": 1}
    assert [row["item_id"] for row in rows] == [conflict]
    assert rows[0]["trigger_keywords"] == ["hotel"]
    assert rows[0]["trigger_phrases"] == []
    assert rows[0]["target_score"] == 2.0
    assert rows[0]["competing_scene"] == "travel_transport"
    assert rows[0]["competing_score"] == 2.0


def test_lexical_conflict_recall_rejects_ordinary_fallback_keyword(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()

    with pytest.raises(ValueError, match="不是.*强信号"):
        run_lexical_conflict_recall(
            database,
            sub_scene="travel_hotel",
            keywords=("room",),
            phrases=(),
            output_path=tmp_path / "hotel.jsonl",
            exclude_ids=set(),
            top_k=100,
        )


def test_lexical_conflict_recall_excludes_saturated_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    _out_of_pool_item(
        database,
        1,
        "The airport is next to the hotel.",
        source_name="saturated-source",
    )
    available = _out_of_pool_item(
        database,
        2,
        "The station is next to the hotel.",
        source_name="available-source",
    )

    class CapacityFixture:
        def allows(self, source_name: str, source_author: str) -> bool:
            return source_name != "saturated-source"

    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: CapacityFixture(),
    )
    output = tmp_path / "hotel.jsonl"
    run_lexical_conflict_recall(
        database,
        sub_scene="travel_hotel",
        keywords=("hotel",),
        phrases=(),
        output_path=output,
        exclude_ids=set(),
        top_k=1,
    )

    assert json.loads(output.read_text())["item_id"] == available


def test_lexical_conflict_recall_cli_loads_strict_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    expected = _out_of_pool_item(
        database,
        1,
        "The airport shuttle took us to the hotel.",
    )

    class CapacityFixture:
        def allows(self, source_name: str, source_author: str) -> bool:
            return True

    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: CapacityFixture(),
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "sub_scene": "travel_hotel",
                "keywords": ["hotel"],
                "phrases": [],
                "top_k": 100,
            }
        )
    )
    output = tmp_path / "hotel.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "listening-cloze-content",
            "recall-lexical-conflicts",
            str(database_path),
            "--config",
            str(config),
            "--output",
            str(output),
        ],
    )

    cli.main()

    assert json.loads(capsys.readouterr().out) == {"matched": 1, "selected": 1}
    assert json.loads(output.read_text())["item_id"] == expected
