from __future__ import annotations

import hashlib
import json
import math
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from tools.content_pipeline.scenes import SCENES, SUB_SCENES
from tools.content_pipeline.work_database import WorkDatabase

_RECALL_FIELDS = {
    "item_id",
    "text",
    "source_name",
    "source_author",
    "similarity",
    "suggested_scene",
}
_REVIEW_FIELDS = {
    "item_id",
    "review_family",
    "source_name",
    "source_author",
    "text",
    "suggestions",
}
_RESULT_FIELDS = {"item_id", "top_scene", "sub_scene", "reason"}
_FAMILY_ORDER = tuple(dict.fromkeys(scene.top_key for scene in SCENES))
_MAX_BATCH_SIZE = 1000
_MAX_EXCHANGE_BYTES = 16 * 1024 * 1024
_MAX_JSONL_BYTES = 64 * 1024 * 1024
_MAX_JSONL_LINE_BYTES = 1024 * 1024
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024


class RecallReviewError(ValueError):
    pass


def apply_recall_review_results(
    database: WorkDatabase,
    manifest_path: Path,
    result_paths: Sequence[Path],
) -> dict[str, int]:
    """按当前 request 的 item_id 原子应用正向复审结果，不生成历史交换文件。"""
    manifest = _load_manifest(manifest_path)
    request_rows = _load_manifest_requests(manifest_path, manifest)
    expected = {int(row["item_id"]): row for rows in request_rows for row in rows}
    decisions: dict[int, dict[str, object]] = {}
    if not result_paths:
        raise RecallReviewError("至少需要一个复审结果文件")
    for path in result_paths:
        for line_number, raw in _read_jsonl(path, max_lines=_MAX_BATCH_SIZE):
            decision = _validate_result_row(path, line_number, raw)
            item_id = int(decision["item_id"])
            if len(decisions) >= len(expected):
                raise RecallReviewError("复审结果总行数超过 manifest item_id 数量")
            if item_id not in expected or item_id in decisions:
                raise RecallReviewError(f"复审结果 item_id 非法或重复: {item_id}")
            decisions[item_id] = decision
    if set(decisions) != set(expected):
        raise RecallReviewError("复审结果必须精确覆盖 manifest item_id")
    positive: list[tuple[int, str, str, str, str, str, str]] = []
    ignored = 0
    for item_id, decision in decisions.items():
        sub_scene = decision["sub_scene"]
        if sub_scene is None:
            ignored += 1
            continue
        request = expected[item_id]
        suggestions = request["suggestions"]
        assert isinstance(suggestions, list)
        if sub_scene not in {row["sub_scene"] for row in suggestions}:
            raise RecallReviewError(f"item_id={item_id} 的正向 sub_scene 不属于 suggestions")
        top_scene = decision["top_scene"]
        assert isinstance(top_scene, str) and isinstance(sub_scene, str)
        positive.append(
            (
                item_id,
                str(request["source_name"]),
                str(request["source_author"]),
                str(request["text"]),
                top_scene,
                sub_scene,
                str(decision["reason"]),
            )
        )
    summary = database.apply_current_recall_reviews(positive)
    return {"result_rows": len(decisions), "positive": len(positive), "ignored": ignored, **summary}


