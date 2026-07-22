from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from tools.content_pipeline import cli
from tools.content_pipeline.historical_replay import (
    HistoricalReplayError,
    replay_classifications,
)
from tools.content_pipeline.work_database import WorkDatabase


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _request(
    item_id: int,
    text: str,
    *,
    source_name: str = "Historical source",
    source_author: str = "Historical author",
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "source_name": source_name,
        "source_author": source_author,
        "text": text,
        "suggested_scene": "daily_home",
    }


def _result(
    item_id: int,
    *,
    top_scene: str | None = "daily",
    sub_scene: str | None = "daily_home",
    reason: str = "历史人工审核确认",
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "top_scene": top_scene,
        "sub_scene": sub_scene,
        "reason": reason,
    }


def _classified_item(
    database: WorkDatabase,
    text: str,
    *,
    source_item_id: str,
    source_name: str = "Historical source",
    source_author: str = "Historical author",
    top_scene: str | None = None,
    sub_scene: str | None = None,
    method: str = "out_of_candidate_pool",
) -> int:
    item_id = database.upsert_raw(
        source_name=source_name,
        source_item_id=source_item_id,
        source_url=f"https://example.test/{source_item_id}",
        source_author=source_author,
        license_name="CC0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        text=text,
    )
    database.mark_stage(item_id, "clean", payload={"clean_text": text})
    database.mark_stage(item_id, "dedupe", payload={"simhash64": source_item_id})
    payload: dict[str, object] = {
        "top_scene": top_scene,
        "sub_scene": sub_scene,
        "confidence": 0.7 if sub_scene is not None else 0.0,
        "method": method,
    }
    if method in {"llm_repair", "llm_rejected", "historical_review_replay"}:
        payload["reason"] = "测试审核理由"
    database.mark_stage(
        item_id,
        "classify",
        payload=payload,
        model_version="rules-v1",
    )
    return item_id


def _payload(database_path: Path, item_id: int, stage: str = "classify") -> dict[str, object]:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT payload_json FROM stage_results WHERE item_id=? AND stage=?",
            (item_id, stage),
        ).fetchone()
    assert row is not None
    return json.loads(row[0])


