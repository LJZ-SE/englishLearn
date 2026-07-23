from __future__ import annotations

import sqlite3
import statistics
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from listening_cloze.infrastructure.database import ContentRepository

SENTENCE_COUNT = 30_000
VARIANT_COUNT = 90_000
QUERY_ITERATIONS = 20
MEDIAN_LIMIT_SECONDS = 0.2
SINGLE_QUERY_LIMIT_SECONDS = 1.0
DIFFICULTIES = ("easy", "medium", "hard")
CONTENT_SCHEMA_VERSION = 2
TOP_SCENE_KEYS = tuple(f"top-{index}" for index in range(8))
SCENE_KEYS = tuple(
    (top_key, f"{top_key}-sub-{sub_index}")
    for top_key in TOP_SCENE_KEYS
    for sub_index in range(4)
)

CONTENT_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE top_scenes(
    key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    sort_order INTEGER NOT NULL
);
CREATE TABLE sub_scenes(
    key TEXT PRIMARY KEY,
    top_key TEXT NOT NULL REFERENCES top_scenes(key),
    label TEXT NOT NULL,
    quota INTEGER NOT NULL,
    sort_order INTEGER NOT NULL
);
CREATE TABLE sentences(
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    translation_zh TEXT NOT NULL,
    sub_scene_key TEXT NOT NULL REFERENCES sub_scenes(key),
    source_url TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_author TEXT NOT NULL,
    source_item_id TEXT NOT NULL,
    license_name TEXT NOT NULL,
    license_url TEXT NOT NULL,
    normalized_hash TEXT NOT NULL UNIQUE,
    random_key INTEGER NOT NULL
);
CREATE TABLE question_variants(
    id TEXT PRIMARY KEY,
    sentence_id TEXT NOT NULL REFERENCES sentences(id),
    difficulty TEXT NOT NULL CHECK(difficulty IN ('easy', 'medium', 'hard')),
    answer_start INTEGER NOT NULL,
    answer_end INTEGER NOT NULL,
    canonical_answer TEXT NOT NULL,
    answer_word_count INTEGER NOT NULL,
    difficulty_score REAL NOT NULL,
    rationale TEXT NOT NULL
);
CREATE TABLE aliases(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_variant_id TEXT NOT NULL REFERENCES question_variants(id),
    alias TEXT NOT NULL,
    UNIQUE(question_variant_id, alias)
);
CREATE INDEX idx_sentences_scene_random
    ON sentences(sub_scene_key, random_key, id);
CREATE UNIQUE INDEX idx_variants_sentence_difficulty
    ON question_variants(sentence_id, difficulty);
