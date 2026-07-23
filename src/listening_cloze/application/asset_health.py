from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

REQUIRED_MODEL_FILES = (
    "onnx/duration_predictor.onnx",
    "onnx/text_encoder.onnx",
    "onnx/vector_estimator.onnx",
    "onnx/vocoder.onnx",
    "onnx/tts.json",
    "onnx/unicode_indexer.json",
    "voice_styles/F3.json",
    "LICENSE",
)
MODEL_REVISION = "724fb5abbf5502583fb520898d45929e62f02c0b"
EXPECTED_SENTENCE_COUNT = 36_000
EXPECTED_QUESTION_COUNT = 108_000


def check_bundled_assets(
    content_database: str | Path,
    model_directory: str | Path,
) -> list[str]:
    content_path = Path(content_database)
    model_path = Path(model_directory)
    issues: list[str] = []

    if not content_path.is_file():
        issues.append(f"缺少题库文件：{content_path.name}")
    else:
        try:
            with sqlite3.connect(
                f"{content_path.resolve().as_uri()}?mode=ro", uri=True
            ) as connection:
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
                sentence_count = connection.execute("SELECT COUNT(*) FROM sentences").fetchone()[0]
                question_count = connection.execute(
                    "SELECT COUNT(*) FROM question_variants"
                ).fetchone()[0]
            if integrity != "ok":
                issues.append("题库 content.db 完整性校验失败")
            if (
                sentence_count != EXPECTED_SENTENCE_COUNT
                or question_count != EXPECTED_QUESTION_COUNT
            ):
                issues.append(
                    f"题库数量异常：应为 {EXPECTED_SENTENCE_COUNT} 个原句 / "
                    f"{EXPECTED_QUESTION_COUNT} 道题，实际为 "
                    f"{sentence_count} / {question_count}"
                )
        except sqlite3.Error as error:
            issues.append(f"题库 content.db 无法读取：{error}")

    missing_model_files = [
        relative_path
        for relative_path in REQUIRED_MODEL_FILES
        if not (model_path / relative_path).is_file()
        or (model_path / relative_path).stat().st_size == 0
    ]
    if missing_model_files:
        issues.append("缺少 Supertonic 离线模型资源：" + "、".join(missing_model_files))

    manifest_path = model_path / "asset-manifest.json"
    if not manifest_path.is_file():
        issues.append("缺少 Supertonic 资产哈希清单：asset-manifest.json")
    else:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if payload.get("revision") != MODEL_REVISION:
                issues.append("Supertonic 模型版本与应用要求不一致")
            expected_hashes = {
                str(item["path"]): str(item["sha256"])
                for item in payload.get("files", [])
                if isinstance(item, dict) and item.get("path") and item.get("sha256")
            }
            for relative_path in REQUIRED_MODEL_FILES:
                asset = model_path / relative_path
                expected = expected_hashes.get(relative_path)
                if expected is None:
                    issues.append(f"Supertonic 哈希清单缺少：{relative_path}")
                elif asset.is_file() and _sha256(asset) != expected:
                    issues.append(f"Supertonic 资产哈希校验失败：{relative_path}")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            issues.append(f"Supertonic 资产哈希清单无法读取：{error}")

    return issues


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
