from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from tools.content_pipeline.scenes import SUB_SCENES
from tools.content_pipeline.selection import select_scene_partial
from tools.content_pipeline.work_database import WorkDatabase


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    name: str
    revision: str
    sha256: str


@dataclass(frozen=True, slots=True)
class RecallScene:
    sub_scene: str
    prototypes: tuple[str, ...]
    top_k: int


@dataclass(frozen=True, slots=True)
class _RecallSelectionRow:
    id: int
    text: str
    source_name: str
    source_author: str
    top_scene: str
    sub_scene: str
    confidence: float
    protected: bool


@dataclass(frozen=True, slots=True)
class SelectionCapacity:
    source_limit: int
    author_limit: int
    source_counts: Counter[str]
    author_counts: Counter[str]

    def allows(self, source_name: str, source_author: str) -> bool:
        if self.source_counts[source_name] >= self.source_limit:
            return False
        author = source_author.strip()
        return not author or self.author_counts[author] < self.author_limit

    def fingerprint_payload(self) -> dict[str, object]:
        return {
            "source_limit": self.source_limit,
            "author_limit": self.author_limit,
            "source_counts": dict(sorted(self.source_counts.items())),
            "author_counts": dict(sorted(self.author_counts.items())),
        }


class Embedder(Protocol):
    metadata: ModelMetadata

    def encode(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_path: Path, metadata: ModelMetadata, *, device: str = "cpu") -> None:
        actual = directory_sha256(model_path)
        if actual != metadata.sha256:
            raise ValueError(
                f"模型目录 SHA-256 不匹配: expected={metadata.sha256}, actual={actual}"
            )
        if model_path.name != metadata.revision:
            raise ValueError(
                f"模型目录 revision 不匹配: expected={metadata.revision}, actual={model_path.name}"
            )
        from sentence_transformers import SentenceTransformer

        self.metadata = metadata
        self._model = SentenceTransformer(str(model_path), device=device)

    def encode(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )


def directory_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(child for child in path.rglob("*") if child.is_file()):
        digest.update(str(child.relative_to(path)).encode())
        digest.update(child.read_bytes())
    return digest.hexdigest()


def run_semantic_recall(
    database: WorkDatabase,
    *,
    sub_scene: str,
    prototypes: tuple[str, ...],
    embedder: Embedder,
    output_path: Path,
    checkpoint_path: Path,
    exclude_ids: set[int],
    top_k: int,
    batch_size: int,
) -> dict[str, int | bool]:
    if not prototypes:
        raise ValueError("语义召回至少需要一条原型句")
    if top_k < 1 or batch_size < 1:
        raise ValueError("top_k 与 batch_size 必须大于 0")
    capacity = selection_capacity(database, sub_scene)
    fingerprint = _fingerprint(
        sub_scene=sub_scene,
        prototypes=prototypes,
        metadata=embedder.metadata,
        exclude_ids=exclude_ids,
        top_k=top_k,
        batch_size=batch_size,
        capacity=capacity,
    )
    state = _load_checkpoint(checkpoint_path, fingerprint)
    resumed = state is not None
    if state is None:
        state = {
            "fingerprint": fingerprint,
            "model": asdict(embedder.metadata),
            "sub_scene": sub_scene,
            "last_item_id": 0,
            "processed": 0,
            "heap": [],
            "completed": False,
        }
    if bool(state["completed"]) and output_path.exists():
        return {
            "processed": int(state["processed"]),
            "selected": len(state["heap"]),
            "resumed": True,
        }

    prototype_vectors = _normalize(embedder.encode(list(prototypes)))
    heap = [_heap_entry(row) for row in state["heap"]]
    heapq.heapify(heap)
    last_item_id = int(state["last_item_id"])
    processed = int(state["processed"])
    with database.connect() as connection:
        cursor = connection.execute(
            """
            SELECT r.id, r.text, r.source_name, r.source_author
            FROM stage_results AS classified
            JOIN raw_items AS r ON r.id=classified.item_id
            LEFT JOIN rejections AS rejected ON rejected.item_id=r.id
            WHERE classified.stage='classify'
              AND json_extract(
                    classified.payload_json, '$.method'
                  )='out_of_candidate_pool'
              AND rejected.item_id IS NULL
              AND r.id > ?
            ORDER BY r.id
            """,
            (last_item_id,),
        )
        while raw_rows := cursor.fetchmany(batch_size):
            last_item_id = int(raw_rows[-1][0])
            rows = [
                row
                for row in raw_rows
                if int(row[0]) not in exclude_ids
                and capacity.allows(str(row[2]), str(row[3]))
            ]
            if rows:
                vectors = _normalize(embedder.encode([str(row[1]) for row in rows]))
                similarities = np.max(vectors @ prototype_vectors.T, axis=1)
                for similarity, row in zip(similarities, rows, strict=True):
                    item_id = int(row[0])
                    entry = (
                        float(similarity),
                        -item_id,
                        {
                            "item_id": item_id,
                            "text": str(row[1]),
                            "source_name": str(row[2]),
                            "source_author": str(row[3]),
                            "similarity": float(similarity),
                            "suggested_scene": sub_scene,
                        },
                    )
                    if len(heap) < top_k:
                        heapq.heappush(heap, entry)
                    elif entry[:2] > heap[0][:2]:
                        heapq.heapreplace(heap, entry)
                processed += len(rows)
            state.update(
                {
                    "last_item_id": last_item_id,
                    "processed": processed,
                    "heap": _checkpoint_rows(heap),
                }
            )
            _write_json_atomic(checkpoint_path, state)

    ranked = [entry[2] for entry in sorted(heap, key=lambda entry: (-entry[0], -entry[1]))]
    _write_jsonl_atomic(output_path, ranked)
    state.update({"heap": ranked, "completed": True})
    _write_json_atomic(checkpoint_path, state)
    return {"processed": processed, "selected": len(ranked), "resumed": resumed}


