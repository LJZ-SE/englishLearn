from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CURRENT_SCHEMA_VERSION = 1
VALID_SESSION_MODES = frozenset({"quantitative", "endless"})


@dataclass(frozen=True, slots=True)
class ContentQuestion:
    id: str
    sentence_id: str
    sentence_text: str
    category: str
    source_url: str
    normalized_hash: str
    difficulty: str
    answer_start: int
    answer_end: int
    canonical_answer: str
    answer_word_count: int
    difficulty_score: float
    rationale: str
    aliases: tuple[str, ...]
    translation_zh: str = ""


@dataclass(frozen=True, slots=True)
class QuestionProgress:
    question_id: str
    first_correct: bool | None
    attempt_count: int
    replay_count: int
    view_answer_count: int
    first_answered_at: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    mode: str
    state: dict[str, Any]
    completed: bool
    created_at: str
    updated_at: str


class MigrationError(RuntimeError):
    def __init__(
        self,
        database_path: Path,
        backup_path: Path | None,
        from_version: int,
        to_version: int,
        cause: Exception,
    ) -> None:
        self.database_path = database_path
        self.backup_path = backup_path
        self.from_version = from_version
        self.to_version = to_version
        self.cause = cause
        super().__init__(f"数据库从版本 {from_version} 迁移到 {to_version} 失败: {cause}")


class SchemaVersionError(RuntimeError):
    pass


