from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.content_pipeline.clean import normalized_hash
from tools.content_pipeline.dedupe import jaccard_similarity, simhash64
from tools.content_pipeline.scenes import SUB_SCENES

STAGE_PREDECESSORS = {
    "clean": None,
    "dedupe": "clean",
    "classify": "dedupe",
    "select": "classify",
    "translate": "select",
    "variants": "translate",
}

_POSITIVE_CLASSIFICATION_METHODS = frozenset(
    {
        "source_explicit",
        "keyword",
        "context_keywords",
        "candidate_source",
        "single_keyword_whitelist",
        "llm_repair",
        "historical_review_replay",
        "recall_review",
    }
)
_NULL_CLASSIFICATION_METHODS = frozenset({"llm_required", "llm_rejected", "out_of_candidate_pool"})
_CLASSIFICATION_REASON_METHODS = frozenset(
    {"llm_repair", "llm_rejected", "historical_review_replay", "recall_review"}
)


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


@dataclass(frozen=True, slots=True)
class TranslationRepair:
    item: WorkItem
    draft: str
    issues: tuple[str, ...]
    model_version: str
    top_scene: str
    sub_scene: str
    review_note: str
    selection_generation: str


@dataclass(frozen=True, slots=True)
class TranslationBatch:
    selection_generation: str
    items: tuple[WorkItem, ...]


@dataclass(frozen=True, slots=True)
class SelectionInputSnapshot:
    top_scene: str
    sub_scene: str
    generation: str


class ProtectedSelectionConflict(ValueError):
    def __init__(self, conflicts: list[str]) -> None:
        self.conflicts = tuple(conflicts)
        super().__init__("; ".join(conflicts))


