from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tools.content_pipeline.sciq_source import iter_sciq_questions


def _write_sciq(path: Path, rows: list[dict[str, object]]) -> None:
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_sciq_emits_science_questions_with_stable_provenance(tmp_path: Path) -> None:
    source = tmp_path / "train.parquet"
    _write_sciq(
        source,
        [
            {
                "question": "What force pulls objects toward Earth",
                "correct_answer": "gravity",
                "distractor1": "light",
                "distractor2": "sound",
                "distractor3": "heat",
                "support": "Gravity attracts objects with mass.",
            },
            {
                "question": "Which organ pumps blood?",
                "correct_answer": "heart",
                "distractor1": "lung",
                "distractor2": "skin",
                "distractor3": "bone",
                "support": "The heart pumps blood.",
            },
        ],
    )

    items = list(iter_sciq_questions(source))

    assert [item.text for item in items] == [
        "What force pulls objects toward Earth?",
        "Which organ pumps blood?",
    ]
    assert [item.source_item_id for item in items] == [
        "sciq:train:0",
        "sciq:train:1",
    ]
    assert all(item.source_name == "SciQ" for item in items)
    assert all(item.source_author == "" for item in items)
    assert all(
        (item.top_scene, item.sub_scene) == ("technology", "technology_science")
        for item in items
    )


def test_sciq_rejects_schema_drift_in_required_columns(tmp_path: Path) -> None:
    source = tmp_path / "train.parquet"
    _write_sciq(source, [{"question": "What is gravity?"}])

    with pytest.raises(ValueError, match="SciQ Parquet schema 漂移"):
        list(iter_sciq_questions(source))


def test_sciq_rejects_non_string_question(tmp_path: Path) -> None:
    source = tmp_path / "train.parquet"
    _write_sciq(
        source,
        [
            {
                "question": "What is gravity?",
                "correct_answer": "gravity",
                "distractor1": "light",
                "distractor2": "sound",
                "distractor3": "heat",
                "support": "Gravity attracts objects with mass.",
            },
            {
                "question": None,
                "correct_answer": "gravity",
                "distractor1": "light",
                "distractor2": "sound",
                "distractor3": "heat",
                "support": "Gravity attracts objects with mass.",
            }
        ],
    )

    with pytest.raises(ValueError, match="SciQ 第 1 行 question 必须是字符串"):
        list(iter_sciq_questions(source))


def test_sciq_rejects_non_string_required_column_type(tmp_path: Path) -> None:
    source = tmp_path / "train.parquet"
    _write_sciq(
        source,
        [
            {
                "question": "What is gravity?",
                "correct_answer": 123,
                "distractor1": "light",
                "distractor2": "sound",
                "distractor3": "heat",
                "support": "Gravity attracts objects with mass.",
            }
        ],
    )

    with pytest.raises(ValueError, match="correct_answer.*字符串"):
        list(iter_sciq_questions(source))


def test_sciq_rejects_empty_dataset(tmp_path: Path) -> None:
    source = tmp_path / "train.parquet"
    schema = pa.schema(
        [
            ("question", pa.string()),
            ("correct_answer", pa.string()),
            ("distractor1", pa.string()),
            ("distractor2", pa.string()),
            ("distractor3", pa.string()),
            ("support", pa.string()),
        ]
    )
    pq.write_table(pa.Table.from_pylist([], schema=schema), source)

    with pytest.raises(ValueError, match="SciQ 没有有效问题"):
        list(iter_sciq_questions(source))
