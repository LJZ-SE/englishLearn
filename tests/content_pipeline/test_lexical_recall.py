from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from tools.content_pipeline import cli
from tools.content_pipeline import lexical_recall as recall_module
from tools.content_pipeline.lexical_recall import run_lexical_conflict_recall
from tools.content_pipeline.semantic_recall import SelectionCapacity
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


def _unlimited_capacity() -> SelectionCapacity:
    return SelectionCapacity(1_000, 1_000, Counter(), Counter())


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

    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: _unlimited_capacity(),
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

    capacity = SelectionCapacity(
        1,
        1,
        Counter({"saturated-source": 1}),
        Counter(),
    )
    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: capacity,
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


def test_lexical_recall_consumes_remaining_source_capacity_across_top_k(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first_a = _out_of_pool_item(
        database,
        1,
        "The airport flight desk is next to the hotel room.",
        source_name="source-a",
    )
    _out_of_pool_item(
        database,
        2,
        "The airport flight gate is next to the hotel room.",
        source_name="source-a",
    )
    candidate_b = _out_of_pool_item(
        database,
        3,
        "The airport is next to the hotel.",
        source_name="source-b",
    )
    capacity = SelectionCapacity(
        source_limit=2,
        author_limit=2,
        source_counts=Counter({"source-a": 1}),
        author_counts=Counter(),
    )
    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: capacity,
    )
    output = tmp_path / "hotel.jsonl"

    run_lexical_conflict_recall(
        database,
        sub_scene="travel_hotel",
        keywords=("hotel",),
        phrases=("hotel room",),
        output_path=output,
        exclude_ids=set(),
        top_k=2,
    )

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert {row["item_id"] for row in rows} == {first_a, candidate_b}


def test_lexical_recall_keeps_lower_ranked_source_needed_to_fill_top_k(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    for index in range(1, 34):
        _out_of_pool_item(
            database,
            index,
            f"The airport flight gate {index} is next to the hotel room.",
            source_name="source-a",
        )
    candidate_b = _out_of_pool_item(
        database,
        34,
        "The airport is next to the hotel.",
        source_name="source-b",
    )
    capacity = SelectionCapacity(
        source_limit=2,
        author_limit=100,
        source_counts=Counter({"source-a": 1}),
        author_counts=Counter(),
    )
    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: capacity,
    )
    output = tmp_path / "hotel.jsonl"

    run_lexical_conflict_recall(
        database,
        sub_scene="travel_hotel",
        keywords=("hotel",),
        phrases=("hotel room",),
        output_path=output,
        exclude_ids=set(),
        top_k=2,
    )

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 2
    assert {row["source_name"] for row in rows} == {"source-a", "source-b"}
    assert candidate_b in {row["item_id"] for row in rows}


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

    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: _unlimited_capacity(),
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


def test_lexical_recall_never_requeues_explicit_llm_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    rejected = _out_of_pool_item(
        database,
        1,
        "The airport shuttle took us to the hotel.",
    )
    database.mark_stage(
        rejected,
        "classify",
        payload={"method": "llm_required", "top_scene": None, "sub_scene": None},
    )
    database.apply_classification_repairs(
        [(rejected, None, None, "independent review rejected this candidate")]
    )

    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: _unlimited_capacity(),
    )
    output = tmp_path / "hotel.jsonl"
    summary = run_lexical_conflict_recall(
        database,
        sub_scene="travel_hotel",
        keywords=("hotel",),
        phrases=(),
        output_path=output,
        exclude_ids=set(),
        top_k=100,
    )

    assert summary == {"matched": 0, "selected": 0}
    assert output.read_text() == ""