CREATE INDEX idx_aliases_question ON aliases(question_variant_id);
"""

@dataclass(frozen=True, slots=True)
class LargeContentDatabase:
    path: Path
    build_seconds: float
    size_bytes: int


def _sentence_row(index: int) -> tuple[object, ...]:
    _top_scene, sub_scene = SCENE_KEYS[index % len(SCENE_KEYS)]
    return (
        f"s{index:05d}",
        f"Sentence {index:05d} contains enough words for a listening exercise.",
        f"第 {index:05d} 个听力练习句子。",
        sub_scene,
        f"https://fixture.test/sentences/{index}",
        "performance-fixture",
        "fixture-author",
        str(index),
        "fixture-license",
        "https://fixture.test/license",
        f"hash-{index:05d}",
        index * 100_000,
    )


def _variant_rows() -> Iterator[tuple[object, ...]]:
    for index in range(SENTENCE_COUNT):
        for difficulty_index, difficulty in enumerate(DIFFICULTIES):
            yield (
                f"q{index:05d}_{difficulty}",
                f"s{index:05d}",
                difficulty,
                0,
                8,
                "Sentence",
                1,
                float(difficulty_index + 1),
                "性能夹具",
            )


def _build_large_content_database(path: Path) -> LargeContentDatabase:
    started_at = time.perf_counter()
    with sqlite3.connect(path) as connection:
        connection.executescript(CONTENT_SCHEMA_SQL)
        with connection:
            connection.executemany(
                "INSERT INTO top_scenes VALUES (?, ?, ?)",
                (
                    (key, f"大类 {sort_order}", sort_order)
                    for sort_order, key in enumerate(TOP_SCENE_KEYS)
                ),
            )
            connection.executemany(
                "INSERT INTO sub_scenes VALUES (?, ?, ?, ?, ?)",
                (
                    (sub_key, top_key, f"子场景 {sort_order}", 938, sort_order)
                    for sort_order, (top_key, sub_key) in enumerate(SCENE_KEYS)
                ),
            )
            connection.executemany(
                "INSERT INTO sentences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_sentence_row(index) for index in range(SENTENCE_COUNT)),
            )
            connection.executemany(
                "INSERT INTO question_variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _variant_rows(),
            )
            connection.executemany(
                "INSERT INTO aliases(question_variant_id, alias) VALUES (?, ?)",
                (
                    (f"q{index:05d}_easy", f"Example {index}")
                    for index in range(0, SENTENCE_COUNT, 997)
                ),
            )
            connection.execute(f"PRAGMA user_version = {CONTENT_SCHEMA_VERSION}")

        assert connection.execute("PRAGMA user_version").fetchone()[0] == CONTENT_SCHEMA_VERSION
        assert connection.execute("SELECT COUNT(*) FROM top_scenes").fetchone()[0] == 8
        assert connection.execute("SELECT COUNT(*) FROM sub_scenes").fetchone()[0] == 32
        assert connection.execute("SELECT COUNT(*) FROM sentences").fetchone()[0] == SENTENCE_COUNT
        variant_count = connection.execute("SELECT COUNT(*) FROM question_variants").fetchone()[0]
        assert variant_count == VARIANT_COUNT
        index_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        assert {
            "idx_sentences_scene_random",
            "idx_variants_sentence_difficulty",
            "idx_aliases_question",
        } <= index_names

    return LargeContentDatabase(
        path=path,
        build_seconds=time.perf_counter() - started_at,
        size_bytes=path.stat().st_size,
    )


@pytest.fixture(scope="module")
def large_content_database(tmp_path_factory: pytest.TempPathFactory) -> LargeContentDatabase:
    path = tmp_path_factory.mktemp("large-content") / "content.db"
    database = _build_large_content_database(path)
    print(
        f"large-content build={database.build_seconds:.3f}s "
        f"size={database.size_bytes / (1024 * 1024):.2f}MiB"
    )
    return database


def _measure_queries[T](operation: Callable[[], T]) -> tuple[list[float], list[T]]:
    durations: list[float] = []
    results: list[T] = []
    for iteration in range(QUERY_ITERATIONS + 1):
        started_at = time.perf_counter()
        result = operation()
        elapsed = time.perf_counter() - started_at
        # 第一次查询只用于预热 SQLite 页缓存，不纳入性能阈值。
        if iteration > 0:
            durations.append(elapsed)
            results.append(result)
    return durations, results


def _assert_query_timings(name: str, durations: list[float]) -> None:
    median_seconds = statistics.median(durations)
    maximum_seconds = max(durations)
    print(
        f"{name} median={median_seconds * 1000:.2f}ms "
        f"max={maximum_seconds * 1000:.2f}ms runs={len(durations)}"
    )
    assert len(durations) == QUERY_ITERATIONS
    assert median_seconds < MEDIAN_LIMIT_SECONDS
    assert all(duration < SINGLE_QUERY_LIMIT_SECONDS for duration in durations)


def _expected_sample_ids(
    database_path: Path,
    *,
    difficulty: str,
    seed: int,
    exclude_ids: frozenset[str],
    limit: int,
) -> list[str]:
    excluded_placeholders = ", ".join("?" for _ in exclude_ids)
    excluded_clause = f" AND q.id NOT IN ({excluded_placeholders})" if exclude_ids else ""
    selected_ids: list[str] = []
    with sqlite3.connect(database_path) as connection:
        for comparison in (">=", "<"):
            remaining = limit - len(selected_ids)
            if remaining <= 0:
                break
            rows = connection.execute(
                f"""
                SELECT q.id
                FROM sentences AS s
                JOIN question_variants AS q ON q.sentence_id = s.id
                WHERE s.random_key {comparison} ?
                    AND q.difficulty = ?
                    {excluded_clause}
                ORDER BY s.random_key, s.id
                LIMIT ?
                """,
                (seed, difficulty, *sorted(exclude_ids), remaining),
            ).fetchall()
            selected_ids.extend(row[0] for row in rows)
    return selected_ids


def test_sample_questions_stays_fast_at_ninety_thousand_questions(
    large_content_database: LargeContentDatabase,
) -> None:
    repository = ContentRepository(large_content_database.path)
    difficulty = "medium"
    seed = 1_499_500_000
    exclude_ids = frozenset(
        {
            "q14995_medium",
            "q14997_medium",
            "q15003_medium",
            "q15008_medium",
        }
    )
    expected_ids = _expected_sample_ids(
        large_content_database.path,
        difficulty=difficulty,
        seed=seed,
        exclude_ids=exclude_ids,
        limit=30,
    )
    scene_to_top = {sub_key: top_key for top_key, sub_key in SCENE_KEYS}

    durations, result_sets = _measure_queries(
        lambda: repository.sample_questions(
            top_scene=None,
            sub_scene=None,
            difficulty=difficulty,
            limit=30,
            exclude_ids=exclude_ids,
            seed=seed,
        )
    )

    for questions in result_sets:
        assert len(questions) == 30
        assert [question.id for question in questions] == expected_ids
        assert not ({question.id for question in questions} & exclude_ids)
        assert all(question.difficulty == difficulty for question in questions)
        assert all(scene_to_top[question.sub_scene] == question.top_scene for question in questions)
        assert len({question.sub_scene for question in questions}) >= 24
    _assert_query_timings("sample_questions", durations)


def test_get_questions_by_ids_stays_fast_and_preserves_order(
    large_content_database: LargeContentDatabase,
) -> None:
    repository = ContentRepository(large_content_database.path)
    sentence_indexes = [0, 997, 1_994, *range(20_027, 20_000, -1)]
    requested_ids = [f"q{index:05d}_easy" for index in sentence_indexes]
    top_scene_keys = set(TOP_SCENE_KEYS)

    durations, result_sets = _measure_queries(
        lambda: repository.get_questions_by_ids(requested_ids)
    )

    for questions in result_sets:
        assert len(questions) == 30
        assert [question.id for question in questions] == requested_ids
        assert all(question.difficulty == "easy" for question in questions)
        assert all(question.top_scene in top_scene_keys for question in questions)
        assert questions[0].aliases == ("Example 0",)
        assert questions[1].aliases == ("Example 997",)
        assert questions[2].aliases == ("Example 1994",)
    _assert_query_timings("get_questions_by_ids", durations)
