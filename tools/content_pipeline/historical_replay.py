from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from tools.content_pipeline.scenes import SUB_SCENES
from tools.content_pipeline.work_database import WorkDatabase

_REQUEST_REQUIRED_FIELDS = {"item_id", "source_name", "source_author", "text"}
_REQUEST_OPTIONAL_FIELDS = {
    "suggested_scene",
    "similarity",
    "competing_scene",
    "competing_score",
    "target_score",
    "trigger_keywords",
    "trigger_phrases",
}
_RESULT_FIELDS = {"item_id", "top_scene", "sub_scene", "reason"}
_MAX_JSONL_BYTES = 16 * 1024 * 1024
_MAX_JSONL_LINE_BYTES = 1024 * 1024
_MAX_JSONL_LINES = 1000

HistoricalDecision = tuple[str, str, str, str, str, str]


class HistoricalReplayError(ValueError):
    pass


def replay_classifications(
    database: WorkDatabase,
    exchanges: list[tuple[Path, Path]],
) -> dict[str, int]:
    """校验并按内容身份安全回放旧工作库中的人工分类结果。"""
    if not exchanges:
        raise HistoricalReplayError("至少需要一组 --exchange REQUEST RESULT")

    result_rows = 0
    positive_decisions = 0
    ignored_rejections = 0
    decisions_by_identity: dict[tuple[str, str, str], HistoricalDecision] = {}
    for request_path, result_path in exchanges:
        requests = _load_requests(request_path)
        results = _load_results(result_path)
        result_rows += len(results)
        for old_item_id, top_scene, sub_scene, reason in results:
            identity = requests.get(old_item_id)
            if identity is None:
                raise HistoricalReplayError(
                    f"{result_path} 的结果 item_id={old_item_id} 找不到对应请求"
                )
            if top_scene is None or sub_scene is None:
                ignored_rejections += 1
                continue
            positive_decisions += 1
            decision: HistoricalDecision = (
                identity[0],
                identity[1],
                identity[2],
                top_scene,
                sub_scene,
                reason,
            )
            previous = decisions_by_identity.get(identity)
            if previous is not None and previous[3:5] != decision[3:5]:
                raise HistoricalReplayError(
                    "同一历史身份存在跨文件场景冲突: "
                    f"source_name={identity[0]!r}, source_author={identity[1]!r}, "
                    f"text={identity[2]!r}"
                )
            decisions_by_identity.setdefault(identity, decision)

    try:
        database_summary = database.apply_historical_classifications(
            list(decisions_by_identity.values())
        )
    except ValueError as error:
        raise HistoricalReplayError(str(error)) from error
    return {
        "result_rows": result_rows,
        "positive_decisions": positive_decisions,
        "ignored_rejections": ignored_rejections,
        "deduplicated_decisions": len(decisions_by_identity),
        **database_summary,
    }


def _load_requests(path: Path) -> dict[int, tuple[str, str, str]]:
    requests: dict[int, tuple[str, str, str]] = {}
    for line_number, row in _read_jsonl(path):
        fields = set(row)
        if not fields >= _REQUEST_REQUIRED_FIELDS or not fields <= (
            _REQUEST_REQUIRED_FIELDS | _REQUEST_OPTIONAL_FIELDS
        ):
            raise HistoricalReplayError(
                f"{path}:{line_number} 请求字段必须包含 "
                f"{sorted(_REQUEST_REQUIRED_FIELDS)}，可选字段仅为 "
                f"{sorted(_REQUEST_OPTIONAL_FIELDS)}"
            )
        item_id = _positive_item_id(path, line_number, row["item_id"])
        if item_id in requests:
            raise HistoricalReplayError(f"{path} 请求包含重复 item_id: {item_id}")
        source_name = row["source_name"]
        source_author = row["source_author"]
        text = row["text"]
        if not isinstance(source_name, str) or not source_name.strip():
            raise HistoricalReplayError(f"{path}:{line_number} source_name 必须为非空字符串")
        if not isinstance(source_author, str):
            raise HistoricalReplayError(f"{path}:{line_number} source_author 必须为字符串")
        if not isinstance(text, str) or not text.strip():
            raise HistoricalReplayError(f"{path}:{line_number} text 必须为非空字符串")
        suggested_scene = row.get("suggested_scene")
        if suggested_scene is not None and (
            not isinstance(suggested_scene, str) or suggested_scene not in SUB_SCENES
        ):
            raise HistoricalReplayError(
                f"{path}:{line_number} suggested_scene 必须是合法子场景"
            )
        competing_scene = row.get("competing_scene")
        if competing_scene is not None and (
            not isinstance(competing_scene, str) or competing_scene not in SUB_SCENES
        ):
            raise HistoricalReplayError(
                f"{path}:{line_number} competing_scene 必须是合法子场景"
            )
        for field in ("similarity", "competing_score", "target_score"):
            value = row.get(field)
            if value is not None and not _is_finite_number(value):
                raise HistoricalReplayError(f"{path}:{line_number} {field} 必须是有限数字")
        for field in ("trigger_keywords", "trigger_phrases"):
            value = row.get(field)
            if value is not None and (
                not isinstance(value, list)
                or any(not isinstance(part, str) or not part for part in value)
            ):
                raise HistoricalReplayError(
                    f"{path}:{line_number} {field} 必须是非空字符串数组"
                )
        requests[item_id] = (source_name, source_author, text)
    return requests


