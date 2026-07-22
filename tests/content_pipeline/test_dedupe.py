from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.content_pipeline import selection
from tools.content_pipeline.categorize import SceneClassifier
from tools.content_pipeline.clean import normalized_hash
from tools.content_pipeline.dedupe import NearDuplicateIndex, simhash64
from tools.content_pipeline.scenes import SCENES, SceneDefinition
from tools.content_pipeline.selection import SceneQuotaError, select_scene_quotas
from tools.content_pipeline.work_database import WorkDatabase


@dataclass(frozen=True, slots=True)
class Candidate:
    id: int
    text: str
    source_name: str
    source_author: str
    top_scene: str
    sub_scene: str
    protected: bool = False


def _candidates(*, protected_ids: frozenset[int] = frozenset()) -> list[Candidate]:
    rows: list[Candidate] = []
    for index in range(60):
        rows.append(
            Candidate(
                id=index + 1,
                text=f"Distinct hotel request number {index} for the summer journey.",
                source_name=f"source-{index % 4}",
                source_author=f"author-{index // 2}",
                top_scene="travel",
                sub_scene="travel_hotel",
                protected=index + 1 in protected_ids,
            )
        )
    return rows


def _single_test_scene(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        selection,
        "SCENES",
        (SceneDefinition("travel", "出行旅行", "travel_hotel", "酒店住宿", 25),),
    )


def test_simhash_index_only_rejects_near_duplicate_content() -> None:
    index = NearDuplicateIndex(threshold=0.76)

    assert index.add("The train leaves the station at nine o'clock.") is True
    assert index.add("The train leaves this station at nine o'clock.") is False
    assert index.duplicate_hash is not None
    assert index.add("Please send the revised report before Friday.") is True
    assert index.duplicate_hash is None


def test_simhash_is_stable_and_uses_all_64_bits() -> None:
    first = simhash64("The train leaves the station at nine o'clock.")

    assert first == simhash64("The train leaves the station at nine o'clock.")
    assert 0 <= first < 2**64


def test_simhash_normalizes_unicode_quotes_case_and_spacing() -> None:
    assert simhash64("Don’t send the final report today.") == simhash64(
        "  DON'T   SEND THE FINAL REPORT TODAY.  "
    )


def test_hierarchical_classifier_returns_fixed_scene_keys() -> None:
    result = SceneClassifier().classify("Could I reserve a double room for two nights?")

    assert result.top_scene == "travel"
    assert result.sub_scene == "travel_hotel"
    assert 0.0 <= result.confidence <= 1.0
    assert result.method == "keyword"


def test_hierarchical_classifier_defers_low_confidence_text_to_llm() -> None:
    result = SceneClassifier().classify("The thoughtful visitor considered several options.")

    assert result.method == "llm_required"
    assert result.top_scene is None
    assert result.sub_scene is None


def test_quota_selection_limits_source_and_author_concentration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _single_test_scene(monkeypatch)

    selected = select_scene_quotas(_candidates())["travel_hotel"]
    sources = Counter(row.source_name for row in selected)
    authors = Counter(row.source_author for row in selected if row.source_author)

    assert len(selected) == 25
    assert max(sources.values()) / len(selected) <= 0.45
    assert max(authors.values()) / len(selected) <= 0.08


def test_quota_selection_always_retains_protected_legacy_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _single_test_scene(monkeypatch)
    protected = frozenset({3, 44})

    selected = select_scene_quotas(_candidates(protected_ids=protected))["travel_hotel"]

    assert protected <= {row.id for row in selected}


def test_quota_selection_rejects_protected_source_concentration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _single_test_scene(monkeypatch)
    rows = _candidates()
    conflicting = [
        Candidate(
            id=row.id,
            text=row.text,
            source_name="legacy-content",
            source_author="",
            top_scene=row.top_scene,
            sub_scene=row.sub_scene,
            protected=True,
        )
        if row.id <= 12
        else row
        for row in rows
    ]

    with pytest.raises(SceneQuotaError, match="protected.*source"):
        select_scene_quotas(conflicting)


