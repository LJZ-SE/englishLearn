from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.content_pipeline.translation import (
    TranslationImportError,
    export_llm_repairs,
    import_llm_repairs,
    run_translation_stage,
    validate_translation,
)
from tools.content_pipeline.work_database import WorkDatabase


class FakeTranslator:
    model_version = "fake-1"

    def translate_batch(self, texts: list[str]) -> list[str]:
        return ["火车九点到达。" for _ in texts]


class InterruptingTranslator:
    model_version = "fake-interrupted"

    def __init__(self) -> None:
        self.calls = 0

    def translate_batch(self, texts: list[str]) -> list[str]:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("simulated interruption")
        return ["火车九点到达。" for _ in texts]


def test_translation_stage_checkpoints_success_and_flags_number_loss(tmp_path: Path) -> None:
    assert validate_translation("The train arrives at 9:30.", "火车到达。") == ("number_mismatch",)
    assert validate_translation("The train arrives at nine.", "火车九点到达。") == ()

    database = _selected_database(
        tmp_path,
        ("The train arrives at nine.", "The train arrives at nine."),
    )
    with pytest.raises(RuntimeError, match="simulated interruption"):
        run_translation_stage(database, InterruptingTranslator(), batch_size=1)

    assert database.stage_counts()["translate"] == 1
    with database.connect() as connection:
        [row] = connection.execute(
            "SELECT payload_json, model_version FROM stage_results WHERE stage = 'translate'"
        ).fetchall()
    assert json.loads(row[0]) == {"issues": [], "translation_zh": "火车九点到达。"}
    assert row[1] == "fake-interrupted"


@pytest.mark.parametrize(
    ("source", "translation", "expected_issue"),
    [
        ("Hello there.", "", "empty_translation"),
        ("Hello there.", "Hello there.", "low_chinese_ratio"),
        ("Please pay $20.", "请支付20元。", "currency_mismatch"),
        ("It costs 20 dollars.", "价格是20欧元。", "currency_mismatch"),
        ("The discount is 20%.", "折扣是20。", "percent_mismatch"),
        ("This train arrives shortly.", "这是 a train arriving shortly。", "english_residue"),
        (
            "This is a deliberately long sentence for checking translation length.",
            "好。",
            "abnormal_length",
        ),
    ],
)
def test_validate_translation_covers_required_quality_checks(
    source: str, translation: str, expected_issue: str
) -> None:
    assert expected_issue in validate_translation(source, translation)


def test_validate_translation_checks_short_sentence_length_and_currency_identity() -> None:
    assert "abnormal_length" in validate_translation(
        "Hi.",
        "这是一段明显过长而且不应被短句长度门禁放行的中文翻译内容。",
    )
    assert validate_translation("Hi.", "你好。") == ()
    assert validate_translation("Please pay $20.", "请支付20美元。") == ()
    assert validate_translation("The fare is EUR 20.", "票价是20欧元。") == ()


