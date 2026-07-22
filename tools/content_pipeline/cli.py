from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from tools.content_pipeline.clean import clean_sentence, rejection_reason
from tools.content_pipeline.convokit_source import iter_convokit_utterances
from tools.content_pipeline.gutenberg import iter_gutenberg_text
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.tatoeba import iter_tatoeba_detailed
from tools.content_pipeline.wikinews import iter_wikinews_extracts
from tools.content_pipeline.work_database import WorkDatabase


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
    else:
        _clean_items(database, arguments.limit)


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
        )


def _clean_items(database: WorkDatabase, limit: int) -> None:
    for item in database.claim_batch("clean", limit=limit):
        reason = rejection_reason(item.text)
        if reason:
            database.record_rejection(item.id, "clean", reason)
            continue
        database.mark_stage(item.id, "clean", payload={"clean_text": clean_sentence(item.text)})


if __name__ == "__main__":
    main()