def run_semantic_recall_many(
    database: WorkDatabase,
    *,
    scenes: tuple[RecallScene, ...],
    embedder: Embedder,
    output_dir: Path,
    checkpoint_path: Path,
    exclude_ids: set[int],
    batch_size: int,
) -> dict[str, object]:
    """一次编码候选批次，同时维护多个场景的确定性 Top-K。"""
    _validate_recall_scenes(scenes, batch_size)
    capacities = {
        scene.sub_scene: selection_capacity(database, scene.sub_scene) for scene in scenes
    }
    fingerprint = _fingerprint_many(
        scenes=scenes,
        metadata=embedder.metadata,
        exclude_ids=exclude_ids,
        batch_size=batch_size,
        capacities=capacities,
    )
    state = _load_checkpoint(checkpoint_path, fingerprint)
    resumed = state is not None
    if state is None:
        state = {
            "fingerprint": fingerprint,
            "model": asdict(embedder.metadata),
            "scenes": [asdict(scene) for scene in scenes],
            "last_item_id": 0,
            "processed": 0,
            "heaps": {scene.sub_scene: [] for scene in scenes},
            "completed": False,
        }
    output_paths = {
        scene.sub_scene: output_dir / f"{scene.sub_scene}.jsonl" for scene in scenes
    }
    state_heaps = state.get("heaps")
    if not isinstance(state_heaps, dict):
        raise ValueError("语义召回 checkpoint heaps 格式非法")
    if bool(state["completed"]) and all(path.exists() for path in output_paths.values()):
        return {
            "processed": int(state["processed"]),
            "selected": {
                scene.sub_scene: len(_checkpoint_heap(state_heaps, scene.sub_scene))
                for scene in scenes
            },
            "resumed": True,
        }

    prototype_texts = [prototype for scene in scenes for prototype in scene.prototypes]
    all_prototype_vectors = _normalize(embedder.encode(prototype_texts))
    prototype_vectors: dict[str, np.ndarray] = {}
    offset = 0
    for scene in scenes:
        next_offset = offset + len(scene.prototypes)
        prototype_vectors[scene.sub_scene] = all_prototype_vectors[offset:next_offset]
        offset = next_offset
    heaps = {
        scene.sub_scene: [
            _heap_entry(row) for row in _checkpoint_heap(state_heaps, scene.sub_scene)
        ]
        for scene in scenes
    }
    for heap in heaps.values():
        heapq.heapify(heap)

    last_item_id = int(state["last_item_id"])
    processed = int(state["processed"])
    with database.connect() as connection:
        cursor = connection.execute(
            """
            SELECT r.id, r.text, r.source_name, r.source_author
            FROM stage_results AS classified
            JOIN raw_items AS r ON r.id=classified.item_id
            LEFT JOIN rejections AS rejected ON rejected.item_id=r.id
            WHERE classified.stage='classify'
              AND json_extract(
                    classified.payload_json, '$.method'
                  )='out_of_candidate_pool'
              AND rejected.item_id IS NULL
              AND r.id > ?
            ORDER BY r.id
            """,
            (last_item_id,),
        )
        while raw_rows := cursor.fetchmany(batch_size):
            last_item_id = int(raw_rows[-1][0])
            rows = [row for row in raw_rows if int(row[0]) not in exclude_ids]
            if rows:
                vectors = _normalize(embedder.encode([str(row[1]) for row in rows]))
                for scene in scenes:
                    allowed_indexes = [
                        index
                        for index, row in enumerate(rows)
                        if capacities[scene.sub_scene].allows(str(row[2]), str(row[3]))
                    ]
                    if not allowed_indexes:
                        continue
                    similarities = np.max(
                        vectors[allowed_indexes] @ prototype_vectors[scene.sub_scene].T,
                        axis=1,
                    )
                    heap = heaps[scene.sub_scene]
                    allowed_rows = [rows[index] for index in allowed_indexes]
                    for similarity, row in zip(similarities, allowed_rows, strict=True):
                        item_id = int(row[0])
                        entry = (
                            float(similarity),
                            -item_id,
                            {
                                "item_id": item_id,
                                "text": str(row[1]),
                                "source_name": str(row[2]),
                                "source_author": str(row[3]),
                                "similarity": float(similarity),
                                "suggested_scene": scene.sub_scene,
                            },
                        )
                        if len(heap) < scene.top_k:
                            heapq.heappush(heap, entry)
                        elif entry[:2] > heap[0][:2]:
                            heapq.heapreplace(heap, entry)
                processed += len(rows)
            state.update(
                {
                    "last_item_id": last_item_id,
                    "processed": processed,
                    "heaps": {
                        sub_scene: _checkpoint_rows(heap)
                        for sub_scene, heap in heaps.items()
                    },
                }
            )
            _write_json_atomic(checkpoint_path, state)

    ranked = {
        sub_scene: [
            entry[2] for entry in sorted(heap, key=lambda entry: (-entry[0], -entry[1]))
        ]
        for sub_scene, heap in heaps.items()
    }
    for sub_scene, rows in ranked.items():
        _write_jsonl_atomic(output_paths[sub_scene], rows)
    state.update({"heaps": ranked, "completed": True})
    _write_json_atomic(checkpoint_path, state)
    return {
        "processed": processed,
        "selected": {sub_scene: len(rows) for sub_scene, rows in sorted(ranked.items())},
        "resumed": resumed,
    }