def _load_results(path: Path) -> list[tuple[int, str | None, str | None, str]]:
    results: list[tuple[int, str | None, str | None, str]] = []
    seen: set[int] = set()
    for line_number, row in _read_jsonl(path):
        if set(row) != _RESULT_FIELDS:
            raise HistoricalReplayError(
                f"{path}:{line_number} 结果字段必须精确为 {sorted(_RESULT_FIELDS)}"
            )
        item_id = _positive_item_id(path, line_number, row["item_id"])
        if item_id in seen:
            raise HistoricalReplayError(f"{path} 结果包含重复 item_id: {item_id}")
        seen.add(item_id)
        top_scene = row["top_scene"]
        sub_scene = row["sub_scene"]
        if (top_scene is None) != (sub_scene is None):
            raise HistoricalReplayError(
                f"{path}:{line_number} top_scene 与 sub_scene 必须同时为 null"
            )
        if top_scene is not None:
            scene = SUB_SCENES.get(sub_scene) if isinstance(sub_scene, str) else None
            if not isinstance(top_scene, str) or scene is None or scene.top_key != top_scene:
                raise HistoricalReplayError(
                    f"{path}:{line_number} 包含非法或不匹配的场景标签"
                )
        reason = row["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise HistoricalReplayError(f"{path}:{line_number} reason 必须为非空字符串")
        results.append((item_id, top_scene, sub_scene, reason.strip()))
    return results


def _read_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    try:
        file_size = path.stat().st_size
    except OSError as error:
        raise HistoricalReplayError(f"无法读取历史交换文件 {path}: {error}") from error
    if file_size > _MAX_JSONL_BYTES:
        raise HistoricalReplayError(
            f"历史交换文件 {path} 超过 {_MAX_JSONL_BYTES} 字节上限"
        )
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if line_number > _MAX_JSONL_LINES:
                    raise HistoricalReplayError(
                        f"历史交换文件 {path} 超过 {_MAX_JSONL_LINES} 行上限"
                    )
                if len(line.encode("utf-8")) > _MAX_JSONL_LINE_BYTES:
                    raise HistoricalReplayError(
                        f"{path}:{line_number} 超过 {_MAX_JSONL_LINE_BYTES} 字节单行上限"
                    )
                if not line.strip():
                    continue
                try:
                    row = json.loads(line, object_pairs_hook=_strict_object)
                except HistoricalReplayError:
                    raise
                except ValueError as error:
                    raise HistoricalReplayError(
                        f"{path}:{line_number} 不是合法 JSON: {error}"
                    ) from error
                if not isinstance(row, dict):
                    raise HistoricalReplayError(f"{path}:{line_number} JSONL 行必须是对象")
                yield line_number, row
    except (OSError, UnicodeError) as error:
        raise HistoricalReplayError(f"无法读取历史交换文件 {path}: {error}") from error


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in pairs:
        if key in row:
            raise HistoricalReplayError(f"JSON 对象包含重复字段 {key!r}")
        row[key] = value
    return row


def _positive_item_id(path: Path, line_number: int, value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise HistoricalReplayError(f"{path}:{line_number} item_id 必须为正整数")
    return value


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False
