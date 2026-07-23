import hashlib
import json
import sqlite3
from pathlib import Path

from listening_cloze.application.asset_health import (
    EXPECTED_QUESTION_COUNT,
    EXPECTED_SENTENCE_COUNT,
    check_bundled_assets,
)


def test_missing_database_and_model_are_reported(tmp_path: Path) -> None:
    issues = check_bundled_assets(tmp_path / "content.db", tmp_path / "supertonic-3")

    assert any("content.db" in issue for issue in issues)
    assert any("Supertonic" in issue for issue in issues)


def test_complete_database_and_required_model_files_pass_health_check(tmp_path: Path) -> None:
    content_db = tmp_path / "content.db"
    with sqlite3.connect(content_db) as connection:
        connection.execute("CREATE TABLE sentences(id TEXT PRIMARY KEY)")
        connection.execute("CREATE TABLE question_variants(id TEXT PRIMARY KEY)")
        connection.executemany(
            "INSERT INTO sentences VALUES (?)",
            ((f"s-{index}",) for index in range(EXPECTED_SENTENCE_COUNT)),
        )
        connection.executemany(
            "INSERT INTO question_variants VALUES (?)",
            ((f"q-{index}",) for index in range(EXPECTED_QUESTION_COUNT)),
        )
    model_dir = tmp_path / "supertonic-3"
    required = [
        "onnx/duration_predictor.onnx",
        "onnx/text_encoder.onnx",
        "onnx/vector_estimator.onnx",
        "onnx/vocoder.onnx",
        "onnx/tts.json",
        "onnx/unicode_indexer.json",
        "voice_styles/F3.json",
        "LICENSE",
    ]
    for relative_path in required:
        target = model_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"asset")
    (model_dir / "asset-manifest.json").write_text(
        json.dumps(
            {
                "revision": "724fb5abbf5502583fb520898d45929e62f02c0b",
                "files": [
                    {"path": relative_path, "sha256": hashlib.sha256(b"asset").hexdigest()}
                    for relative_path in required
                ],
            }
        ),
        encoding="utf-8",
    )

    assert check_bundled_assets(content_db, model_dir) == []

    (model_dir / "voice_styles/F3.json").write_bytes(b"damaged")
    assert any("哈希" in issue for issue in check_bundled_assets(content_db, model_dir))
