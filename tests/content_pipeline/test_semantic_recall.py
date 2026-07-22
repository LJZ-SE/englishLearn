from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from tools.content_pipeline import cli
from tools.content_pipeline import semantic_recall as recall_module
from tools.content_pipeline.semantic_recall import (
    ModelMetadata,
    RecallScene,
    SelectionCapacity,
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


class MembershipGuardTuple(tuple[int, ...]):
    def __contains__(self, item: object) -> bool:
        raise AssertionError("场景排除 ID 必须先转换成 set 再执行 membership")


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


def test_completed_semantic_checkpoint_rescans_when_candidate_pool_changes(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first = _out_of_pool_item(database, 1, "low similarity")
    vectors = {
        "prototype": (1.0, 0.0),
        "low similarity": (0.6, 0.4),
        "high similarity": (1.0, 0.0),
    }
    checkpoint = tmp_path / "checkpoint.json"
    output = tmp_path / "recall.jsonl"
    run_semantic_recall(
        database,
        sub_scene="travel_hotel",
        prototypes=("prototype",),
        embedder=FakeEmbedder(vectors),
        output_path=output,
        checkpoint_path=checkpoint,
        exclude_ids=set(),
        top_k=1,
        batch_size=2,
    )
    assert json.loads(output.read_text())["item_id"] == first

    second = _out_of_pool_item(database, 2, "high similarity")
    summary = run_semantic_recall(
        database,
        sub_scene="travel_hotel",
        prototypes=("prototype",),
        embedder=FakeEmbedder(vectors),
        output_path=output,
        checkpoint_path=checkpoint,
        exclude_ids=set(),
        top_k=1,
        batch_size=2,
    )

    assert summary["resumed"] is False
    assert json.loads(output.read_text())["item_id"] == second


def test_candidate_pool_version_changes_when_membership_swaps_at_same_size(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first = _out_of_pool_item(database, 1, "first candidate")
    replacement = _out_of_pool_item(database, 2, "replacement candidate")
    _out_of_pool_item(database, 3, "stable maximum candidate")
    database.mark_stage(
        replacement,
        "classify",
        payload={"method": "llm_rejected", "top_scene": None, "sub_scene": None},
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE stage_results SET updated_at='fixed' WHERE stage='classify'"
        )
    before = database.recall_candidate_pool_fingerprint()

    database.mark_stage(
        first,
        "classify",
        payload={"method": "llm_rejected", "top_scene": None, "sub_scene": None},
    )
    database.mark_stage(
        replacement,
        "classify",
        payload={
            "method": "out_of_candidate_pool",
            "top_scene": None,
            "sub_scene": None,
        },
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE stage_results SET updated_at='fixed' WHERE stage='classify'"
        )

    after = database.recall_candidate_pool_fingerprint()
    assert before["eligible_count"] == after["eligible_count"] == 2
    assert before != after


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


def test_semantic_recall_many_excludes_ids_only_from_their_scene(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    shared = _out_of_pool_item(database, 1, "shared-best")
    fallback = _out_of_pool_item(database, 2, "fallback")
    output_dir = tmp_path / "recalls"

    run_semantic_recall_many(
        database,
        scenes=(
            RecallScene(
                "travel_hotel",
                ("prototype",),
                1,
                excluded_item_ids=(shared,),
            ),
            RecallScene("study_exams", ("prototype",), 1),
        ),
        embedder=FakeEmbedder(
            {
                "prototype": (1.0, 0.0),
                "shared-best": (1.0, 0.0),
                "fallback": (0.8, 0.2),
            }
        ),
        output_dir=output_dir,
        checkpoint_path=tmp_path / "checkpoint.json",
        exclude_ids=set(),
        batch_size=2,
    )

    assert json.loads((output_dir / "travel_hotel.jsonl").read_text())[
        "item_id"
    ] == fallback
    assert json.loads((output_dir / "study_exams.jsonl").read_text())[
        "item_id"
    ] == shared


def test_semantic_recall_many_global_exclusion_still_applies_to_every_scene(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    globally_excluded = _out_of_pool_item(database, 1, "shared-best")
    fallback = _out_of_pool_item(database, 2, "fallback")
    output_dir = tmp_path / "recalls"

    run_semantic_recall_many(
        database,
        scenes=(
            RecallScene("travel_hotel", ("prototype",), 1),
            RecallScene("study_exams", ("prototype",), 1),
        ),
        embedder=FakeEmbedder(
            {
                "prototype": (1.0, 0.0),
                "shared-best": (1.0, 0.0),
                "fallback": (0.8, 0.2),
            }
        ),
        output_dir=output_dir,
        checkpoint_path=tmp_path / "checkpoint.json",
        exclude_ids={globally_excluded},
        batch_size=2,
    )

    assert json.loads((output_dir / "travel_hotel.jsonl").read_text())[
        "item_id"
    ] == fallback
    assert json.loads((output_dir / "study_exams.jsonl").read_text())[
        "item_id"
    ] == fallback


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


def test_multi_semantic_recall_config_accepts_legacy_and_scene_exclusions(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "recall-config.json"
    config_path.write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "sub_scene": "travel_hotel",
                        "prototypes": [" hotel prototype "],
                        "top_k": 1,
                        "excluded_item_ids": [9, 3],
                    },
                    {
                        "sub_scene": "study_exams",
                        "prototypes": ["exam prototype"],
                        "top_k": 2,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    scenes = cli._load_recall_scenes(config_path)

    assert scenes == (
        RecallScene("travel_hotel", ("hotel prototype",), 1, (3, 9)),
        RecallScene("study_exams", ("exam prototype",), 2),
    )


@pytest.mark.parametrize(
    "excluded_item_ids",
    ([1, 1], [0], [-1], [True], ["1"], None),
)
def test_multi_semantic_recall_config_rejects_invalid_scene_exclusions(
    tmp_path: Path,
    excluded_item_ids: object,
) -> None:
    config_path = tmp_path / "recall-config.json"
    config_path.write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "sub_scene": "travel_hotel",
                        "prototypes": ["hotel prototype"],
                        "top_k": 1,
                        "excluded_item_ids": excluded_item_ids,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="excluded_item_ids 非法"):
        cli._load_recall_scenes(config_path)


def test_multi_semantic_recall_config_still_rejects_unknown_scene_fields(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "recall-config.json"
    config_path.write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "sub_scene": "travel_hotel",
                        "prototypes": ["hotel prototype"],
                        "top_k": 1,
                        "excluded_item_ids": [],
                        "unexpected": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="字段非法"):
        cli._load_recall_scenes(config_path)


def test_scene_exclusions_are_normalized_for_deterministic_fingerprints() -> None:
    first = RecallScene("travel_hotel", ("prototype",), 1, (9, 3))
    second = RecallScene("travel_hotel", ("prototype",), 1, (3, 9))

    assert first.excluded_item_ids == (3, 9)
    assert recall_module._fingerprint_many(
        scenes=(first,),
        metadata=FakeEmbedder.metadata,
        exclude_ids=set(),
        batch_size=8,
    ) == recall_module._fingerprint_many(
        scenes=(second,),
        metadata=FakeEmbedder.metadata,
        exclude_ids=set(),
        batch_size=8,
    )


def test_semantic_recall_many_checkpoint_tracks_scene_exclusions_and_rejects_drift(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    candidate = _out_of_pool_item(database, 1, "candidate")
    checkpoint = tmp_path / "checkpoint.json"
    output_dir = tmp_path / "recalls"
    run_semantic_recall_many(
        database,
        scenes=(
            RecallScene(
                "travel_hotel",
                ("prototype",),
                1,
                excluded_item_ids=(candidate,),
            ),
        ),
        embedder=FakeEmbedder(
            {"prototype": (1.0, 0.0), "candidate": (1.0, 0.0)}
        ),
        output_dir=output_dir,
        checkpoint_path=checkpoint,
        exclude_ids=set(),
        batch_size=1,
    )
    state = json.loads(checkpoint.read_text())
    assert state["scenes"][0]["excluded_item_ids"] == [candidate]

    with pytest.raises(ValueError, match="checkpoint.*不匹配"):
        run_semantic_recall_many(
            database,
            scenes=(RecallScene("travel_hotel", ("prototype",), 1),),
            embedder=FakeEmbedder(
                {"prototype": (1.0, 0.0), "candidate": (1.0, 0.0)}
            ),
            output_dir=output_dir,
            checkpoint_path=checkpoint,
            exclude_ids=set(),
            batch_size=1,
        )


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

    capacity = SelectionCapacity(
        source_limit=1,
        author_limit=1,
        source_counts=Counter({"saturated-source": 1}),
        author_counts=Counter(),
    )
    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: capacity,
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


def test_semantic_recall_consumes_remaining_source_capacity_across_top_k(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first_a = _out_of_pool_named(database, 1, "highest A", source_name="source-a")
    _out_of_pool_named(database, 2, "second A", source_name="source-a")
    candidate_b = _out_of_pool_named(database, 3, "lower B", source_name="source-b")
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
    output = tmp_path / "recall.jsonl"

    run_semantic_recall(
        database,
        sub_scene="travel_hotel",
        prototypes=("prototype",),
        embedder=FakeEmbedder(
            {
                "prototype": (1.0, 0.0),
                "highest A": (1.0, 0.0),
                "second A": (0.99, 0.01),
                "lower B": (0.8, 0.2),
            }
        ),
        output_path=output,
        checkpoint_path=tmp_path / "checkpoint.json",
        exclude_ids=set(),
        top_k=2,
        batch_size=3,
    )

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert {row["item_id"] for row in rows} == {first_a, candidate_b}


def test_semantic_recall_expands_reservoir_until_capacity_can_fill_top_k(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    vectors = {"prototype": (1.0, 0.0), "lower B": (0.6, 0.4)}
    first_a = 0
    for index in range(1, 34):
        text = f"high A {index}"
        item_id = _out_of_pool_named(database, index, text, source_name="source-a")
        first_a = first_a or item_id
        vectors[text] = (1.0 - index / 1_000, index / 1_000)
    candidate_b = _out_of_pool_named(database, 34, "lower B", source_name="source-b")
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
    embedder = FakeEmbedder(vectors)

    run_semantic_recall(
        database,
        sub_scene="travel_hotel",
        prototypes=("prototype",),
        embedder=embedder,
        output_path=output,
        checkpoint_path=tmp_path / "checkpoint.json",
        exclude_ids=set(),
        top_k=2,
        batch_size=8,
    )

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert {row["item_id"] for row in rows} == {first_a, candidate_b}
    assert embedder.calls == 11


def test_semantic_recall_many_rescan_keeps_scene_exclusions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    vectors = {
        "prototype": (1.0, 0.0),
        "excluded B": (0.6, 0.4),
        "available C": (0.5, 0.5),
    }
    first_a = 0
    for index in range(1, 34):
        text = f"high A {index}"
        item_id = _out_of_pool_named(database, index, text, source_name="source-a")
        first_a = first_a or item_id
        vectors[text] = (1.0 - index / 1_000, index / 1_000)
    excluded_b = _out_of_pool_named(
        database,
        34,
        "excluded B",
        source_name="source-b",
    )
    available_c = _out_of_pool_named(
        database,
        35,
        "available C",
        source_name="source-c",
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
    output_dir = tmp_path / "recalls"

    scene = RecallScene(
        "travel_hotel",
        ("prototype",),
        2,
        excluded_item_ids=(excluded_b,),
    )
    object.__setattr__(
        scene,
        "excluded_item_ids",
        MembershipGuardTuple(scene.excluded_item_ids),
    )

    run_semantic_recall_many(
        database,
        scenes=(scene,),
        embedder=FakeEmbedder(vectors),
        output_dir=output_dir,
        checkpoint_path=tmp_path / "checkpoint.json",
        exclude_ids=set(),
        batch_size=8,
    )

    rows = [
        json.loads(line)
        for line in (output_dir / "travel_hotel.jsonl").read_text().splitlines()
    ]
    assert {row["item_id"] for row in rows} == {first_a, available_c}
    assert excluded_b not in {row["item_id"] for row in rows}


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

    capacity = SelectionCapacity(
        source_limit=1,
        author_limit=1,
        source_counts=Counter({"saturated-source": 1}),
        author_counts=Counter(),
    )
    monkeypatch.setattr(
        recall_module,
        "selection_capacity",
        lambda *args, **kwargs: capacity,
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


def test_semantic_recall_never_requeues_explicit_llm_rejection(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    rejected = _out_of_pool_item(database, 1, "hotel-like")
    database.mark_stage(
        rejected,
        "classify",
        payload={"method": "llm_required", "top_scene": None, "sub_scene": None},
    )
    database.apply_classification_repairs(
        [(rejected, None, None, "independent review rejected this candidate")]
    )
    output = tmp_path / "recall.jsonl"

    summary = run_semantic_recall(
        database,
        sub_scene="travel_hotel",
        prototypes=("prototype",),
        embedder=FakeEmbedder(
            {"prototype": (1.0, 0.0), "hotel-like": (1.0, 0.0)}
        ),
        output_path=output,
        checkpoint_path=tmp_path / "checkpoint.json",
        exclude_ids=set(),
        top_k=1,
        batch_size=1,
    )

    assert summary["selected"] == 0
    assert output.read_text() == ""


def test_single_semantic_recall_rejects_unknown_scene(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()

    with pytest.raises(ValueError, match="未知场景"):
        run_semantic_recall(
            database,
            sub_scene="unknown_scene",
            prototypes=("prototype",),
            embedder=FakeEmbedder({"prototype": (1.0, 0.0)}),
            output_path=tmp_path / "recall.jsonl",
            checkpoint_path=tmp_path / "checkpoint.json",
            exclude_ids=set(),
            top_k=1,
            batch_size=1,
        )


@pytest.mark.parametrize("top_k", (0, 501))
def test_single_semantic_recall_limits_top_k(tmp_path: Path, top_k: int) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()

    with pytest.raises(ValueError, match="1 到 500"):
        run_semantic_recall(
            database,
            sub_scene="travel_hotel",
            prototypes=("prototype",),
            embedder=FakeEmbedder({"prototype": (1.0, 0.0)}),
            output_path=tmp_path / "recall.jsonl",
            checkpoint_path=tmp_path / "checkpoint.json",
            exclude_ids=set(),
            top_k=top_k,
            batch_size=1,
        )


def test_multi_semantic_recall_limits_each_scene_top_k(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()

    with pytest.raises(ValueError, match="1 到 500"):
        run_semantic_recall_many(
            database,
            scenes=(RecallScene("travel_hotel", ("prototype",), 501),),
            embedder=FakeEmbedder({"prototype": (1.0, 0.0)}),
            output_dir=tmp_path / "recalls",
            checkpoint_path=tmp_path / "checkpoint.json",
            exclude_ids=set(),
            batch_size=1,
        )


def test_single_semantic_recall_cli_rejects_top_k_above_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "listening-cloze-content",
            "recall-classification",
            str(tmp_path / "work.db"),
            "--sub-scene",
            "travel_hotel",
            "--prototypes",
            str(tmp_path / "prototypes.json"),
            "--model-path",
            str(tmp_path / "model"),
            "--model-revision",
            "fixture-revision",
            "--model-sha256",
            "a" * 64,
            "--output",
            str(tmp_path / "recall.jsonl"),
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--top-k",
            "501",
        ],
    )

    with pytest.raises(SystemExit):
        cli.main()


def test_multi_semantic_recall_config_rejects_top_k_above_limit(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "recall-config.json"
    config_path.write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "sub_scene": "travel_hotel",
                        "prototypes": ["hotel prototype"],
                        "top_k": 501,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="top_k 非法"):
        cli._load_recall_scenes(config_path)
