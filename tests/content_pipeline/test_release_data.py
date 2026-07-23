from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

from tools.content_pipeline.clean import rejection_reason
from tools.content_pipeline.dedupe import NearDuplicateIndex
from tools.content_pipeline.scenes import SCENES, TOTAL_SENTENCE_QUOTA
from tools.content_pipeline.selection import is_near_duplicate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "src" / "listening_cloze" / "data"
CONTENT_DATABASE = Path(
    os.environ.get("LISTENING_CLOZE_CONTENT_DB", DATA_DIR / "content.db")
)
REPORT_PATH = CONTENT_DATABASE.with_name("quality-report.json")
SOURCES_PATH = CONTENT_DATABASE.with_name("sources.json")


def test_first_release_database_passes_all_structural_and_content_gates() -> None:
    with sqlite3.connect(CONTENT_DATABASE) as connection:
        connection.row_factory = sqlite3.Row
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
        sentences = connection.execute("SELECT * FROM sentences ORDER BY id").fetchall()
        variants = connection.execute(
            """
            SELECT q.*, s.text
            FROM question_variants AS q
            JOIN sentences AS s ON s.id = q.sentence_id
            ORDER BY q.sentence_id, q.difficulty_score
            """
        ).fetchall()

        if schema_version == 2:
            top_scene_count = connection.execute("SELECT COUNT(*) FROM top_scenes").fetchone()[0]
            sub_scene_count = connection.execute("SELECT COUNT(*) FROM sub_scenes").fetchone()[0]
        else:
            top_scene_count = sub_scene_count = 0

    assert schema_version in {1, 2}
    assert len(variants) == len(sentences) * 3
    if schema_version == 1:
        assert len(sentences) == 300
        assert Counter(row["category"] for row in sentences) == {
            "daily": 75,
            "exam": 75,
            "movies": 75,
            "news_podcasts": 75,
        }
    else:
        assert top_scene_count == 8
        assert sub_scene_count == 32
        assert all(row["sub_scene_key"] and row["source_item_id"] for row in sentences)
        assert all(0 <= row["random_key"] <= (1 << 63) - 1 for row in sentences)
    assert len({row["normalized_hash"] for row in sentences}) == len(sentences)
    assert all(row["translation_zh"].strip() for row in sentences)
    assert all(row["source_url"].startswith("https://") for row in sentences)
    assert all(
        row["license_name"] and row["license_url"].startswith("https://")
        for row in sentences
    )
    if schema_version == 2:
        rows_by_scene: dict[str, list[sqlite3.Row]] = {}
        for row in sentences:
            rows_by_scene.setdefault(row["sub_scene_key"], []).append(row)
        for rows in rows_by_scene.values():
            named_authors = Counter(
                row["source_author"].strip()
                for row in rows
                if row["source_author"].strip()
            )
            assert not named_authors or max(named_authors.values()) <= max(
                1, int(len(rows) * 0.08)
            )
    assert all(rejection_reason(row["text"]) is None for row in sentences)

    texts = [row["text"] for row in sentences]
    if schema_version == 1:
        assert not any(
            is_near_duplicate(texts[left], texts[right])
            for left in range(len(texts))
            for right in range(left + 1, len(texts))
        )
    else:
        near_duplicates = NearDuplicateIndex()
        assert all(near_duplicates.add(text) for text in texts)

    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in variants:
        grouped.setdefault(row["sentence_id"], []).append(row)
        answer = row["canonical_answer"]
        assert row["text"][row["answer_start"] : row["answer_end"]] == answer
        assert row["answer_word_count"] == len(answer.split())
        assert 1 <= row["answer_word_count"] <= 4

    for rows in grouped.values():
        assert [row["difficulty"] for row in rows] == ["easy", "medium", "hard"]
        assert len({row["canonical_answer"].casefold() for row in rows}) == 3
        assert rows[0]["difficulty_score"] < rows[1]["difficulty_score"]
        assert rows[1]["difficulty_score"] < rows[2]["difficulty_score"]


def test_first_release_reports_and_source_manifest_match_database() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))

    assert report["gate_status"] == "passed"
    assert report["variant_count"] == report["sentence_count"] * 3
    assert sum(item["sentence_count"] for item in sources) == report["sentence_count"]
    assert all(item["license_name"] and item["license_url"] for item in sources)
    if CONTENT_DATABASE == DATA_DIR / "content.db":
        assert report["sentence_count"] == TOTAL_SENTENCE_QUOTA == 30_000
        assert report["variant_count"] == 90_000
        assert report["scene_distribution"] == {
            scene.key: scene.quota for scene in SCENES
        }
        assert report["difficulty_distribution"] == {
            "easy": 30_000,
            "medium": 30_000,
            "hard": 30_000,
        }
        assert report["source_distribution"]["legacy-content"] == 300
        assert len(report["source_distribution"]) >= 20
