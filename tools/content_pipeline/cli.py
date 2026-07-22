from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tools.content_pipeline.categorize import SceneClassifier
from tools.content_pipeline.clean import clean_sentence, rejection_reason
from tools.content_pipeline.convokit_source import iter_convokit_utterances
from tools.content_pipeline.dedupe import NearDuplicateIndex, simhash64
from tools.content_pipeline.gutenberg import iter_gutenberg_text
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.selection import select_scene_quotas
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
    protected: bool


def main() -> None:
    parser = argparse.ArgumentParser(prog="listening-cloze-content")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "status"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("work_db", type=Path)
    _add_import_parser(subparsers, "import-tatoeba", "path")
    convokit_parser = _add_import_parser(subparsers, "import-convokit", "path")
    convokit_parser.add_argument("source_name", choices=("cornell-movie-dialogs", "switchboard"))
    _add_import_parser(subparsers, "import-wikinews", "path")
    gutenberg_parser = _add_import_parser(subparsers, "import-gutenberg", "path")
    gutenberg_parser.add_argument("ebook_id", type=int)
    clean_parser = subparsers.add_parser("clean")
    clean_parser.add_argument("work_db", type=Path)
    clean_parser.add_argument("--limit", type=int, default=1000)
    for command in ("dedupe", "classify"):
        stage_parser = subparsers.add_parser(command)
        stage_parser.add_argument("work_db", type=Path)
        stage_parser.add_argument("--limit", type=int, default=1000)
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("work_db", type=Path)
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
    if arguments.command == "import-tatoeba":
        _import_items(database, iter_tatoeba_detailed(arguments.path))
    elif arguments.command == "import-convokit":
        _import_items(database, iter_convokit_utterances(arguments.path, arguments.source_name))
    elif arguments.command == "import-wikinews":
        _import_items(database, iter_wikinews_extracts(arguments.path))
    elif arguments.command == "import-gutenberg":
        _import_items(database, iter_gutenberg_text(arguments.path, arguments.ebook_id))
    elif arguments.command == "clean":
        _clean_items(database, arguments.limit)
    elif arguments.command == "dedupe":
        _dedupe_items(database, arguments.limit)
    elif arguments.command == "classify":
        _classify_items(database, arguments.limit)
    elif arguments.command == "select":
        _select_items(database)
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


def _clean_items(database: WorkDatabase, limit: int) -> None:
    for item in database.claim_batch("clean", limit=limit):
        reason = rejection_reason(item.text)
        if reason:
            database.record_rejection(item.id, "clean", reason)
            continue
        database.mark_stage(item.id, "clean", payload={"clean_text": clean_sentence(item.text)})


def _dedupe_items(database: WorkDatabase, limit: int) -> None:
    index = NearDuplicateIndex()
    completed = database.stage_inputs("dedupe", include_completed=True, include_rejected=True)
    for stage_input in completed:
        if stage_input.stage_payload is None:
            continue
        text = str(stage_input.predecessor_payload.get("clean_text") or stage_input.item.text)
        index.add(text, force=stage_input.item.protected)

    for item in database.claim_batch("dedupe", limit=limit):
        text = _clean_text(database, item)
        unique = index.add(text, force=item.protected)
        if unique or item.protected:
            database.mark_stage(
                item.id,
                "dedupe",
                payload={"simhash64": f"{simhash64(text):016x}"},
            )
            continue
        database.record_rejection(
            item.id,
            "dedupe",
            f"near_duplicate:{index.duplicate_hash}",
        )


def _classify_items(database: WorkDatabase, limit: int) -> None:
    classifier = SceneClassifier()
    for item in database.claim_batch("classify", limit=limit):
        result = classifier.classify(
            _clean_text(database, item),
            top_scene=item.top_scene,
            sub_scene=item.sub_scene,
        )
        database.mark_stage(
            item.id,
            "classify",
            payload={
                "top_scene": result.top_scene,
                "sub_scene": result.sub_scene,
                "confidence": result.confidence,
                "method": result.method,
            },
        )


def _select_items(database: WorkDatabase) -> None:
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