def test_quota_selection_finds_feasible_cross_source_author_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _single_test_scene(monkeypatch)
    protected: list[Candidate] = []
    for index in range(10):
        protected.append(
            Candidate(
                id=index + 1,
                text=f"Protected source A hotel sentence {index} with distinct wording.",
                source_name="source-a",
                source_author="author-x" if index == 0 else f"a-author-{index}",
                top_scene="travel",
                sub_scene="travel_hotel",
                protected=True,
            )
        )
        protected.append(
            Candidate(
                id=index + 101,
                text=f"Protected source B hotel sentence {index} with distinct wording.",
                source_name="source-b",
                source_author="author-y" if index == 0 else f"b-author-{index}",
                top_scene="travel",
                sub_scene="travel_hotel",
                protected=True,
            )
        )
    for index in range(3):
        protected.append(
            Candidate(
                id=index + 201,
                text=f"Protected source C hotel sentence {index} with distinct wording.",
                source_name="source-c",
                source_author=f"c-author-{index}",
                top_scene="travel",
                sub_scene="travel_hotel",
                protected=True,
            )
        )
    texts = sorted(
        (
            "Candidate alpha reserves a quiet hotel room for the journey.",
            "Candidate beta reserves a quiet hotel room for the journey.",
            "Candidate gamma reserves a quiet hotel room for the journey.",
        ),
        key=normalized_hash,
    )
    regular = [
        Candidate(301, texts[0], "source-a", "author-x", "travel", "travel_hotel"),
        Candidate(302, texts[1], "source-a", "author-y", "travel", "travel_hotel"),
        Candidate(303, texts[2], "source-b", "author-x", "travel", "travel_hotel"),
    ]

    selected = select_scene_quotas([*protected, *regular])["travel_hotel"]

    assert {row.id for row in selected if not row.protected} == {302, 303}


def test_quota_error_reports_every_scene_shortage() -> None:
    with pytest.raises(SceneQuotaError) as captured:
        select_scene_quotas([])

    assert tuple(captured.value.shortages) == tuple(scene.key for scene in SCENES)
    assert captured.value.shortages["daily_home"] == 1500
    assert captured.value.shortages["news_environment"] == 500


def test_cli_runs_dedupe_and_classify_then_fails_select_without_partial_writes(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "work.db"
    database = WorkDatabase(database_path)
    database.initialize()
    texts = (
        "Could I reserve a double hotel room for two nights?",
        "Could I reserve this double hotel room for two nights?",
    )
    for index, text in enumerate(texts, start=1):
        item_id = database.upsert_raw(
            source_name="source-a",
            source_item_id=str(index),
            source_url=f"https://example.test/{index}",
            source_author=f"author-{index}",
            license_name="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            text=text,
        )
        database.mark_stage(item_id, "clean", payload={"clean_text": text})

    command = [sys.executable, "-m", "tools.content_pipeline.cli"]
    subprocess.run([*command, "dedupe", str(database_path), "--limit", "100"], check=True)
    subprocess.run([*command, "classify", str(database_path), "--limit", "100"], check=True)
    failed = subprocess.run(
        [*command, "select", str(database_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert database.stage_counts() == {
        "raw": 2,
        "clean": 2,
        "dedupe": 1,
        "classify": 1,
        "rejected": 1,
    }
    assert failed.returncode != 0
    assert "场景配额差额" in failed.stderr
    with sqlite3.connect(database_path) as connection:
        payload = json.loads(
            connection.execute(
                "SELECT payload_json FROM stage_results WHERE stage = 'classify'"
            ).fetchone()[0]
        )
        selected_count = connection.execute(
            "SELECT COUNT(*) FROM stage_results WHERE stage = 'select'"
        ).fetchone()[0]
    assert payload["method"] == "keyword"
    assert payload["sub_scene"] == "travel_hotel"
    assert selected_count == 0
