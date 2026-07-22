import json
import sqlite3
from pathlib import Path

import pytest

from listening_cloze.infrastructure.database import (
    CURRENT_SCHEMA_VERSION,
    MIGRATIONS,
    ContentRepository,
    MigrationError,
    UserRepository,
)


def create_content_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE sentences (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                translation_zh TEXT NOT NULL,
                category TEXT NOT NULL,
                source_url TEXT NOT NULL,
                normalized_hash TEXT NOT NULL
            );
            CREATE TABLE question_variants (
                id TEXT PRIMARY KEY,
                sentence_id TEXT NOT NULL REFERENCES sentences(id),
                difficulty TEXT NOT NULL,
                answer_start INTEGER NOT NULL,
                answer_end INTEGER NOT NULL,
                canonical_answer TEXT NOT NULL,
                answer_word_count INTEGER NOT NULL,
                difficulty_score REAL NOT NULL,
                rationale TEXT NOT NULL
            );
            CREATE TABLE aliases (
                id INTEGER PRIMARY KEY,
                question_variant_id TEXT NOT NULL REFERENCES question_variants(id),
                alias TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO sentences VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    "s1",
                    "We take part in the meeting.",
                    "我们参加这场会议。",
                    "daily",
                    "https://a.test/1",
                    "h1",
                ),
                (
                    "s2",
                    "Markets recovered after lunch.",
                    "午后市场回升。",
                    "news",
                    "https://a.test/2",
                    "h2",
                ),
            ],
        )
        connection.executemany(
            "INSERT INTO question_variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("q1", "s1", "easy", 3, 7, "take", 1, 1.0, "高频动词"),
                ("q2", "s1", "hard", 3, 15, "take part in", 3, 3.0, "固定短语"),
                ("q3", "s2", "hard", 8, 17, "recovered", 1, 2.8, "低频动词"),
            ],
        )
        connection.executemany(
            "INSERT INTO aliases(question_variant_id, alias) VALUES (?, ?)",
            [("q2", "participate in"), ("q2", "join in")],
        )


def create_legacy_user_database(path: Path, marker: str = "original") -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE legacy_marker(value TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_marker VALUES (?)", (marker,))
        connection.execute("PRAGMA user_version = 0")


def test_content_repository_lists_by_category_and_difficulty_with_aliases(tmp_path: Path) -> None:
    database = tmp_path / "content.db"
    create_content_database(database)
    repository = ContentRepository(database)

    questions = repository.list_questions(category="daily", difficulty="hard")

    assert len(questions) == 1
    question = questions[0]
    assert question.id == "q2"
    assert question.sentence_id == "s1"
    assert question.sentence_text == "We take part in the meeting."
    assert question.translation_zh == "我们参加这场会议。"
    assert question.category == "daily"
    assert question.difficulty == "hard"
    assert question.canonical_answer == "take part in"
    assert question.answer_word_count == 3
    assert question.aliases == ("join in", "participate in")


def test_content_repository_supports_all_categories_and_is_read_only(tmp_path: Path) -> None:
    database = tmp_path / "content.db"
    create_content_database(database)
    repository = ContentRepository(database)

    assert [item.id for item in repository.list_questions(difficulty="hard")] == ["q2", "q3"]
    assert [item.id for item in repository.list_questions(category="all")] == ["q1", "q2", "q3"]

    with repository.connect() as connection:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            connection.execute("DELETE FROM sentences")


def test_new_user_database_has_current_schema_version(tmp_path: Path) -> None:
    database = tmp_path / "user.db"

    repository = UserRepository(database)

    assert repository.schema_version == CURRENT_SCHEMA_VERSION
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"settings", "question_progress", "sessions"} <= tables


def test_settings_round_trip_json_values_across_repository_instances(tmp_path: Path) -> None:
    database = tmp_path / "user.db"
    repository = UserRepository(database)

    repository.set_setting("playback", {"rate": 0.8, "animation": True})

    reopened = UserRepository(database)
    assert reopened.get_setting("playback") == {"rate": 0.8, "animation": True}
    assert reopened.get_setting("missing", "fallback") == "fallback"


def test_first_result_is_immediately_committed_and_never_overwritten(tmp_path: Path) -> None:
    database = tmp_path / "user.db"
    repository = UserRepository(database)

    first = repository.record_attempt("q1", is_correct=False)
    persisted = UserRepository(database).get_question_progress("q1")
    second = repository.record_attempt("q1", is_correct=True)

    assert first.first_correct is False
    assert persisted is not None
    assert persisted.first_correct is False
    assert persisted.attempt_count == 1
    assert second.first_correct is False
    assert second.attempt_count == 2


