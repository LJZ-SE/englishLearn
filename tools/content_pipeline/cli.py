from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.content_pipeline.work_database import WorkDatabase


def main() -> None:
    parser = argparse.ArgumentParser(prog="listening-cloze-content")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "status"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("work_db", type=Path)
    arguments = parser.parse_args()
    database = WorkDatabase(arguments.work_db)

    if arguments.command == "init":
        database.initialize()
        return
    print(json.dumps(database.stage_counts(), ensure_ascii=False))


if __name__ == "__main__":
    main()
