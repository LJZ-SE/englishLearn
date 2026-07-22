from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from tools.content_pipeline import cli
from tools.content_pipeline import semantic_recall as recall_module
from tools.content_pipeline.semantic_recall import (
    ModelMetadata,
    RecallScene,
    run_semantic_recall,
    run_semantic_recall_many,
)
from tools.content_pipeline.work_database import WorkDatabase


class FakeEmbedder:
    metadata = ModelMetadata("fixture-model", "fixture-revision", "a" * 64)

    def __init__(
        self,
        vectors: dict[str, tuple[float, float]],
        *,
        fail_on_call: int | None = None,
    ) -> None:
        self.vectors = vectors
        self.fail_on_call = fail_on_call
        self.calls = 0

    def encode(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("fixture interruption")
        return np.asarray([self.vectors[text] for text in texts], dtype=np.float32)


def _out_of_pool_item(database: WorkDatabase, index: int, text: str) -> int:
    item_id = database.upsert_raw(
        source_name=f"source-{index % 2}",
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


def _out_of_pool_named(
    database: WorkDatabase,
    index: int,
    text: str,
    *,
    source_name: str,
) -> int:
    item_id = database.upsert_raw(
        source_name=source_name,
        source_item_id=f"named-{index}",
        source_url=f"https://example.test/named/{index}",
        source_author=f"named-author-{index}",
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


def test_semantic_recall_is_deterministic_and_excludes_reviewed_ids(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first = _out_of_pool_item(database, 1, "hotel-like")
    second = _out_of_pool_item(database, 2, "exam-like")
    third = _out_of_pool_item(database, 3, "another-hotel")
    embedder = FakeEmbedder(
        {
            "hotel prototype": (1.0, 0.0),
            "hotel-like": (0.9, 0.1),
            "exam-like": (0.1, 0.9),
            "another-hotel": (0.8, 0.2),
        }
    )
    output = tmp_path / "recall.jsonl"

    summary = run_semantic_recall(
        database,
        sub_scene="travel_hotel",
        prototypes=("hotel prototype",),
        embedder=embedder,
        output_path=output,
        checkpoint_path=tmp_path / "checkpoint.json",
        exclude_ids={first},
        top_k=2,
        batch_size=2,
    )
    rows = [json.loads(line) for line in output.read_text().splitlines()]

    assert summary == {"processed": 2, "selected": 2, "resumed": False}
    assert [row["item_id"] for row in rows] == [third, second]
    assert all(row["suggested_scene"] == "travel_hotel" for row in rows)
    assert rows[0]["similarity"] > rows[1]["similarity"]


def test_semantic_recall_resumes_from_atomic_checkpoint(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    texts = ("first", "second", "third", "fourth", "fifth")
    for index, text in enumerate(texts, start=1):
        _out_of_pool_item(database, index, text)
    vectors = {
        "prototype": (1.0, 0.0),
        **{text: (1.0 - index / 10, index / 10) for index, text in enumerate(texts)},
    }
    checkpoint = tmp_path / "checkpoint.json"
    output = tmp_path / "recall.jsonl"

    with pytest.raises(RuntimeError, match="fixture interruption"):
        run_semantic_recall(
            database,
            sub_scene="study_exams",
            prototypes=("prototype",),
            embedder=FakeEmbedder(vectors, fail_on_call=3),
            output_path=output,
            checkpoint_path=checkpoint,
            exclude_ids=set(),
            top_k=3,
            batch_size=2,
        )
    interrupted = json.loads(checkpoint.read_text())
    assert interrupted["last_item_id"] > 0
    assert interrupted["completed"] is False

    summary = run_semantic_recall(
        database,
        sub_scene="study_exams",
        prototypes=("prototype",),
        embedder=FakeEmbedder(vectors),
        output_path=output,
        checkpoint_path=checkpoint,
        exclude_ids=set(),
        top_k=3,
        batch_size=2,
    )

    assert summary == {"processed": 5, "selected": 3, "resumed": True}
    assert json.loads(checkpoint.read_text())["completed"] is True
    assert len(output.read_text().splitlines()) == 3


def test_semantic_recall_rejects_checkpoint_from_other_model(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    _out_of_pool_item(database, 1, "candidate")
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "fingerprint": "wrong",
                "last_item_id": 1,
                "processed": 1,
                "heap": [],
                "completed": False,
            }
        )
    )

    with pytest.raises(ValueError, match="checkpoint.*不匹配"):
        run_semantic_recall(
            database,
            sub_scene="travel_hotel",
            prototypes=("prototype",),
            embedder=FakeEmbedder({"prototype": (1.0, 0.0), "candidate": (0.9, 0.1)}),
            output_path=tmp_path / "recall.jsonl",
            checkpoint_path=checkpoint,
            exclude_ids=set(),
            top_k=1,
            batch_size=1,
        )


def test_semantic_recall_cli_loads_prototypes_exclusions_and_model_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    excluded = _out_of_pool_item(database, 1, "excluded")
    recalled = _out_of_pool_item(database, 2, "recalled")
    prototypes_path = tmp_path / "prototypes.json"
    prototypes_path.write_text(
        json.dumps(
            {
                "sub_scene": "travel_hotel",
                "prototypes": ["prototype"],
            }
        )
    )
    exclude_path = tmp_path / "reviewed.jsonl"
    exclude_path.write_text(json.dumps({"item_id": excluded}) + "\n")
    output = tmp_path / "recall.jsonl"
    checkpoint = tmp_path / "checkpoint.json"
    monkeypatch.setattr(
        cli,
        "SentenceTransformerEmbedder",
        lambda *args, **kwargs: FakeEmbedder(
            {"prototype": (1.0, 0.0), "excluded": (1.0, 0.0), "recalled": (0.9, 0.1)}
        ),
        raising=False,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "listening-cloze-content",
            "recall-classification",
            str(database_path),
            "--sub-scene",
            "travel_hotel",
            "--prototypes",
            str(prototypes_path),
            "--model-path",
            str(tmp_path / "model"),
            "--model-revision",
            "fixture-revision",
            "--model-sha256",
            "a" * 64,
            "--output",
            str(output),
            "--checkpoint",
            str(checkpoint),
            "--exclude",
            str(exclude_path),
            "--top-k",
            "1",
            "--batch-size",
            "1",
        ],
    )

    cli.main()

    assert json.loads(capsys.readouterr().out) == {
        "processed": 1,
        "selected": 1,
        "resumed": False,
    }
    assert json.loads(output.read_text())["item_id"] == recalled


def test_semantic_recall_many_encodes_each_candidate_batch_once(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    hotel = _out_of_pool_item(database, 1, "hotel-like")
    exam = _out_of_pool_item(database, 2, "exam-like")
    neutral = _out_of_pool_item(database, 3, "neutral")
    embedder = FakeEmbedder(
        {
            "hotel prototype": (1.0, 0.0),
            "exam prototype": (0.0, 1.0),
            "hotel-like": (0.9, 0.1),
            "exam-like": (0.1, 0.9),
            "neutral": (0.5, 0.5),
        }
    )
    output_dir = tmp_path / "recalls"

    summary = run_semantic_recall_many(
        database,
        scenes=(
            RecallScene("travel_hotel", ("hotel prototype",), 1),
            RecallScene("study_exams", ("exam prototype",), 1),
        ),
        embedder=embedder,
        output_dir=output_dir,
        checkpoint_path=tmp_path / "checkpoint.json",
        exclude_ids={neutral},
        batch_size=2,
    )

    assert summary == {
        "processed": 2,
        "selected": {"study_exams": 1, "travel_hotel": 1},
        "resumed": False,
    }
    # 原型整体编码一次；有候选的批次只编码一次，而不是按场景重复编码。
    assert embedder.calls == 2
    assert json.loads((output_dir / "travel_hotel.jsonl").read_text())["item_id"] == hotel
    assert json.loads((output_dir / "study_exams.jsonl").read_text())["item_id"] == exam


def test_semantic_recall_many_resumes_all_scene_heaps_atomically(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    texts = ("first", "second", "third", "fourth", "fifth")
    for index, text in enumerate(texts, start=1):
        _out_of_pool_item(database, index, text)
    vectors = {
        "left": (1.0, 0.0),
        "right": (0.0, 1.0),
        **{text: (1.0 - index / 10, index / 10) for index, text in enumerate(texts)},
    }
    scenes = (
        RecallScene("travel_hotel", ("left",), 2),
        RecallScene("study_exams", ("right",), 2),
    )
    checkpoint = tmp_path / "checkpoint.json"
    output_dir = tmp_path / "recalls"

    with pytest.raises(RuntimeError, match="fixture interruption"):
        run_semantic_recall_many(
            database,
            scenes=scenes,
            embedder=FakeEmbedder(vectors, fail_on_call=3),
            output_dir=output_dir,
            checkpoint_path=checkpoint,
            exclude_ids=set(),
            batch_size=2,
        )
    interrupted = json.loads(checkpoint.read_text())
    assert interrupted["last_item_id"] > 0
    assert set(interrupted["heaps"]) == {"travel_hotel", "study_exams"}
    assert interrupted["completed"] is False

    summary = run_semantic_recall_many(
        database,
        scenes=scenes,
        embedder=FakeEmbedder(vectors),
        output_dir=output_dir,
        checkpoint_path=checkpoint,
        exclude_ids=set(),
        batch_size=2,
    )

    assert summary["processed"] == 5
    assert summary["selected"] == {"study_exams": 2, "travel_hotel": 2}
    assert summary["resumed"] is True
    assert json.loads(checkpoint.read_text())["completed"] is True


def test_semantic_recall_many_cli_loads_scene_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    _out_of_pool_item(database, 1, "hotel-like")
    _out_of_pool_item(database, 2, "exam-like")
    config_path = tmp_path / "recall-config.json"
    config_path.write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "sub_scene": "travel_hotel",
                        "prototypes": ["hotel prototype"],
                        "top_k": 1,
                    },
                    {
                        "sub_scene": "study_exams",
                        "prototypes": ["exam prototype"],
                        "top_k": 1,
                    },
                ]
            }
        )
    )
    monkeypatch.setattr(
        cli,
        "SentenceTransformerEmbedder",
        lambda *args, **kwargs: FakeEmbedder(
            {
                "hotel prototype": (1.0, 0.0),
                "exam prototype": (0.0, 1.0),
                "hotel-like": (0.9, 0.1),
                "exam-like": (0.1, 0.9),
            }
        ),
    )
    output_dir = tmp_path / "recalls"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "listening-cloze-content",
            "recall-classifications",
            str(database_path),
            "--config",
            str(config_path),
            "--model-path",
            str(tmp_path / "model"),
            "--model-revision",
            "fixture-revision",
            "--model-sha256",
            "a" * 64,
            "--output-dir",
            str(output_dir),
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--batch-size",
            "2",
        ],
    )

    cli.main()

    summary = json.loads(capsys.readouterr().out)
    assert summary["selected"] == {"study_exams": 1, "travel_hotel": 1}
    assert (output_dir / "travel_hotel.jsonl").exists()
    assert (output_dir / "study_exams.jsonl").exists()