def test_replay_and_view_answer_have_independent_persistent_counters(tmp_path: Path) -> None:
    database = tmp_path / "user.db"
    repository = UserRepository(database)

    repository.record_replay("q2")
    repository.record_replay("q2")
    progress = repository.record_view_answer("q2")
    progress = repository.record_view_answer("q2")

    assert progress.first_correct is False
    assert progress.attempt_count == 0
    assert progress.replay_count == 2
    assert progress.view_answer_count == 2
    assert UserRepository(database).get_question_progress("q2") == progress


def test_progress_list_and_learning_reset_keep_user_settings(tmp_path: Path) -> None:
    repository = UserRepository(tmp_path / "user.db")
    repository.set_setting("volume", 0.65)
    repository.record_attempt("q2", is_correct=False)
    repository.record_attempt("q1", is_correct=True)
    repository.save_session("unfinished", mode="quantitative", state={"position": 0})

    assert [item.question_id for item in repository.list_question_progress()] == ["q1", "q2"]

    repository.reset_learning_records()

    assert repository.list_question_progress() == []
    assert repository.load_unfinished_session() is None
    assert repository.get_setting("volume") == 0.65


def test_learning_summary_reports_practiced_pending_and_latest_session(tmp_path: Path) -> None:
    repository = UserRepository(tmp_path / "user.db")
    repository.record_attempt("correct", is_correct=True)
    repository.record_attempt("pending", is_correct=False)
    repository.record_replay("not-yet-scored")
    repository.save_session("latest", mode="endless", state={"position": 3})

    summary = repository.get_learning_summary()

    assert summary["practiced"] == 2
    assert summary["pending"] == 1
    assert summary["latest_mode"] == "endless"
    assert summary["latest_completed"] is False


@pytest.mark.parametrize(
    ("mode", "state"),
    [
        (
            "quantitative",
            {"question_ids": ["q1", "q2"], "position": 1, "target_count": 10},
        ),
        (
            "endless",
            {
                "difficulty": "medium",
                "correct_streak": 3,
                "wrong_streak": 0,
                "statistics": {"correct": 8, "wrong": 2},
            },
        ),
    ],
)
def test_unfinished_session_json_state_can_be_restored(
    tmp_path: Path,
    mode: str,
    state: dict[str, object],
) -> None:
    database = tmp_path / "user.db"
    repository = UserRepository(database)

    saved = repository.save_session(f"session-{mode}", mode=mode, state=state)
    restored = UserRepository(database).load_unfinished_session(mode=mode)

    assert restored == saved
    assert restored is not None
    assert restored.state == state


def test_completed_sessions_are_not_offered_for_resume(tmp_path: Path) -> None:
    repository = UserRepository(tmp_path / "user.db")
    repository.save_session("finished", mode="quantitative", state={"position": 10})

    repository.complete_session("finished")

    assert repository.load_session("finished").completed is True
    assert repository.load_unfinished_session(mode="quantitative") is None


def test_migration_creates_backup_and_keeps_only_three_newest(tmp_path: Path) -> None:
    database = tmp_path / "user.db"
    backups = tmp_path / "backups"

    for index in range(5):
        if database.exists():
            database.unlink()
        create_legacy_user_database(database, marker=f"version-{index}")
        UserRepository(database, backups_dir=backups)

    backup_files = sorted(backups.glob("user-*.db.bak"))
    assert len(backup_files) == 3
    markers = []
    for backup in backup_files:
        with sqlite3.connect(backup) as connection:
            markers.append(connection.execute("SELECT value FROM legacy_marker").fetchone()[0])
    assert markers == ["version-2", "version-3", "version-4"]


def test_failed_migration_rolls_back_original_and_keeps_backup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "user.db"
    backups = tmp_path / "backups"
    create_legacy_user_database(database)

    def failing_migration(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE should_be_rolled_back(value TEXT)")
        raise RuntimeError("模拟迁移故障")

    monkeypatch.setitem(MIGRATIONS, 0, failing_migration)

    with pytest.raises(MigrationError, match="模拟迁移故障") as caught:
        UserRepository(database, backups_dir=backups)

    assert caught.value.backup_path.exists()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT value FROM legacy_marker").fetchone()[0] == "original"
        rolled_back = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'should_be_rolled_back'"
        ).fetchone()
    assert rolled_back is None
    with sqlite3.connect(caught.value.backup_path) as connection:
        assert connection.execute("SELECT value FROM legacy_marker").fetchone()[0] == "original"


def test_session_state_is_stored_as_json_not_pickle(tmp_path: Path) -> None:
    database = tmp_path / "user.db"
    repository = UserRepository(database)
    repository.save_session("json-session", mode="endless", state={"difficulty": "easy"})

    with sqlite3.connect(database) as connection:
        raw_state = connection.execute(
            "SELECT state_json FROM sessions WHERE session_id = ?",
            ("json-session",),
        ).fetchone()[0]

    assert json.loads(raw_state) == {"difficulty": "easy"}
