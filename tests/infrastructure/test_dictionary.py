from __future__ import annotations

import sqlite3
from pathlib import Path

from listening_cloze.infrastructure.dictionary import DictionaryRepository


def _dictionary_database(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY,
                word TEXT NOT NULL,
                phonetic TEXT NOT NULL DEFAULT '',
                definition TEXT NOT NULL DEFAULT '',
                translation TEXT NOT NULL DEFAULT '',
                pos TEXT NOT NULL DEFAULT '',
                collins INTEGER NOT NULL DEFAULT 0,
                oxford INTEGER NOT NULL DEFAULT 0,
                tag TEXT NOT NULL DEFAULT '',
                bnc INTEGER NOT NULL DEFAULT 0,
                frq INTEGER NOT NULL DEFAULT 0,
                exchange TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '',
                audio TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX idx_entries_word ON entries(word COLLATE NOCASE);
            """
        )
        connection.executemany(
            """
            INSERT INTO entries (
                word, phonetic, definition, translation, pos, collins, oxford,
                tag, bnc, frq, exchange, detail, audio
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    "take part in",
                    "teik pɑ:t in",
                    "participate in something",
                    "参加；参与",
                    "v:100",
                    3,
                    1,
                    "cet4 cet6",
                    1000,
                    800,
                    "",
                    "",
                    "",
                ),
                (
                    "listen",
                    "lisn",
                    "give attention to sound",
                    "听；倾听",
                    "v:100",
                    4,
                    1,
                    "zk gk cet4",
                    900,
                    700,
                    "p:listened/d:listened/i:listening/3:listens",
                    "",
                    "",
                ),
                (
                    "listener",
                    "lisənə",
                    "a person who listens",
                    "听众",
                    "n:100",
                    3,
                    0,
                    "",
                    4000,
                    3200,
                    "s:listeners",
                    "",
                    "",
                ),
            ),
        )
    return path


def test_dictionary_repository_finds_word_and_phrase_case_insensitively(
    tmp_path: Path,
) -> None:
    repository = DictionaryRepository(_dictionary_database(tmp_path / "dictionary.db"))

    phrase = repository.lookup("  TAKE   PART IN ")
    word = repository.lookup("Listen")

    assert len(phrase) == 1
    assert phrase[0].word == "take part in"
    assert phrase[0].translation == "参加；参与"
    assert phrase[0].tags == ("cet4", "cet6")
    assert word[0].exchange.startswith("p:listened")


def test_dictionary_repository_returns_frequency_ordered_prefix_suggestions(
    tmp_path: Path,
) -> None:
    repository = DictionaryRepository(_dictionary_database(tmp_path / "dictionary.db"))

    results = repository.lookup("liste")

    assert [entry.word for entry in results] == ["listen", "listener"]


def test_dictionary_repository_rejects_empty_lookup(tmp_path: Path) -> None:
    repository = DictionaryRepository(_dictionary_database(tmp_path / "dictionary.db"))

    assert repository.lookup("   ") == ()