def selection_capacity(database: WorkDatabase, sub_scene: str) -> SelectionCapacity:
    scene = SUB_SCENES[sub_scene]
    candidates = []
    for stage_input in database.bounded_selection_candidates(sub_scene, quota=scene.quota):
        payload = stage_input.predecessor_payload
        item = stage_input.item
        candidates.append(
            _RecallSelectionRow(
                id=item.id,
                text=item.text,
                source_name=item.source_name,
                source_author=item.source_author,
                top_scene=str(payload.get("top_scene") or ""),
                sub_scene=str(payload.get("sub_scene") or ""),
                confidence=float(payload.get("confidence") or 0.0),
                protected=item.protected,
            )
        )
    selected = select_scene_partial(scene, candidates)
    return SelectionCapacity(
        source_limit=max(1, math.floor(scene.quota * 0.45)),
        author_limit=max(1, math.floor(scene.quota * 0.08)),
        source_counts=Counter(row.source_name for row in selected),
        author_counts=Counter(
            row.source_author.strip() for row in selected if row.source_author.strip()
        ),
    )


def _validate_recall_scenes(scenes: tuple[RecallScene, ...], batch_size: int) -> None:
    if not scenes:
        raise ValueError("语义召回至少需要一个场景")
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")
    scene_keys = [scene.sub_scene for scene in scenes]
    if len(scene_keys) != len(set(scene_keys)):
        raise ValueError("语义召回场景不能重复")
    for scene in scenes:
        if scene.sub_scene not in SUB_SCENES:
            raise ValueError(f"未知场景: {scene.sub_scene}")
        if not scene.prototypes:
            raise ValueError(f"{scene.sub_scene} 至少需要一条原型句")
        if scene.top_k < 1:
            raise ValueError(f"{scene.sub_scene} top_k 必须大于 0")


def _checkpoint_heap(heaps: dict[object, object], sub_scene: str) -> list[object]:
    rows = heaps.get(sub_scene)
    if not isinstance(rows, list):
        raise ValueError(f"语义召回 checkpoint 缺少场景 heap: {sub_scene}")
    return rows


def _normalize(vectors: np.ndarray) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    return array / np.maximum(norms, np.finfo(np.float32).eps)


def _fingerprint(
    *,
    sub_scene: str,
    prototypes: tuple[str, ...],
    metadata: ModelMetadata,
    exclude_ids: set[int],
    top_k: int,
    batch_size: int,
    capacity: SelectionCapacity,
) -> str:
    payload = json.dumps(
        {
            "sub_scene": sub_scene,
            "prototypes": prototypes,
            "model": asdict(metadata),
            "exclude_ids": sorted(exclude_ids),
            "top_k": top_k,
            "batch_size": batch_size,
            "capacity": capacity.fingerprint_payload(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _fingerprint_many(
    *,
    scenes: tuple[RecallScene, ...],
    metadata: ModelMetadata,
    exclude_ids: set[int],
    batch_size: int,
    capacities: dict[str, SelectionCapacity],
) -> str:
    payload = json.dumps(
        {
            "scenes": [asdict(scene) for scene in scenes],
            "model": asdict(metadata),
            "exclude_ids": sorted(exclude_ids),
            "batch_size": batch_size,
            "capacities": {
                key: capacity.fingerprint_payload()
                for key, capacity in sorted(capacities.items())
            },
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_checkpoint(path: Path, fingerprint: str) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取语义召回 checkpoint: {error}") from error
    if not isinstance(state, dict) or state.get("fingerprint") != fingerprint:
        raise ValueError("语义召回 checkpoint 与当前模型或参数不匹配")
    return state


def _heap_entry(row: object) -> tuple[float, int, dict[str, object]]:
    if not isinstance(row, dict):
        raise ValueError("语义召回 checkpoint heap 格式非法")
    item_id = int(row["item_id"])
    return float(row["similarity"]), -item_id, row


def _checkpoint_rows(
    heap: list[tuple[float, int, dict[str, object]]],
) -> list[dict[str, object]]:
    return [entry[2] for entry in heap]


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_jsonl_atomic(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)
