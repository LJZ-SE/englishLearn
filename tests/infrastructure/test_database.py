import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import listening_cloze.infrastructure.database as database_module
from listening_cloze.infrastructure.database import (
    CURRENT_SCHEMA_VERSION,
    MIGRATIONS,
    ContentRepository,
    MigrationError,
    SceneMetadata,
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


def create_hierarchical_content_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
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
                difficulty TEXT NOT NULL,
                answer_start INTEGER NOT NULL,
                answer_end INTEGER NOT NULL,
                canonical_answer TEXT NOT NULL,
                answer_word_count INTEGER NOT NULL,
                difficulty_score REAL NOT NULL,
                rationale TEXT NOT NULL
            );
            CREATE TABLE aliases(
                id INTEGER PRIMARY KEY,
                question_variant_id TEXT NOT NULL REFERENCES question_variants(id),
                alias TEXT NOT NULL
            );
            CREATE INDEX idx_sentences_scene_random
                ON sentences(sub_scene_key, random_key, id);
            CREATE UNIQUE INDEX idx_variants_sentence_difficulty
                ON question_variants(sentence_id, difficulty);
            CREATE INDEX idx_aliases_question ON aliases(question_variant_id);
            """
        )
        connection.executemany(
            "INSERT INTO top_scenes VALUES (?, ?, ?)",
            [("daily", "日常生活", 0), ("travel", "出行旅行", 1)],
        )
        connection.executemany(
            "INSERT INTO sub_scenes VALUES (?, ?, ?, ?, ?)",
            [
                ("daily_home", "daily", "家庭家务", 1, 0),
                ("travel_transport", "travel", "交通通勤", 2, 0),
                ("travel_hotel", "travel", "酒店住宿", 12, 1),
            ],
        )
        sentence_rows = []
        variant_rows = []
        for index in range(1, 16):
            sub_scene = (
                "daily_home"
                if index == 15
                else "travel_transport"
                if index >= 13
                else "travel_hotel"
            )
            sentence_rows.append(
                (
                    f"s{index}",
                    f"Example sentence number {index}.",
                    f"示例句子 {index}。",
                    sub_scene,
                    f"https://a.test/{index}",
                    "fixture",
                    "tester",
                    str(index),
                    "test",
                    "https://a.test/license",
                    f"hash-{index}",
                    index * 100,
                )
            )
            variant_rows.append(
                (
                    f"q{index}",
                    f"s{index}",
                    "easy",
                    0,
                    7,
                    "Example",
                    1,
                    1.0,
                    "测试题",
                )
            )
        connection.executemany(
            "INSERT INTO sentences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", sentence_rows
        )
        connection.executemany(
            "INSERT INTO question_variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            variant_rows,
        )
        connection.executemany(
            "INSERT INTO aliases(question_variant_id, alias) VALUES (?, ?)",
            [("q1", "Sample"), ("q3", "Illustration")],
        )


def expand_hierarchical_scene_count(
    path: Path,
    *,
    top_scene: str | None,
    target_count: int,
) -> None:
    with sqlite3.connect(path) as connection:
        where = " WHERE top_key = ?" if top_scene is not None else ""
        parameters = (top_scene,) if top_scene is not None else ()
        existing = connection.execute(
            f"SELECT COUNT(*) FROM sub_scenes{where}", parameters
        ).fetchone()[0]
        connection.executemany(
            "INSERT INTO sub_scenes VALUES (?, 'travel', ?, 0, ?)",
            [
                (f"travel_extra_{index}", f"扩展场景 {index}", 100 + index)
                for index in range(target_count - existing)
            ],
        )


def create_legacy_user_database(path: Path, marker: str = "original") -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
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


def test_repository_samples_small_filtered_batch_without_full_scan(tmp_path: Path) -> None:
    database = tmp_path / "content-v2.db"
    create_hierarchical_content_database(database)

    rows = ContentRepository(database).sample_questions(
        top_scene="travel",
        sub_scene="travel_hotel",
        difficulty="easy",
        limit=10,
        exclude_ids=frozenset(),
        seed=450,
    )

    assert len(rows) == 10
    assert [row.id for row in rows[:2]] == ["q5", "q6"]
    assert [row.id for row in rows[-2:]] == ["q1", "q2"]
    assert all(row.top_scene == "travel" and row.sub_scene == "travel_hotel" for row in rows)


def test_repository_restores_requested_ids_in_requested_order(tmp_path: Path) -> None:
    database = tmp_path / "content-v2.db"
    create_hierarchical_content_database(database)

    rows = ContentRepository(database).get_questions_by_ids(["q3", "q1"])

    assert [row.id for row in rows] == ["q3", "q1"]
    assert rows[0].aliases == ("Illustration",)


def test_repository_lists_hierarchical_scene_metadata_in_database_order(tmp_path: Path) -> None:
    database = tmp_path / "content-v2.db"
    create_hierarchical_content_database(database)

    scenes = ContentRepository(database).list_scenes()

    assert scenes == [
        SceneMetadata(
            key="daily",
            label="日常生活",
            children=(SceneMetadata(key="daily_home", label="家庭家务"),),
        ),
        SceneMetadata(
            key="travel",
            label="出行旅行",
            children=(
                SceneMetadata(key="travel_transport", label="交通通勤"),
                SceneMetadata(key="travel_hotel", label="酒店住宿"),
            ),
        ),
    ]


def test_repository_samples_across_top_scene_and_excludes_requested_ids(tmp_path: Path) -> None:
    database = tmp_path / "content-v2.db"
    create_hierarchical_content_database(database)

    rows = ContentRepository(database).sample_questions(
        top_scene="travel",
        sub_scene=None,
        difficulty="easy",
        limit=5,
        exclude_ids=frozenset({"q12", "q13"}),
        seed=1150,
    )

    assert [row.id for row in rows] == ["q14", "q1", "q2", "q3", "q4"]
    assert {row.sub_scene for row in rows} == {"travel_hotel", "travel_transport"}


def test_repository_returns_empty_results_without_relaxing_filters(tmp_path: Path) -> None:
    database = tmp_path / "content-v2.db"
    create_hierarchical_content_database(database)
    repository = ContentRepository(database)

    assert (
        repository.sample_questions(
            top_scene="daily",
            sub_scene="daily_home",
            difficulty="hard",
            limit=10,
            exclude_ids=frozenset(),
            seed=0,
        )
        == []
    )
    assert (
        repository.sample_questions(
            top_scene=None,
            sub_scene=None,
            difficulty="easy",
            limit=0,
            exclude_ids=frozenset(),
            seed=0,
        )
        == []
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"difficulty": "expert"}, "无效难度"),
        ({"limit": -1}, "抽题数量"),
        ({"limit": True}, "抽题数量"),
        ({"seed": -1}, "随机种子"),
        ({"seed": 1 << 63}, "随机种子"),
        ({"top_scene": None, "sub_scene": "travel_hotel"}, "同时指定大类"),
        ({"exclude_ids": frozenset({""})}, "排除题目 ID"),
    ],
)
def test_repository_rejects_invalid_sample_inputs(
    tmp_path: Path,
    overrides: dict[str, object],
    message: str,
) -> None:
    database = tmp_path / "content-v2.db"
    create_hierarchical_content_database(database)
    arguments: dict[str, object] = {
        "top_scene": "travel",
        "sub_scene": "travel_hotel",
        "difficulty": "easy",
        "limit": 3,
        "exclude_ids": frozenset(),
        "seed": 0,
    }
    arguments.update(overrides)

    with pytest.raises(ValueError, match=message):
        ContentRepository(database).sample_questions(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("top_scene", "sub_scene"),
    [("missing", None), ("travel", "daily_home")],
)
def test_repository_rejects_unknown_or_mismatched_scenes(
    tmp_path: Path,
    top_scene: str,
    sub_scene: str | None,
) -> None:
    database = tmp_path / "content-v2.db"
    create_hierarchical_content_database(database)

    with pytest.raises(ValueError, match="场景不存在"):
        ContentRepository(database).sample_questions(
            top_scene=top_scene,
            sub_scene=sub_scene,
            difficulty="easy",
            limit=3,
            exclude_ids=frozenset(),
            seed=0,
        )


def test_repository_restores_duplicate_ids_and_omits_missing_ids(tmp_path: Path) -> None:
    database = tmp_path / "content-v2.db"
    create_hierarchical_content_database(database)
    repository = ContentRepository(database)

    rows = repository.get_questions_by_ids(["q3", "missing", "q1", "q3"])

    assert [row.id for row in rows] == ["q3", "q1", "q3"]
    assert repository.get_questions_by_ids([]) == []
    with pytest.raises(ValueError, match="非空字符串"):
        repository.get_questions_by_ids([""])


@pytest.mark.parametrize("exclude_ids", [frozenset(), frozenset({"q1", "q2"})])
def test_sample_query_plan_uses_scene_and_variant_indexes(
    tmp_path: Path,
    exclude_ids: frozenset[str],
) -> None:
    database = tmp_path / "content-v2.db"
    create_hierarchical_content_database(database)
    repository = ContentRepository(database)
    query = repository._sample_candidate_query(
        exclude_count=len(exclude_ids),
        comparison=">=",
    )
    parameters = repository._sample_candidate_parameters(
        scene_key="travel_hotel",
        seed=450,
        difficulty="easy",
        exclude_ids=exclude_ids,
        limit=10,
    )

    with repository.connect() as connection:
        details = [row[3] for row in connection.execute(f"EXPLAIN QUERY PLAN {query}", parameters)]

    assert any("idx_sentences_scene_random" in detail for detail in details)
    assert any("idx_variants_sentence_difficulty" in detail for detail in details)
    assert not any("USE TEMP B-TREE" in detail for detail in details)
    assert not any(
        "SCAN q" in detail and "USING INDEX idx_variants_sentence_difficulty" not in detail
        for detail in details
    )


@pytest.mark.parametrize(
    ("top_scene", "scene_count"),
    [("travel", 4), (None, 32)],
)
def test_sample_queries_each_scene_with_bounded_index_range_without_temp_sort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    top_scene: str | None,
    scene_count: int,
) -> None:
    database = tmp_path / "content-v2.db"
    create_hierarchical_content_database(database)
    expand_hierarchical_scene_count(
        database,
        top_scene=top_scene,
        target_count=scene_count,
    )
    traced_statements: list[str] = []
    real_connect = database_module.sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(traced_statements.append)
        return connection

    monkeypatch.setattr(database_module.sqlite3, "connect", traced_connect)

    rows = ContentRepository(database).sample_questions(
        top_scene=top_scene,
        sub_scene=None,
        difficulty="hard",
        limit=10,
        exclude_ids=frozenset(),
        seed=450,
    )

    assert rows == []
    candidate_queries = [
        statement
        for statement in traced_statements
        if "SELECT q.id AS question_id" in statement and "FROM sentences AS s" in statement
    ]
    assert len(candidate_queries) == scene_count * 2
    assert all("s.sub_scene_key =" in statement for statement in candidate_queries)
    assert all("s.sub_scene_key IN" not in statement for statement in candidate_queries)
    assert all("INDEXED BY" not in statement for statement in candidate_queries)

    with real_connect(database) as connection:
        for query in candidate_queries:
            details = [row[3] for row in connection.execute(f"EXPLAIN QUERY PLAN {query}")]
            assert any("idx_sentences_scene_random" in detail for detail in details)
            assert any("idx_variants_sentence_difficulty" in detail for detail in details)
            assert not any("USE TEMP B-TREE" in detail for detail in details)
            assert not any(detail.startswith("SCAN q") for detail in details)


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
