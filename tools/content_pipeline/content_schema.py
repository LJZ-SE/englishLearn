from __future__ import annotations

import sqlite3

from tools.content_pipeline.scenes import SCENES, TOP_SCENES

CONTENT_SCHEMA_VERSION = 2

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


def initialize_content_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(CONTENT_SCHEMA_SQL)
    connection.executemany(
        "INSERT INTO top_scenes(key, label, sort_order) VALUES (?, ?, ?)",
        [
            (key, label, sort_order)
            for sort_order, (key, label) in enumerate(TOP_SCENES)
        ],
    )
    connection.executemany(
        """
        INSERT INTO sub_scenes(key, top_key, label, quota, sort_order)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (scene.key, scene.top_key, scene.label, scene.quota, sort_order)
            for sort_order, scene in enumerate(SCENES)
        ],
    )
    connection.execute(f"PRAGMA user_version = {CONTENT_SCHEMA_VERSION}")
