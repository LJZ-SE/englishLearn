from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from tools.content_pipeline.cet_extension import (
    CET_QUOTA_PER_LEVEL,
    CET_SIMULATED_PER_LEVEL,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = (
    PROJECT_ROOT / "tools" / "content_pipeline" / "data" / "cet_extension_snapshot.json"
)


def test_bundled_cet_snapshot_has_exact_level_and_origin_quotas() -> None:
    rows = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    counts = Counter((row["level"], row["origin"]) for row in rows)

    assert len(rows) == CET_QUOTA_PER_LEVEL * 2
    assert counts == {
        ("cet4", "authentic"): CET_QUOTA_PER_LEVEL - CET_SIMULATED_PER_LEVEL,
        ("cet4", "simulated"): CET_SIMULATED_PER_LEVEL,
        ("cet6", "authentic"): CET_QUOTA_PER_LEVEL - CET_SIMULATED_PER_LEVEL,
        ("cet6", "simulated"): CET_SIMULATED_PER_LEVEL,
    }


def test_bundled_cet_snapshot_is_complete_and_traceable() -> None:
    rows = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    assert all(row["translation_zh"].strip() for row in rows)
    assert all(row["source_url"].startswith("https://") for row in rows)
    assert all(row["license_url"].startswith("https://") for row in rows)
    assert all(
        row["source_item_id"].startswith(
            f"{row['origin']}:{row['level']}:"
        )
        for row in rows
    )
    assert len({row["text"].casefold() for row in rows}) == len(rows)
