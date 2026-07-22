from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STAGE_PREDECESSORS = {
    "clean": None,
    "dedupe": "clean",
    "classify": "dedupe",
    "select": "classify",
    "translate": "select",
    "variants": "translate",
}


@dataclass(frozen=True, slots=True)
class WorkItem:
    id: int
    source_name: str
    source_item_id: str
    source_url: str
    source_author: str
    license_name: str
    license_url: str
    text: str
    protected: bool
    top_scene: str | None = None
    sub_scene: str | None = None


@dataclass(frozen=True, slots=True)
class StageInput:
    item: WorkItem
    predecessor_payload: dict[str, Any]
    stage_payload: dict[str, Any] | None


class WorkDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("BEGIN")
            for statement in _schema_statements():
                connection.execute(statement)
            _migrate_raw_scene_columns(connection)

    def upsert_raw(
        self,
        *,
        source_name: str,
        source_item_id: str,
        source_url: str,
        source_author: str,
        license_name: str,
        license_url: str,
        text: str,
        protected: bool = False,
        top_scene: str | None = None,
        sub_scene: str | None = None,
    ) -> int:
        with self.connect() as connection:
            connection.execute("BEGIN")
            existing = connection.execute(
                """
                SELECT id, source_url, source_author, license_name, license_url, text, protected,
                       top_scene, sub_scene
                FROM raw_items
                WHERE source_name = ? AND source_item_id = ?
                """,
                (source_name, source_item_id),
            ).fetchone()
            derived_input = (
                source_url,
                source_author,
                license_name,
                license_url,
                text,
                int(protected),
                top_scene,
                sub_scene,
            )
            connection.execute(
                """
                INSERT INTO raw_items(
                    source_name, source_item_id, source_url, source_author, license_name,
                    license_url, text, protected, top_scene, sub_scene, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_name, source_item_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    source_author = excluded.source_author,
                    license_name = excluded.license_name,
                    license_url = excluded.license_url,
                    text = excluded.text,
                    protected = excluded.protected,
                    top_scene = excluded.top_scene,
                    sub_scene = excluded.sub_scene
                """,
                (
                    source_name,
                    source_item_id,
                    source_url,
                    source_author,
                    license_name,
                    license_url,
                    text,
                    int(protected),
                    top_scene,
                    sub_scene,
                    _now(),
                ),
            )
            if existing is None:
                row = connection.execute(
                    "SELECT id FROM raw_items WHERE source_name = ? AND source_item_id = ?",
                    (source_name, source_item_id),
                ).fetchone()
                if row is None:
                    raise RuntimeError("未能读取已写入的原始条目")
                item_id = int(row[0])
            else:
                item_id = int(existing[0])
                if tuple(existing[1:]) != derived_input:
                    connection.execute("DELETE FROM stage_results WHERE item_id = ?", (item_id,))
                    connection.execute("DELETE FROM rejections WHERE item_id = ?", (item_id,))
        return item_id

    def claim_batch(self, stage: str, limit: int) -> list[WorkItem]:
        if limit < 1:
            return []
        previous_stage = _previous_stage(stage)
        with self.connect() as connection:
            if previous_stage is None:
                rows = connection.execute(
                    """
                    SELECT r.id, r.source_name, r.source_item_id, r.source_url, r.source_author,
                           r.license_name, r.license_url, r.text, r.protected,
                           r.top_scene, r.sub_scene
                    FROM raw_items AS r
                    LEFT JOIN stage_results AS s ON s.item_id = r.id AND s.stage = :stage
                    LEFT JOIN rejections AS x ON x.item_id = r.id
                    WHERE s.item_id IS NULL AND x.item_id IS NULL
                    ORDER BY r.id
                    LIMIT :limit
                    """,
                    {"stage": stage, "limit": limit},
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT r.id, r.source_name, r.source_item_id, r.source_url, r.source_author,
                           r.license_name, r.license_url, r.text, r.protected,
                           r.top_scene, r.sub_scene
                    FROM raw_items AS r
                    LEFT JOIN stage_results AS s ON s.item_id = r.id AND s.stage = :stage
                    JOIN stage_results AS p ON p.item_id = r.id AND p.stage = :previous_stage
                    LEFT JOIN rejections AS x ON x.item_id = r.id
                    WHERE s.item_id IS NULL AND x.item_id IS NULL
                    ORDER BY r.id
                    LIMIT :limit
                    """,
                    {"stage": stage, "previous_stage": previous_stage, "limit": limit},
                ).fetchall()
        return [
            WorkItem(
                id=row[0],
                source_name=row[1],
                source_item_id=row[2],
                source_url=row[3],
                source_author=row[4],
                license_name=row[5],
                license_url=row[6],
                text=row[7],
                protected=bool(row[8]),
                top_scene=row[9],
                sub_scene=row[10],
            )
            for row in rows
        ]

    def stage_inputs(
        self,
        stage: str,
        *,
        include_completed: bool = False,
        include_rejected: bool = False,
    ) -> list[StageInput]:
        previous_stage = _previous_stage(stage)
        with self.connect() as connection:
            if previous_stage is None:
                rows = connection.execute(
                    """
                    SELECT r.id, r.source_name, r.source_item_id, r.source_url, r.source_author,
                           r.license_name, r.license_url, r.text, r.protected,
                           r.top_scene, r.sub_scene, '{}', s.payload_json
                    FROM raw_items AS r
                    LEFT JOIN stage_results AS s ON s.item_id = r.id AND s.stage = :stage
                    LEFT JOIN rejections AS x ON x.item_id = r.id
                    WHERE (:include_rejected = 1 OR x.item_id IS NULL)
                      AND (:include_completed = 1 OR s.item_id IS NULL)
                    ORDER BY r.id
                    """,
                    {
                        "stage": stage,
                        "include_completed": int(include_completed),
                        "include_rejected": int(include_rejected),
                    },
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT r.id, r.source_name, r.source_item_id, r.source_url, r.source_author,
                           r.license_name, r.license_url, r.text, r.protected,
                           r.top_scene, r.sub_scene, p.payload_json, s.payload_json
                    FROM raw_items AS r
                    JOIN stage_results AS p
                      ON p.item_id = r.id AND p.stage = :previous_stage
                    LEFT JOIN stage_results AS s ON s.item_id = r.id AND s.stage = :stage
                    LEFT JOIN rejections AS x ON x.item_id = r.id
                    WHERE (:include_rejected = 1 OR x.item_id IS NULL)
                      AND (:include_completed = 1 OR s.item_id IS NULL)
                    ORDER BY r.id
                    """,
                    {
                        "stage": stage,
                        "previous_stage": previous_stage,
                        "include_completed": int(include_completed),
                        "include_rejected": int(include_rejected),
                    },
                ).fetchall()
        return [
            StageInput(
                item=_work_item(row),
                predecessor_payload=json.loads(row[11]),
                stage_payload=json.loads(row[12]) if row[12] is not None else None,
            )
            for row in rows
        ]

    def replace_stage(
        self,
        stage: str,
        results: list[tuple[int, dict[str, Any]]],
        *,
        model_version: str = "",
    ) -> bool:
        previous_stage = _previous_stage(stage)
        serialized = [(item_id, _dump_payload(payload)) for item_id, payload in results]
        item_ids = [item_id for item_id, _ in serialized]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError(f"阶段 {stage} 的批量结果包含重复条目")
        proposed = {item_id: (payload_json, model_version) for item_id, payload_json in serialized}
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = {
                int(item_id): (str(payload_json), str(version))
                for item_id, payload_json, version in connection.execute(
                    """
                    SELECT item_id, payload_json, model_version
                    FROM stage_results
                    WHERE stage = ?
                    """,
                    (stage,),
                )
            }
            if existing == proposed:
                return False
            if previous_stage is None:
                eligible = {int(row[0]) for row in connection.execute("SELECT id FROM raw_items")}
            else:
                eligible = {
                    int(row[0])
                    for row in connection.execute(
                        "SELECT item_id FROM stage_results WHERE stage = ?", (previous_stage,)
                    )
                }
            rejected = {int(row[0]) for row in connection.execute("SELECT item_id FROM rejections")}
            invalid = sorted((set(item_ids) - eligible) | (set(item_ids) & rejected))
            if invalid:
                raise ValueError(f"阶段 {stage} 的批量结果包含不可写条目: {invalid}")

            for descendant in _stage_descendants(stage):
                connection.execute("DELETE FROM stage_results WHERE stage = ?", (descendant,))
            connection.execute("DELETE FROM stage_results WHERE stage = ?", (stage,))
            updated_at = _now()
            connection.executemany(
                """
                INSERT INTO stage_results(
                    item_id, stage, payload_json, model_version, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (item_id, stage, payload_json, model_version, updated_at)
                    for item_id, payload_json in serialized
                ],
            )
        return True

    def mark_stage(
        self,
        item_id: int,
        stage: str,
        *,
        payload: dict[str, Any],
        model_version: str = "",
    ) -> None:
        previous_stage = _previous_stage(stage)
        with self.connect() as connection:
            connection.execute("BEGIN")
            rejection = connection.execute(
                "SELECT 1 FROM rejections WHERE item_id = ?", (item_id,)
            ).fetchone()
            if rejection is not None:
                raise ValueError(f"条目 {item_id} 已拒绝，不能写入阶段结果")
            if previous_stage is not None:
                predecessor = connection.execute(
                    "SELECT 1 FROM stage_results WHERE item_id = ? AND stage = ?",
                    (item_id, previous_stage),
                ).fetchone()
                if predecessor is None:
                    raise ValueError(f"阶段 {stage} 缺少成功前置阶段: {previous_stage}")
            connection.execute(
                """
                INSERT INTO stage_results(item_id, stage, payload_json, model_version, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id, stage) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    model_version = excluded.model_version,
                    updated_at = excluded.updated_at
                """,
                (item_id, stage, _dump_payload(payload), model_version, _now()),
            )

    def record_rejection(self, item_id: int, stage: str, reason: str) -> None:
        _previous_stage(stage)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO rejections(item_id, stage, reason, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    stage = excluded.stage,
                    reason = excluded.reason,
                    updated_at = excluded.updated_at
                """,
                (item_id, stage, reason, _now()),
            )

    def stage_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            raw_count = connection.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
            rejected_count = connection.execute("SELECT COUNT(*) FROM rejections").fetchone()[0]
            stage_rows = connection.execute(
                "SELECT stage, COUNT(*) FROM stage_results GROUP BY stage ORDER BY stage"
            ).fetchall()
        return {
            "raw": int(raw_count),
            **{str(stage): int(count) for stage, count in stage_rows},
            "rejected": int(rejected_count),
        }


