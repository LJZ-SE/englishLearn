from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from tools.content_pipeline import cli
from tools.content_pipeline import recall_review as review_module
from tools.content_pipeline.historical_replay import replay_classifications
from tools.content_pipeline.recall_review import (
    RecallReviewError,
    apply_recall_review_results,
    prepare_recall_review_batches,
    validate_recall_review_results,
)
from tools.content_pipeline.work_database import WorkDatabase


def _write_recall(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _recall_row(item_id: int, scene: str, similarity: float) -> dict[str, object]:
    return {
        "item_id": item_id,
        "text": f"sentence {item_id}",
        "source_name": "fixture-source",
        "source_author": "fixture-author",
        "similarity": similarity,
        "suggested_scene": scene,
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _insert_review_item(
    database: WorkDatabase,
    source_item_id: str,
    *,
    text: str | None = None,
    source_name: str = "fixture-source",
    source_author: str = "fixture-author",
    classify: bool = True,
    top_scene: str | None = None,
    sub_scene: str | None = None,
    method: str = "out_of_candidate_pool",
) -> int:
    resolved_text = text or f"sentence {source_item_id}"
    item_id = database.upsert_raw(
        source_name=source_name,
        source_item_id=source_item_id,
        source_url="",
        source_author=source_author,
        license_name="",
        license_url="",
        text=resolved_text,
    )
    database.mark_stage(item_id, "clean", payload={"clean_text": resolved_text})
    database.mark_stage(item_id, "dedupe", payload={"simhash64": source_item_id})
    if classify:
        payload: dict[str, object] = {
            "top_scene": top_scene,
            "sub_scene": sub_scene,
            "confidence": 1.0 if sub_scene else 0.0,
            "method": method,
        }
        if method == "llm_rejected":
            payload["reason"] = "已拒绝"
        database.mark_stage(item_id, "classify", payload=payload)
    return item_id


def _current_decision(
    item_id: int,
    *,
    source_name: str = "fixture-source",
    source_author: str = "fixture-author",
    text: str | None = None,
    top_scene: str = "study",
    sub_scene: str = "study_exams",
    reason: str = "明确考试",
) -> tuple[int, str, str, str, str, str, str]:
    return (
        item_id,
        source_name,
        source_author,
        text or f"sentence {item_id}",
        top_scene,
        sub_scene,
        reason,
    )


def _classification(database: WorkDatabase, item_id: int) -> dict[str, object]:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT payload_json FROM stage_results WHERE item_id=? AND stage='classify'",
            (item_id,),
        ).fetchone()
    assert row is not None
    return json.loads(row[0])


def _insert_descendants(database: WorkDatabase, item_id: int) -> None:
    with database.connect() as connection:
        for stage in ("select", "translate", "variants"):
            connection.execute(
                "INSERT INTO stage_results("
                "item_id, stage, payload_json, model_version, updated_at) "
                "VALUES (?, ?, '{}', 'fixture', ?)",
                (item_id, stage, f"{stage}-snapshot"),
            )


def test_apply_recall_review_uses_current_item_id_when_identity_is_duplicated(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first = database.upsert_raw(
        source_name="source",
        source_item_id="first",
        source_url="",
        source_author="",
        license_name="",
        license_url="",
        text="same text",
    )
    second = database.upsert_raw(
        source_name="source",
        source_item_id="second",
        source_url="",
        source_author="",
        license_name="",
        license_url="",
        text="same text",
    )
    with database.connect() as connection:
        for item_id in (first, second):
            connection.execute(
                    "INSERT INTO stage_results(item_id, stage, payload_json, "
                    "model_version, updated_at) VALUES (?, 'classify', ?, 'test', 'now')",
                (
                    item_id,
                    json.dumps(
                        {
                            "top_scene": None,
                            "sub_scene": None,
                            "confidence": 0.0,
                            "method": "out_of_candidate_pool",
                        }
                    ),
                ),
            )
    manifest = tmp_path / "manifest.json"
    request = tmp_path / "recall-review-study-0001.request.jsonl"
    _write_recall(
        request,
        [
            {
                "item_id": second,
                "review_family": "study",
                "source_name": "source",
                "source_author": "",
                "text": "same text",
                "suggestions": [
                    {"top_scene": "study", "sub_scene": "study_exams", "similarity": 0.9}
                ],
            }
        ],
    )
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "batch_size": 1,
                "total_items": 1,
                "total_suggestions": 1,
                "source_files": [{"file": "study_exams.jsonl", "count": 1, "sha256": "0" * 64}],
                "batches": [
                    {
                        "family": "study",
                        "index": 1,
                        "request_file": request.name,
                        "count": 1,
                        "item_ids": [second],
                        "sha256": review_module._sha256(request),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = tmp_path / "result.jsonl"
    _write_recall(
        result,
        [
            {
                "item_id": second,
                "top_scene": "study",
                "sub_scene": "study_exams",
                "reason": "明确考试",
            }
        ],
    )

    summary = apply_recall_review_results(database, manifest, [result])

    assert summary == {
        "result_rows": 1,
        "positive": 1,
        "ignored": 0,
        "applied": 1,
        "noop": 0,
        "skipped_rejected": 0,
    }
    with database.connect() as connection:
        assert (
            json.loads(
                connection.execute(
                    "SELECT payload_json FROM stage_results WHERE item_id=? AND stage='classify'",
                    (first,),
                ).fetchone()[0]
            )["sub_scene"]
            is None
        )
        assert (
            json.loads(
                connection.execute(
                    "SELECT payload_json FROM stage_results WHERE item_id=? AND stage='classify'",
                    (second,),
                ).fetchone()[0]
            )["sub_scene"]
            == "study_exams"
        )
        assert (
            json.loads(
                connection.execute(
                    "SELECT payload_json FROM stage_results WHERE item_id=? AND stage='classify'",
                    (second,),
                ).fetchone()[0]
            )["reason"]
            == "明确考试"
        )


def test_recall_review_same_scene_is_idempotent_without_invalidating_snapshot(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    item_id = database.upsert_raw(
        source_name="fixture-source",
        source_item_id="one",
        source_url="",
        source_author="fixture-author",
        license_name="",
        license_url="",
        text="sentence 1",
    )
    database.mark_stage(item_id, "clean", payload={"clean_text": "sentence 1"})
    database.mark_stage(item_id, "dedupe", payload={"simhash64": "1"})
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
    recall_dir = tmp_path / "recall"
    _write_recall(recall_dir / "study_exams.jsonl", [_recall_row(item_id, "study_exams", 0.9)])
    review_dir = tmp_path / "review"
    prepare_recall_review_batches(recall_dir, review_dir)
    result = tmp_path / "result.jsonl"
    _write_recall(
        result,
        [
            {
                "item_id": item_id,
                "top_scene": "study",
                "sub_scene": "study_exams",
                "reason": "明确考试",
            }
        ],
    )

    assert (
        apply_recall_review_results(database, review_dir / "manifest.json", [result])["applied"]
        == 1
    )
    _insert_descendants(database, item_id)
    with database.connect() as connection:
        classify_updated_at = connection.execute(
            "SELECT updated_at FROM stage_results WHERE item_id=? AND stage='classify'",
            (item_id,),
        ).fetchone()[0]

    summary = apply_recall_review_results(database, review_dir / "manifest.json", [result])

    assert summary == {
        "result_rows": 1,
        "positive": 1,
        "ignored": 0,
        "applied": 0,
        "noop": 1,
        "skipped_rejected": 0,
    }
    with database.connect() as connection:
        assert (
            connection.execute(
                "SELECT updated_at FROM stage_results WHERE item_id=? AND stage='classify'",
                (item_id,),
            ).fetchone()[0]
            == classify_updated_at
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage IN ('select','translate','variants')"
        ).fetchone()[0] == 3


@pytest.mark.parametrize("failure", ["identity", "missing", "state"])
def test_current_recall_review_prevalidates_entire_batch_before_writing(
    tmp_path: Path, failure: str
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first = _insert_review_item(database, "1")
    if failure == "missing":
        second = 999_999
    else:
        second = _insert_review_item(database, "2", classify=failure != "state")
    second_decision = _current_decision(second)
    if failure == "identity":
        second_decision = _current_decision(second, source_author="tampered")

    with pytest.raises(ValueError, match="身份不一致|不存在|未完成 classify"):
        database.apply_current_recall_reviews(
            [_current_decision(first), second_decision]
        )

    assert _classification(database, first)["method"] == "out_of_candidate_pool"


@pytest.mark.parametrize(
    ("method", "top_scene", "sub_scene"),
    [
        ("keyword", "study", "study_language"),
        ("llm_rejected", None, None),
    ],
)
def test_current_recall_review_conflicts_fail_closed_without_partial_write(
    tmp_path: Path,
    method: str,
    top_scene: str | None,
    sub_scene: str | None,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    first = _insert_review_item(database, "1")
    second = _insert_review_item(
        database,
        "2",
        top_scene=top_scene,
        sub_scene=sub_scene,
        method=method,
    )
    _insert_descendants(database, first)

    with pytest.raises(ValueError, match="分类冲突"):
        database.apply_current_recall_reviews(
            [_current_decision(first), _current_decision(second)]
        )

    assert _classification(database, first)["method"] == "out_of_candidate_pool"
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage IN ('select','translate','variants')"
        ).fetchone()[0] == 3


def test_current_recall_review_skips_rejected_item_without_reviving_or_invalidating(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    item_id = _insert_review_item(database, "1")
    database.record_rejection(item_id, "classify", "quality")
    _insert_descendants(database, item_id)

    summary = database.apply_current_recall_reviews([_current_decision(item_id)])

    assert summary == {"applied": 0, "noop": 0, "skipped_rejected": 1}
    assert _classification(database, item_id)["method"] == "out_of_candidate_pool"
    with database.connect() as connection:
        assert connection.execute(
            "SELECT reason FROM rejections WHERE item_id=?", (item_id,)
        ).fetchone() == ("quality",)
        assert connection.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage IN ('select','translate','variants')"
        ).fetchone()[0] == 3


def test_current_recall_review_applied_update_saves_reason_and_invalidates_descendants(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    item_id = _insert_review_item(database, "1")
    _insert_descendants(database, item_id)

    summary = database.apply_current_recall_reviews(
        [_current_decision(item_id, reason="人工确认考试语义")]
    )

    assert summary == {"applied": 1, "noop": 0, "skipped_rejected": 0}
    assert _classification(database, item_id) == {
        "top_scene": "study",
        "sub_scene": "study_exams",
        "confidence": 1.0,
        "method": "recall_review",
        "reason": "人工确认考试语义",
    }
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage IN ('select','translate','variants')"
        ).fetchone()[0] == 0


def test_apply_recall_review_treats_null_as_ignored_without_invalidating_descendants(
    tmp_path: Path,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    item_id = _insert_review_item(database, "1")
    _insert_descendants(database, item_id)
    recall_dir = tmp_path / "recall"
    _write_recall(recall_dir / "study_exams.jsonl", [_recall_row(1, "study_exams", 0.9)])
    review_dir = tmp_path / "review"
    prepare_recall_review_batches(recall_dir, review_dir)
    result = tmp_path / "result.jsonl"
    _write_recall(
        result,
        [{"item_id": 1, "top_scene": None, "sub_scene": None, "reason": "不相关"}],
    )

    summary = apply_recall_review_results(database, review_dir / "manifest.json", [result])

    assert summary == {
        "result_rows": 1,
        "positive": 0,
        "ignored": 1,
        "applied": 0,
        "noop": 0,
        "skipped_rejected": 0,
    }
    assert _classification(database, item_id)["method"] == "out_of_candidate_pool"
    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage IN ('select','translate','variants')"
        ).fetchone()[0] == 3


@pytest.mark.parametrize(
    ("first_ids", "second_ids", "message"),
    [
        ([1], [1], "重复"),
        ([1], [], "精确覆盖"),
        ([1], [999], "非法|unexpected"),
        ([1, 2], [999], "总行数超过"),
    ],
)
def test_apply_recall_review_requires_exact_coverage_across_multiple_result_files(
    tmp_path: Path,
    first_ids: list[int],
    second_ids: list[int],
    message: str,
) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(
        recall_dir / "study_exams.jsonl",
        [_recall_row(1, "study_exams", 0.9), _recall_row(2, "study_exams", 0.8)],
    )
    review_dir = tmp_path / "review"
    prepare_recall_review_batches(recall_dir, review_dir)

    def result_row(item_id: int) -> dict[str, object]:
        return {
            "item_id": item_id,
            "top_scene": None,
            "sub_scene": None,
            "reason": "不相关",
        }

    first = tmp_path / "first.result.jsonl"
    second = tmp_path / "second.result.jsonl"
    _write_recall(first, [result_row(item_id) for item_id in first_ids])
    _write_recall(second, [result_row(item_id) for item_id in second_ids])
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()

    with pytest.raises(RecallReviewError, match=message):
        apply_recall_review_results(database, review_dir / "manifest.json", [first, second])


def test_apply_recall_review_cli_uses_real_manifest_and_multiple_result_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    first = _insert_review_item(database, "1")
    second = _insert_review_item(database, "2")
    recall_dir = tmp_path / "recall"
    _write_recall(recall_dir / "study_exams.jsonl", [_recall_row(first, "study_exams", 0.9)])
    _write_recall(recall_dir / "work_jobs.jsonl", [_recall_row(second, "work_jobs", 0.8)])
    review_dir = tmp_path / "review"
    prepare_recall_review_batches(recall_dir, review_dir, batch_size=1)
    first_result = tmp_path / "study.result.jsonl"
    second_result = tmp_path / "work.result.jsonl"
    _write_recall(
        first_result,
        [
            {
                "item_id": first,
                "top_scene": "study",
                "sub_scene": "study_exams",
                "reason": "CLI 确认考试",
            }
        ],
    )
    _write_recall(
        second_result,
        [
            {
                "item_id": second,
                "top_scene": None,
                "sub_scene": None,
                "reason": "CLI 判断不相关",
            }
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "listening-cloze-content",
            "apply-recall-review",
            str(database_path),
            str(review_dir / "manifest.json"),
            str(first_result),
            str(second_result),
        ],
    )

    cli.main()

    assert json.loads(capsys.readouterr().out) == {
        "applied": 1,
        "ignored": 1,
        "noop": 0,
        "positive": 1,
        "result_rows": 2,
        "skipped_rejected": 0,
    }
    assert _classification(database, first)["reason"] == "CLI 确认考试"
    assert _classification(database, second)["method"] == "out_of_candidate_pool"


def test_prepare_merges_cross_scene_items_and_groups_by_highest_scene_family(
    tmp_path: Path,
) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(
        recall_dir / "study_exams.jsonl",
        [_recall_row(2, "study_exams", 0.91), _recall_row(1, "study_exams", 0.80)],
    )
    _write_recall(
        recall_dir / "technology_science.jsonl",
        [
            _recall_row(1, "technology_science", 0.95),
            _recall_row(3, "technology_science", 0.70),
        ],
    )
    output_dir = tmp_path / "review"

    summary = prepare_recall_review_batches(recall_dir, output_dir, batch_size=1)

    assert summary == {"batch_count": 3, "item_count": 3, "suggestion_count": 4}
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [batch["family"] for batch in manifest["batches"]] == [
        "study",
        "technology",
        "technology",
    ]
    assert all(batch["count"] == 1 for batch in manifest["batches"])
    technology_first = _read_jsonl(output_dir / manifest["batches"][1]["request_file"])[0]
    assert technology_first == {
        "item_id": 1,
        "review_family": "technology",
        "source_author": "fixture-author",
        "source_name": "fixture-source",
        "suggestions": [
            {
                "similarity": 0.95,
                "sub_scene": "technology_science",
                "top_scene": "technology",
            },
            {
                "similarity": 0.8,
                "sub_scene": "study_exams",
                "top_scene": "study",
            },
        ],
        "text": "sentence 1",
    }
    assert manifest["total_items"] == 3
    assert manifest["total_suggestions"] == 4


def test_prepare_is_deterministic_and_rejects_identity_conflicts(tmp_path: Path) -> None:
    recall_dir = tmp_path / "recall"
    first = _recall_row(1, "study_exams", 0.8)
    second = _recall_row(1, "technology_science", 0.9)
    second["text"] = "different sentence"
    _write_recall(recall_dir / "study_exams.jsonl", [first])
    _write_recall(recall_dir / "technology_science.jsonl", [second])

    with pytest.raises(RecallReviewError, match="身份不一致"):
        prepare_recall_review_batches(recall_dir, tmp_path / "review")


def test_prepare_splits_batches_by_historical_file_byte_limit(tmp_path: Path) -> None:
    recall_dir = tmp_path / "recall"
    rows = [_recall_row(index, "study_exams", 0.9) for index in range(1, 19)]
    for row in rows:
        row["text"] = f"{row['item_id']}:" + "x" * 950_000
    _write_recall(recall_dir / "study_exams.jsonl", rows)
    output_dir = tmp_path / "review"

    summary = prepare_recall_review_batches(recall_dir, output_dir)

    assert summary["batch_count"] == 2
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    for batch in manifest["batches"]:
        path = output_dir / batch["request_file"]
        assert path.stat().st_size <= 16 * 1024 * 1024
        assert batch["count"] <= 1000
        assert all(
            len(line.encode("utf-8")) <= 1024 * 1024
            for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
        )


def test_prepare_rejects_scene_filename_mismatch_and_batch_size_over_contract(
    tmp_path: Path,
) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(
        recall_dir / "study_exams.jsonl",
        [_recall_row(1, "technology_science", 0.8)],
    )

    with pytest.raises(RecallReviewError, match="文件名场景"):
        prepare_recall_review_batches(recall_dir, tmp_path / "review")
    with pytest.raises(RecallReviewError, match="1 到 1000"):
        prepare_recall_review_batches(recall_dir, tmp_path / "review", batch_size=1001)


def test_prepare_preserves_unknown_blank_author_for_identity_replay(tmp_path: Path) -> None:
    recall_dir = tmp_path / "recall"
    row = _recall_row(1, "study_exams", 0.8)
    row["source_author"] = ""
    _write_recall(recall_dir / "study_exams.jsonl", [row])

    prepare_recall_review_batches(recall_dir, tmp_path / "review")

    request = _read_jsonl(tmp_path / "review" / "recall-review-study-0001.request.jsonl")[0]
    assert request["source_author"] == ""


def test_prepare_rejects_self_output_and_existing_snapshot_without_changing_it(
    tmp_path: Path,
) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(recall_dir / "study_exams.jsonl", [_recall_row(1, "study_exams", 0.8)])
    existing = tmp_path / "review"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("old snapshot", encoding="utf-8")

    with pytest.raises(RecallReviewError, match="必须不存在或为空"):
        prepare_recall_review_batches(recall_dir, existing)
    with pytest.raises(RecallReviewError, match="不能相同"):
        prepare_recall_review_batches(recall_dir, recall_dir)

    assert sentinel.read_text(encoding="utf-8") == "old snapshot"


def test_prepare_cleans_staging_when_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(recall_dir / "study_exams.jsonl", [_recall_row(1, "study_exams", 0.8)])
    output_dir = tmp_path / "review"

    def fail_write(_path: Path, _payload: object) -> None:
        raise OSError("fixture interruption")

    monkeypatch.setattr(review_module, "_write_json_atomic", fail_write)
    with pytest.raises(OSError, match="fixture interruption"):
        prepare_recall_review_batches(recall_dir, output_dir)

    assert not output_dir.exists()
    assert not list(tmp_path.glob(".review.staging-*"))


def test_validate_requires_exact_coverage_and_exports_replay_compatible_exchanges(
    tmp_path: Path,
) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(
        recall_dir / "study_exams.jsonl",
        [_recall_row(1, "study_exams", 0.8), _recall_row(2, "study_exams", 0.7)],
    )
    review_dir = tmp_path / "review"
    prepare_recall_review_batches(recall_dir, review_dir, batch_size=1)
    results = tmp_path / "results.jsonl"
    results.write_text(
        "".join(
            (
                json.dumps(
                    {
                        "item_id": 2,
                        "top_scene": None,
                        "sub_scene": None,
                        "reason": "内容与考试场景不够相关",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                json.dumps(
                    {
                        "item_id": 1,
                        "top_scene": "study",
                        "sub_scene": "study_exams",
                        "reason": "明确描述考试",
                    },
                    ensure_ascii=False,
                )
                + "\n",
            )
        ),
        encoding="utf-8",
    )
    exchange_dir = tmp_path / "exchange"

    summary = validate_recall_review_results(review_dir / "manifest.json", [results], exchange_dir)

    assert summary == {"batch_count": 2, "item_count": 2, "positive_count": 1}
    exchange_manifest = json.loads((exchange_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(exchange_manifest["exchanges"]) == 2
    for exchange in exchange_manifest["exchanges"]:
        request_path = exchange_dir / exchange["request_file"]
        result_path = exchange_dir / exchange["result_file"]
        assert hashlib.sha256(request_path.read_bytes()).hexdigest() == exchange["request_sha256"]
        assert hashlib.sha256(result_path.read_bytes()).hexdigest() == exchange["result_sha256"]
        request = _read_jsonl(request_path)[0]
        assert set(request) == {
            "item_id",
            "source_name",
            "source_author",
            "text",
            "suggested_scene",
            "similarity",
        }
        assert set(_read_jsonl(result_path)[0]) == {
            "item_id",
            "top_scene",
            "sub_scene",
            "reason",
        }


def test_validate_splits_large_results_and_every_exchange_replays_end_to_end(
    tmp_path: Path,
) -> None:
    recall_dir = tmp_path / "recall"
    rows = [_recall_row(index, "study_exams", 0.9) for index in range(1, 18)]
    _write_recall(recall_dir / "study_exams.jsonl", rows)
    review_dir = tmp_path / "review"
    prepare_recall_review_batches(recall_dir, review_dir)
    result_path = tmp_path / "result.jsonl"
    _write_recall(
        result_path,
        [
            {
                "item_id": index,
                "top_scene": "study",
                "sub_scene": "study_exams",
                "reason": "r" * 990_000,
            }
            for index in range(1, 18)
        ],
    )
    exchange_dir = tmp_path / "exchange"

    summary = validate_recall_review_results(
        review_dir / "manifest.json", [result_path], exchange_dir
    )

    assert summary["batch_count"] == 2
    exchange_manifest = json.loads((exchange_dir / "manifest.json").read_text(encoding="utf-8"))
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    for row in rows:
        item_id = database.upsert_raw(
            source_name=str(row["source_name"]),
            source_item_id=str(row["item_id"]),
            source_url=f"https://example.test/{row['item_id']}",
            source_author=str(row["source_author"]),
            license_name="CC0",
            license_url="https://creativecommons.org/publicdomain/zero/1.0/",
            text=str(row["text"]),
        )
        database.mark_stage(item_id, "clean", payload={"clean_text": row["text"]})
        database.mark_stage(item_id, "dedupe", payload={"simhash64": str(item_id)})
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
    for exchange in exchange_manifest["exchanges"]:
        request = exchange_dir / exchange["request_file"]
        result = exchange_dir / exchange["result_file"]
        assert request.stat().st_size <= 16 * 1024 * 1024
        assert result.stat().st_size <= 16 * 1024 * 1024
        assert exchange["count"] <= 1000
        replay_classifications(database, [(request, result)])


@pytest.mark.parametrize(
    ("result_rows", "message"),
    [
        (
            [
                {"item_id": 1, "top_scene": None, "sub_scene": None, "reason": "no"},
            ],
            "精确覆盖",
        ),
        (
            [
                {"item_id": 1, "top_scene": "study", "sub_scene": None, "reason": "no"},
                {"item_id": 2, "top_scene": None, "sub_scene": None, "reason": "no"},
            ],
            "必须同时为 null",
        ),
        (
            [
                {
                    "item_id": 1,
                    "top_scene": "travel",
                    "sub_scene": "study_exams",
                    "reason": "no",
                },
                {"item_id": 2, "top_scene": None, "sub_scene": None, "reason": "no"},
            ],
            "非法或不匹配",
        ),
        (
            [
                {
                    "item_id": 1,
                    "top_scene": "technology",
                    "sub_scene": "technology_science",
                    "reason": "未展示过的场景",
                },
                {"item_id": 2, "top_scene": None, "sub_scene": None, "reason": "no"},
            ],
            "不属于该 item 的 suggestions",
        ),
        (
            [
                {"item_id": 1, "top_scene": None, "sub_scene": None, "reason": " "},
                {"item_id": 2, "top_scene": None, "sub_scene": None, "reason": "no"},
            ],
            "reason 必须为非空",
        ),
    ],
)
def test_validate_enforces_result_contract(
    tmp_path: Path, result_rows: list[dict[str, object]], message: str
) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(
        recall_dir / "study_exams.jsonl",
        [_recall_row(1, "study_exams", 0.8), _recall_row(2, "study_exams", 0.7)],
    )
    review_dir = tmp_path / "review"
    prepare_recall_review_batches(recall_dir, review_dir)
    result = tmp_path / "result.jsonl"
    _write_recall(result, result_rows)

    with pytest.raises(RecallReviewError, match=message):
        validate_recall_review_results(
            review_dir / "manifest.json", [result], tmp_path / "exchange"
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda manifest: manifest["batches"][0].update(index=True), "index 必须为正整数"),
        (
            lambda manifest: manifest["batches"][0].update(request_file="other.request.jsonl"),
            "canonical",
        ),
        (lambda manifest: manifest.update(batch_size=0), "batch_size"),
        (lambda manifest: manifest.update(total_suggestions=99), "total_suggestions"),
        (
            lambda manifest: manifest["source_files"].append(dict(manifest["source_files"][0])),
            "source_files.*重复",
        ),
    ],
)
def test_validate_rejects_tampered_manifest_contract(
    tmp_path: Path, mutation: object, message: str
) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(recall_dir / "study_exams.jsonl", [_recall_row(1, "study_exams", 0.8)])
    review_dir = tmp_path / "review"
    prepare_recall_review_batches(recall_dir, review_dir)
    manifest_path = review_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutation(manifest)  # type: ignore[operator]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = tmp_path / "result.jsonl"
    _write_recall(
        result,
        [{"item_id": 1, "top_scene": None, "sub_scene": None, "reason": "no"}],
    )

    with pytest.raises(RecallReviewError, match=message):
        validate_recall_review_results(manifest_path, [result], tmp_path / "exchange")


@pytest.mark.parametrize("second_index", [1, 3])
def test_validate_rejects_duplicate_or_non_continuous_family_indexes_before_io(
    tmp_path: Path, second_index: int
) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(
        recall_dir / "study_exams.jsonl",
        [_recall_row(1, "study_exams", 0.8), _recall_row(2, "study_exams", 0.7)],
    )
    review_dir = tmp_path / "review"
    prepare_recall_review_batches(recall_dir, review_dir, batch_size=1)
    manifest_path = review_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["batches"][1]["index"] = second_index
    manifest["batches"][1]["request_file"] = f"recall-review-study-{second_index:04d}.request.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = tmp_path / "result.jsonl"
    _write_recall(
        result,
        [
            {"item_id": 1, "top_scene": None, "sub_scene": None, "reason": "no"},
            {"item_id": 2, "top_scene": None, "sub_scene": None, "reason": "no"},
        ],
    )

    with pytest.raises(RecallReviewError, match="重复|连续"):
        validate_recall_review_results(manifest_path, [result], tmp_path / "exchange")


def test_validate_rejects_exchange_self_output_and_existing_snapshot(tmp_path: Path) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(recall_dir / "study_exams.jsonl", [_recall_row(1, "study_exams", 0.8)])
    review_dir = tmp_path / "review"
    prepare_recall_review_batches(recall_dir, review_dir)
    result = tmp_path / "result.jsonl"
    _write_recall(
        result,
        [{"item_id": 1, "top_scene": None, "sub_scene": None, "reason": "no"}],
    )
    existing = tmp_path / "exchange"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("old snapshot", encoding="utf-8")

    with pytest.raises(RecallReviewError, match="必须不存在或为空"):
        validate_recall_review_results(review_dir / "manifest.json", [result], existing)
    with pytest.raises(RecallReviewError, match="不能相同"):
        validate_recall_review_results(review_dir / "manifest.json", [result], review_dir)

    assert sentinel.read_text(encoding="utf-8") == "old snapshot"


def test_prepare_wraps_overflowing_similarity_as_domain_error(tmp_path: Path) -> None:
    recall_dir = tmp_path / "recall"
    recall_dir.mkdir()
    (recall_dir / "study_exams.jsonl").write_text(
        '{"item_id":1,"text":"Sentence","source_name":"source",'
        '"source_author":"","similarity":' + "9" * 5000 + ',"suggested_scene":"study_exams"}\n',
        encoding="utf-8",
    )

    with pytest.raises(RecallReviewError, match="不是合法 JSON|有限数字"):
        prepare_recall_review_batches(recall_dir, tmp_path / "review")


def test_recall_review_cli_prepares_and_validates_without_work_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    recall_dir = tmp_path / "recall"
    _write_recall(recall_dir / "study_exams.jsonl", [_recall_row(1, "study_exams", 0.8)])
    review_dir = tmp_path / "review"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "listening-cloze-content",
            "prepare-recall-review",
            str(recall_dir),
            str(review_dir),
        ],
    )
    cli.main()
    assert json.loads(capsys.readouterr().out)["item_count"] == 1

    result = tmp_path / "result.jsonl"
    _write_recall(
        result,
        [{"item_id": 1, "top_scene": None, "sub_scene": None, "reason": "不相关"}],
    )
    exchange_dir = tmp_path / "exchange"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "listening-cloze-content",
            "validate-recall-review",
            str(review_dir / "manifest.json"),
            str(result),
            "--exchange-dir",
            str(exchange_dir),
        ],
    )
    cli.main()
    assert json.loads(capsys.readouterr().out)["item_count"] == 1