def prepare_recall_review_batches(
    recall_dir: Path,
    output_dir: Path,
    *,
    batch_size: int = _MAX_BATCH_SIZE,
) -> dict[str, int]:
    """合并多场景召回结果，并生成可确定性复现的复审批次。"""
    if (
        not isinstance(batch_size, int)
        or isinstance(batch_size, bool)
        or not 1 <= batch_size <= _MAX_BATCH_SIZE
    ):
        raise RecallReviewError("batch_size 必须在 1 到 1000 之间")
    if not recall_dir.is_dir():
        raise RecallReviewError(f"语义召回目录不存在: {recall_dir}")
    _require_distinct_directories(recall_dir, output_dir, "recall_dir 与 output_dir 不能相同")
    _require_available_output_directory(output_dir)
    recall_paths = sorted(recall_dir.glob("*.jsonl"), key=lambda path: path.name)
    if not recall_paths:
        raise RecallReviewError(f"语义召回目录中没有 JSONL 文件: {recall_dir}")

    items: dict[int, dict[str, object]] = {}
    source_files: list[dict[str, object]] = []
    suggestion_count = 0
    for path in recall_paths:
        file_scene = path.stem
        if file_scene not in SUB_SCENES:
            raise RecallReviewError(f"召回文件名场景非法: {path.name}")
        file_count = 0
        seen_in_file: set[int] = set()
        for line_number, raw in _read_jsonl(path, max_lines=_MAX_BATCH_SIZE):
            row = _validate_recall_row(path, line_number, raw, file_scene)
            item_id = int(row["item_id"])
            if item_id in seen_in_file:
                raise RecallReviewError(f"{path} 包含重复 item_id: {item_id}")
            seen_in_file.add(item_id)
            file_count += 1
            suggestion_count += 1
            identity = (
                row["source_name"],
                row["source_author"],
                row["text"],
            )
            existing = items.get(item_id)
            if existing is None:
                existing = {
                    "item_id": item_id,
                    "source_name": identity[0],
                    "source_author": identity[1],
                    "text": identity[2],
                    "suggestions": [],
                }
                items[item_id] = existing
            elif (
                existing["source_name"],
                existing["source_author"],
                existing["text"],
            ) != identity:
                raise RecallReviewError(f"跨场景重复 item_id={item_id} 的身份不一致")
            suggestions = existing["suggestions"]
            assert isinstance(suggestions, list)
            suggestions.append(
                {
                    "top_scene": SUB_SCENES[file_scene].top_key,
                    "sub_scene": file_scene,
                    "similarity": row["similarity"],
                }
            )
        source_files.append(
            {
                "file": path.name,
                "count": file_count,
                "sha256": _sha256(path),
            }
        )

    families: dict[str, list[dict[str, object]]] = {family: [] for family in _FAMILY_ORDER}
    for item_id in sorted(items):
        item = items[item_id]
        suggestions = item["suggestions"]
        assert isinstance(suggestions, list)
        suggestions.sort(key=lambda row: (-float(row["similarity"]), str(row["sub_scene"])))
        review_family = str(suggestions[0]["top_scene"])
        families[review_family].append(
            {
                **item,
                "review_family": review_family,
            }
        )
    for rows in families.values():
        rows.sort(
            key=lambda row: (
                -float(row["suggestions"][0]["similarity"]),  # type: ignore[index]
                int(row["item_id"]),
            )
        )

    if not items:
        raise RecallReviewError("语义召回目录中没有可复审条目")

    batch_specs: list[tuple[dict[str, object], list[dict[str, object]]]] = []
    request_files: set[str] = set()
    for family in _FAMILY_ORDER:
        rows = families[family]
        for batch_index, chunk in enumerate(_chunk_jsonl_rows(rows, max_count=batch_size), start=1):
            request_file = f"recall-review-{family}-{batch_index:04d}.request.jsonl"
            if request_file in request_files:
                raise RecallReviewError(f"复审批次输出路径冲突: {request_file}")
            request_files.add(request_file)
            batch_specs.append(
                (
                    {
                        "family": family,
                        "index": batch_index,
                        "request_file": request_file,
                        "count": len(chunk),
                        "item_ids": [int(row["item_id"]) for row in chunk],
                    },
                    chunk,
                )
            )

    staging = _create_staging_directory(output_dir)
    try:
        batches: list[dict[str, object]] = []
        for batch, chunk in batch_specs:
            request_path = staging / str(batch["request_file"])
            _write_jsonl_atomic(request_path, chunk)
            batches.append({**batch, "sha256": _sha256(request_path)})
        manifest = {
            "version": 1,
            "batch_size": batch_size,
            "total_items": len(items),
            "total_suggestions": suggestion_count,
            "source_files": source_files,
            "batches": batches,
        }
        _write_json_atomic(staging / "manifest.json", manifest)
        _publish_staging_directory(staging, output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {
        "batch_count": len(batch_specs),
        "item_count": len(items),
        "suggestion_count": suggestion_count,
    }


def validate_recall_review_results(
    manifest_path: Path,
    result_paths: Sequence[Path],
    exchange_dir: Path,
) -> dict[str, int]:
    """校验 LLM 结果精确覆盖输入，并生成历史回放兼容的交换文件。"""
    _require_distinct_directories(
        manifest_path.parent,
        exchange_dir,
        "exchange_dir 与 manifest 所在目录不能相同",
    )
    _require_available_output_directory(exchange_dir)
    manifest = _load_manifest(manifest_path)
    batch_rows = _load_manifest_requests(manifest_path, manifest)
    expected_ids = {int(row["item_id"]) for rows in batch_rows for row in rows}
    decisions: dict[int, dict[str, object]] = {}
    if not result_paths:
        raise RecallReviewError("至少需要一个复审结果文件")
    result_count = 0
    for path in result_paths:
        for line_number, raw in _read_jsonl(path, max_lines=_MAX_BATCH_SIZE):
            decision = _validate_result_row(path, line_number, raw)
            item_id = int(decision["item_id"])
            result_count += 1
            if result_count > len(expected_ids):
                raise RecallReviewError("复审结果总行数超过 manifest item_id 数量")
            if item_id not in expected_ids:
                raise RecallReviewError(f"复审结果包含 unexpected item_id: {item_id}")
            if item_id in decisions:
                raise RecallReviewError(f"复审结果包含重复 item_id: {item_id}")
            decisions[item_id] = decision
    actual_ids = set(decisions)
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        unexpected = sorted(actual_ids - expected_ids)
        raise RecallReviewError(
            "复审结果必须精确覆盖 manifest item_id: "
            f"missing={missing[:10]}, unexpected={unexpected[:10]}"
        )
    suggestions_by_id = {
        int(row["item_id"]): {
            str(suggestion["sub_scene"])
            for suggestion in row["suggestions"]  # type: ignore[union-attr]
        }
        for rows in batch_rows
        for row in rows
    }
    for item_id, decision in decisions.items():
        sub_scene = decision["sub_scene"]
        if sub_scene is not None and sub_scene not in suggestions_by_id[item_id]:
            raise RecallReviewError(
                f"item_id={item_id} 的正向 sub_scene 不属于该 item 的 suggestions"
            )

    exchange_specs: list[tuple[str, int, list[dict[str, object]], list[dict[str, object]]]] = []
    positive_count = 0
    family_indexes = {family: 0 for family in _FAMILY_ORDER}
    batches = manifest["batches"]
    assert isinstance(batches, list)
    for batch, rows in zip(batches, batch_rows, strict=True):
        family = str(batch["family"])
        paired_rows: list[tuple[dict[str, object], dict[str, object]]] = []
        for row in rows:
            suggestions = row["suggestions"]
            assert isinstance(suggestions, list)
            best = suggestions[0]
            assert isinstance(best, dict)
            standard_request = {
                "item_id": row["item_id"],
                "source_name": row["source_name"],
                "source_author": row["source_author"],
                "text": row["text"],
                "suggested_scene": best["sub_scene"],
                "similarity": best["similarity"],
            }
            decision = decisions[int(row["item_id"])]
            paired_rows.append((standard_request, decision))
            if decision["sub_scene"] is not None:
                positive_count += 1
        for requests, results in _chunk_exchange_rows(paired_rows):
            family_indexes[family] += 1
            exchange_specs.append((family, family_indexes[family], requests, results))

    output_files: set[str] = set()
    for family, index, _requests, _results in exchange_specs:
        stem = f"recall-review-{family}-{index:04d}"
        for file_name in (f"{stem}.request.jsonl", f"{stem}.result.jsonl"):
            if file_name in output_files:
                raise RecallReviewError(f"历史回放输出路径冲突: {file_name}")
            output_files.add(file_name)

    staging = _create_staging_directory(exchange_dir)
    try:
        exchanges: list[dict[str, object]] = []
        for family, index, standard_requests, standard_results in exchange_specs:
            stem = f"recall-review-{family}-{index:04d}"
            request_file = f"{stem}.request.jsonl"
            result_file = f"{stem}.result.jsonl"
            request_path = staging / request_file
            result_path = staging / result_file
            _write_jsonl_atomic(request_path, standard_requests)
            _write_jsonl_atomic(result_path, standard_results)
            exchanges.append(
                {
                    "family": family,
                    "index": index,
                    "count": len(standard_requests),
                    "request_file": request_file,
                    "result_file": result_file,
                    "request_sha256": _sha256(request_path),
                    "result_sha256": _sha256(result_path),
                }
            )
        _write_json_atomic(
            staging / "manifest.json",
            {
                "version": 1,
                "source_manifest_sha256": _sha256(manifest_path),
                "total_items": len(expected_ids),
                "positive_count": positive_count,
                "exchanges": exchanges,
            },
        )
        _publish_staging_directory(staging, exchange_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {
        "batch_count": len(exchange_specs),
        "item_count": len(expected_ids),
        "positive_count": positive_count,
    }


def _validate_recall_row(
    path: Path,
    line_number: int,
    row: dict[str, Any],
    file_scene: str,
) -> dict[str, object]:
    if set(row) != _RECALL_FIELDS:
        raise RecallReviewError(f"{path}:{line_number} 召回字段必须精确为 {sorted(_RECALL_FIELDS)}")
    item_id = _positive_item_id(path, line_number, row["item_id"])
    for field in ("text", "source_name"):
        value = row[field]
        if not isinstance(value, str) or not value.strip():
            raise RecallReviewError(f"{path}:{line_number} {field} 必须为非空字符串")
    if not isinstance(row["source_author"], str):
        raise RecallReviewError(f"{path}:{line_number} source_author 必须为字符串")
    suggested_scene = row["suggested_scene"]
    if suggested_scene != file_scene:
        raise RecallReviewError(f"{path}:{line_number} suggested_scene 与文件名场景不一致")
    similarity = row["similarity"]
    if not _is_finite_number(similarity):
        raise RecallReviewError(f"{path}:{line_number} similarity 必须是有限数字")
    return {
        "item_id": item_id,
        "text": row["text"],
        "source_name": row["source_name"],
        "source_author": row["source_author"],
        "similarity": float(similarity),
        "suggested_scene": suggested_scene,
    }


def _validate_result_row(path: Path, line_number: int, row: dict[str, Any]) -> dict[str, object]:
    if set(row) != _RESULT_FIELDS:
        raise RecallReviewError(f"{path}:{line_number} 结果字段必须精确为 {sorted(_RESULT_FIELDS)}")
    item_id = _positive_item_id(path, line_number, row["item_id"])
    top_scene = row["top_scene"]
    sub_scene = row["sub_scene"]
    if (top_scene is None) != (sub_scene is None):
        raise RecallReviewError(f"{path}:{line_number} top_scene 与 sub_scene 必须同时为 null")
    if top_scene is not None:
        scene = SUB_SCENES.get(sub_scene) if isinstance(sub_scene, str) else None
        if not isinstance(top_scene, str) or scene is None or scene.top_key != top_scene:
            raise RecallReviewError(f"{path}:{line_number} 包含非法或不匹配的场景标签")
    reason = row["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise RecallReviewError(f"{path}:{line_number} reason 必须为非空字符串")
    return {
        "item_id": item_id,
        "top_scene": top_scene,
        "sub_scene": sub_scene,
        "reason": reason.strip(),
    }


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        stat_result = path.stat()
        if not path.is_file():
            raise RecallReviewError(f"复审 manifest 不是普通文件: {path}")
        if stat_result.st_size > _MAX_MANIFEST_BYTES:
            raise RecallReviewError(f"复审 manifest 超过 {_MAX_MANIFEST_BYTES} 字节上限")
        payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except RecallReviewError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise RecallReviewError(f"无法读取复审 manifest {path}: {error}") from error
    expected = {
        "version",
        "batch_size",
        "total_items",
        "total_suggestions",
        "source_files",
        "batches",
    }
    if not isinstance(payload, dict) or set(payload) != expected or payload["version"] != 1:
        raise RecallReviewError("复审 manifest 字段或版本非法")
    batch_size = payload["batch_size"]
    if not _is_positive_int(batch_size) or int(batch_size) > _MAX_BATCH_SIZE:
        raise RecallReviewError("复审 manifest batch_size 必须在 1 到 1000 之间")
    total_items = payload["total_items"]
    total_suggestions = payload["total_suggestions"]
    if not _is_positive_int(total_items):
        raise RecallReviewError("复审 manifest total_items 必须为正整数")
    if not _is_positive_int(total_suggestions) or int(total_suggestions) < int(total_items):
        raise RecallReviewError("复审 manifest total_suggestions 非法")
    source_files = payload["source_files"]
    if not isinstance(source_files, list) or not source_files:
        raise RecallReviewError("复审 manifest source_files 必须是非空列表")
    source_names: set[str] = set()
    source_suggestions = 0
    for index, source in enumerate(source_files, start=1):
        if not isinstance(source, dict) or set(source) != {"file", "count", "sha256"}:
            raise RecallReviewError(f"复审 manifest source_files[{index}] 字段非法")
        file_name = source["file"]
        count = source["count"]
        if (
            not isinstance(file_name, str)
            or Path(file_name).name != file_name
            or not file_name.endswith(".jsonl")
            or Path(file_name).stem not in SUB_SCENES
        ):
            raise RecallReviewError(f"复审 manifest source_files[{index}] 文件名非法")
        if file_name in source_names:
            raise RecallReviewError(f"复审 manifest source_files 包含重复文件: {file_name}")
        if not _is_nonnegative_int(count) or int(count) > _MAX_BATCH_SIZE:
            raise RecallReviewError(f"复审 manifest source_files[{index}] count 非法")
        if not _is_sha256(source["sha256"]):
            raise RecallReviewError(f"复审 manifest source_files[{index}] sha256 非法")
        source_names.add(file_name)
        source_suggestions += int(count)
    if [source["file"] for source in source_files] != sorted(source_names):
        raise RecallReviewError("复审 manifest source_files 顺序非法")
    if source_suggestions != total_suggestions:
        raise RecallReviewError("复审 manifest total_suggestions 与 source_files 不一致")
    if not isinstance(payload["batches"], list) or not payload["batches"]:
        raise RecallReviewError("复审 manifest batches 必须是非空列表")
    _validate_manifest_batches(payload["batches"], int(batch_size))
    return payload


def _validate_manifest_batches(batches: list[object], batch_size: int) -> None:
    batch_keys: set[tuple[str, int]] = set()
    request_files: set[str] = set()
    observed_order: list[tuple[int, int]] = []
    indexes_by_family: dict[str, list[int]] = {}
    for batch_number, batch in enumerate(batches, start=1):
        if not isinstance(batch, dict) or set(batch) != {
            "family",
            "index",
            "request_file",
            "count",
            "item_ids",
            "sha256",
        }:
            raise RecallReviewError(f"复审 manifest batches[{batch_number}] 字段非法")
        family = batch["family"]
        index = batch["index"]
        request_file = batch["request_file"]
        if family not in _FAMILY_ORDER:
            raise RecallReviewError(f"复审 manifest batches[{batch_number}] family 非法")
        if not _is_positive_int(index):
            raise RecallReviewError(f"复审 manifest batches[{batch_number}] index 必须为正整数")
        key = (str(family), int(index))
        if key in batch_keys:
            raise RecallReviewError(f"复审 manifest family/index 重复: {key}")
        batch_keys.add(key)
        indexes_by_family.setdefault(str(family), []).append(int(index))
        observed_order.append((_FAMILY_ORDER.index(str(family)), int(index)))
        canonical = f"recall-review-{family}-{int(index):04d}.request.jsonl"
        if request_file != canonical:
            raise RecallReviewError(
                f"复审 manifest batches[{batch_number}] request_file 必须为 canonical: {canonical}"
            )
        if request_file in request_files:
            raise RecallReviewError(f"复审 manifest request_file 路径冲突: {request_file}")
        request_files.add(str(request_file))
        if not _is_positive_int(batch["count"]) or int(batch["count"]) > batch_size:
            raise RecallReviewError(f"复审 manifest batches[{batch_number}] count 非法")
        item_ids = batch["item_ids"]
        if (
            not isinstance(item_ids, list)
            or len(item_ids) != int(batch["count"])
            or any(not _is_positive_int(item_id) for item_id in item_ids)
            or len(set(item_ids)) != len(item_ids)
        ):
            raise RecallReviewError(f"复审 manifest batches[{batch_number}] item_ids 非法")
        if not _is_sha256(batch["sha256"]):
            raise RecallReviewError(f"复审 manifest batches[{batch_number}] sha256 非法")
    if observed_order != sorted(observed_order):
        raise RecallReviewError("复审 manifest batches 顺序非法")
    for family, indexes in indexes_by_family.items():
        if sorted(indexes) != list(range(1, len(indexes) + 1)):
            raise RecallReviewError(f"复审 manifest family={family} index 必须连续")


def _load_manifest_requests(
    manifest_path: Path, manifest: dict[str, object]
) -> list[list[dict[str, object]]]:
    batches = manifest["batches"]
    assert isinstance(batches, list)
    all_ids: set[int] = set()
    loaded: list[list[dict[str, object]]] = []
    suggestion_count = 0
    batch_size = int(manifest["batch_size"])
    for batch in batches:
        assert isinstance(batch, dict)
        request_file = str(batch["request_file"])
        request_path = manifest_path.parent / request_file
        if _sha256(request_path, max_bytes=_MAX_EXCHANGE_BYTES) != batch["sha256"]:
            raise RecallReviewError(f"复审批次校验和不匹配: {request_file}")
        rows: list[dict[str, object]] = []
        for line_number, row in _read_jsonl(
            request_path,
            max_lines=batch_size,
            max_bytes=_MAX_EXCHANGE_BYTES,
        ):
            validated = _validate_review_row(request_path, line_number, row)
            rows.append(validated)
            suggestions = validated["suggestions"]
            assert isinstance(suggestions, list)
            suggestion_count += len(suggestions)
        item_ids = [int(row["item_id"]) for row in rows]
        if batch["count"] != len(rows) or batch["item_ids"] != item_ids:
            raise RecallReviewError(f"复审批次 manifest 计数或 item_id 不匹配: {request_file}")
        duplicated = all_ids.intersection(item_ids)
        if duplicated:
            raise RecallReviewError(f"manifest 跨批次包含重复 item_id: {min(duplicated)}")
        all_ids.update(item_ids)
        loaded.append(rows)
    if manifest["total_items"] != len(all_ids):
        raise RecallReviewError("复审 manifest total_items 与批次不一致")
    if manifest["total_suggestions"] != suggestion_count:
        raise RecallReviewError("复审 manifest total_suggestions 与批次内容不一致")
    return loaded


def _validate_review_row(path: Path, line_number: int, row: dict[str, Any]) -> dict[str, object]:
    if set(row) != _REVIEW_FIELDS:
        raise RecallReviewError(f"{path}:{line_number} 扩展复审字段非法")
    item_id = _positive_item_id(path, line_number, row["item_id"])
    family = row["review_family"]
    if family not in _FAMILY_ORDER:
        raise RecallReviewError(f"{path}:{line_number} review_family 非法")
    for field in ("text", "source_name"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise RecallReviewError(f"{path}:{line_number} {field} 必须为非空字符串")
    if not isinstance(row["source_author"], str):
        raise RecallReviewError(f"{path}:{line_number} source_author 必须为字符串")
    raw_suggestions = row["suggestions"]
    if not isinstance(raw_suggestions, list) or not raw_suggestions:
        raise RecallReviewError(f"{path}:{line_number} suggestions 必须是非空列表")
    suggestions: list[dict[str, object]] = []
    seen_scenes: set[str] = set()
    for suggestion in raw_suggestions:
        if not isinstance(suggestion, dict) or set(suggestion) != {
            "top_scene",
            "sub_scene",
            "similarity",
        }:
            raise RecallReviewError(f"{path}:{line_number} suggestion 字段非法")
        sub_scene = suggestion["sub_scene"]
        scene = SUB_SCENES.get(sub_scene) if isinstance(sub_scene, str) else None
        if scene is None or suggestion["top_scene"] != scene.top_key:
            raise RecallReviewError(f"{path}:{line_number} suggestion 场景非法")
        if sub_scene in seen_scenes:
            raise RecallReviewError(f"{path}:{line_number} suggestion 场景重复")
        if not _is_finite_number(suggestion["similarity"]):
            raise RecallReviewError(f"{path}:{line_number} suggestion similarity 非法")
        seen_scenes.add(sub_scene)
        suggestions.append(
            {
                "top_scene": scene.top_key,
                "sub_scene": sub_scene,
                "similarity": float(suggestion["similarity"]),
            }
        )
    expected_order = sorted(
        suggestions, key=lambda value: (-float(value["similarity"]), str(value["sub_scene"]))
    )
    if suggestions != expected_order or suggestions[0]["top_scene"] != family:
        raise RecallReviewError(f"{path}:{line_number} suggestions 排序或 review_family 非法")
    return {
        "item_id": item_id,
        "review_family": family,
        "source_name": row["source_name"],
        "source_author": row["source_author"],
        "text": row["text"],
        "suggestions": suggestions,
    }


def _read_jsonl(
    path: Path,
    *,
    max_lines: int,
    max_bytes: int = _MAX_JSONL_BYTES,
) -> Iterator[tuple[int, dict[str, Any]]]:
    try:
        stat_result = path.stat()
        if not path.is_file():
            raise RecallReviewError(f"JSONL 路径不是普通文件: {path}")
        if stat_result.st_size > max_bytes:
            raise RecallReviewError(f"JSONL 文件超过 {max_bytes} 字节上限: {path}")
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if line_number > max_lines:
                    raise RecallReviewError(f"JSONL 文件超过 {max_lines} 行上限: {path}")
                if len(line.encode("utf-8")) > _MAX_JSONL_LINE_BYTES:
                    raise RecallReviewError(f"{path}:{line_number} 超过单行字节上限")
                if not line.strip():
                    continue
                try:
                    row = json.loads(line, object_pairs_hook=_strict_object)
                except RecallReviewError:
                    raise
                except (json.JSONDecodeError, ValueError) as error:
                    raise RecallReviewError(
                        f"{path}:{line_number} 不是合法 JSON: {error}"
                    ) from error
                if not isinstance(row, dict):
                    raise RecallReviewError(f"{path}:{line_number} JSONL 行必须是对象")
                yield line_number, row
    except RecallReviewError:
        raise
    except (OSError, UnicodeError) as error:
        raise RecallReviewError(f"无法读取 JSONL 文件 {path}: {error}") from error


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in pairs:
        if key in row:
            raise RecallReviewError(f"JSON 对象包含重复字段 {key!r}")
        row[key] = value
    return row


def _positive_item_id(path: Path, line_number: int, value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RecallReviewError(f"{path}:{line_number} item_id 必须为正整数")
    return value


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _sha256(path: Path, *, max_bytes: int | None = None) -> str:
    try:
        stat_result = path.stat()
        if not path.is_file():
            raise RecallReviewError(f"路径不是普通文件: {path}")
        if max_bytes is not None and stat_result.st_size > max_bytes:
            raise RecallReviewError(f"文件超过 {max_bytes} 字节上限: {path}")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except RecallReviewError:
        raise
    except OSError as error:
        raise RecallReviewError(f"无法读取文件 {path}: {error}") from error


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_jsonl_atomic(path: Path, rows: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    payload = b"".join(_encode_jsonl_row(row) for row in rows)
    if len(rows) > _MAX_BATCH_SIZE or len(payload) > _MAX_EXCHANGE_BYTES:
        raise RecallReviewError(f"输出 JSONL 超过历史回放文件边界: {path.name}")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _chunk_jsonl_rows(
    rows: Sequence[dict[str, object]],
    *,
    max_count: int,
) -> list[list[dict[str, object]]]:
    chunks: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    current_bytes = 0
    for row in rows:
        row_bytes = len(_encode_jsonl_row(row))
        if current and (
            len(current) >= max_count or current_bytes + row_bytes > _MAX_EXCHANGE_BYTES
        ):
            chunks.append(current)
            current = []
            current_bytes = 0
        current.append(row)
        current_bytes += row_bytes
    if current:
        chunks.append(current)
    return chunks


def _chunk_exchange_rows(
    pairs: Sequence[tuple[dict[str, object], dict[str, object]]],
) -> list[tuple[list[dict[str, object]], list[dict[str, object]]]]:
    chunks: list[tuple[list[dict[str, object]], list[dict[str, object]]]] = []
    requests: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    request_bytes = 0
    result_bytes = 0
    for request, result in pairs:
        next_request_bytes = len(_encode_jsonl_row(request))
        next_result_bytes = len(_encode_jsonl_row(result))
        if requests and (
            len(requests) >= _MAX_BATCH_SIZE
            or request_bytes + next_request_bytes > _MAX_EXCHANGE_BYTES
            or result_bytes + next_result_bytes > _MAX_EXCHANGE_BYTES
        ):
            chunks.append((requests, results))
            requests = []
            results = []
            request_bytes = 0
            result_bytes = 0
        requests.append(request)
        results.append(result)
        request_bytes += next_request_bytes
        result_bytes += next_result_bytes
    if requests:
        chunks.append((requests, results))
    return chunks


def _encode_jsonl_row(row: dict[str, object]) -> bytes:
    encoded = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > _MAX_JSONL_LINE_BYTES:
        raise RecallReviewError("JSONL 输出行超过 1048576 字节上限")
    return encoded


def _require_distinct_directories(first: Path, second: Path, message: str) -> None:
    if first.resolve(strict=False) == second.resolve(strict=False):
        raise RecallReviewError(message)


def _require_available_output_directory(path: Path) -> None:
    if not path.exists():
        return
    if not path.is_dir() or any(path.iterdir()):
        raise RecallReviewError(f"输出目录必须不存在或为空: {path}")


def _create_staging_directory(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.staging-",
            dir=target.parent,
        )
    )


def _publish_staging_directory(staging: Path, target: Path) -> None:
    removed_empty_target = False
    if target.exists():
        target.rmdir()
        removed_empty_target = True
    try:
        staging.replace(target)
    except OSError:
        if removed_empty_target and not target.exists():
            target.mkdir()
        raise


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
