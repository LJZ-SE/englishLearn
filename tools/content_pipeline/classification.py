from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.content_pipeline.scenes import SCENES, SUB_SCENES
from tools.content_pipeline.work_database import WorkDatabase

_RESULT_FIELDS = {"item_id", "top_scene", "sub_scene", "reason"}


class ClassificationImportError(ValueError):
    pass


def export_classification_repairs(database: WorkDatabase, path: Path) -> int:
    labels = [
        {
            "top_scene": scene.top_key,
            "sub_scene": scene.key,
            "top_label": scene.top_label,
            "label": scene.label,
        }
        for scene in SCENES
    ]
    rows = database.classification_repair_rows()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for item, payload in rows:
            stream.write(
                json.dumps(
                    {
                        "item_id": item.id,
                        "text": item.text,
                        "source_name": item.source_name,
                        "source_item_id": item.source_item_id,
                        "source_author": item.source_author,
                        "method": payload.get("method"),
                        "confidence": payload.get("confidence", 0.0),
                        "candidate_labels": labels,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    temporary.replace(path)
    return len(rows)


def import_classification_repairs(database: WorkDatabase, paths: list[Path]) -> int:
    parsed: list[tuple[int, str, str, str]] = []
    seen: set[int] = set()
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ClassificationImportError(f"无法读取分类修正文件 {path}: {error}") from error
        nonempty_lines = [line for line in lines if line.strip()]
        if len(nonempty_lines) > 500:
            raise ClassificationImportError(f"{path} 超过每批 500 条的上限")
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row: Any = json.loads(line)
            except json.JSONDecodeError as error:
                raise ClassificationImportError(
                    f"{path}:{line_number} 不是合法 JSON"
                ) from error
            if not isinstance(row, dict) or set(row) != _RESULT_FIELDS:
                raise ClassificationImportError(
                    f"{path}:{line_number} 字段必须精确为 {sorted(_RESULT_FIELDS)}"
                )
            item_id = row["item_id"]
            top_scene = row["top_scene"]
            sub_scene = row["sub_scene"]
            reason = row["reason"]
            if not isinstance(item_id, int) or isinstance(item_id, bool):
                raise ClassificationImportError(f"{path}:{line_number} item_id 必须为整数")
            if item_id in seen:
                raise ClassificationImportError(f"分类修正结果包含重复 item_id: {item_id}")
            seen.add(item_id)
            scene = SUB_SCENES.get(sub_scene) if isinstance(sub_scene, str) else None
            if (
                scene is None
                or not isinstance(top_scene, str)
                or scene.top_key != top_scene
            ):
                raise ClassificationImportError(
                    f"{path}:{line_number} 包含非法或不匹配的场景标签"
                )
            if not isinstance(reason, str) or not reason.strip():
                raise ClassificationImportError(f"{path}:{line_number} reason 不能为空")
            parsed.append((item_id, top_scene, sub_scene, reason.strip()))
    try:
        return database.apply_classification_repairs(parsed)
    except ValueError as error:
        raise ClassificationImportError(str(error)) from error
