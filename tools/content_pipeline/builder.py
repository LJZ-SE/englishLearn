from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from tools.content_pipeline.candidates import generate_variants
from tools.content_pipeline.categorize import CATEGORIES, CategoryClassifier
from tools.content_pipeline.clean import clean_sentence, normalized_hash, rejection_reason
from tools.content_pipeline.models import BuildResult, CollectedSentence, QuestionVariant
from tools.content_pipeline.selection import is_near_duplicate


class BuildError(RuntimeError):
    pass


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE sentences (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    translation_zh TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('daily', 'exam', 'movies', 'news_podcasts')),
    source_url TEXT NOT NULL,
    source_name TEXT NOT NULL,
    license_name TEXT NOT NULL,
    license_url TEXT NOT NULL,
    source_author TEXT NOT NULL,
    normalized_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE question_variants (
    id TEXT PRIMARY KEY,
    sentence_id TEXT NOT NULL REFERENCES sentences(id),
    difficulty TEXT NOT NULL CHECK(difficulty IN ('easy', 'medium', 'hard')),
    answer_start INTEGER NOT NULL,
    answer_end INTEGER NOT NULL,
    canonical_answer TEXT NOT NULL,
    answer_word_count INTEGER NOT NULL,
    difficulty_score REAL NOT NULL,
    rationale TEXT NOT NULL,
    UNIQUE(sentence_id, difficulty),
    UNIQUE(sentence_id, canonical_answer)
);
CREATE TABLE aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_variant_id TEXT NOT NULL REFERENCES question_variants(id),
    alias TEXT NOT NULL,
    UNIQUE(question_variant_id, alias)
);
CREATE INDEX idx_sentences_category ON sentences(category);
CREATE INDEX idx_variants_difficulty ON question_variants(difficulty);
"""


def _prepare(
    inputs: list[CollectedSentence],
) -> tuple[
    dict[str, list[tuple[CollectedSentence, str, str, tuple[QuestionVariant, ...]]]],
    Counter[str],
]:
    classifier = CategoryClassifier()
    accepted: dict[str, list[tuple[CollectedSentence, str, str, tuple[QuestionVariant, ...]]]] = (
        defaultdict(list)
    )
    rejected: Counter[str] = Counter()
    seen: set[str] = set()
    seen_texts: list[str] = []
    for item in inputs:
        text = clean_sentence(item.text)
        reason = rejection_reason(text)
        if reason:
            rejected[reason] += 1
            continue
        digest = normalized_hash(text)
        if digest in seen:
            rejected["duplicate"] += 1
            continue
        if any(is_near_duplicate(text, previous) for previous in seen_texts):
            rejected["near_duplicate"] += 1
            continue
        try:
            variants = generate_variants(text)
        except ValueError:
            rejected["insufficient_variants"] += 1
            continue
        category = classifier.classify(item)
        accepted[category].append((item, text, digest, variants))
        seen.add(digest)
        seen_texts.append(text)
    return accepted, rejected


def _validate_variant(text: str, variant: QuestionVariant) -> None:
    if text[variant.answer_start : variant.answer_end] != variant.canonical_answer:
        raise BuildError("答案区间无法精确填回原句")
    if variant.blank_count != len(variant.canonical_answer.split()):
        raise BuildError("blank_count 与规范答案单词数不一致")


def build_database(
    inputs: list[CollectedSentence],
    database_path: Path,
    report_path: Path,
    sources_path: Path,
) -> BuildResult:
    accepted, rejected = _prepare(inputs)
    shortages = {category: 75 - len(accepted[category]) for category in CATEGORIES}
    shortages = {category: count for category, count in shortages.items() if count > 0}
    if shortages:
        raise BuildError(f"每类 75 句门禁未满足: {shortages}")

    chosen = {category: accepted[category][:75] for category in CATEGORIES}
    database_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    sources_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = database_path.with_suffix(database_path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()

    phrase_lengths: Counter[int] = Counter()
    source_counts: Counter[tuple[str, str, str, str, str]] = Counter()
    with sqlite3.connect(temporary) as connection:
        connection.executescript(_SCHEMA)
        sentence_number = 0
        for category in CATEGORIES:
            for item, text, digest, variants in chosen[category]:
                sentence_number += 1
                sentence_id = f"s{sentence_number:04d}"
                connection.execute(
                    "INSERT INTO sentences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        sentence_id,
                        text,
                        item.translation_zh,
                        category,
                        item.source_url,
                        item.source_name,
                        item.license_name,
                        item.license_url,
                        item.source_author,
                        digest,
                    ),
                )
                previous_score = float("-inf")
                answers: set[str] = set()
                for variant in variants:
                    _validate_variant(text, variant)
                    if variant.score <= previous_score:
                        raise BuildError("三个版本的难度分值必须严格递增")
                    if variant.canonical_answer.casefold() in answers:
                        raise BuildError("三个版本的答案必须不同")
                    previous_score = variant.score
                    answers.add(variant.canonical_answer.casefold())
                    variant_id = f"{sentence_id}-{variant.difficulty}"
                    connection.execute(
                        "INSERT INTO question_variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            variant_id,
                            sentence_id,
                            variant.difficulty,
                            variant.answer_start,
                            variant.answer_end,
                            variant.canonical_answer,
                            variant.blank_count,
                            variant.score,
                            variant.rationale,
                        ),
                    )
                    for alias in variant.aliases:
                        connection.execute(
                            "INSERT INTO aliases(question_variant_id, alias) VALUES (?, ?)",
                            (variant_id, alias),
                        )
                    phrase_lengths[variant.blank_count] += 1
                source_counts[
                    (
                        item.source_name,
                        item.source_url,
                        item.license_name,
                        item.license_url,
                        item.source_author,
                    )
                ] += 1
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    temporary.replace(database_path)

    category_counts = {category: 75 for category in CATEGORIES}
    report = {
        "gate_status": "passed",
        "sentence_count": 300,
        "variant_count": 900,
        "category_distribution": category_counts,
        "difficulty_distribution": {"easy": 300, "medium": 300, "hard": 300},
        "answer_word_count_distribution": {
            str(length): phrase_lengths[length] for length in sorted(phrase_lengths)
        },
        "duplicate_rate": rejected["duplicate"] / max(1, len(inputs)),
        "rejected_count": sum(rejected.values()),
        "rejection_reasons": dict(sorted(rejected.items())),
        "source_distribution": {
            name: sum(count for key, count in source_counts.items() if key[0] == name)
            for name in sorted({key[0] for key in source_counts})
        },
    }
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    source_manifest = [
        {
            "source_name": key[0],
            "source_url": key[1],
            "license_name": key[2],
            "license_url": key[3],
            "source_author": key[4],
            "sentence_count": count,
        }
        for key, count in sorted(source_counts.items())
    ]
    sources_path.write_text(
        json.dumps(source_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return BuildResult(300, 900, sum(rejected.values()))
