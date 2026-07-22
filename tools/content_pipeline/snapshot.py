from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from tools.content_pipeline.models import CollectedSentence


def write_snapshot(items: list[CollectedSentence], path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(item) for item in items]
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_snapshot(path: str | Path) -> list[CollectedSentence]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("题库快照必须是 JSON 数组")
    return [CollectedSentence(**item) for item in payload if isinstance(item, dict)]
