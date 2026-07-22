from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tools.content_pipeline.categorize import SceneClassifier
from tools.content_pipeline.classification import (
    ClassificationImportError,
    export_classification_repairs,
    import_classification_repairs,
)
from tools.content_pipeline.clean import clean_sentence, rejection_reason
from tools.content_pipeline.convokit_source import iter_convokit_utterances
from tools.content_pipeline.gutenberg import iter_gutenberg_text
from tools.content_pipeline.historical_replay import (
    HistoricalReplayError,
    replay_classifications,
)
from tools.content_pipeline.lexical_recall import run_lexical_conflict_recall
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.production_sources import (
    import_all_sources,
    import_legacy_database,
    report_sources,
)
from tools.content_pipeline.scenes import SCENES, SUB_SCENES
from tools.content_pipeline.selection import select_scene_quota, select_scene_quotas
from tools.content_pipeline.semantic_recall import (
    ModelMetadata,
    RecallScene,
    SentenceTransformerEmbedder,
    run_semantic_recall,
    run_semantic_recall_many,
)
from tools.content_pipeline.tatoeba import iter_tatoeba_detailed
from tools.content_pipeline.translation import (
    OpusMtTranslator,
    TranslationImportError,
    export_llm_repairs,
    import_llm_repairs,
    run_translation_stage,
)
from tools.content_pipeline.wikinews import iter_wikinews_extracts
from tools.content_pipeline.work_database import WorkDatabase, WorkItem


@dataclass(frozen=True, slots=True)
class _SelectionRow:
    id: int
    text: str
    source_name: str
    source_author: str
    top_scene: str
    sub_scene: str
    confidence: float
    protected: bool