def test_failed_draft_is_exported_and_only_valid_repair_completes_stage(tmp_path: Path) -> None:
    database = _selected_database(tmp_path, ("The train arrives at 9:30.",))
    assert run_translation_stage(database, FakeTranslator(), batch_size=32) == 1
    assert database.stage_counts().get("translate", 0) == 0

    exchange_path = tmp_path / "repairs.jsonl"
    assert export_llm_repairs(database, exchange_path) == 1
    assert json.loads(exchange_path.read_text(encoding="utf-8")) == {
        "item_id": 1,
        "source": "The train arrives at 9:30.",
        "draft": "火车九点到达。",
        "issues": ["number_mismatch"],
        "top_scene": "travel",
        "sub_scene": "travel_transport",
    }

    exchange_path.write_text(
        json.dumps(
            {"item_id": 1, "translation_zh": "火车在9:30到达。", "review_note": "补回时间"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    assert import_llm_repairs(database, exchange_path) == 1
    assert database.stage_counts()["translate"] == 1
    assert export_llm_repairs(database, tmp_path / "remaining.jsonl") == 0

    with database.connect() as connection:
        payload_json, model_version = connection.execute(
            "SELECT payload_json, model_version FROM stage_results WHERE stage = 'translate'"
        ).fetchone()
    assert json.loads(payload_json) == {
        "issues": [],
        "repair_processor_version": "llm-repair",
        "review_note": "补回时间",
        "source_model_version": "fake-1",
        "translation_zh": "火车在9:30到达。",
    }
    assert model_version == "llm-repair"


def test_import_is_recoverable_per_line_and_revalidates_failed_repair(tmp_path: Path) -> None:
    database = _selected_database(
        tmp_path,
        ("The train arrives at 9:30.", "The train arrives at 10:45."),
    )
    assert run_translation_stage(database, FakeTranslator(), batch_size=32) == 2
    exchange_path = tmp_path / "repairs.jsonl"
    exchange_path.write_text(
        "\n".join(
            (
                json.dumps(
                    {"item_id": 1, "translation_zh": "火车在9:30到达。", "review_note": "已修正"},
                    ensure_ascii=False,
                ),
                "{not-json}",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(TranslationImportError, match="第 2 行"):
        import_llm_repairs(database, exchange_path)

    assert database.stage_counts()["translate"] == 1
    exchange_path.write_text(
        json.dumps(
            {"item_id": 2, "translation_zh": "火车十点到达。", "review_note": "仍缺数字"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    assert import_llm_repairs(database, exchange_path) == 0
    remaining_path = tmp_path / "remaining.jsonl"
    assert export_llm_repairs(database, remaining_path) == 1
    assert json.loads(remaining_path.read_text(encoding="utf-8"))["issues"] == ["number_mismatch"]


def test_import_rejects_unknown_fields_without_exposing_record_contents(tmp_path: Path) -> None:
    database = _selected_database(tmp_path, ("The train arrives at 9:30.",))
    run_translation_stage(database, FakeTranslator())
    exchange_path = tmp_path / "repairs.jsonl"
    exchange_path.write_text(
        json.dumps(
            {
                "item_id": 1,
                "translation_zh": "火车在9:30到达。",
                "review_note": "ok",
                "secret": "do-not-echo",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(TranslationImportError) as captured:
        import_llm_repairs(database, exchange_path)

    assert "secret" not in str(captured.value)
    assert "do-not-echo" not in str(captured.value)


def test_stale_selection_generation_cannot_checkpoint_translation(tmp_path: Path) -> None:
    database = _selected_database(tmp_path, ("The train arrives at nine.",))
    claimed = database.claim_translation_batch(1)
    assert claimed is not None

    database.replace_stage(
        "select",
        [(1, {"top_scene": "travel", "sub_scene": "travel_rail"})],
        model_version="selector-v2",
    )

    with pytest.raises(ValueError, match="选择快照已变化"):
        database.checkpoint_translation_batch(
            [(1, "火车九点到达。", ())],
            model_version="fake-1",
            selection_generation=claimed.selection_generation,
        )

    assert database.stage_counts().get("translate", 0) == 0
    assert database.translation_repairs() == []


def test_mark_stage_rejects_partial_select_snapshot_write(tmp_path: Path) -> None:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()

    with pytest.raises(ValueError, match="replace_stage"):
        database.mark_stage(1, "select", payload={})


def _selected_database(tmp_path: Path, texts: tuple[str, ...]) -> WorkDatabase:
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    item_ids: list[int] = []
    for index, text in enumerate(texts, start=1):
        item_id = database.upsert_raw(
            source_name="Tatoeba",
            source_item_id=str(index),
            source_url=f"https://tatoeba.org/en/sentences/show/{index}",
            source_author="alice",
            license_name="CC BY 2.0 FR",
            license_url="https://creativecommons.org/licenses/by/2.0/fr/",
            text=text,
        )
        database.mark_stage(item_id, "clean", payload={"clean_text": text})
        database.mark_stage(item_id, "dedupe", payload={"simhash64": str(index)})
        database.mark_stage(
            item_id,
            "classify",
            payload={"top_scene": "travel", "sub_scene": "travel_transport"},
        )
        item_ids.append(item_id)
    database.replace_stage(
        "select",
        [
            (item_id, {"top_scene": "travel", "sub_scene": "travel_transport"})
            for item_id in item_ids
        ],
        model_version="selector-v1",
    )
    return database