class SelectionCandidatePages:
    def __init__(
        self,
        database: WorkDatabase,
        *,
        top_scene: str,
        sub_scene: str,
        quota: int,
        source_limit: int,
        author_limit: int,
        page_size: int,
    ) -> None:
        self.database = database
        self.top_scene = top_scene
        self.sub_scene = sub_scene
        self.quota = quota
        self.source_limit = source_limit
        self.author_limit = author_limit
        self.page_size = page_size
        self.snapshot: SelectionInputSnapshot | None = None
        self._started = False

    def __iter__(self) -> Iterator[list[StageInput]]:
        if self._started:
            raise RuntimeError("选择候选分页只允许消费一次")
        self._started = True
        digest = hashlib.sha256()
        with closing(self.database.connect()) as connection:
            # 聚合检查、protected 和 regular 游标必须共享同一个显式读事务，
            # 否则并发分类更新可能拼出数据库中从未真实存在过的混合快照。
            connection.execute("BEGIN")
            conflicts = _protected_selection_conflicts(
                connection,
                top_scene=self.top_scene,
                sub_scene=self.sub_scene,
                quota=self.quota,
                source_limit=self.source_limit,
                author_limit=self.author_limit,
            )
            if conflicts:
                raise ProtectedSelectionConflict(conflicts)
            for protected in (1, 0):
                cursor = connection.execute(
                    _SELECTION_INPUT_QUERY,
                    (self.sub_scene, self.top_scene, protected),
                )
                while rows := cursor.fetchmany(self.page_size):
                    for row in rows:
                        _update_selection_input_digest(digest, row)
                    yield [_stage_input(row) for row in rows]
        self.snapshot = SelectionInputSnapshot(
            top_scene=self.top_scene,
            sub_scene=self.sub_scene,
            generation=digest.hexdigest(),
        )


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
            _migrate_translation_generation(connection)
            _migrate_classification_rejections(connection)

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
            if existing is not None and tuple(existing[1:]) == derived_input:
                return int(existing[0])
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
                    connection.execute(
                        "DELETE FROM dedupe_fingerprints WHERE item_id = ?", (item_id,)
                    )
                    connection.execute(
                        "DELETE FROM translation_repairs WHERE item_id = ?", (item_id,)
                    )
                    _invalidate_selection_snapshot(connection)
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

    def delete_raw_source(self, source_name: str) -> int:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM raw_items WHERE source_name = ?", (source_name,)
                ).fetchone()[0]
            )
            if not count:
                return 0
            for table in (
                "stage_results",
                "rejections",
                "translation_repairs",
                "dedupe_fingerprints",
            ):
                connection.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE item_id IN (
                        SELECT id FROM raw_items WHERE source_name = ?
                    )
                    """,
                    (source_name,),
                )
            connection.execute("DELETE FROM raw_items WHERE source_name = ?", (source_name,))
            _invalidate_selection_snapshot(connection)
        return count

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

    def claim_stage_batch(
        self,
        stage: str,
        limit: int,
        *,
        stale_model_version: str | None = None,
    ) -> list[StageInput]:
        """领取带前置阶段载荷的有界批次，避免把完整工作库载入内存。"""
        if limit < 1:
            return []
        previous_stage = _previous_stage(stage)
        with self.connect() as connection:
            if previous_stage is None:
                rows = connection.execute(
                    """
                    SELECT r.id, r.source_name, r.source_item_id, r.source_url, r.source_author,
                           r.license_name, r.license_url, r.text, r.protected,
                           r.top_scene, r.sub_scene, '{}', NULL
                    FROM raw_items AS r
                    LEFT JOIN stage_results AS s ON s.item_id = r.id AND s.stage = :stage
                    LEFT JOIN rejections AS x ON x.item_id = r.id
                    WHERE (
                            s.item_id IS NULL
                            OR (:model_version IS NOT NULL
                                AND s.model_version NOT IN (:model_version, 'llm-repair'))
                          )
                      AND x.item_id IS NULL
                    ORDER BY r.id LIMIT :limit
                    """,
                    {
                        "stage": stage,
                        "limit": limit,
                        "model_version": stale_model_version,
                    },
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT r.id, r.source_name, r.source_item_id, r.source_url, r.source_author,
                           r.license_name, r.license_url, r.text, r.protected,
                           r.top_scene, r.sub_scene, p.payload_json, NULL
                    FROM raw_items AS r
                    JOIN stage_results AS p
                      ON p.item_id = r.id AND p.stage = :previous_stage
                    LEFT JOIN stage_results AS s ON s.item_id = r.id AND s.stage = :stage
                    LEFT JOIN rejections AS x ON x.item_id = r.id
                    WHERE (
                            s.item_id IS NULL
                            OR (:model_version IS NOT NULL
                                AND s.model_version NOT IN (:model_version, 'llm-repair'))
                          )
                      AND x.item_id IS NULL
                    ORDER BY r.id LIMIT :limit
                    """,
                    {
                        "stage": stage,
                        "previous_stage": previous_stage,
                        "limit": limit,
                        "model_version": stale_model_version,
                    },
                ).fetchall()
        return [
            StageInput(
                item=_work_item(row),
                predecessor_payload=json.loads(row[11]),
                stage_payload=None,
            )
            for row in rows
        ]

    def checkpoint_stage_batch(
        self,
        stage: str,
        results: list[tuple[int, dict[str, Any]]],
        rejections: list[tuple[int, str]] | None = None,
        *,
        model_version: str = "",
    ) -> None:
        """在单个事务内保存普通阶段批次及拒绝结果。"""
        if stage == "select":
            raise ValueError("select 阶段必须使用 replace_stage 写入完整原子快照")
        previous_stage = _previous_stage(stage)
        rejected_rows = rejections or []
        item_ids = [item_id for item_id, _ in results] + [item_id for item_id, _ in rejected_rows]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError(f"阶段 {stage} 批次包含重复条目")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if previous_stage is None:
                eligible = (
                    {
                        int(row[0])
                        for row in connection.execute(
                            f"SELECT id FROM raw_items WHERE id IN ({_placeholders(item_ids)})",
                            item_ids,
                        )
                    }
                    if item_ids
                    else set()
                )
            else:
                eligible = (
                    {
                        int(row[0])
                        for row in connection.execute(
                            f"""
                        SELECT item_id FROM stage_results
                        WHERE stage = ? AND item_id IN ({_placeholders(item_ids)})
                        """,
                            [previous_stage, *item_ids],
                        )
                    }
                    if item_ids
                    else set()
                )
            if eligible != set(item_ids):
                raise ValueError(f"阶段 {stage} 批次包含不可写条目")
            updated_at = _now()
            connection.executemany(
                """
                INSERT INTO stage_results(item_id, stage, payload_json, model_version, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id, stage) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    model_version=excluded.model_version,
                    updated_at=excluded.updated_at
                """,
                [
                    (item_id, stage, _dump_payload(payload), model_version, updated_at)
                    for item_id, payload in results
                ],
            )
            connection.executemany(
                """
                INSERT INTO rejections(item_id, stage, reason, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    stage=excluded.stage, reason=excluded.reason, updated_at=excluded.updated_at
                """,
                [(item_id, stage, reason, updated_at) for item_id, reason in rejected_rows],
            )
            if stage in {"clean", "dedupe", "classify"} and item_ids:
                _invalidate_selection_snapshot(connection)

    def checkpoint_dedupe_batch(self, inputs: list[StageInput]) -> dict[str, int]:
        """使用 SQLite 持久化分桶完成有界近似去重，并与阶段结果原子提交。"""
        summary = {"processed": 0, "accepted": 0, "exact_duplicate": 0, "near_duplicate": 0}
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated_at = _now()
            for stage_input in inputs:
                item = stage_input.item
                text = str(stage_input.predecessor_payload.get("clean_text") or item.text)
                digest = normalized_hash(text)
                fingerprint = simhash64(text)
                bands = tuple((fingerprint >> (band * 16)) & 0xFFFF for band in range(4))
                exact = connection.execute(
                    """
                    SELECT normalized_hash FROM dedupe_fingerprints
                    WHERE normalized_hash = ? ORDER BY item_id LIMIT 1
                    """,
                    (digest,),
                ).fetchone()
                duplicate_hash = str(exact[0]) if exact is not None else None
                duplicate_kind = "exact_duplicate" if exact is not None else ""
                if exact is None:
                    candidate_hashes: dict[int, str] = {}
                    for band_index, band_value in enumerate(bands):
                        # 四条等值查询能稳定命中单列索引，避免 SQLite 从大表连接侧起扫。
                        for candidate_id, candidate_hash in connection.execute(
                            f"""
                            SELECT item_id, normalized_hash
                            FROM dedupe_fingerprints
                            WHERE band{band_index} = ?
                            """,
                            (band_value,),
                        ):
                            candidate_hashes[int(candidate_id)] = str(candidate_hash)
                    candidate_texts: dict[int, str] = {}
                    candidate_ids = sorted(candidate_hashes)
                    for offset in range(0, len(candidate_ids), 500):
                        chunk = candidate_ids[offset : offset + 500]
                        for candidate_id, clean_payload, raw_text in connection.execute(
                            f"""
                            SELECT r.id, clean.payload_json, r.text
                            FROM raw_items AS r
                            JOIN stage_results AS clean
                              ON clean.item_id=r.id AND clean.stage='clean'
                            WHERE r.id IN ({_placeholders(chunk)})
                            """,
                            chunk,
                        ):
                            candidate_texts[int(candidate_id)] = str(
                                json.loads(clean_payload).get("clean_text") or raw_text
                            )
                    for candidate_id in candidate_ids:
                        candidate_hash = candidate_hashes[candidate_id]
                        candidate_text = candidate_texts[candidate_id]
                        if jaccard_similarity(text, candidate_text) >= 0.76:
                            duplicate_hash = str(candidate_hash)
                            duplicate_kind = "near_duplicate"
                            break
                summary["processed"] += 1
                if duplicate_hash is not None and not item.protected:
                    summary[duplicate_kind] += 1
                    connection.execute(
                        """
                        INSERT INTO rejections(item_id, stage, reason, updated_at)
                        VALUES (?, 'dedupe', ?, ?)
                        ON CONFLICT(item_id) DO UPDATE SET
                            stage='dedupe', reason=excluded.reason, updated_at=excluded.updated_at
                        """,
                        (item.id, f"{duplicate_kind}:{duplicate_hash}", updated_at),
                    )
                    continue
                connection.execute(
                    """
                    INSERT INTO dedupe_fingerprints(
                        item_id, normalized_hash, simhash64, band0, band1, band2, band3
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        normalized_hash=excluded.normalized_hash,
                        simhash64=excluded.simhash64,
                        band0=excluded.band0, band1=excluded.band1,
                        band2=excluded.band2, band3=excluded.band3
                    """,
                    (item.id, digest, f"{fingerprint:016x}", *bands),
                )
                connection.execute(
                    """
                    INSERT INTO stage_results(
                        item_id, stage, payload_json, model_version, updated_at
                    )
                    VALUES (?, 'dedupe', ?, '', ?)
                    ON CONFLICT(item_id, stage) DO UPDATE SET
                        payload_json=excluded.payload_json, updated_at=excluded.updated_at
                    """,
                    (item.id, _dump_payload({"simhash64": f"{fingerprint:016x}"}), updated_at),
                )
                summary["accepted"] += 1
            if inputs:
                _invalidate_selection_snapshot(connection)
        return summary

    def pending_classification_repairs(self) -> int:
        with self.connect() as connection:
            return int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM stage_results
                    WHERE stage='classify'
                      AND json_extract(payload_json, '$.method')='llm_required'
                    """
                ).fetchone()[0]
            )

    def classification_method_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT json_extract(payload_json, '$.method'), COUNT(*)
                FROM stage_results
                WHERE stage='classify'
                GROUP BY 1 ORDER BY 1
                """
            ).fetchall()
        return {str(method): int(count) for method, count in rows}

    def recall_candidate_pool_fingerprint(self) -> dict[str, int | str]:
        """返回覆盖候选成员及召回输入内容的稳定版本指纹。"""
        digest = hashlib.sha256()
        eligible_count = 0
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT classified.item_id, r.text, r.source_name, r.source_author,
                       classified.payload_json, classified.model_version,
                       classified.updated_at
                FROM stage_results AS classified
                JOIN raw_items AS r ON r.id=classified.item_id
                LEFT JOIN rejections AS rejected ON rejected.item_id=classified.item_id
                WHERE classified.stage='classify'
                  AND json_extract(
                        classified.payload_json, '$.method'
                      )='out_of_candidate_pool'
                  AND rejected.item_id IS NULL
                ORDER BY classified.item_id
                """
            )
            for row in rows:
                eligible_count += 1
                digest.update(
                    json.dumps(
                        tuple(row),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                digest.update(b"\n")
        return {
            "eligible_count": eligible_count,
            "pool_version": digest.hexdigest(),
        }

    def rejection_reason_counts(self, stage: str) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT CASE
                           WHEN instr(reason, ':') > 0
                           THEN substr(reason, 1, instr(reason, ':') - 1)
                           ELSE reason
                       END AS reason_kind,
                       COUNT(*)
                FROM rejections
                WHERE stage=?
                GROUP BY reason_kind ORDER BY reason_kind
                """,
                (stage,),
            ).fetchall()
        return {str(reason): int(count) for reason, count in rows}

    def classification_repair_rows(self) -> list[tuple[WorkItem, dict[str, Any]]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT r.id, r.source_name, r.source_item_id, r.source_url, r.source_author,
                       r.license_name, r.license_url, r.text, r.protected,
                       r.top_scene, r.sub_scene, classified.payload_json
                FROM stage_results AS classified
                JOIN raw_items AS r ON r.id=classified.item_id
                WHERE classified.stage='classify'
                  AND json_extract(classified.payload_json, '$.method')='llm_required'
                ORDER BY r.id
                """
            ).fetchall()
        return [(_work_item(row), json.loads(row[11])) for row in rows]

    def apply_classification_repairs(
        self, results: list[tuple[int, str | None, str | None, str]]
    ) -> int:
        item_ids = [row[0] for row in results]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("分类修正结果包含重复 item_id")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            pending = {
                int(row[0])
                for row in connection.execute(
                    """
                    SELECT item_id FROM stage_results
                    WHERE stage='classify'
                      AND json_extract(payload_json, '$.method')='llm_required'
                    """
                )
            }
            supplied = set(item_ids)
            if supplied != pending:
                missing = sorted(pending - supplied)
                unknown = sorted(supplied - pending)
                raise ValueError(
                    f"分类修正集合不完整: missing={missing[:20]}, unknown={unknown[:20]}"
                )
            updated_at = _now()
            connection.executemany(
                """
                UPDATE stage_results
                SET payload_json=?, model_version='llm-repair', updated_at=?
                WHERE item_id=? AND stage='classify'
                """,
                [
                    (
                        _dump_payload(
                            {
                                "top_scene": top_scene,
                                "sub_scene": sub_scene,
                                "confidence": 1.0 if sub_scene is not None else 0.0,
                                "method": (
                                    "llm_repair" if sub_scene is not None else "llm_rejected"
                                ),
                                "reason": reason,
                            }
                        ),
                        updated_at,
                        item_id,
                    )
                    for item_id, top_scene, sub_scene, reason in results
                ],
            )
            if results:
                _invalidate_selection_snapshot(connection)
        return len(results)

    def apply_historical_classifications(
        self,
        decisions: list[tuple[str, str, str, str, str, str]],
    ) -> dict[str, int]:
        """按来源、作者和原文唯一映射，并原子回放历史正向分类。"""
        identities = [(row[0], row[1], row[2]) for row in decisions]
        if len(identities) != len(set(identities)):
            raise ValueError("历史分类决定包含重复内容身份")
        if not decisions:
            return {"applied": 0, "skipped_rejected": 0, "noop": 0}

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TEMP TABLE historical_replay_decisions(
                    ordinal INTEGER PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    source_author TEXT NOT NULL,
                    text TEXT NOT NULL,
                    top_scene TEXT NOT NULL,
                    sub_scene TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    UNIQUE(source_name, source_author, text)
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO historical_replay_decisions(
                    ordinal, source_name, source_author, text,
                    top_scene, sub_scene, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [(ordinal, *decision) for ordinal, decision in enumerate(decisions)],
            )
            # 固定从 raw_items 扫描一次，再用临时表的身份索引筛选，避免逐项全库查找。
            rows = connection.execute(
                """
                SELECT requested.ordinal, raw.id, rejected.item_id,
                       classified.payload_json, classified.model_version
                FROM raw_items AS raw NOT INDEXED
                CROSS JOIN historical_replay_decisions AS requested
                LEFT JOIN rejections AS rejected ON rejected.item_id=raw.id
                LEFT JOIN stage_results AS classified
                  ON classified.item_id=raw.id AND classified.stage='classify'
                WHERE raw.source_name=requested.source_name
                  AND raw.source_author=requested.source_author
                  AND raw.text=requested.text
                ORDER BY requested.ordinal, raw.id
                """
            ).fetchall()
            matches: dict[int, list[tuple[Any, ...]]] = {
                ordinal: [] for ordinal in range(len(decisions))
            }
            for row in rows:
                matches[int(row[0])].append(tuple(row[1:]))

            updates: list[tuple[str, str, int]] = []
            skipped_rejected = 0
            noop = 0
            updated_at = _now()
            for ordinal, decision in enumerate(decisions):
                source_name, source_author, text, top_scene, sub_scene, reason = decision
                identity_matches = [row for row in matches[ordinal] if row[0] is not None]
                if len(identity_matches) != 1:
                    raise ValueError(
                        "历史内容身份无法在当前 raw_items 唯一映射: "
                        f"source_name={source_name!r}, source_author={source_author!r}, "
                        f"text={text!r}, matches={len(identity_matches)}"
                    )
                item_id, rejected_item_id, payload_json, _model_version = identity_matches[0]
                if rejected_item_id is not None:
                    skipped_rejected += 1
                    continue
                if payload_json is None:
                    raise ValueError(
                        f"历史内容身份对应条目 {item_id} 未完成 classify，无法唯一映射"
                    )
                current = _validate_classification_payload(int(item_id), str(payload_json))
                current_top = current.get("top_scene")
                current_sub = current.get("sub_scene")
                current_method = current.get("method")
                if current_top == top_scene and current_sub == sub_scene:
                    noop += 1
                    continue
                if current_method != "out_of_candidate_pool":
                    raise ValueError(
                        f"条目 {item_id} 已有分类冲突: "
                        f"current=({current_top!r}, {current_sub!r}, {current_method!r}), "
                        f"historical=({top_scene!r}, {sub_scene!r})"
                    )
                payload = _dump_payload(
                    {
                        "top_scene": top_scene,
                        "sub_scene": sub_scene,
                        "confidence": 1.0,
                        "method": "historical_review_replay",
                        "reason": reason,
                    }
                )
                updates.append((payload, updated_at, int(item_id)))

            if updates:
                connection.executemany(
                    """
                    UPDATE stage_results
                    SET payload_json=?, model_version='historical-review-replay-v1', updated_at=?
                    WHERE item_id=? AND stage='classify'
                    """,
                    updates,
                )
                _invalidate_selection_snapshot(connection)
        return {
            "applied": len(updates),
            "skipped_rejected": skipped_rejected,
            "noop": noop,
        }

    def apply_current_recall_reviews(
        self, decisions: list[tuple[int, str, str, str, str, str, str]]
    ) -> dict[str, int]:
        """按当前 item_id 应用复审，同时以 request 身份字段防止错库更新。"""
        if not decisions:
            return {"applied": 0, "noop": 0, "skipped_rejected": 0}
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updates: list[tuple[str, str, int]] = []
            noop = skipped_rejected = 0
            updated_at = _now()
            for (
                item_id,
                source_name,
                source_author,
                text,
                top_scene,
                sub_scene,
                reason,
            ) in decisions:
                raw = connection.execute(
                    "SELECT source_name, source_author, text FROM raw_items WHERE id=?", (item_id,)
                ).fetchone()
                if raw is None or tuple(raw) != (source_name, source_author, text):
                    raise ValueError(f"当前复审 item_id={item_id} 的身份不一致或不存在")
                if (
                    connection.execute(
                        "SELECT 1 FROM rejections WHERE item_id=?", (item_id,)
                    ).fetchone()
                    is not None
                ):
                    skipped_rejected += 1
                    continue
                row = connection.execute(
                    "SELECT payload_json FROM stage_results WHERE item_id=? AND stage='classify'",
                    (item_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"条目 {item_id} 未完成 classify")
                current = _validate_classification_payload(item_id, str(row[0]))
                if current.get("top_scene") == top_scene and current.get("sub_scene") == sub_scene:
                    noop += 1
                    continue
                if current.get("method") != "out_of_candidate_pool":
                    raise ValueError(f"条目 {item_id} 已有分类冲突")
                updates.append(
                    (
                        _dump_payload(
                            {
                                "top_scene": top_scene,
                                "sub_scene": sub_scene,
                                "confidence": 1.0,
                                "method": "recall_review",
                            "reason": reason,
                            }
                        ),
                        updated_at,
                        item_id,
                    )
                )
            if updates:
                connection.executemany(
                    "UPDATE stage_results SET payload_json=?, "
                    "model_version='recall-review-v1', updated_at=? "
                    "WHERE item_id=? AND stage='classify'",
                    updates,
                )
                _invalidate_selection_snapshot(connection)
        return {"applied": len(updates), "noop": noop, "skipped_rejected": skipped_rejected}

    def bounded_selection_candidates(
        self,
        sub_scene: str,
        *,
        quota: int,
        multiplier: int = 16,
    ) -> list[StageInput]:
        """按来源和作者预分层，返回单场景固定上限的候选集合。"""
        source_limit = max(1, math.floor(quota * 0.45))
        author_limit = max(1, math.floor(quota * 0.08))
        with self.connect() as connection:
            protected_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM stage_results AS classified
                    JOIN raw_items AS r ON r.id=classified.item_id
                    LEFT JOIN rejections AS rejected ON rejected.item_id=r.id
                    WHERE classified.stage='classify'
                      AND json_extract(classified.payload_json, '$.sub_scene')=?
                      AND r.protected=1 AND rejected.item_id IS NULL
                    """,
                    (sub_scene,),
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                WITH candidates AS (
                    SELECT r.id, r.source_name, r.source_item_id, r.source_url,
                           r.source_author, r.license_name, r.license_url,
                           COALESCE(
                               json_extract(cleaned.payload_json, '$.clean_text'), r.text
                           ) AS text,
                           r.protected, r.top_scene, r.sub_scene, classified.payload_json,
                           ROW_NUMBER() OVER (
                               PARTITION BY r.source_name
                               ORDER BY json_extract(
                                   classified.payload_json, '$.confidence'
                               ) DESC, r.id
                           ) AS source_rank,
                           ROW_NUMBER() OVER (
                               PARTITION BY CASE
                                   WHEN trim(r.source_author)='' THEN 'empty:' || r.id
                                   ELSE r.source_author
                               END
                               ORDER BY json_extract(
                                   classified.payload_json, '$.confidence'
                               ) DESC, r.id
                           ) AS author_rank
                    FROM stage_results AS classified
                    JOIN raw_items AS r ON r.id=classified.item_id
                    JOIN stage_results AS cleaned
                      ON cleaned.item_id=r.id AND cleaned.stage='clean'
                    LEFT JOIN rejections AS rejected ON rejected.item_id=r.id
                    WHERE classified.stage='classify'
                      AND json_extract(classified.payload_json, '$.sub_scene')=:sub_scene
                      AND rejected.item_id IS NULL
                )
                SELECT id, source_name, source_item_id, source_url, source_author,
                       license_name, license_url, text, protected, top_scene, sub_scene,
                       payload_json, NULL
                FROM candidates
                WHERE protected=1
                   OR (source_rank <= :source_cap AND author_rank <= :author_cap)
                ORDER BY protected DESC,
                         json_extract(payload_json, '$.confidence') DESC,
                         id
                LIMIT :candidate_limit
                """,
                {
                    "sub_scene": sub_scene,
                    "source_cap": source_limit * 2,
                    "author_cap": author_limit * 2,
                    "candidate_limit": protected_count + quota * multiplier,
                },
            ).fetchall()
        return [
            StageInput(
                item=_work_item(row),
                predecessor_payload=json.loads(row[11]),
                stage_payload=None,
            )
            for row in rows
        ]

    def selection_candidate_pages(
        self,
        sub_scene: str,
        *,
        top_scene: str | None = None,
        quota: int | None = None,
        source_limit: int | None = None,
        author_limit: int | None = None,
        page_size: int = 512,
    ) -> SelectionCandidatePages:
        """按质量顺序分页读取完整场景池，避免门控前截断合法后备。"""
        if page_size < 1:
            raise ValueError("选择候选页大小必须大于零")
        scene = SUB_SCENES.get(sub_scene)
        resolved_top_scene = top_scene or (scene.top_key if scene is not None else "")
        resolved_quota = quota if quota is not None else (scene.quota if scene is not None else 1)
        resolved_source_limit = (
            source_limit
            if source_limit is not None
            else max(1, math.floor(resolved_quota * 0.45))
        )
        resolved_author_limit = (
            author_limit
            if author_limit is not None
            else max(1, math.floor(resolved_quota * 0.08))
        )
        return SelectionCandidatePages(
            self,
            top_scene=resolved_top_scene,
            sub_scene=sub_scene,
            quota=resolved_quota,
            source_limit=resolved_source_limit,
            author_limit=resolved_author_limit,
            page_size=page_size,
        )

    def selection_concentration(self) -> dict[str, dict[str, float | int | str]]:
        report: dict[str, dict[str, float | int | str]] = {}
        with self.connect() as connection:
            scenes = [
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT DISTINCT json_extract(payload_json, '$.sub_scene')
                    FROM stage_results WHERE stage='select' ORDER BY 1
                    """
                )
            ]
            for scene in scenes:
                total = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM stage_results
                        WHERE stage='select'
                          AND json_extract(payload_json, '$.sub_scene')=?
                        """,
                        (scene,),
                    ).fetchone()[0]
                )
                source_name, source_count = connection.execute(
                    """
                    SELECT r.source_name, COUNT(*) AS count
                    FROM stage_results AS selected
                    JOIN raw_items AS r ON r.id=selected.item_id
                    WHERE selected.stage='select'
                      AND json_extract(selected.payload_json, '$.sub_scene')=?
                    GROUP BY r.source_name ORDER BY count DESC, r.source_name LIMIT 1
                    """,
                    (scene,),
                ).fetchone()
                author_row = connection.execute(
                    """
                    SELECT r.source_author, COUNT(*) AS count
                    FROM stage_results AS selected
                    JOIN raw_items AS r ON r.id=selected.item_id
                    WHERE selected.stage='select'
                      AND json_extract(selected.payload_json, '$.sub_scene')=?
                      AND trim(r.source_author)<>''
                    GROUP BY r.source_author ORDER BY count DESC, r.source_author LIMIT 1
                    """,
                    (scene,),
                ).fetchone()
                author_name, author_count = author_row or ("", 0)
                report[scene] = {
                    "total": total,
                    "max_source": str(source_name),
                    "max_source_count": int(source_count),
                    "max_source_share": round(int(source_count) / total, 6),
                    "max_author": str(author_name),
                    "max_author_count": int(author_count),
                    "max_author_share": round(int(author_count) / total, 6),
                }
        return report

    def replace_stage(
        self,
        stage: str,
        results: list[tuple[int, dict[str, Any]]],
        *,
        model_version: str = "",
        expected_selection_inputs: tuple[SelectionInputSnapshot, ...] | None = None,
    ) -> bool:
        if expected_selection_inputs is not None and stage != "select":
            raise ValueError("输入快照 CAS 只适用于 select 阶段")
        previous_stage = _previous_stage(stage)
        serialized = [(item_id, _dump_payload(payload)) for item_id, payload in results]
        item_ids = [item_id for item_id, _ in serialized]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError(f"阶段 {stage} 的批量结果包含重复条目")
        proposed = {item_id: (payload_json, model_version) for item_id, payload_json in serialized}
        proposed_generation = (
            _selection_generation(serialized, model_version) if stage == "select" else None
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for snapshot in expected_selection_inputs or ():
                current_generation = _selection_input_generation(
                    connection,
                    top_scene=snapshot.top_scene,
                    sub_scene=snapshot.sub_scene,
                )
                if current_generation != snapshot.generation:
                    raise ValueError(
                        f"选择输入快照已变化，拒绝覆盖旧结果: {snapshot.sub_scene}"
                    )
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
            existing_generation_row = connection.execute(
                "SELECT generation_id FROM stage_generations WHERE stage = ?", (stage,)
            ).fetchone()
            existing_generation = (
                str(existing_generation_row[0]) if existing_generation_row is not None else None
            )
            if existing == proposed and (
                stage != "select" or existing_generation == proposed_generation
            ):
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
                connection.execute("DELETE FROM stage_generations WHERE stage = ?", (descendant,))
            if stage in {"clean", "dedupe", "classify", "select"}:
                connection.execute("DELETE FROM translation_repairs")
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
            if proposed_generation is not None:
                connection.execute(
                    """
                    INSERT INTO stage_generations(stage, generation_id, updated_at)
                    VALUES ('select', ?, ?)
                    ON CONFLICT(stage) DO UPDATE SET
                        generation_id = excluded.generation_id,
                        updated_at = excluded.updated_at
                    """,
                    (proposed_generation, updated_at),
                )
        return True

    def claim_translation_batch(self, limit: int) -> TranslationBatch | None:
        if limit < 1:
            return None
        with self.connect() as connection:
            connection.execute("BEGIN")
            generation_row = connection.execute(
                "SELECT generation_id FROM stage_generations WHERE stage = 'select'"
            ).fetchone()
            rows = connection.execute(
                """
                SELECT r.id, r.source_name, r.source_item_id, r.source_url, r.source_author,
                       r.license_name, r.license_url, r.text, r.protected,
                       r.top_scene, r.sub_scene
                FROM raw_items AS r
                JOIN stage_results AS selected
                  ON selected.item_id = r.id AND selected.stage = 'select'
                LEFT JOIN stage_results AS translated
                  ON translated.item_id = r.id AND translated.stage = 'translate'
                LEFT JOIN translation_repairs AS repair ON repair.item_id = r.id
                LEFT JOIN rejections AS rejected ON rejected.item_id = r.id
                WHERE translated.item_id IS NULL
                  AND repair.item_id IS NULL
                  AND rejected.item_id IS NULL
                ORDER BY r.id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        if not rows:
            return None
        if generation_row is None:
            raise RuntimeError("当前选择快照缺少 generation，无法领取翻译批次")
        return TranslationBatch(
            selection_generation=str(generation_row[0]),
            items=tuple(_work_item(row) for row in rows),
        )

    def checkpoint_translation_batch(
        self,
        results: list[tuple[int, str, tuple[str, ...]]],
        *,
        model_version: str,
        selection_generation: str,
    ) -> None:
        item_ids = [item_id for item_id, _, _ in results]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("翻译批次包含重复条目")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_generation = connection.execute(
                "SELECT generation_id FROM stage_generations WHERE stage = 'select'"
            ).fetchone()
            if current_generation != (selection_generation,):
                raise ValueError("选择快照已变化，拒绝写入旧 generation 的翻译批次")
            selected_rows = {
                int(row[0]): str(row[1])
                for row in connection.execute(
                    f"""
                    SELECT item_id, payload_json FROM stage_results
                    WHERE stage='select' AND item_id IN ({_placeholders(item_ids)})
                    """,
                    item_ids,
                )
            }
            eligible = set(selected_rows)
            rejected = {
                int(row[0])
                for row in connection.execute(
                    f"SELECT item_id FROM rejections WHERE item_id IN ({_placeholders(item_ids)})",
                    item_ids,
                )
            }
            invalid = sorted((set(item_ids) - eligible) | (set(item_ids) & rejected))
            if invalid:
                raise ValueError(f"翻译批次包含不可写条目: {invalid}")

            updated_at = _now()
            for item_id, translation, issues in results:
                connection.execute(
                    "DELETE FROM stage_results WHERE item_id = ? AND stage = 'variants'",
                    (item_id,),
                )
                if issues:
                    connection.execute(
                        "DELETE FROM stage_results WHERE item_id = ? AND stage = 'translate'",
                        (item_id,),
                    )
                    connection.execute(
                        """
                        INSERT INTO translation_repairs(
                            item_id, draft, issues_json, model_version, review_note,
                            selection_generation, updated_at
                        ) VALUES (?, ?, ?, ?, '', ?, ?)
                        ON CONFLICT(item_id) DO UPDATE SET
                            draft = excluded.draft,
                            issues_json = excluded.issues_json,
                            model_version = excluded.model_version,
                            review_note = '',
                            selection_generation = excluded.selection_generation,
                            updated_at = excluded.updated_at
                        """,
                        (
                            item_id,
                            translation,
                            json.dumps(issues),
                            model_version,
                            selection_generation,
                            updated_at,
                        ),
                    )
                    continue
                connection.execute("DELETE FROM translation_repairs WHERE item_id = ?", (item_id,))
                connection.execute(
                    """
                    INSERT INTO stage_results(
                        item_id, stage, payload_json, model_version, updated_at
                    ) VALUES (?, 'translate', ?, ?, ?)
                    ON CONFLICT(item_id, stage) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        model_version = excluded.model_version,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item_id,
                        _dump_payload({"translation_zh": translation, "issues": []}),
                        model_version,
                        updated_at,
                    ),
                )
                _materialize_cached_variants(
                    connection,
                    item_id=item_id,
                    select_payload_json=selected_rows[item_id],
                    updated_at=updated_at,
                )

    def translation_repairs(self) -> list[TranslationRepair]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT r.id, r.source_name, r.source_item_id, r.source_url, r.source_author,
                       r.license_name, r.license_url, r.text, r.protected,
                       r.top_scene, r.sub_scene, repair.draft, repair.issues_json,
                       repair.model_version, selected.payload_json, repair.review_note,
                       repair.selection_generation
                FROM translation_repairs AS repair
                JOIN raw_items AS r ON r.id = repair.item_id
                JOIN stage_results AS selected
                  ON selected.item_id = r.id AND selected.stage = 'select'
                JOIN stage_generations AS generation
                  ON generation.stage = 'select'
                 AND generation.generation_id = repair.selection_generation
                ORDER BY r.id
                """
            ).fetchall()
        repairs: list[TranslationRepair] = []
        for row in rows:
            selected = json.loads(row[14])
            repairs.append(
                TranslationRepair(
                    item=_work_item(row),
                    draft=str(row[11]),
                    issues=tuple(str(issue) for issue in json.loads(row[12])),
                    model_version=str(row[13]),
                    top_scene=str(selected.get("top_scene") or ""),
                    sub_scene=str(selected.get("sub_scene") or ""),
                    review_note=str(row[15]),
                    selection_generation=str(row[16]),
                )
            )
        return repairs

    def apply_translation_repair(
        self,
        item_id: int,
        *,
        translation: str,
        issues: tuple[str, ...],
        review_note: str,
    ) -> bool:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            repair = connection.execute(
                """
                SELECT model_version, selection_generation
                FROM translation_repairs
                WHERE item_id = ?
                """,
                (item_id,),
            ).fetchone()
            if repair is None:
                raise ValueError(f"条目 {item_id} 不在待修正队列中")
            current_generation = connection.execute(
                "SELECT generation_id FROM stage_generations WHERE stage = 'select'"
            ).fetchone()
            if current_generation != (str(repair[1]),):
                raise ValueError(f"条目 {item_id} 的选择快照已变化")
            selected = connection.execute(
                "SELECT payload_json FROM stage_results WHERE item_id = ? AND stage = 'select'",
                (item_id,),
            ).fetchone()
            if selected is None:
                raise ValueError(f"条目 {item_id} 已不在当前选择快照中")
            updated_at = _now()
            if issues:
                connection.execute(
                    """
                    UPDATE translation_repairs
                    SET draft = ?, issues_json = ?, review_note = ?, updated_at = ?
                    WHERE item_id = ?
                    """,
                    (translation, json.dumps(issues), review_note, updated_at, item_id),
                )
                return False

            connection.execute("DELETE FROM translation_repairs WHERE item_id = ?", (item_id,))
            connection.execute(
                """
                INSERT INTO stage_results(item_id, stage, payload_json, model_version, updated_at)
                VALUES (?, 'translate', ?, 'llm-repair', ?)
                ON CONFLICT(item_id, stage) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    model_version = excluded.model_version,
                    updated_at = excluded.updated_at
                """,
                (
                    item_id,
                    _dump_payload(
                        {
                            "translation_zh": translation,
                            "issues": [],
                            "review_note": review_note,
                            "source_model_version": str(repair[0]),
                            "repair_processor_version": "llm-repair",
                        }
                    ),
                    updated_at,
                ),
            )
            _materialize_cached_variants(
                connection,
                item_id=item_id,
                select_payload_json=str(selected[0]),
                updated_at=updated_at,
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
        if stage == "select":
            raise ValueError("select 阶段必须使用 replace_stage 写入完整原子快照")
        previous_stage = _previous_stage(stage)
        payload_json = _dump_payload(payload)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE" if stage == "classify" else "BEGIN")
            existing_generation = None
            if stage == "classify":
                existing_generation = connection.execute(
                    """
                    SELECT payload_json, model_version
                    FROM stage_results
                    WHERE item_id = ? AND stage = ?
                    """,
                    (item_id, stage),
                ).fetchone()
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
            if existing_generation == (payload_json, model_version):
                return
            if stage == "classify":
                _invalidate_selection_snapshot(connection)
            connection.execute(
                """
                INSERT INTO stage_results(item_id, stage, payload_json, model_version, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id, stage) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    model_version = excluded.model_version,
                    updated_at = excluded.updated_at
                """,
                (item_id, stage, payload_json, model_version, _now()),
            )

    def record_rejection(self, item_id: int, stage: str, reason: str) -> None:
        _previous_stage(stage)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT stage, reason FROM rejections WHERE item_id = ?", (item_id,)
            ).fetchone()
            if existing == (stage, reason):
                return
            _invalidate_selection_snapshot(connection)
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
        CREATE TABLE IF NOT EXISTS translation_repairs(
            item_id INTEGER PRIMARY KEY REFERENCES raw_items(id),
            draft TEXT NOT NULL,
            issues_json TEXT NOT NULL,
            model_version TEXT NOT NULL,
            review_note TEXT NOT NULL DEFAULT '',
            selection_generation TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stage_generations(
            stage TEXT PRIMARY KEY,
            generation_id TEXT NOT NULL,
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
        """
        CREATE TABLE IF NOT EXISTS dedupe_fingerprints(
            item_id INTEGER PRIMARY KEY REFERENCES raw_items(id),
            normalized_hash TEXT NOT NULL,
            simhash64 TEXT NOT NULL,
            band0 INTEGER NOT NULL,
            band1 INTEGER NOT NULL,
            band2 INTEGER NOT NULL,
            band3 INTEGER NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_stage_results_stage ON stage_results(stage, item_id)",
        """
        CREATE INDEX IF NOT EXISTS idx_classify_sub_scene
        ON stage_results(json_extract(payload_json, '$.sub_scene'), item_id)
        WHERE stage='classify'
        """,
        "CREATE INDEX IF NOT EXISTS idx_rejections_stage ON rejections(stage, item_id)",
        "CREATE INDEX IF NOT EXISTS idx_dedupe_hash ON dedupe_fingerprints(normalized_hash)",
        "CREATE INDEX IF NOT EXISTS idx_dedupe_band0 ON dedupe_fingerprints(band0)",
        "CREATE INDEX IF NOT EXISTS idx_dedupe_band1 ON dedupe_fingerprints(band1)",
        "CREATE INDEX IF NOT EXISTS idx_dedupe_band2 ON dedupe_fingerprints(band2)",
        "CREATE INDEX IF NOT EXISTS idx_dedupe_band3 ON dedupe_fingerprints(band3)",
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _placeholders(values: list[int]) -> str:
    return ",".join("?" for _ in values) or "NULL"


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


def _stage_input(row: tuple[Any, ...]) -> StageInput:
    return StageInput(
        item=_work_item(row),
        predecessor_payload=json.loads(row[11]),
        stage_payload=json.loads(row[12]) if row[12] is not None else None,
    )


_SELECTION_INPUT_QUERY = """
    SELECT r.id, r.source_name, r.source_item_id, r.source_url,
           r.source_author, r.license_name, r.license_url,
           COALESCE(json_extract(cleaned.payload_json, '$.clean_text'), r.text),
           r.protected, r.top_scene, r.sub_scene, classified.payload_json, NULL
    FROM stage_results AS classified
    JOIN raw_items AS r ON r.id=classified.item_id
    JOIN stage_results AS cleaned
      ON cleaned.item_id=r.id AND cleaned.stage='clean'
    LEFT JOIN rejections AS rejected ON rejected.item_id=r.id
    WHERE classified.stage='classify'
      AND json_extract(classified.payload_json, '$.sub_scene')=?
      AND json_extract(classified.payload_json, '$.top_scene')=?
      AND r.protected=?
      AND rejected.item_id IS NULL
    ORDER BY json_extract(classified.payload_json, '$.confidence') DESC, r.id
"""


def _protected_selection_conflicts(
    connection: sqlite3.Connection,
    *,
    top_scene: str,
    sub_scene: str,
    quota: int,
    source_limit: int,
    author_limit: int,
) -> list[str]:
    parameters = (sub_scene, top_scene)
    protected_cte = """
        WITH protected AS (
            SELECT r.source_name, trim(r.source_author) AS source_author
            FROM stage_results AS classified
            JOIN raw_items AS r ON r.id=classified.item_id
            JOIN stage_results AS cleaned
              ON cleaned.item_id=r.id AND cleaned.stage='clean'
            LEFT JOIN rejections AS rejected ON rejected.item_id=r.id
            WHERE classified.stage='classify'
              AND json_extract(classified.payload_json, '$.sub_scene')=?
              AND json_extract(classified.payload_json, '$.top_scene')=?
              AND r.protected=1
              AND rejected.item_id IS NULL
        )
    """
    total = int(
        connection.execute(
            protected_cte + "SELECT COUNT(*) FROM protected", parameters
        ).fetchone()[0]
    )
    source_conflicts = connection.execute(
        protected_cte
        + """
        SELECT source_name, COUNT(*) AS count
        FROM protected GROUP BY source_name HAVING count>?
        ORDER BY count DESC, source_name LIMIT 8
        """,
        (*parameters, source_limit),
    ).fetchall()
    author_conflicts = connection.execute(
        protected_cte
        + """
        SELECT source_author, COUNT(*) AS count
        FROM protected WHERE source_author<>''
        GROUP BY source_author HAVING count>?
        ORDER BY count DESC, source_author LIMIT 8
        """,
        (*parameters, author_limit),
    ).fetchall()
    conflicts: list[str] = []
    if total > quota:
        conflicts.append(f"protected quota conflict in {sub_scene}: {total} > {quota}")
    conflicts.extend(
        f"protected source conflict in {sub_scene}: {str(source)!r} {count} > {source_limit}"
        for source, count in source_conflicts
    )
    conflicts.extend(
        f"protected author conflict in {sub_scene}: {str(author)!r} {count} > {author_limit}"
        for author, count in author_conflicts
    )
    return conflicts


def _update_selection_input_digest(digest: Any, row: tuple[Any, ...]) -> None:
    canonical = json.dumps(
        list(row), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    digest.update(canonical.encode("utf-8"))
    digest.update(b"\n")


def _selection_input_generation(
    connection: sqlite3.Connection,
    *,
    top_scene: str,
    sub_scene: str,
) -> str:
    digest = hashlib.sha256()
    for protected in (1, 0):
        cursor = connection.execute(
            _SELECTION_INPUT_QUERY,
            (sub_scene, top_scene, protected),
        )
        while rows := cursor.fetchmany(512):
            for row in rows:
                _update_selection_input_digest(digest, row)
    return digest.hexdigest()


def _dump_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _materialize_cached_variants(
    connection: sqlite3.Connection,
    *,
    item_id: int,
    select_payload_json: str,
    updated_at: str,
) -> None:
    try:
        selected = json.loads(select_payload_json)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"条目 {item_id} 的 select payload 无效") from error
    if not isinstance(selected, dict):
        raise ValueError(f"条目 {item_id} 的 select payload 无效")
    gate_version = selected.get("variant_gate_version")
    if gate_version is None:
        return
    if gate_version != 1:
        raise ValueError(f"条目 {item_id} 的 variant gate 版本无效")
    variants = selected.get("variants")
    if (
        not isinstance(variants, list)
        or len(variants) != 3
        or any(not isinstance(variant, dict) for variant in variants)
        or [variant.get("difficulty") for variant in variants] != ["easy", "medium", "hard"]
    ):
        raise ValueError(f"条目 {item_id} 的缓存 variants 无效")
    connection.execute(
        """
        INSERT INTO stage_results(item_id, stage, payload_json, model_version, updated_at)
        VALUES (?, 'variants', ?, 'selection-variant-gate-v1', ?)
        ON CONFLICT(item_id, stage) DO UPDATE SET
            payload_json = excluded.payload_json,
            model_version = excluded.model_version,
            updated_at = excluded.updated_at
        """,
        (item_id, _dump_payload({"variants": variants}), updated_at),
    )


def _validate_classification_payload(item_id: int, payload_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError) as error:
        raise ValueError(f"条目 {item_id} 的 classify 载荷损坏") from error
    if not isinstance(payload, dict):
        raise ValueError(f"条目 {item_id} 的 classify 载荷必须是对象")
    if not {"top_scene", "sub_scene", "method", "confidence"} <= set(payload):
        raise ValueError(f"条目 {item_id} 的 classify 载荷缺少状态字段")
    top_scene = payload["top_scene"]
    sub_scene = payload["sub_scene"]
    method = payload["method"]
    if not isinstance(method, str) or not method.strip():
        raise ValueError(f"条目 {item_id} 的 classify 载荷 method 非法")
    allowed_methods = _POSITIVE_CLASSIFICATION_METHODS | _NULL_CLASSIFICATION_METHODS
    if method not in allowed_methods:
        raise ValueError(f"条目 {item_id} 的 classify 载荷 method 未知")
    confidence = payload["confidence"]
    try:
        confidence_value = float(confidence)
    except (OverflowError, TypeError, ValueError):
        confidence_value = math.nan
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not (math.isfinite(confidence_value) and 0.0 <= confidence_value <= 1.0)
    ):
        raise ValueError(f"条目 {item_id} 的 classify 载荷 confidence 非法")
    if method in _CLASSIFICATION_REASON_METHODS:
        reason = payload.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"条目 {item_id} 的 classify 载荷 reason 非法")
    if (top_scene is None) != (sub_scene is None):
        raise ValueError(f"条目 {item_id} 的 classify 载荷场景状态不完整")
    if top_scene is None:
        if method not in _NULL_CLASSIFICATION_METHODS:
            raise ValueError(f"条目 {item_id} 的 classify 载荷 method 与空场景不一致")
        return payload
    scene = SUB_SCENES.get(sub_scene) if isinstance(sub_scene, str) else None
    if not isinstance(top_scene, str) or scene is None or scene.top_key != top_scene:
        raise ValueError(f"条目 {item_id} 的 classify 载荷包含非法场景")
    if method not in _POSITIVE_CLASSIFICATION_METHODS:
        raise ValueError(f"条目 {item_id} 的 classify 载荷 method 与正向场景不一致")
    return payload


def _stage_descendants(stage: str) -> tuple[str, ...]:
    stages = tuple(STAGE_PREDECESSORS)
    return stages[stages.index(stage) + 1 :]


def _migrate_raw_scene_columns(connection: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(raw_items)")}
    if "top_scene" not in columns:
        connection.execute("ALTER TABLE raw_items ADD COLUMN top_scene TEXT")
    if "sub_scene" not in columns:
        connection.execute("ALTER TABLE raw_items ADD COLUMN sub_scene TEXT")


def _migrate_translation_generation(connection: sqlite3.Connection) -> None:
    repair_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(translation_repairs)")
    }
    if "selection_generation" not in repair_columns:
        connection.execute(
            "ALTER TABLE translation_repairs "
            "ADD COLUMN selection_generation TEXT NOT NULL DEFAULT ''"
        )
    selected = [
        (int(item_id), str(payload_json))
        for item_id, payload_json in connection.execute(
            "SELECT item_id, payload_json FROM stage_results WHERE stage = 'select'"
        )
    ]
    if not selected:
        connection.execute("DELETE FROM translation_repairs")
        connection.execute("DELETE FROM stage_generations WHERE stage = 'select'")
        return
    model_versions = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT model_version FROM stage_results WHERE stage = 'select'"
        )
    }
    if len(model_versions) != 1:
        raise RuntimeError("历史 select 快照包含不一致的 model_version")
    model_version = model_versions.pop()
    generation = _selection_generation(selected, model_version)
    connection.execute(
        """
        INSERT INTO stage_generations(stage, generation_id, updated_at)
        VALUES ('select', ?, ?)
        ON CONFLICT(stage) DO UPDATE SET generation_id = excluded.generation_id
        """,
        (generation, _now()),
    )
    connection.execute(
        """
        UPDATE translation_repairs
        SET selection_generation = ?
        WHERE selection_generation = ''
        """,
        (generation,),
    )


def _migrate_classification_rejections(connection: sqlite3.Connection) -> None:
    """把旧版 LLM 明确拒绝与尚未审核的候选池状态永久区分。"""
    connection.execute(
        """
        UPDATE stage_results
        SET payload_json=json_set(payload_json, '$.method', 'llm_rejected')
        WHERE stage='classify'
          AND model_version='llm-repair'
          AND json_extract(payload_json, '$.method')='out_of_candidate_pool'
        """
    )


def _selection_generation(serialized: list[tuple[int, str]], model_version: str) -> str:
    target = [
        {"item_id": item_id, "payload_json": payload_json, "model_version": model_version}
        for item_id, payload_json in sorted(serialized)
    ]
    canonical = json.dumps(target, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _invalidate_selection_snapshot(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "DELETE FROM stage_results WHERE stage = ?",
        ((stage,) for stage in ("select", "translate", "variants")),
    )
    connection.execute("DELETE FROM translation_repairs")
    connection.execute("DELETE FROM stage_generations WHERE stage = 'select'")
