from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DictionaryEntry:
    word: str
    phonetic: str
    definition: str
    translation: str
    pos: str
    collins: int
    oxford: bool
    tags: tuple[str, ...]
    bnc: int
    frq: int
    exchange: str
    detail: str
    audio: str


class DictionaryRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        uri = f"{self.database_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        try:
            yield connection
        finally:
            connection.close()

    def lookup(self, term: str, *, limit: int = 12) -> tuple[DictionaryEntry, ...]:
        normalized = " ".join(term.split())
        if not normalized or limit <= 0:
            return ()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    word, phonetic, definition, translation, pos, collins,
                    oxford, tag, bnc, frq, exchange, detail, audio
                FROM entries
                WHERE word = ? COLLATE NOCASE
                ORDER BY id
                LIMIT ?
                """,
                (normalized, limit),
            ).fetchall()
            if not rows:
                rows = connection.execute(
                    """
                    SELECT
                        word, phonetic, definition, translation, pos, collins,
                        oxford, tag, bnc, frq, exchange, detail, audio
                    FROM entries
                    WHERE word LIKE ? ESCAPE '\\' COLLATE NOCASE
                    ORDER BY
                        CASE WHEN frq > 0 THEN 0 ELSE 1 END,
                        frq,
                        CASE WHEN bnc > 0 THEN 0 ELSE 1 END,
                        bnc,
                        word COLLATE NOCASE
                    LIMIT ?
                    """,
                    (_escaped_prefix(normalized) + "%", limit),
                ).fetchall()
        return tuple(_entry_from_row(row) for row in rows)

    def lookup_homophones(self, term: str, *, limit: int = 6) -> tuple[DictionaryEntry, ...]:
        """用离线词典音标找同音候选；目标词自身不作为消歧提示重复展示。"""
        normalized_term = " ".join(term.split())
        if not normalized_term or limit <= 0:
            return ()
        with self.connect() as connection:
            target_rows = connection.execute(
                """
                SELECT phonetic FROM entries
                WHERE word = ? COLLATE NOCASE AND trim(phonetic) <> ''
                ORDER BY id
                """,
                (normalized_term,),
            ).fetchall()
            phonetics = {
                _normalize_phonetic(str(row["phonetic"])) for row in target_rows
            }
            phonetics.discard("")
            if not phonetics:
                return ()
            normalized_phonetics = sorted(phonetics)
            placeholders = ", ".join("?" for _ in normalized_phonetics)
            rows = connection.execute(
                f"""
                SELECT
                    word, phonetic, definition, translation, pos, collins,
                    oxford, tag, bnc, frq, exchange, detail, audio
                FROM entries
                WHERE lower(trim(phonetic)) IN ({placeholders})
                  AND word <> ? COLLATE NOCASE
                ORDER BY id
                LIMIT ?
                """,
                (*normalized_phonetics, normalized_term, limit),
            ).fetchall()
        return tuple(_entry_from_row(row) for row in rows)


def _escaped_prefix(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _normalize_phonetic(value: str) -> str:
    return " ".join(value.casefold().split())


def _entry_from_row(row: sqlite3.Row) -> DictionaryEntry:
    return DictionaryEntry(
        word=str(row["word"]),
        phonetic=str(row["phonetic"]),
        definition=str(row["definition"]),
        translation=str(row["translation"]),
        pos=str(row["pos"]),
        collins=int(row["collins"]),
        oxford=bool(row["oxford"]),
        tags=tuple(str(row["tag"]).split()),
        bnc=int(row["bnc"]),
        frq=int(row["frq"]),
        exchange=str(row["exchange"]),
        detail=str(row["detail"]),
        audio=str(row["audio"]),
    )