class ContentRepository:
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

    def list_questions(
        self,
        *,
        category: str | None = None,
        difficulty: str | None = None,
    ) -> list[ContentQuestion]:
        clauses: list[str] = []
        parameters: list[str] = []
        if category and category != "all":
            clauses.append("s.category = ?")
            parameters.append(category)
        if difficulty and difficulty != "all":
            clauses.append("q.difficulty = ?")
            parameters.append(difficulty)

        where_clause = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            "SELECT q.id, q.sentence_id, s.text AS sentence_text, s.translation_zh, s.category, "
            "s.source_url, s.normalized_hash, q.difficulty, q.answer_start, "
            "q.answer_end, q.canonical_answer, q.answer_word_count, "
            "q.difficulty_score, q.rationale "
            "FROM question_variants AS q "
            "JOIN sentences AS s ON s.id = q.sentence_id"
            f"{where_clause} ORDER BY q.id"
        )

        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
            return [self._question_from_row(connection, row) for row in rows]

    @staticmethod
    def _question_from_row(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> ContentQuestion:
        aliases = tuple(
            alias_row[0]
            for alias_row in connection.execute(
                "SELECT alias FROM aliases WHERE question_variant_id = ? ORDER BY alias",
                (row["id"],),
            )
        )
        return ContentQuestion(
            id=row["id"],
            sentence_id=row["sentence_id"],
            sentence_text=row["sentence_text"],
            translation_zh=row["translation_zh"],
            category=row["category"],
            source_url=row["source_url"],
            normalized_hash=row["normalized_hash"],
            difficulty=row["difficulty"],
            answer_start=row["answer_start"],
            answer_end=row["answer_end"],
            canonical_answer=row["canonical_answer"],
            answer_word_count=row["answer_word_count"],
            difficulty_score=row["difficulty_score"],
            rationale=row["rationale"],
            aliases=aliases,
        )


def _create_schema_v1(connection: sqlite3.Connection) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS question_progress (
            question_id TEXT PRIMARY KEY,
            first_correct INTEGER CHECK(first_correct IN (0, 1)),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
            replay_count INTEGER NOT NULL DEFAULT 0 CHECK(replay_count >= 0),
            view_answer_count INTEGER NOT NULL DEFAULT 0 CHECK(view_answer_count >= 0),
            first_answered_at TEXT,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL CHECK(mode IN ('quantitative', 'endless')),
            state_json TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0 CHECK(completed IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_sessions_resume "
        "ON sessions(completed, mode, updated_at DESC)",
    )
    for statement in statements:
        connection.execute(statement)


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {0: _create_schema_v1}


class UserRepository:
    def __init__(
        self,
        database_path: str | Path,
        *,
        backups_dir: str | Path | None = None,
        migrations: Mapping[int, Callable[[sqlite3.Connection], None]] | None = None,
        target_version: int = CURRENT_SCHEMA_VERSION,
    ) -> None:
        self.database_path = Path(database_path)
        self.backups_dir = (
            Path(backups_dir) if backups_dir is not None else self.database_path.parent / "backups"
        )
        self._migrations = MIGRATIONS if migrations is None else migrations
        self._target_version = target_version
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._prepare_database()

    @property
    def schema_version(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def set_setting(self, key: str, value: Any) -> None:
        value_json = _encode_json(value)
        now = _utc_now()
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO settings(key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, value_json, now),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = ?",
                (key,),
            ).fetchone()
        return default if row is None else json.loads(row[0])

    def record_attempt(self, question_id: str, *, is_correct: bool) -> QuestionProgress:
        now = _utc_now()
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO question_progress(
                    question_id, first_correct, attempt_count, replay_count,
                    view_answer_count, first_answered_at, updated_at
                ) VALUES (?, ?, 1, 0, 0, ?, ?)
                ON CONFLICT(question_id) DO UPDATE SET
                    first_correct = COALESCE(
                        question_progress.first_correct,
                        excluded.first_correct
                    ),
                    attempt_count = question_progress.attempt_count + 1,
                    first_answered_at = COALESCE(
                        question_progress.first_answered_at,
                        excluded.first_answered_at
                    ),
                    updated_at = excluded.updated_at
                """,
                (question_id, int(is_correct), now, now),
            )
            return self._get_question_progress(connection, question_id)

    def record_replay(self, question_id: str) -> QuestionProgress:
        now = _utc_now()
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO question_progress(
                    question_id, first_correct, attempt_count, replay_count,
                    view_answer_count, first_answered_at, updated_at
                ) VALUES (?, NULL, 0, 1, 0, NULL, ?)
                ON CONFLICT(question_id) DO UPDATE SET
                    replay_count = question_progress.replay_count + 1,
                    updated_at = excluded.updated_at
                """,
                (question_id, now),
            )
            return self._get_question_progress(connection, question_id)

    def record_view_answer(self, question_id: str) -> QuestionProgress:
        now = _utc_now()
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO question_progress(
                    question_id, first_correct, attempt_count, replay_count,
                    view_answer_count, first_answered_at, updated_at
                ) VALUES (?, 0, 0, 0, 1, ?, ?)
                ON CONFLICT(question_id) DO UPDATE SET
                    first_correct = COALESCE(question_progress.first_correct, 0),
                    view_answer_count = question_progress.view_answer_count + 1,
                    first_answered_at = COALESCE(question_progress.first_answered_at, ?),
                    updated_at = excluded.updated_at
                """,
                (question_id, now, now, now),
            )
            return self._get_question_progress(connection, question_id)

    def get_question_progress(self, question_id: str) -> QuestionProgress | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM question_progress WHERE question_id = ?",
                (question_id,),
            ).fetchone()
        return None if row is None else _progress_from_row(row)

    def list_question_progress(self) -> list[QuestionProgress]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM question_progress ORDER BY question_id"
            ).fetchall()
        return [_progress_from_row(row) for row in rows]

    def reset_learning_records(self) -> None:
        with self._connection() as connection, connection:
            connection.execute("DELETE FROM question_progress")
            connection.execute("DELETE FROM sessions")

    def get_learning_summary(self) -> dict[str, Any]:
        with self._connection() as connection:
            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN first_correct IS NOT NULL THEN 1 ELSE 0 END) AS practiced,
                    SUM(CASE WHEN first_correct = 0 THEN 1 ELSE 0 END) AS pending
                FROM question_progress
                """
            ).fetchone()
            latest = connection.execute(
                "SELECT mode, completed, updated_at FROM sessions "
                "ORDER BY updated_at DESC, session_id DESC LIMIT 1"
            ).fetchone()
        return {
            "practiced": int(counts["practiced"] or 0),
            "pending": int(counts["pending"] or 0),
            "latest_mode": latest["mode"] if latest is not None else None,
            "latest_completed": bool(latest["completed"]) if latest is not None else None,
            "latest_updated_at": latest["updated_at"] if latest is not None else None,
        }

    def save_session(
        self,
        session_id: str,
        *,
        mode: str,
        state: Mapping[str, Any],
        completed: bool = False,
    ) -> SessionRecord:
        if mode not in VALID_SESSION_MODES:
            raise ValueError(f"不支持的练习模式: {mode}")
        state_json = _encode_json(dict(state))
        now = _utc_now()
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO sessions(
                    session_id, mode, state_json, completed, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    mode = excluded.mode,
                    state_json = excluded.state_json,
                    completed = excluded.completed,
                    updated_at = excluded.updated_at
                """,
                (session_id, mode, state_json, int(completed), now, now),
            )
            return self._get_session(connection, session_id)

    def load_session(self, session_id: str) -> SessionRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return None if row is None else _session_from_row(row)

    def load_unfinished_session(self, *, mode: str | None = None) -> SessionRecord | None:
        if mode is not None and mode not in VALID_SESSION_MODES:
            raise ValueError(f"不支持的练习模式: {mode}")
        query = "SELECT * FROM sessions WHERE completed = 0"
        parameters: tuple[str, ...] = ()
        if mode is not None:
            query += " AND mode = ?"
            parameters = (mode,)
        query += " ORDER BY updated_at DESC, session_id DESC LIMIT 1"
        with self._connection() as connection:
            row = connection.execute(query, parameters).fetchone()
        return None if row is None else _session_from_row(row)

    def complete_session(self, session_id: str) -> SessionRecord:
        now = _utc_now()
        with self._connection() as connection, connection:
            cursor = connection.execute(
                "UPDATE sessions SET completed = 1, updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(session_id)
            return self._get_session(connection, session_id)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    def _prepare_database(self) -> None:
        database_existed = self.database_path.exists() and self.database_path.stat().st_size > 0
        with self._connection() as connection:
            from_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if from_version > self._target_version:
            raise SchemaVersionError(
                f"数据库版本 {from_version} 高于程序支持版本 {self._target_version}"
            )
        if from_version == self._target_version:
            return

        backup_path = self._create_backup() if database_existed else None
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    version = from_version
                    while version < self._target_version:
                        migration = self._migrations.get(version)
                        if migration is None:
                            raise RuntimeError(f"缺少从版本 {version} 开始的迁移")
                        migration(connection)
                        version += 1
                        connection.execute(f"PRAGMA user_version = {version}")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except Exception as error:
            raise MigrationError(
                self.database_path,
                backup_path,
                from_version,
                self._target_version,
                error,
            ) from error

    def _create_backup(self) -> Path:
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        backup_path = self.backups_dir / f"user-{time.time_ns():020d}.db.bak"
        with (
            closing(sqlite3.connect(self.database_path)) as source,
            closing(sqlite3.connect(backup_path)) as target,
        ):
            source.backup(target)

        backup_files = sorted(self.backups_dir.glob("user-*.db.bak"))
        for obsolete_backup in backup_files[:-3]:
            obsolete_backup.unlink()
        return backup_path

    @staticmethod
    def _get_question_progress(
        connection: sqlite3.Connection,
        question_id: str,
    ) -> QuestionProgress:
        row = connection.execute(
            "SELECT * FROM question_progress WHERE question_id = ?",
            (question_id,),
        ).fetchone()
        if row is None:
            raise KeyError(question_id)
        return _progress_from_row(row)

    @staticmethod
    def _get_session(connection: sqlite3.Connection, session_id: str) -> SessionRecord:
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return _session_from_row(row)


def _progress_from_row(row: sqlite3.Row) -> QuestionProgress:
    raw_first_correct = row["first_correct"]
    return QuestionProgress(
        question_id=row["question_id"],
        first_correct=None if raw_first_correct is None else bool(raw_first_correct),
        attempt_count=row["attempt_count"],
        replay_count=row["replay_count"],
        view_answer_count=row["view_answer_count"],
        first_answered_at=row["first_answered_at"],
        updated_at=row["updated_at"],
    )


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        session_id=row["session_id"],
        mode=row["mode"],
        state=json.loads(row["state_json"]),
        completed=bool(row["completed"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")