def test_semantic_recall_does_not_rank_saturated_source_above_available_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    saturated = _out_of_pool_named(
        database,
        1,
        "high similarity",
        source_name="saturated-source",
    )
    available = _out_of_pool_named(
        database,
        2,
        "lower similarity",
        source_name="available-source",
    )

    class CapacityFixture:
        def allows(self, source_name: str, source_author: str) -> bool:
            return source_name != "saturated-source"

        def fingerprint_payload(self) -> dict[str, str]:
            return {"fixture": "capacity"}

    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: CapacityFixture(),
        raising=False,
    )
    output_dir = tmp_path / "recalls"
    run_semantic_recall_many(
        database,
        scenes=(RecallScene("travel_hotel", ("prototype",), 1),),
        embedder=FakeEmbedder(
            {
                "prototype": (1.0, 0.0),
                "high similarity": (1.0, 0.0),
                "lower similarity": (0.8, 0.2),
            }
        ),
        output_dir=output_dir,
        checkpoint_path=tmp_path / "checkpoint.json",
        exclude_ids=set(),
        batch_size=2,
    )

    row = json.loads((output_dir / "travel_hotel.jsonl").read_text())
    assert row["item_id"] == available
    assert row["item_id"] != saturated


def test_single_scene_semantic_recall_also_excludes_saturated_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    _out_of_pool_named(
        database,
        1,
        "high similarity",
        source_name="saturated-source",
    )
    available = _out_of_pool_named(
        database,
        2,
        "lower similarity",
        source_name="available-source",
    )

    class CapacityFixture:
        def allows(self, source_name: str, source_author: str) -> bool:
            return source_name != "saturated-source"

        def fingerprint_payload(self) -> dict[str, str]:
            return {"fixture": "capacity"}

    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: CapacityFixture(),
    )
    output = tmp_path / "recall.jsonl"
    run_semantic_recall(
        database,
        sub_scene="travel_hotel",
        prototypes=("prototype",),
        embedder=FakeEmbedder(
            {
                "prototype": (1.0, 0.0),
                "high similarity": (1.0, 0.0),
                "lower similarity": (0.8, 0.2),
            }
        ),
        output_path=output,
        checkpoint_path=tmp_path / "checkpoint.json",
        exclude_ids=set(),
        top_k=1,
        batch_size=2,
    )

    assert json.loads(output.read_text())["item_id"] == available
