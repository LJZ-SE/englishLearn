from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from tools.content_pipeline.clean import rejection_reason
from tools.content_pipeline.selection import is_near_duplicate

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "src" / "listening_cloze" / "data"


def test_first_release_database_passes_all_structural_and_content_gates() -> None:
    with sqlite3.connect(DATA_DIR / "content.db") as connection:
        connection.row_factory = sqlite3.Row
        sentences = connection.execute("SELECT * FROM sentences ORDER BY id").fetchall()
        variants = connection.execute(
            """
            SELECT q.*, s.text
            FROM question_variants AS q
            JOIN sentences AS s ON s.id = q.sentence_id
            ORDER BY q.sentence_id, q.difficulty_score
            """
        ).fetchall()

    assert len(sentences) == 300
    assert len(variants) == 900
    assert Counter(row["category"] for row in sentences) == {
        "daily": 75,
        "exam": 75,
        "movies": 75,
        "news_podcasts": 75,
    }
    assert len({row["normalized_hash"] for row in sentences}) == 300
    assert all(row["source_url"].startswith("https://") for row in sentences)
    assert all(row["source_author"] and row["license_url"] for row in sentences)
    assert all(rejection_reason(row["text"]) is None for row in sentences)

    texts = [row["text"] for row in sentences]
    assert not any(
        is_near_duplicate(texts[left], texts[right])
        for left in range(len(texts))
        for right in range(left + 1, len(texts))
    )

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
    report = json.loads((DATA_DIR / "quality-report.json").read_text(encoding="utf-8"))
    sources = json.loads((DATA_DIR / "sources.json").read_text(encoding="utf-8"))

    assert report["gate_status"] == "passed"
    assert report["sentence_count"] == 300
    assert report["variant_count"] == 900
    assert report["category_distribution"] == {
        "daily": 75,
        "exam": 75,
        "movies": 75,
        "news_podcasts": 75,
    }
    assert report["source_distribution"] == {
        "English Wikinews": 75,
        "Tatoeba": 225,
    }
    assert sum(item["sentence_count"] for item in sources) == 300
    assert {item["license_name"] for item in sources} == {
        "CC BY 2.0 FR",
        "CC BY 2.5",
        "CC BY 4.0",
        "Public domain",
    }