def _previous_stage(stage: str) -> str | None:
    try:
        return STAGE_PREDECESSORS[stage]
    except KeyError as error:
        raise ValueError(f"不支持的处理阶段: {stage}") from error


def _schema_statements() -> tuple[str, ...]:
    return (
        """
        CREATE TABLE IF NOT EXISTS raw_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            source_item_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_author TEXT NOT NULL,
            license_name TEXT NOT NULL,
            license_url TEXT NOT NULL,
            text TEXT NOT NULL,
            protected INTEGER NOT NULL DEFAULT 0 CHECK(protected IN (0, 1)),
            top_scene TEXT,
            sub_scene TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(source_name, source_item_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stage_results(
            item_id INTEGER NOT NULL REFERENCES raw_items(id),
            stage TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            model_version TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(item_id, stage)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rejections(
            item_id INTEGER PRIMARY KEY REFERENCES raw_items(id),
            stage TEXT NOT NULL,
            reason TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS build_runs(
            id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('running','passed','failed')),
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}'
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_stage_results_stage ON stage_results(stage, item_id)",
        "CREATE INDEX IF NOT EXISTS idx_rejections_stage ON rejections(stage, item_id)",
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _work_item(row: tuple[Any, ...]) -> WorkItem:
    return WorkItem(
        id=int(row[0]),
        source_name=str(row[1]),
        source_item_id=str(row[2]),
        source_url=str(row[3]),
        source_author=str(row[4]),
        license_name=str(row[5]),
        license_url=str(row[6]),
        text=str(row[7]),
        protected=bool(row[8]),
        top_scene=str(row[9]) if row[9] is not None else None,
        sub_scene=str(row[10]) if row[10] is not None else None,
    )


def _dump_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _stage_descendants(stage: str) -> tuple[str, ...]:
    stages = tuple(STAGE_PREDECESSORS)
    return stages[stages.index(stage) + 1 :]


def _migrate_raw_scene_columns(connection: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(raw_items)")}
    if "top_scene" not in columns:
        connection.execute("ALTER TABLE raw_items ADD COLUMN top_scene TEXT")
    if "sub_scene" not in columns:
        connection.execute("ALTER TABLE raw_items ADD COLUMN sub_scene TEXT")
