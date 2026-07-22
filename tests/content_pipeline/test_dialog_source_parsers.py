from __future__ import annotations

import csv
import importlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from tools.content_pipeline.models import CollectedSentence


def _load_parser(module_name: str, function_name: str):
    try:
        module = importlib.import_module(f"tools.content_pipeline.{module_name}")
    except ModuleNotFoundError:
        pytest.fail(f"尚未实现来源解析器: {module_name}")
    return getattr(module, function_name)


def test_multiwoz_reader_emits_only_original_turns_with_stable_provenance(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "multiwoz.zip"
    payload = [
        {
            "dialogue_id": "PMUL0012.json",
            "services": ["hotel"],
            "turns": [
                {"speaker": "USER", "utterance": "I need a hotel near the station."},
                {"speaker": "SYSTEM", "utterance": "What price range do you prefer?"},
                {"speaker": "USER", "utterance": "   "},
            ],
        }
    ]
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "multiwoz-master/data/MultiWOZ_2.2/train/dialogues_001.json",
            json.dumps(payload),
        )
        archive.writestr("multiwoz-master/data/MultiWOZ_2.2/schema.json", "[]")

    reader = _load_parser("multiwoz_source", "iter_multiwoz_utterances")
    expected = [
        CollectedSentence(
            text="I need a hotel near the station.",
            source_item_id="train:PMUL0012.json:turn:1",
            source_author="",
            source_url=(
                "https://github.com/budzianowski/multiwoz/tree/"
                "fe0c8e65cfcd8462bd33c86e35f21addc84ca82b/data/MultiWOZ_2.2"
            ),
            source_name="multiwoz-2-2",
            license_name="MIT",
            license_url=(
                "https://github.com/budzianowski/multiwoz/blob/"
                "fe0c8e65cfcd8462bd33c86e35f21addc84ca82b/LICENSE"
            ),
        ),
        CollectedSentence(
            text="What price range do you prefer?",
            source_item_id="train:PMUL0012.json:turn:2",
            source_author="",
            source_url=(
                "https://github.com/budzianowski/multiwoz/tree/"
                "fe0c8e65cfcd8462bd33c86e35f21addc84ca82b/data/MultiWOZ_2.2"
            ),
            source_name="multiwoz-2-2",
            license_name="MIT",
            license_url=(
                "https://github.com/budzianowski/multiwoz/blob/"
                "fe0c8e65cfcd8462bd33c86e35f21addc84ca82b/LICENSE"
            ),
        ),
    ]

    assert list(reader(archive_path)) == expected
    assert list(reader(archive_path)) == expected
    assert all(item.top_scene is None and item.sub_scene is None for item in expected)


def test_dailydialog_reader_uses_original_and_turn_ids_without_metadata_labels(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "dailydialog.zip"
    payload = [
        {
            "dataset": "dailydialog",
            "data_split": "train",
            "dialogue_id": "dailydialog-train-7",
            "original_id": "train-7",
            "domains": ["Work"],
            "turns": [
                {
                    "speaker": "user",
                    "utterance": "We should start the meeting.",
                    "utt_idx": 0,
                    "dialogue_acts": {"binary": [], "categorical": [], "non-categorical": []},
                    "emotion": "no emotion",
                },
                {
                    "speaker": "system",
                    "utterance": "Yes, let's begin.",
                    "utt_idx": 1,
                    "dialogue_acts": {"binary": [], "categorical": [], "non-categorical": []},
                    "emotion": "happiness",
                },
            ],
        }
    ]
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("data/dialogues.json", json.dumps(payload))
        archive.writestr("data/ontology.json", "{}")

    reader = _load_parser("dailydialog_source", "iter_dailydialog_utterances")
    items = list(reader(archive_path))

    assert [item.text for item in items] == [
        "We should start the meeting.",
        "Yes, let's begin.",
    ]
    assert [item.source_item_id for item in items] == [
        "train-7:turn:0",
        "train-7:turn:1",
    ]
    assert all(item.source_author == "" for item in items)
    assert all(item.source_name == "daily-dialog" for item in items)
    assert all(
        item.source_url
        == (
            "https://huggingface.co/datasets/ConvLab/dailydialog/tree/"
            "745c1796cfe209b469394567f496815d2bc495d2"
        )
        for item in items
    )
    assert all(item.category_hint is None for item in items)


def test_mts_dialog_reader_ignores_summaries_and_augmented_data(tmp_path: Path) -> None:
    archive_path = tmp_path / "mts-dialog.zip"
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["ID", "section_header", "section_text", "dialogue"])
    writer.writeheader()
    writer.writerow(
        {
            "ID": "37",
            "section_header": "medications",
            "section_text": "This generated clinical summary must not be imported.",
            "dialogue": (
                "Doctor: Are you taking any medication? "
                "Patient: I take one tablet every morning. "
                "Doctor: Please continue it until Friday. "
                "Guest_family: We will help her remember."
            ),
        }
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "MTS-Dialog-main/Main-Dataset/MTS-Dialog-TrainingSet.csv",
            output.getvalue(),
        )
        archive.writestr(
            "MTS-Dialog-main/Augmented-Data/MTS-Dialog-Augmented-TrainingSet.csv",
            output.getvalue(),
        )

    reader = _load_parser("mts_dialog_source", "iter_mts_dialog_utterances")
    items = list(reader(archive_path))

    assert [item.text for item in items] == [
        "Are you taking any medication?",
        "I take one tablet every morning.",
        "Please continue it until Friday.",
        "We will help her remember.",
    ]
    assert [item.source_item_id for item in items] == [
        "train:37:turn:1",
        "train:37:turn:2",
        "train:37:turn:3",
        "train:37:turn:4",
    ]
    assert all(item.source_author == "" for item in items)
    assert all("summary" not in item.text for item in items)
    assert all(item.source_name == "mts-dialog" for item in items)
    assert all(
        item.source_url
        == (
            "https://github.com/abachaa/MTS-Dialog/tree/"
            "3ff0801933608d6f570468c13125125fb5cabdea/Main-Dataset"
        )
        for item in items
    )


def test_source_manifest_adds_three_official_dialogue_archives() -> None:
    manifest_path = Path(__file__).parents[2] / "tools/content_pipeline/source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_key = {str(source["key"]): source for source in manifest}

    assert by_key["multiwoz-2-2"] == {
        "key": "multiwoz-2-2",
        "kind": "multiwoz",
        "url": (
            "https://github.com/budzianowski/multiwoz/archive/"
            "fe0c8e65cfcd8462bd33c86e35f21addc84ca82b.zip"
        ),
        "license_name": "MIT",
        "license_url": (
            "https://github.com/budzianowski/multiwoz/blob/"
            "fe0c8e65cfcd8462bd33c86e35f21addc84ca82b/LICENSE"
        ),
    }
    assert by_key["daily-dialog"] == {
        "key": "daily-dialog",
        "kind": "dailydialog",
        "url": (
            "https://huggingface.co/datasets/ConvLab/dailydialog/resolve/"
            "745c1796cfe209b469394567f496815d2bc495d2/data.zip"
        ),
        "expected_sha256": (
            "b1f38f3bf5431f9384107011a943f1a3446027721292e3a248a894b7766fa9d3"
        ),
        "license_name": "CC BY-NC-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    }
    assert by_key["mts-dialog"] == {
        "key": "mts-dialog",
        "kind": "mts-dialog",
        "url": (
            "https://github.com/abachaa/MTS-Dialog/archive/"
            "3ff0801933608d6f570468c13125125fb5cabdea.zip"
        ),
        "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
    }
