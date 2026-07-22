from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tools.content_pipeline.categorize import SceneClassifier
from tools.content_pipeline.semantic_recall import selection_capacity
from tools.content_pipeline.work_database import WorkDatabase


@dataclass(frozen=True, slots=True)
class _LexicalRankedRow:
    id: int
    text: str
    source_name: str
    source_author: str
    confidence: float
    payload: dict[str, object]


def run_lexical_conflict_recall(
    database: WorkDatabase,
    *,
    sub_scene: str,
    keywords: tuple[str, ...],
    phrases: tuple[str, ...],
    output_path: Path,
    exclude_ids: set[int],
    top_k: int,
) -> dict[str, int]:
    """只召回包含注册强信号、但因场景冲突未自动分类的记录。"""
    if top_k < 1 or top_k > 500:
        raise ValueError("lexical conflict recall 的 top_k 必须在 1 到 500 之间")
    classifier = SceneClassifier()
    registered_keywords, registered_phrases = classifier.strong_signals(sub_scene)
    requested_keywords = tuple(dict.fromkeys(keyword.casefold() for keyword in keywords))
    requested_phrases = tuple(dict.fromkeys(phrase.casefold() for phrase in phrases))
    invalid_keywords = sorted(set(requested_keywords) - registered_keywords)
    invalid_phrases = sorted(set(requested_phrases) - set(registered_phrases))
    if invalid_keywords or invalid_phrases:
        raise ValueError(
            f"配置项不是 {sub_scene} 的注册强信号: "
            f"keywords={invalid_keywords}, phrases={invalid_phrases}"
        )
    if not requested_keywords and not requested_phrases:
        raise ValueError("lexical conflict recall 至少需要一个注册强信号")

    capacity = selection_capacity(database, sub_scene)
    matches: list[tuple[int, float, float, int, dict[str, object]]] = []
    matched = 0
    with database.connect() as connection:
        rows = connection.execute(
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
            ORDER BY r.id
            """
        )
        for item_id, text, source_name, source_author in rows:
            item_id = int(item_id)
            if item_id in exclude_ids or not capacity.allows(
                str(source_name), str(source_author)
            ):
                continue
            classification = classifier.classify(str(text))
            if classification.method != "llm_required":
                continue
            evidence_keywords, evidence_phrases = classifier.strong_signal_evidence(
                str(text), sub_scene
            )
            trigger_keywords = sorted(set(evidence_keywords).intersection(requested_keywords))
            trigger_phrases = [
                phrase for phrase in requested_phrases if phrase in evidence_phrases
            ]
            if not trigger_keywords and not trigger_phrases:
                continue
            scores = classifier.scene_scores(str(text))
            competitors = sorted(
                ((score, scene) for scene, score in scores.items() if scene != sub_scene),
                key=lambda value: (-value[0], value[1]),
            )
            competing_score, competing_scene = competitors[0]
            target_score = scores[sub_scene]
            if target_score <= 0 or competing_score <= 0:
                continue
            matched += 1
            payload: dict[str, object] = {
                "item_id": item_id,
                "text": str(text),
                "source_name": str(source_name),
                "source_author": str(source_author),
                "suggested_scene": sub_scene,
                "trigger_keywords": trigger_keywords,
                "trigger_phrases": trigger_phrases,
                "target_score": target_score,
                "competing_scene": competing_scene,
                "competing_score": competing_score,
            }
            matches.append(
                (
                    int(bool(trigger_phrases)),
                    target_score,
                    -competing_score,
                    -item_id,
                    payload,
                )
            )

    candidates = [
        _LexicalRankedRow(
            id=int(payload["item_id"]),
            text=str(payload["text"]),
            source_name=str(payload["source_name"]),
            source_author=str(payload["source_author"]),
            confidence=(
                (0.75 if has_phrase else 0.25)
                + min(target_score, 100.0) / 1_000.0
                - min(-negative_competing_score, 100.0) / 100_000.0
            ),
            payload=payload,
        )
        for has_phrase, target_score, negative_competing_score, _, payload in matches
    ]
    selected = capacity.select(candidates, needed=top_k)
    selected.sort(key=lambda row: (-row.confidence, row.id))
    ranked = [row.payload for row in selected]
    _write_jsonl_atomic(output_path, ranked)
    return {"matched": matched, "selected": len(ranked)}


def _write_jsonl_atomic(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)
