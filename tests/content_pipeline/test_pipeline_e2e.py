from __future__ import annotations

import bz2
import json
import sys
from pathlib import Path

import pytest

from tools.content_pipeline import cli, selection
from tools.content_pipeline.scenes import SCENES, SceneDefinition
from tools.content_pipeline.work_database import WorkDatabase


class FakeTranslator:
    model_version = "fake-e2e"

    def __init__(self, **_: object) -> None:
        pass

    def translate_batch(self, texts: list[str]) -> list[str]:
        return ["这是一句用于完整流程验证的中文译文。" for _ in texts]


SCENE_KEYWORDS = {
    "daily_home": ("kitchen", "cupboard", "laundry", "dishes", "family", "house"),
    "daily_social": ("friend", "invite", "party", "neighbor", "welcome", "visit"),
    "daily_shopping": ("buy", "shop", "price", "cashier", "refund", "store"),
    "daily_food": ("breakfast", "lunch", "dinner", "cook", "restaurant", "menu"),
    "travel_transport": ("train", "bus", "taxi", "airport", "ticket", "platform"),
    "travel_directions": ("direction", "turn", "left", "map", "route", "street"),
    "travel_hotel": ("hotel", "room", "reserve", "reservation", "double", "night"),
    "travel_tourism": ("tour", "travel", "vacation", "journey", "museum", "landmark"),
    "work_office": ("office", "colleague", "project", "deadline", "report", "document"),
    "work_meetings": ("meeting", "presentation", "agenda", "discuss", "conference", "slide"),
    "work_contact": ("email", "call", "phone", "message", "reply", "attachment"),
    "work_jobs": ("job", "interview", "resume", "salary", "hire", "applicant"),
    "study_campus": ("campus", "classroom", "lecture", "professor", "student", "lesson"),
    "study_exams": ("exam", "test", "revise", "revision", "score", "prepare"),
    "study_academic": ("research", "hypothesis", "evidence", "analysis", "paper", "theory"),
    "study_language": (
        "language",
        "grammar",
        "vocabulary",
        "pronunciation",
        "translate",
        "english",
    ),
    "health_clinic": ("doctor", "hospital", "clinic", "appointment", "patient", "nurse"),
    "health_pharmacy": ("medicine", "pharmacy", "prescription", "tablet", "dose", "pharmacist"),
    "health_fitness": ("exercise", "gym", "fitness", "run", "workout", "sport"),
    "health_wellbeing": ("sleep", "stress", "relax", "wellbeing", "mental", "healthy"),
    "technology_devices": ("phone", "computer", "laptop", "screen", "device", "battery"),
    "technology_software": ("software", "app", "internet", "website", "password", "account"),
    "technology_engineering": (
        "engineer",
        "engineering",
        "machine",
        "system",
        "design",
        "technical",
    ),
    "technology_science": ("science", "scientist", "experiment", "space", "energy", "laboratory"),
    "culture_movies": ("movie", "film", "cinema", "actor", "director", "theater"),
    "culture_music": ("music", "song", "concert", "singer", "instrument", "album"),
    "culture_books": ("book", "novel", "author", "read", "library", "literature"),
    "culture_sports": ("sport", "game", "match", "team", "player", "football"),
    "news_current": ("news", "report", "journalist", "announce", "president", "minister"),
    "news_business": ("business", "market", "bank", "economy", "stocks", "finance"),
    "news_public": ("law", "court", "police", "government", "council", "public"),
    "news_environment": ("environment", "climate", "weather", "pollution", "wildlife", "flood"),
}


def test_cli_pipeline_processes_all_micro_quota_sentences_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_db = tmp_path / "work.db"
    tatoeba_path = tmp_path / "tatoeba.tsv.bz2"
    switchboard_path = tmp_path / "switchboard.jsonl"
    cornell_path = tmp_path / "cornell.jsonl"
    scene_definitions = tuple(
        SceneDefinition(scene.top_key, scene.top_label, scene.key, scene.label, 3)
        for scene in SCENES
    )
    monkeypatch.setattr(selection, "SCENES", scene_definitions)
    monkeypatch.setattr(cli, "OpusMtTranslator", FakeTranslator)
    _write_source_fixtures(tatoeba_path, switchboard_path, cornell_path)

    _run_cli(monkeypatch, "init", work_db)
    _run_cli(monkeypatch, "import-tatoeba", work_db, tatoeba_path)
    _run_cli(monkeypatch, "import-convokit", work_db, switchboard_path, "switchboard")
    _run_cli(monkeypatch, "import-convokit", work_db, cornell_path, "cornell-movie-dialogs")
    _run_cli(monkeypatch, "clean", work_db, "--limit", "96")
    _run_cli(monkeypatch, "dedupe", work_db, "--limit", "96")
    _run_cli(monkeypatch, "classify", work_db, "--limit", "96")
    _run_cli(monkeypatch, "select", work_db)
    _run_cli(monkeypatch, "translate", work_db, "--batch-size", "32")

    database = WorkDatabase(work_db)
    assert database.stage_counts() == {
        "raw": 96,
        "clean": 96,
        "dedupe": 96,
        "classify": 96,
        "select": 96,
        "translate": 96,
        "rejected": 0,
    }
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT classified.payload_json, translated.payload_json
            FROM stage_results AS classified
            JOIN stage_results AS translated
              ON translated.item_id = classified.item_id AND translated.stage = 'translate'
            WHERE classified.stage = 'classify'
            ORDER BY classified.item_id
            """
        ).fetchall()
    assert len(rows) == 96
    assert {
        json.loads(classified)["sub_scene"]
        for classified, _ in rows
    } == set(SCENE_KEYWORDS)
    assert all(json.loads(translated)["translation_zh"] for _, translated in rows)


def _write_source_fixtures(tatoeba: Path, switchboard: Path, cornell: Path) -> None:
    scene_items = tuple(SCENE_KEYWORDS.items())
    with bz2.open(tatoeba, "wt", encoding="utf-8") as stream:
        for index, (_, words) in enumerate(scene_items, start=1):
            sentence = _sentence(words[:2], "amber velvet quartz lantern garden")
            stream.write(f"{index}\teng\t{sentence}\tauthor-{index}\n")
    for path, words, distinct_words, source_marker in (
        (switchboard, slice(2, 4), "cobalt river meadow autumn bridge", "switchboard"),
        (cornell, slice(4, 6), "saffron marble willow sunset harbor", "cornell"),
    ):
        path.write_text(
            "\n".join(
                json.dumps(
                    {
                        "id": f"{source_marker}-{index}",
                        "text": _sentence(scene_words[words], distinct_words),
                        "speaker": {"id": f"{source_marker}-author-{index}"},
                    }
                )
                for index, (_, scene_words) in enumerate(scene_items, start=1)
            )
            + "\n",
        encoding="utf-8",
    )


def _sentence(scene_words: tuple[str, ...], distinct_words: str) -> str:
    return f"The {scene_words[0]} and {scene_words[1]} appeared beside {distinct_words}."


def _run_cli(monkeypatch: pytest.MonkeyPatch, *arguments: str | Path) -> None:
    monkeypatch.setattr(sys, "argv", ["listening-cloze-content", *(str(arg) for arg in arguments)])
    cli.main()