def test_replay_maps_by_identity_ignores_null_and_deduplicates_across_exchanges(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    current_id = _classified_item(database, "Please wash the dishes.", source_item_id="new-1")
    assert current_id != 9001

    request_a = tmp_path / "request-a.jsonl"
    result_a = tmp_path / "result-a.jsonl"
    request_b = tmp_path / "request-b.jsonl"
    result_b = tmp_path / "result-b.jsonl"
    _write_jsonl(
        request_a,
        [_request(9001, "Please wash the dishes."), _request(9002, "Unused rejection.")],
    )
    _write_jsonl(
        result_a,
        [_result(9001), _result(9002, top_scene=None, sub_scene=None)],
    )
    _write_jsonl(request_b, [_request(42, "Please wash the dishes.")])
    _write_jsonl(result_b, [_result(42)])

    summary = replay_classifications(
        database,
        [(request_a, result_a), (request_b, result_b)],
    )

    assert summary == {
        "result_rows": 3,
        "positive_decisions": 2,
        "ignored_rejections": 1,
        "deduplicated_decisions": 1,
        "applied": 1,
        "skipped_rejected": 0,
        "noop": 0,
    }
    assert _payload(database_path, current_id) == {
        "confidence": 1.0,
        "method": "historical_review_replay",
        "reason": "历史人工审核确认",
        "sub_scene": "daily_home",
        "top_scene": "daily",
    }
    assert database.rejection_reason_counts("classify") == {}


def test_replay_fails_closed_on_cross_exchange_conflict(tmp_path: Path) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    current_id = _classified_item(database, "Please wash the dishes.", source_item_id="new-1")
    before = _payload(database_path, current_id)
    exchanges: list[tuple[Path, Path]] = []
    for suffix, top_scene, sub_scene in (
        ("a", "daily", "daily_home"),
        ("b", "work", "work_office"),
    ):
        request_path = tmp_path / f"request-{suffix}.jsonl"
        result_path = tmp_path / f"result-{suffix}.jsonl"
        _write_jsonl(request_path, [_request(1, "Please wash the dishes.")])
        _write_jsonl(
            result_path,
            [_result(1, top_scene=top_scene, sub_scene=sub_scene)],
        )
        exchanges.append((request_path, result_path))

    with pytest.raises(HistoricalReplayError, match="冲突"):
        replay_classifications(database, exchanges)

    assert _payload(database_path, current_id) == before


@pytest.mark.parametrize("mode", ["missing", "ambiguous"])
def test_replay_fails_closed_when_current_identity_is_not_unique(
    tmp_path: Path,
    mode: str,
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    existing_id = _classified_item(database, "Keep this unchanged.", source_item_id="control")
    if mode == "ambiguous":
        _classified_item(database, "Target sentence.", source_item_id="duplicate-a")
        _classified_item(database, "Target sentence.", source_item_id="duplicate-b")
    request_path = tmp_path / "request.jsonl"
    result_path = tmp_path / "result.jsonl"
    _write_jsonl(request_path, [_request(700, "Target sentence.")])
    _write_jsonl(result_path, [_result(700)])

    with pytest.raises(HistoricalReplayError, match="唯一映射"):
        replay_classifications(database, [(request_path, result_path)])

    assert _payload(database_path, existing_id)["method"] == "out_of_candidate_pool"


@pytest.mark.parametrize(
    ("request_rows", "result_rows", "message"),
    [
        ([{"item_id": 1, "text": "Missing identity"}], [_result(1)], "请求字段"),
        ([_request(1, "Sentence")], [{**_result(1), "extra": True}], "结果字段"),
        ([_request(1, "Sentence")], [_result(1, top_scene="work")], "场景标签"),
        ([_request(1, "Sentence")], [_result(2)], "找不到对应请求"),
    ],
)
def test_replay_rejects_invalid_schema_scene_and_unknown_result_reference(
    tmp_path: Path,
    request_rows: list[dict[str, object]],
    result_rows: list[dict[str, object]],
    message: str,
) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    request_path = tmp_path / "request.jsonl"
    result_path = tmp_path / "result.jsonl"
    _write_jsonl(request_path, request_rows)
    _write_jsonl(result_path, result_rows)

    with pytest.raises(HistoricalReplayError, match=message):
        replay_classifications(database, [(request_path, result_path)])


def test_replay_rejects_duplicate_old_ids_and_malformed_json(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    request_path = tmp_path / "request.jsonl"
    result_path = tmp_path / "result.jsonl"
    _write_jsonl(request_path, [_request(1, "First"), _request(1, "Second")])
    result_path.write_text('{"item_id": 1,\n', encoding="utf-8")

    with pytest.raises(HistoricalReplayError, match="合法 JSON|重复 item_id"):
        replay_classifications(database, [(request_path, result_path)])


def test_replay_accepts_strict_lexical_recall_request_schema(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    _classified_item(database, "Please book the hotel.", source_item_id="hotel")
    request_path = tmp_path / "request.jsonl"
    result_path = tmp_path / "result.jsonl"
    lexical_request = {
        **_request(700, "Please book the hotel."),
        "competing_scene": "daily_home",
        "competing_score": 0.25,
        "target_score": 1.5,
        "trigger_keywords": ["book", "hotel"],
        "trigger_phrases": ["book the hotel"],
    }
    lexical_request["suggested_scene"] = "travel_hotel"
    _write_jsonl(request_path, [lexical_request])
    _write_jsonl(
        result_path,
        [_result(700, top_scene="travel", sub_scene="travel_hotel")],
    )

    summary = replay_classifications(database, [(request_path, result_path)])

    assert summary["applied"] == 1


@pytest.mark.parametrize("field", ["source_name", "source_author", "text"])
def test_replay_rejects_whitespace_only_identity_fields(tmp_path: Path, field: str) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    request_path = tmp_path / "request.jsonl"
    result_path = tmp_path / "result.jsonl"
    row = _request(1, "Sentence")
    row[field] = " \t "
    _write_jsonl(request_path, [row])
    _write_jsonl(result_path, [_result(1)])

    with pytest.raises(HistoricalReplayError, match=rf"{field} 必须为非空字符串"):
        replay_classifications(database, [(request_path, result_path)])


def test_replay_streaming_reader_rejects_excessive_line_count(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    request_path = tmp_path / "request.jsonl"
    result_path = tmp_path / "result.jsonl"
    request_path.write_text("\n" * 1001, encoding="utf-8")
    _write_jsonl(result_path, [])

    with pytest.raises(HistoricalReplayError, match="1000 行"):
        replay_classifications(database, [(request_path, result_path)])


def test_replay_rejects_overflowing_numeric_metadata(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    request_path = tmp_path / "request.jsonl"
    result_path = tmp_path / "result.jsonl"
    row = _request(1, "Sentence")
    row["similarity"] = 10**400
    _write_jsonl(request_path, [row])
    _write_jsonl(result_path, [_result(1)])

    with pytest.raises(HistoricalReplayError, match="similarity 必须是有限数字"):
        replay_classifications(database, [(request_path, result_path)])


def test_replay_converts_oversized_integer_literal_to_domain_error(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    request_path = tmp_path / "request.jsonl"
    result_path = tmp_path / "result.jsonl"
    request_path.write_text(
        '{"item_id":1,"source_name":"Source","source_author":"Author",'
        '"text":"Sentence","similarity":' + "9" * 5000 + "}\n",
        encoding="utf-8",
    )
    _write_jsonl(result_path, [_result(1)])

    with pytest.raises(HistoricalReplayError, match="不是合法 JSON"):
        replay_classifications(database, [(request_path, result_path)])


def test_database_apply_is_atomic_invalidates_descendants_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    first_id = _classified_item(database, "First target.", source_item_id="first")
    second_id = _classified_item(database, "Second target.", source_item_id="second")
    database.replace_stage(
        "select",
        [
            (first_id, {"top_scene": "daily", "sub_scene": "daily_social"}),
            (second_id, {"top_scene": "daily", "sub_scene": "daily_social"}),
        ],
        model_version="selection-v1",
    )
    database.mark_stage(first_id, "translate", payload={"translation": "第一句"})
    database.mark_stage(first_id, "variants", payload={"variants": []})
    before = _payload(database_path, first_id)

    with pytest.raises(ValueError, match="唯一映射"):
        database.apply_historical_classifications(
            [
                (
                    "Historical source",
                    "Historical author",
                    "First target.",
                    "daily",
                    "daily_home",
                    "确认一",
                ),
                (
                    "Historical source",
                    "Historical author",
                    "Missing target.",
                    "daily",
                    "daily_home",
                    "确认二",
                ),
            ]
        )
    assert _payload(database_path, first_id) == before
    assert database.stage_counts()["select"] == 2

    decision = [
        (
            "Historical source",
            "Historical author",
            "First target.",
            "daily",
            "daily_home",
            "确认一",
        )
    ]
    assert database.apply_historical_classifications(decision) == {
        "applied": 1,
        "skipped_rejected": 0,
        "noop": 0,
    }
    counts = database.stage_counts()
    assert counts.get("select", 0) == 0
    assert counts.get("translate", 0) == 0
    assert counts.get("variants", 0) == 0
    with sqlite3.connect(database_path) as connection:
        model_version, updated_at = connection.execute(
            "SELECT model_version, updated_at FROM stage_results "
            "WHERE item_id=? AND stage='classify'",
            (first_id,),
        ).fetchone()
    assert model_version == "historical-review-replay-v1"
    assert database.apply_historical_classifications(decision) == {
        "applied": 0,
        "skipped_rejected": 0,
        "noop": 1,
    }
    with sqlite3.connect(database_path) as connection:
        repeated_updated_at = connection.execute(
            "SELECT updated_at FROM stage_results WHERE item_id=? AND stage='classify'",
            (first_id,),
        ).fetchone()[0]
    assert repeated_updated_at == updated_at


def test_database_apply_skips_rejected_identity_without_resurrecting_it(tmp_path: Path) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    rejected_id = _classified_item(database, "Rejected target.", source_item_id="rejected")
    database.record_rejection(rejected_id, "dedupe", "near_duplicate:abc")

    summary = database.apply_historical_classifications(
        [
            (
                "Historical source",
                "Historical author",
                "Rejected target.",
                "daily",
                "daily_home",
                "历史决定不应复活拒绝项",
            )
        ]
    )

    assert summary == {"applied": 0, "skipped_rejected": 1, "noop": 0}
    assert database.rejection_reason_counts("dedupe") == {"near_duplicate": 1}
    assert _payload(database_path, rejected_id)["method"] == "out_of_candidate_pool"


def test_database_apply_noops_same_scene_and_fails_on_different_positive_scene(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    same_id = _classified_item(
        database,
        "Same scene.",
        source_item_id="same",
        top_scene="daily",
        sub_scene="daily_home",
        method="keyword",
    )
    conflict_id = _classified_item(
        database,
        "Different scene.",
        source_item_id="conflict",
        top_scene="work",
        sub_scene="work_office",
        method="keyword",
    )
    same_before = _payload(database_path, same_id)
    conflict_before = _payload(database_path, conflict_id)

    with pytest.raises(ValueError, match="已有分类冲突"):
        database.apply_historical_classifications(
            [
                (
                    "Historical source",
                    "Historical author",
                    "Same scene.",
                    "daily",
                    "daily_home",
                    "相同场景",
                ),
                (
                    "Historical source",
                    "Historical author",
                    "Different scene.",
                    "daily",
                    "daily_home",
                    "冲突场景",
                ),
            ]
        )

    assert _payload(database_path, same_id) == same_before
    assert _payload(database_path, conflict_id) == conflict_before


def test_database_apply_fails_on_historical_llm_rejection(tmp_path: Path) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    rejected_id = _classified_item(
        database,
        "Historically rejected.",
        source_item_id="llm-rejected",
        method="llm_rejected",
    )

    with pytest.raises(ValueError, match="已有分类冲突"):
        database.apply_historical_classifications(
            [
                (
                    "Historical source",
                    "Historical author",
                    "Historically rejected.",
                    "daily",
                    "daily_home",
                    "不能覆盖旧拒绝",
                )
            ]
        )

    assert _payload(database_path, rejected_id)["method"] == "llm_rejected"


@pytest.mark.parametrize(
    "corrupt_payload",
    [
        [],
        {"top_scene": None, "sub_scene": None},
        {
            "top_scene": "daily",
            "sub_scene": None,
            "method": "out_of_candidate_pool",
            "confidence": 0.0,
        },
        {
            "top_scene": "daily",
            "sub_scene": "work_office",
            "method": "keyword",
            "confidence": 0.8,
        },
        {"top_scene": None, "sub_scene": None, "method": "keyword", "confidence": 0.0},
        {
            "top_scene": "daily",
            "sub_scene": "daily_home",
            "method": "llm_rejected",
            "confidence": 1.0,
            "reason": "状态不一致",
        },
        {
            "top_scene": None,
            "sub_scene": None,
            "method": "   ",
            "confidence": 0.0,
        },
        {
            "top_scene": "daily",
            "sub_scene": "daily_home",
            "method": "made_up",
            "confidence": 1.0,
        },
        {
            "top_scene": "daily",
            "sub_scene": "daily_home",
            "method": "keyword",
        },
        {
            "top_scene": "daily",
            "sub_scene": "daily_home",
            "method": "keyword",
            "confidence": True,
        },
        {
            "top_scene": "daily",
            "sub_scene": "daily_home",
            "method": "keyword",
            "confidence": float("nan"),
        },
        {
            "top_scene": "daily",
            "sub_scene": "daily_home",
            "method": "keyword",
            "confidence": 1.01,
        },
        {
            "top_scene": "daily",
            "sub_scene": "daily_home",
            "method": "llm_repair",
            "confidence": 1.0,
        },
    ],
)
def test_database_apply_rejects_corrupt_classification_payload_atomically(
    tmp_path: Path,
    corrupt_payload: object,
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    valid_id = _classified_item(database, "Valid target.", source_item_id="valid")
    corrupt_id = _classified_item(database, "Corrupt target.", source_item_id="corrupt")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE stage_results SET payload_json=? WHERE item_id=? AND stage='classify'",
            (json.dumps(corrupt_payload), corrupt_id),
        )
    valid_before = _payload(database_path, valid_id)

    with pytest.raises(ValueError, match="classify 载荷"):
        database.apply_historical_classifications(
            [
                (
                    "Historical source",
                    "Historical author",
                    "Valid target.",
                    "daily",
                    "daily_home",
                    "先处理但不得落库",
                ),
                (
                    "Historical source",
                    "Historical author",
                    "Corrupt target.",
                    "daily",
                    "daily_home",
                    "损坏载荷",
                ),
            ]
        )

    assert _payload(database_path, valid_id) == valid_before


def test_cli_replays_repeatable_exchange_and_prints_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    _classified_item(database, "Please wash the dishes.", source_item_id="new-1")
    request_path = tmp_path / "request.jsonl"
    result_path = tmp_path / "result.jsonl"
    _write_jsonl(request_path, [_request(88, "Please wash the dishes.")])
    _write_jsonl(result_path, [_result(88)])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "listening-cloze-content",
            "replay-classifications",
            str(database_path),
            "--exchange",
            str(request_path),
            str(result_path),
        ],
    )

    cli.main()

    assert json.loads(capsys.readouterr().out) == {
        "result_rows": 1,
        "positive_decisions": 1,
        "ignored_rejections": 0,
        "deduplicated_decisions": 1,
        "applied": 1,
        "skipped_rejected": 0,
        "noop": 0,
    }


def test_cli_converts_replay_errors_to_argparse_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "work.db"
    request_path = tmp_path / "request.jsonl"
    result_path = tmp_path / "result.jsonl"
    request_path.write_text("not-json\n", encoding="utf-8")
    _write_jsonl(result_path, [])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "listening-cloze-content",
            "replay-classifications",
            str(database_path),
            "--exchange",
            str(request_path),
            str(result_path),
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        cli.main()

    assert "不是合法 JSON" in capsys.readouterr().err