def main() -> None:
    parser = argparse.ArgumentParser(prog="listening-cloze-content")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "status"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("work_db", type=Path)
    import_all_parser = subparsers.add_parser("import-all")
    import_all_parser.add_argument("work_db", type=Path)
    import_all_parser.add_argument("--manifest", type=Path, required=True)
    import_all_parser.add_argument("--lock", type=Path, required=True)
    import_all_parser.add_argument("--refresh-lock", action="store_true")
    import_legacy_parser = subparsers.add_parser("import-legacy")
    import_legacy_parser.add_argument("legacy_db", type=Path)
    import_legacy_parser.add_argument("work_db", type=Path)
    import_legacy_parser.add_argument("--protected", action="store_true")
    report_parser = subparsers.add_parser("report-sources")
    report_parser.add_argument("work_db", type=Path)
    report_parser.add_argument("--output", type=Path, required=True)
    _add_import_parser(subparsers, "import-tatoeba", "path")
    convokit_parser = _add_import_parser(subparsers, "import-convokit", "path")
    convokit_parser.add_argument("source_name", choices=("cornell-movie-dialogs", "switchboard"))
    _add_import_parser(subparsers, "import-wikinews", "path")
    gutenberg_parser = _add_import_parser(subparsers, "import-gutenberg", "path")
    gutenberg_parser.add_argument("ebook_id", type=int)
    clean_parser = subparsers.add_parser("clean")
    clean_parser.add_argument("work_db", type=Path)
    clean_batch_group = clean_parser.add_mutually_exclusive_group()
    clean_batch_group.add_argument("--limit", type=_positive_int)
    clean_batch_group.add_argument("--batch-size", type=_positive_int)
    for command in ("dedupe", "classify"):
        stage_parser = subparsers.add_parser(command)
        stage_parser.add_argument("work_db", type=Path)
        stage_batch_group = stage_parser.add_mutually_exclusive_group()
        stage_batch_group.add_argument("--limit", type=_positive_int)
        stage_batch_group.add_argument("--batch-size", type=_positive_int)
        if command == "classify":
            stage_parser.add_argument("--export-llm", type=Path)
    classification_import = subparsers.add_parser("import-classifications")
    classification_import.add_argument("work_db", type=Path)
    classification_import.add_argument("paths", nargs="+", type=Path)
    replay_parser = subparsers.add_parser("replay-classifications")
    replay_parser.add_argument("work_db", type=Path)
    replay_parser.add_argument(
        "--exchange",
        action="append",
        nargs=2,
        metavar=("REQUEST", "RESULT"),
        type=Path,
        required=True,
    )
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("work_db", type=Path)
    select_parser.add_argument("--exact-quotas", action="store_true")
    recall_parser = subparsers.add_parser("recall-classification")
    recall_parser.add_argument("work_db", type=Path)
    recall_parser.add_argument("--sub-scene", choices=tuple(SUB_SCENES), required=True)
    recall_parser.add_argument("--prototypes", type=Path, required=True)
    recall_parser.add_argument("--model-path", type=Path, required=True)
    recall_parser.add_argument("--model-name", default="sentence-transformers/all-MiniLM-L6-v2")
    recall_parser.add_argument("--model-revision", required=True)
    recall_parser.add_argument("--model-sha256", required=True)
    recall_parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    recall_parser.add_argument("--output", type=Path, required=True)
    recall_parser.add_argument("--checkpoint", type=Path, required=True)
    recall_parser.add_argument("--exclude", type=Path, nargs="*", default=[])
    recall_parser.add_argument("--top-k", type=_recall_top_k, required=True)
    recall_parser.add_argument("--batch-size", type=_positive_int, default=512)
    recalls_parser = subparsers.add_parser("recall-classifications")
    recalls_parser.add_argument("work_db", type=Path)
    recalls_parser.add_argument("--config", type=Path, required=True)
    recalls_parser.add_argument("--model-path", type=Path, required=True)
    recalls_parser.add_argument(
        "--model-name", default="sentence-transformers/all-MiniLM-L6-v2"
    )
    recalls_parser.add_argument("--model-revision", required=True)
    recalls_parser.add_argument("--model-sha256", required=True)
    recalls_parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    recalls_parser.add_argument("--output-dir", type=Path, required=True)
    recalls_parser.add_argument("--checkpoint", type=Path, required=True)
    recalls_parser.add_argument("--exclude", type=Path, nargs="*", default=[])
    recalls_parser.add_argument("--batch-size", type=_positive_int, default=512)
    lexical_recall_parser = subparsers.add_parser("recall-lexical-conflicts")
    lexical_recall_parser.add_argument("work_db", type=Path)
    lexical_recall_parser.add_argument("--config", type=Path, required=True)
    lexical_recall_parser.add_argument("--output", type=Path, required=True)
    lexical_recall_parser.add_argument("--exclude", type=Path, nargs="*", default=[])
    translate_parser = subparsers.add_parser("translate")
    translate_parser.add_argument("work_db", type=Path)
    translate_parser.add_argument("--batch-size", type=int, default=32)
    translate_parser.add_argument("--revision", default="main")
    for command in ("export-llm-repairs", "import-llm-repairs"):
        exchange_parser = subparsers.add_parser(command)
        exchange_parser.add_argument("work_db", type=Path)
        exchange_parser.add_argument("path", type=Path)
    arguments = parser.parse_args()
    database = WorkDatabase(arguments.work_db)

    if arguments.command == "init":
        database.initialize()
        return
    if arguments.command == "status":
        print(json.dumps(database.stage_counts(), ensure_ascii=False))
        return
    database.initialize()
    if arguments.command == "import-all":
        source_counts = import_all_sources(
            database,
            arguments.manifest,
            arguments.lock,
            refresh_lock=arguments.refresh_lock,
        )
        print(
            json.dumps(
                {
                    "source_kinds": len(source_counts),
                    "source_counts": source_counts,
                    **database.stage_counts(),
                },
                ensure_ascii=False,
            )
        )
    elif arguments.command == "import-legacy":
        count = import_legacy_database(
            arguments.legacy_db,
            database,
            protected=arguments.protected,
        )
        print(json.dumps({"legacy_sentences": count}, ensure_ascii=False))
    elif arguments.command == "report-sources":
        print(json.dumps(report_sources(database, arguments.output), ensure_ascii=False))
    elif arguments.command == "import-tatoeba":
        _import_items(database, iter_tatoeba_detailed(arguments.path))
    elif arguments.command == "import-convokit":
        _import_items(database, iter_convokit_utterances(arguments.path, arguments.source_name))
    elif arguments.command == "import-wikinews":
        _import_items(database, iter_wikinews_extracts(arguments.path))
    elif arguments.command == "import-gutenberg":
        _import_items(database, iter_gutenberg_text(arguments.path, arguments.ebook_id))
    elif arguments.command == "clean":
        summary = _clean_items(database, *_stage_options(arguments))
        print(
            json.dumps(
                {**summary, "rejection_reasons": database.rejection_reason_counts("clean")},
                ensure_ascii=False,
            )
        )
    elif arguments.command == "dedupe":
        summary = _dedupe_items(database, *_stage_options(arguments))
        totals = database.rejection_reason_counts("dedupe")
        print(
            json.dumps(
                {
                    **summary,
                    "total_exact_duplicate": totals.get("exact_duplicate", 0),
                    "total_near_duplicate": totals.get("near_duplicate", 0),
                },
                ensure_ascii=False,
            )
        )
    elif arguments.command == "classify":
        summary = _classify_items(database, *_stage_options(arguments))
        if arguments.export_llm is not None:
            summary["exported_llm"] = export_classification_repairs(
                database, arguments.export_llm
            )
        summary["method_counts"] = database.classification_method_counts()
        summary["pending"] = database.pending_classification_repairs()
        print(json.dumps(summary, ensure_ascii=False))
    elif arguments.command == "import-classifications":
        try:
            imported = import_classification_repairs(database, arguments.paths)
        except ClassificationImportError as error:
            parser.error(str(error))
        print(
            json.dumps(
                {"imported": imported, "pending": database.pending_classification_repairs()},
                ensure_ascii=False,
            )
        )
    elif arguments.command == "replay-classifications":
        try:
            summary = replay_classifications(
                database,
                [(request, result) for request, result in arguments.exchange],
            )
        except HistoricalReplayError as error:
            parser.error(str(error))
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    elif arguments.command == "select":
        summary = _select_items(database, bounded=arguments.exact_quotas)
        if summary is not None:
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    elif arguments.command == "recall-classification":
        prototypes = _load_recall_prototypes(arguments.prototypes, arguments.sub_scene)
        excluded_ids = _load_recall_excluded_ids(arguments.exclude)
        embedder = SentenceTransformerEmbedder(
            arguments.model_path,
            ModelMetadata(
                arguments.model_name,
                arguments.model_revision,
                arguments.model_sha256,
            ),
            device=arguments.device,
        )
        summary = run_semantic_recall(
            database,
            sub_scene=arguments.sub_scene,
            prototypes=prototypes,
            embedder=embedder,
            output_path=arguments.output,
            checkpoint_path=arguments.checkpoint,
            exclude_ids=excluded_ids,
            top_k=arguments.top_k,
            batch_size=arguments.batch_size,
        )
        print(json.dumps(summary, ensure_ascii=False))
    elif arguments.command == "recall-classifications":
        scenes = _load_recall_scenes(arguments.config)
        excluded_ids = _load_recall_excluded_ids(arguments.exclude)
        embedder = SentenceTransformerEmbedder(
            arguments.model_path,
            ModelMetadata(
                arguments.model_name,
                arguments.model_revision,
                arguments.model_sha256,
            ),
            device=arguments.device,
        )
        summary = run_semantic_recall_many(
            database,
            scenes=scenes,
            embedder=embedder,
            output_dir=arguments.output_dir,
            checkpoint_path=arguments.checkpoint,
            exclude_ids=excluded_ids,
            batch_size=arguments.batch_size,
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    elif arguments.command == "recall-lexical-conflicts":
        lexical_config = _load_lexical_recall_config(arguments.config)
        summary = run_lexical_conflict_recall(
            database,
            **lexical_config,
            output_path=arguments.output,
            exclude_ids=_load_recall_excluded_ids(arguments.exclude),
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    elif arguments.command == "translate":
        translator = OpusMtTranslator(
            batch_size=arguments.batch_size,
            revision=arguments.revision,
        )
        run_translation_stage(database, translator, batch_size=arguments.batch_size)
    elif arguments.command == "export-llm-repairs":
        export_llm_repairs(database, arguments.path)
    else:
        try:
            import_llm_repairs(database, arguments.path)
        except TranslationImportError as error:
            parser.error(str(error))


def _stage_options(arguments: argparse.Namespace) -> tuple[int, bool]:
    if arguments.batch_size is not None and arguments.limit is not None:
        raise ValueError("--batch-size 与 --limit 不能同时使用")
    if arguments.batch_size is not None:
        return arguments.batch_size, True
    if arguments.limit is not None:
        return arguments.limit, False
    return 1000, False


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("必须是大于 0 的整数")
    return parsed


def _recall_top_k(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 500:
        raise argparse.ArgumentTypeError("必须是 1 到 500 之间的整数")
    return parsed


def _load_recall_prototypes(path: Path, sub_scene: str) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取语义召回原型文件 {path}: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"sub_scene", "prototypes"}:
        raise ValueError("语义召回原型文件字段必须精确为 sub_scene/prototypes")
    prototypes = payload["prototypes"]
    if payload["sub_scene"] != sub_scene:
        raise ValueError("语义召回原型文件的 sub_scene 与命令参数不匹配")
    if (
        not isinstance(prototypes, list)
        or not prototypes
        or any(not isinstance(text, str) or not text.strip() for text in prototypes)
    ):
        raise ValueError("语义召回 prototypes 必须是非空字符串列表")
    return tuple(text.strip() for text in prototypes)


def _load_recall_scenes(path: Path) -> tuple[RecallScene, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取多场景语义召回配置 {path}: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"scenes"}:
        raise ValueError("多场景语义召回配置字段必须精确为 scenes")
    raw_scenes = payload["scenes"]
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("多场景语义召回 scenes 必须是非空列表")
    scenes: list[RecallScene] = []
    for index, raw_scene in enumerate(raw_scenes, start=1):
        if not isinstance(raw_scene, dict) or set(raw_scene) != {
            "sub_scene",
            "prototypes",
            "top_k",
        }:
            raise ValueError(f"多场景语义召回 scenes[{index}] 字段非法")
        sub_scene = raw_scene["sub_scene"]
        prototypes = raw_scene["prototypes"]
        top_k = raw_scene["top_k"]
        if not isinstance(sub_scene, str) or sub_scene not in SUB_SCENES:
            raise ValueError(f"多场景语义召回 scenes[{index}] 场景非法")
        if (
            not isinstance(prototypes, list)
            or not prototypes
            or any(not isinstance(text, str) or not text.strip() for text in prototypes)
        ):
            raise ValueError(f"多场景语义召回 scenes[{index}] prototypes 非法")
        if (
            not isinstance(top_k, int)
            or isinstance(top_k, bool)
            or not 1 <= top_k <= 500
        ):
            raise ValueError(f"多场景语义召回 scenes[{index}] top_k 非法")
        scenes.append(
            RecallScene(
                sub_scene=sub_scene,
                prototypes=tuple(text.strip() for text in prototypes),
                top_k=top_k,
            )
        )
    return tuple(scenes)


def _load_recall_excluded_ids(paths: list[Path]) -> set[int]:
    item_ids: set[int] = set()
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ValueError(f"无法读取语义召回排除文件 {path}: {error}") from error
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number} 不是合法 JSON") from error
            item_id = row.get("item_id") if isinstance(row, dict) else None
            if not isinstance(item_id, int) or isinstance(item_id, bool):
                raise ValueError(f"{path}:{line_number} 缺少整数 item_id")
            item_ids.add(item_id)
    return item_ids


def _load_lexical_recall_config(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 lexical conflict recall 配置 {path}: {error}") from error
    expected = {"sub_scene", "keywords", "phrases", "top_k"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError(f"lexical conflict recall 配置字段必须精确为 {sorted(expected)}")
    sub_scene = payload["sub_scene"]
    keywords = payload["keywords"]
    phrases = payload["phrases"]
    top_k = payload["top_k"]
    if not isinstance(sub_scene, str) or sub_scene not in SUB_SCENES:
        raise ValueError("lexical conflict recall 的 sub_scene 非法")
    for name, values in (("keywords", keywords), ("phrases", phrases)):
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError(f"lexical conflict recall 的 {name} 必须是字符串列表")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 500:
        raise ValueError("lexical conflict recall 的 top_k 必须在 1 到 500 之间")
    return {
        "sub_scene": sub_scene,
        "keywords": tuple(value.strip() for value in keywords),
        "phrases": tuple(value.strip() for value in phrases),
        "top_k": top_k,
    }


def _add_import_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], command: str, argument: str
) -> argparse.ArgumentParser:
    command_parser = subparsers.add_parser(command)
    command_parser.add_argument("work_db", type=Path)
    command_parser.add_argument(argument, type=Path)
    return command_parser


def _import_items(database: WorkDatabase, items: Iterable[CollectedSentence]) -> None:
    for item in items:
        missing = [
            field
            for field in (
                "source_name",
                "source_item_id",
                "source_url",
                "source_author",
                "license_name",
                "license_url",
            )
            if not getattr(item, field).strip()
        ]
        if missing:
            raise ValueError(f"来源条目缺少必需溯源字段: {', '.join(missing)}")
        database.upsert_raw(
            source_name=item.source_name,
            source_item_id=item.source_item_id,
            source_url=item.source_url,
            source_author=item.source_author,
            license_name=item.license_name,
            license_url=item.license_url,
            text=item.text,
            top_scene=item.top_scene,
            sub_scene=item.sub_scene,
        )


def _clean_items(
    database: WorkDatabase, limit: int, run_to_completion: bool = False
) -> dict[str, int]:
    summary = {"processed": 0, "accepted": 0, "rejected": 0}
    while batch := database.claim_stage_batch("clean", limit=limit):
        results: list[tuple[int, dict[str, str]]] = []
        rejections: list[tuple[int, str]] = []
        for stage_input in batch:
            item = stage_input.item
            reason = None if item.protected else rejection_reason(item.text)
            if reason:
                rejections.append((item.id, reason))
            else:
                results.append((item.id, {"clean_text": clean_sentence(item.text)}))
        database.checkpoint_stage_batch("clean", results, rejections)
        summary["processed"] += len(batch)
        summary["accepted"] += len(results)
        summary["rejected"] += len(rejections)
        if not run_to_completion:
            break
    return summary


def _dedupe_items(
    database: WorkDatabase, limit: int, run_to_completion: bool = False
) -> dict[str, int]:
    summary = {"processed": 0, "accepted": 0, "exact_duplicate": 0, "near_duplicate": 0}
    while batch := database.claim_stage_batch("dedupe", limit=limit):
        current = database.checkpoint_dedupe_batch(batch)
        for key in summary:
            summary[key] += current[key]
        if not run_to_completion:
            break
    return summary


def _classify_items(
    database: WorkDatabase, limit: int, run_to_completion: bool = False
) -> dict[str, int]:
    classifier = SceneClassifier()
    summary = {
        "processed": 0,
        "classified": 0,
        "llm_required": 0,
        "out_of_candidate_pool": 0,
    }
    model_version = "scene-candidate-v13"
    while batch := database.claim_stage_batch(
        "classify", limit=limit, stale_model_version=model_version
    ):
        results: list[tuple[int, dict[str, object]]] = []
        for stage_input in batch:
            item = stage_input.item
            text = str(stage_input.predecessor_payload.get("clean_text") or item.text)
            result = classifier.classify_candidate(
                text,
                top_scene=item.top_scene,
                sub_scene=item.sub_scene,
                protected=item.protected,
                source_name=item.source_name,
            )
            results.append(
                (
                    item.id,
                    {
                        "top_scene": result.top_scene,
                        "sub_scene": result.sub_scene,
                        "confidence": result.confidence,
                        "method": result.method,
                    },
                )
            )
            summary["processed"] += 1
            if result.method == "llm_required":
                summary["llm_required"] += 1
            elif result.method == "out_of_candidate_pool":
                summary["out_of_candidate_pool"] += 1
            else:
                summary["classified"] += 1
        database.checkpoint_stage_batch(
            "classify", results, model_version=model_version
        )
        if not run_to_completion:
            break
    return summary


def _select_items(
    database: WorkDatabase, *, bounded: bool = False
) -> dict[str, object] | None:
    if bounded:
        return _select_items_bounded(database)
    candidates: list[_SelectionRow] = []
    for stage_input in database.stage_inputs("select", include_completed=True):
        item = stage_input.item
        payload = stage_input.predecessor_payload
        top_scene = payload.get("top_scene")
        sub_scene = payload.get("sub_scene")
        if not isinstance(top_scene, str) or not isinstance(sub_scene, str):
            continue
        candidates.append(
            _SelectionRow(
                id=item.id,
                text=item.text,
                source_name=item.source_name,
                source_author=item.source_author,
                top_scene=top_scene,
                sub_scene=sub_scene,
                confidence=float(payload.get("confidence") or 0.0),
                protected=item.protected,
            )
        )

    selected = select_scene_quotas(candidates)
    database.replace_stage(
        "select",
        [
            (row.id, {"top_scene": row.top_scene, "sub_scene": sub_scene})
            for sub_scene, scene_rows in selected.items()
            for row in scene_rows
        ],
    )
    return None


def _select_items_bounded(database: WorkDatabase) -> dict[str, object]:
    selected_rows: list[tuple[_SelectionRow, str]] = []
    scene_counts: dict[str, int] = {}
    for scene in SCENES:
        candidates = [
            _SelectionRow(
                id=stage_input.item.id,
                text=stage_input.item.text,
                source_name=stage_input.item.source_name,
                source_author=stage_input.item.source_author,
                top_scene=str(stage_input.predecessor_payload.get("top_scene") or ""),
                sub_scene=str(stage_input.predecessor_payload.get("sub_scene") or ""),
                confidence=float(stage_input.predecessor_payload.get("confidence") or 0.0),
                protected=stage_input.item.protected,
            )
            for stage_input in database.bounded_selection_candidates(
                scene.key, quota=scene.quota
            )
        ]
        scene_selected = select_scene_quota(scene, candidates)
        scene_counts[scene.key] = len(scene_selected)
        selected_rows.extend((row, scene.key) for row in scene_selected)
    database.replace_stage(
        "select",
        [
            (row.id, {"top_scene": row.top_scene, "sub_scene": sub_scene})
            for row, sub_scene in selected_rows
        ],
    )
    return {
        "selected": len(selected_rows),
        "protected": sum(row.protected for row, _ in selected_rows),
        "scene_counts": scene_counts,
        "concentration": database.selection_concentration(),
    }


def _clean_text(database: WorkDatabase, item: WorkItem) -> str:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT payload_json FROM stage_results WHERE item_id = ? AND stage = ?",
            (item.id, "clean"),
        ).fetchone()
    if row is None:
        return clean_sentence(item.text)
    payload = json.loads(row[0])
    return str(payload.get("clean_text") or clean_sentence(item.text))


if __name__ == "__main__":
    main()
