from __future__ import annotations

import io
import json
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from tools.content_pipeline import production_sources
from tools.content_pipeline.archive_safety import validate_archive_member_path
from tools.content_pipeline.production_sources import import_all_sources
from tools.content_pipeline.work_database import WorkDatabase


def _write_sgd_archive(path: Path, dialogues: list[dict], schemas: list[dict]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("dstc8-schema-guided-dialogue-rev/train/schema.json", json.dumps(schemas))
        archive.writestr(
            "dstc8-schema-guided-dialogue-rev/train/dialogues_001.json",
            json.dumps(dialogues),
        )


def test_sgd_maps_only_unambiguous_services_and_writes_explicit_scenes(tmp_path: Path) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    archive_path = tmp_path / "sgd.zip"
    _write_sgd_archive(
        archive_path,
        [
            {
                "dialogue_id": "dlg-1",
                "services": ["Flights_1", "Hotels_1"],
                "turns": [
                    {
                        "speaker": "USER",
                        "utterance": "I need a flight tomorrow.",
                        "frames": [{"service": "Flights_1"}],
                    },
                    {
                        "speaker": "SYSTEM",
                        "utterance": "Which city are you leaving from?",
                        "frames": [{"service": "Flights_1"}, {"service": "Hotels_1"}],
                    },
                ],
            },
            {
                "dialogue_id": "dlg-2",
                "services": ["Hotels_1"],
                "turns": [
                    {"speaker": "USER", "utterance": "Find me a quiet hotel.", "frames": []}
                ],
            },
        ],
        [
            {"service_name": "Flights_1", "description": "Search and book flights."},
            {"service_name": "Hotels_1", "description": "Search and book hotels."},
        ],
    )

    items = list(iter_sgd_utterances(archive_path))

    assert [(item.text, item.source_item_id, item.top_scene, item.sub_scene) for item in items] == [
        ("I need a flight tomorrow.", "sgd:train:dlg-1:turn:0", "travel", "travel_transport"),
        ("Find me a quiet hotel.", "sgd:train:dlg-2:turn:0", "travel", "travel_hotel"),
    ]
    assert all(item.source_author == "" for item in items)
    assert all(item.source_name == "sgd" for item in items)


def test_sgd_skips_empty_string_turns_and_keeps_valid_turns(tmp_path: Path) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    archive_path = tmp_path / "sgd.zip"
    _write_sgd_archive(
        archive_path,
        [
            {
                "dialogue_id": "goodbye-with-empty-system-utterance",
                "services": ["Flights_1"],
                "turns": [
                    {
                        "speaker": "SYSTEM",
                        "utterance": " \t\n ",
                        "frames": [{"service": "Flights_1"}],
                    },
                    {
                        "speaker": "USER",
                        "utterance": "Book a flight tomorrow.",
                        "frames": [{"service": "Flights_1"}],
                    },
                ],
            }
        ],
        [{"service_name": "Flights_1", "description": "Search and book flights."}],
    )

    [item] = list(iter_sgd_utterances(archive_path))

    assert item.text == "Book a flight tomorrow."
    assert item.source_item_id == (
        "sgd:train:goodbye-with-empty-system-utterance:turn:1"
    )


def test_sgd_rejects_invalid_frames_container_on_empty_turn(tmp_path: Path) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    archive_path = tmp_path / "sgd.zip"
    _write_sgd_archive(
        archive_path,
        [
            {
                "dialogue_id": "malformed-empty-turn",
                "services": ["Flights_1"],
                "turns": [
                    {"speaker": "SYSTEM", "utterance": "  ", "frames": 7},
                    {
                        "speaker": "USER",
                        "utterance": "Book a flight tomorrow.",
                        "frames": [{"service": "Flights_1"}],
                    },
                ],
            }
        ],
        [{"service_name": "Flights_1", "description": "Search and book flights."}],
    )

    with pytest.raises(ValueError, match="SGD turn 缺少 frames 数组"):
        list(iter_sgd_utterances(archive_path))


def test_sgd_uses_schema_description_for_health_services(tmp_path: Path) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    archive_path = tmp_path / "sgd.zip"
    _write_sgd_archive(
        archive_path,
        [
            {
                "dialogue_id": "health",
                "services": ["Services_2"],
                "turns": [
                    {"speaker": "USER", "utterance": "I need a dentist appointment.", "frames": []}
                ],
            }
        ],
        [{"service_name": "Services_2", "description": "Find dentists and book appointments."}],
    )

    [item] = list(iter_sgd_utterances(archive_path))
    assert (item.top_scene, item.sub_scene) == ("health", "health_clinic")


@pytest.mark.parametrize(
    ("service", "description", "expected"),
    [
        ("Services_2", "Find dentists and book appointments.", "health_clinic"),
        ("Services_3", "Find a doctor or physician nearby.", "health_clinic"),
        ("Services_4", "Find a mental health therapist.", "health_wellbeing"),
        ("Services_2", "Find a hair salon and book a haircut.", None),
        ("Services_3", "Arrange home maintenance services.", None),
        ("Services_4", "Book professional photography services.", None),
    ],
)
def test_sgd_health_service_mapping_requires_matching_schema_description(
    service: str, description: str, expected: str | None
) -> None:
    from tools.content_pipeline.sgd_source import _service_scene

    assert _service_scene(service, {service: description}) == expected


def test_sgd_skips_service_labels_missing_from_the_matching_schema(tmp_path: Path) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    archive_path = tmp_path / "sgd.zip"
    _write_sgd_archive(
        archive_path,
        [
            {
                "dialogue_id": "missing-schema",
                "services": ["Flights_9"],
                "turns": [
                    {"speaker": "USER", "utterance": "Do not trust this label.", "frames": []}
                ],
            },
            {
                "dialogue_id": "valid-schema",
                "services": ["Hotels_1"],
                "turns": [
                    {"speaker": "USER", "utterance": "Find a hotel.", "frames": []}
                ],
            },
        ],
        [{"service_name": "Hotels_1", "description": "Search hotels."}],
    )

    items = list(iter_sgd_utterances(archive_path))
    assert [item.source_item_id for item in items] == ["sgd:train:valid-schema:turn:0"]


def test_sgd_does_not_borrow_a_service_schema_from_another_split(tmp_path: Path) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    archive_path = tmp_path / "sgd.zip"
    dialogue = {
        "dialogue_id": "wrong-split",
        "services": ["Flights_1"],
        "turns": [{"speaker": "USER", "utterance": "Book a flight.", "frames": []}],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "root/train/schema.json",
            json.dumps([{"service_name": "Hotels_1", "description": "Hotels"}]),
        )
        archive.writestr("root/train/dialogues_001.json", json.dumps([dialogue]))
        archive.writestr(
            "root/dev/schema.json",
            json.dumps([{"service_name": "Flights_1", "description": "Flights"}]),
        )

    with pytest.raises(ValueError, match="SGD.*有效记录"):
        list(iter_sgd_utterances(archive_path))


def test_sgd_rejects_frame_service_outside_dialogue_services(tmp_path: Path) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    archive_path = tmp_path / "sgd.zip"
    _write_sgd_archive(
        archive_path,
        [
            {
                "dialogue_id": "contradiction",
                "services": ["Hotels_1"],
                "turns": [
                    {
                        "speaker": "USER",
                        "utterance": "This frame contradicts the dialogue.",
                        "frames": [{"service": "Flights_1"}],
                    }
                ],
            }
        ],
        [
            {"service_name": "Hotels_1", "description": "Hotels"},
            {"service_name": "Flights_1", "description": "Flights"},
        ],
    )

    with pytest.raises(ValueError, match="frame service.*dialogue services"):
        list(iter_sgd_utterances(archive_path))


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_message"),
    [
        ("dialogue_id", 7, "必须是非空字符串"),
        ("services_item", 7, "必须是非空字符串"),
        ("speaker", 7, "必须是非空字符串"),
        ("utterance", 7, "必须是字符串"),
        ("frame_service", 7, "必须是非空字符串"),
    ],
)
def test_sgd_rejects_non_string_json_fields(
    tmp_path: Path, field: str, invalid_value: object, expected_message: str
) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    dialogue = {
        "dialogue_id": "strict",
        "services": ["Flights_1"],
        "turns": [
            {
                "speaker": "USER",
                "utterance": "Book a flight.",
                "frames": [{"service": "Flights_1"}],
            }
        ],
    }
    if field == "dialogue_id":
        dialogue["dialogue_id"] = invalid_value
    elif field == "services_item":
        dialogue["services"] = [invalid_value]
    elif field == "speaker":
        dialogue["turns"][0]["speaker"] = invalid_value
    elif field == "utterance":
        dialogue["turns"][0]["utterance"] = invalid_value
    else:
        dialogue["turns"][0]["frames"][0]["service"] = invalid_value
    archive_path = tmp_path / "strict.zip"
    _write_sgd_archive(
        archive_path,
        [dialogue],
        [{"service_name": "Flights_1", "description": "Flights"}],
    )

    with pytest.raises(ValueError, match=expected_message):
        list(iter_sgd_utterances(archive_path))


def test_sgd_rejects_path_drift_empty_archives_and_duplicate_ids(tmp_path: Path) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    wrong_path = tmp_path / "wrong.zip"
    with zipfile.ZipFile(wrong_path, "w") as archive:
        archive.writestr("train/dialog.json", "[]")
    with pytest.raises(ValueError, match="SGD.*结构"):
        list(iter_sgd_utterances(wrong_path))

    empty = tmp_path / "empty.zip"
    _write_sgd_archive(empty, [], [{"service_name": "Flights_1", "description": "Flights"}])
    with pytest.raises(ValueError, match="SGD.*有效记录"):
        list(iter_sgd_utterances(empty))

    duplicate = tmp_path / "duplicate.zip"
    dialogue = {
        "dialogue_id": "same",
        "services": ["Flights_1"],
        "turns": [{"speaker": "USER", "utterance": "Book a flight.", "frames": []}],
    }
    with zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr(
            "dstc8-schema-guided-dialogue-rev/train/schema.json",
            json.dumps([{"service_name": "Flights_1", "description": "Flights"}]),
        )
        archive.writestr(
            "dstc8-schema-guided-dialogue-rev/train/dialogues_001.json", json.dumps([dialogue])
        )
        archive.writestr(
            "dstc8-schema-guided-dialogue-rev/train/dialogues_002.json", json.dumps([dialogue])
        )
    with pytest.raises(ValueError, match="重复稳定 ID"):
        list(iter_sgd_utterances(duplicate))


@pytest.mark.parametrize("unsafe_root", ["..", ".", "C:/escape", "/absolute"])
def test_sgd_rejects_unsafe_member_paths(tmp_path: Path, unsafe_root: str) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    archive_path = tmp_path / "unsafe.zip"
    dialogue = {
        "dialogue_id": "one",
        "services": ["Flights_1"],
        "turns": [{"speaker": "USER", "utterance": "Book a flight.", "frames": []}],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            f"{unsafe_root}/train/schema.json",
            json.dumps([{"service_name": "Flights_1", "description": "Flights"}]),
        )
        archive.writestr(
            f"{unsafe_root}/train/dialogues_001.json", json.dumps([dialogue])
        )

    with pytest.raises(ValueError, match="不安全路径"):
        list(iter_sgd_utterances(archive_path))


@pytest.mark.parametrize("member_kind", ["symlink", "fifo"])
def test_sgd_rejects_non_regular_matching_zip_members(
    tmp_path: Path, member_kind: str
) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    archive_path = tmp_path / "special.zip"
    info = zipfile.ZipInfo("root/train/schema.json")
    info.create_system = 3
    file_type = stat.S_IFLNK if member_kind == "symlink" else stat.S_IFIFO
    info.external_attr = (file_type | 0o644) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, "target")
        archive.writestr("root/train/dialogues_001.json", "[]")

    with pytest.raises(ValueError, match="普通文件"):
        list(iter_sgd_utterances(archive_path))


def test_sgd_rejects_mixed_archive_roots(tmp_path: Path) -> None:
    from tools.content_pipeline.sgd_source import iter_sgd_utterances

    archive_path = tmp_path / "mixed-root.zip"
    dialogue = {
        "dialogue_id": "one",
        "services": ["Flights_1"],
        "turns": [{"speaker": "USER", "utterance": "Book a flight.", "frames": []}],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "root-a/train/schema.json",
            json.dumps([{"service_name": "Flights_1", "description": "Flights"}]),
        )
        archive.writestr("root-b/train/dialogues_001.json", json.dumps([dialogue]))

    with pytest.raises(ValueError, match="SGD.*根目录"):
        list(iter_sgd_utterances(archive_path))


def test_production_validator_exhausts_labeled_parser_to_detect_duplicate_ids(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "duplicate.zip"
    dialogue = {
        "dialogue_id": "same",
        "services": ["Flights_1"],
        "turns": [{"speaker": "USER", "utterance": "Book a flight.", "frames": []}],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "root/train/schema.json",
            json.dumps([{"service_name": "Flights_1", "description": "Flights"}]),
        )
        archive.writestr("root/train/dialogues_001.json", json.dumps([dialogue]))
        archive.writestr("root/train/dialogues_002.json", json.dumps([dialogue]))

    with pytest.raises(ValueError, match="重复稳定 ID"):
        production_sources._validate_downloaded_source(
            "sgd", archive_path, {"key": "sgd"}, "0" * 64
        )


def test_clinc_imports_only_allowlisted_in_scope_rows_and_appends_punctuation(
    tmp_path: Path,
) -> None:
    from tools.content_pipeline.clinc_source import iter_clinc150_utterances

    archive_path = tmp_path / "clinc.zip"
    payload = {
        "train": [
            ["where is the nearest station", "directions"],
            ["Keep THIS?", "directions"],
            ['He asked, “where?”', "directions"],
        ],
        "val": [["book a hotel room", "book_hotel"]],
        "test": [["debug the device", "unsupported_intent"]],
        "oos_train": [["must never import", "oos"]],
        "oos_val": [],
        "oos_test": [],
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("oos-eval-rev/data/data_full.json", json.dumps(payload))

    items = list(iter_clinc150_utterances(archive_path, normalization_version=1))

    assert [(item.text, item.source_item_id, item.sub_scene) for item in items] == [
        ("where is the nearest station.", "clinc150:train:0:norm-v1", "travel_directions"),
        ("Keep THIS?", "clinc150:train:1:norm-v1", "travel_directions"),
        ('He asked, “where?”', "clinc150:train:2:norm-v1", "travel_directions"),
        ("book a hotel room.", "clinc150:val:0:norm-v1", "travel_hotel"),
    ]
    assert all(item.source_author == "" for item in items)
    assert all("oos" not in item.source_item_id for item in items)


def test_clinc_allowlist_matches_the_25_live_fixed_archive_intents() -> None:
    from tools.content_pipeline.clinc_source import CLINC_INTENT_SCENES

    assert CLINC_INTENT_SCENES == {
        "book_flight": "travel_transport",
        "book_hotel": "travel_hotel",
        "car_rental": "travel_transport",
        "carry_on": "travel_transport",
        "change_volume": "technology_devices",
        "definition": "study_language",
        "directions": "travel_directions",
        "exchange_rate": "news_business",
        "flight_status": "travel_transport",
        "jump_start": "technology_engineering",
        "meal_suggestion": "daily_food",
        "meeting_schedule": "work_meetings",
        "oil_change_how": "technology_engineering",
        "order_status": "daily_shopping",
        "payday": "work_jobs",
        "pto_request": "work_office",
        "recipe": "daily_food",
        "schedule_meeting": "work_meetings",
        "shopping_list": "daily_shopping",
        "smart_home": "daily_home",
        "spelling": "study_language",
        "sync_device": "technology_devices",
        "tire_change": "technology_engineering",
        "tire_pressure": "technology_engineering",
        "translate": "study_language",
    }


def test_dead_clinc_intents_from_the_fixed_archive_are_not_allowlisted() -> None:
    from tools.content_pipeline.clinc_source import CLINC_INTENT_SCENES

    dead_intents = {
        "balance_not_updated_after_bank_transfer",
        "balance_not_updated_after_cheque_or_cash_deposit",
        "benefits",
        "cancel_meeting",
        "cancel_order",
        "car_manual",
        "card_payment_fee_charged",
        "cash_withdrawal",
        "connect_device",
        "email_contact",
        "engineering_support",
        "gas_station",
        "hotel_check_in",
        "hotel_check_out",
        "install_software",
        "job_application",
        "pending_transfer",
        "public_transport",
        "receiving_money",
        "restaurant",
        "return_item",
        "send_email",
        "software_update",
        "tourist_attraction",
        "transfer_fee_charged",
        "visa_or_passport",
    }
    assert dead_intents.isdisjoint(CLINC_INTENT_SCENES)


def test_massive_allowlist_excludes_reviewed_mixed_semantics() -> None:
    from tools.content_pipeline.massive_source import MASSIVE_LABEL_SCENES

    assert MASSIVE_LABEL_SCENES[("iot", "iot_hue_lighton")] == "technology_devices"
    assert MASSIVE_LABEL_SCENES[("cooking", "cooking_recipe")] == "daily_food"
    assert MASSIVE_LABEL_SCENES[("play", "play_music")] == "culture_music"
    assert MASSIVE_LABEL_SCENES[("news", "news_query")] == "news_current"
    assert MASSIVE_LABEL_SCENES[("social", "social_post")] == "daily_social"
    assert MASSIVE_LABEL_SCENES[("weather", "weather_query")] == "news_environment"
    assert MASSIVE_LABEL_SCENES[("play", "play_audiobook")] == "culture_books"
    assert MASSIVE_LABEL_SCENES[("recommendation", "recommendation_movies")] == "culture_movies"
    assert MASSIVE_LABEL_SCENES[("qa", "qa_stock")] == "news_business"
    assert MASSIVE_LABEL_SCENES[("transport", "transport_directions")] == "travel_directions"

    for unsafe_pair in (
        ("alarm", "alarm_set"),
        ("calendar", "calendar_set"),
        ("lists", "lists_query"),
        ("play", "play_podcasts"),
        ("play", "play_radio"),
        ("play", "play_game"),
        ("recommendation", "recommendation_events"),
        ("recommendation", "recommendation_locations"),
        ("qa", "qa_factoid"),
        ("qa", "qa_maths"),
        ("qa", "qa_definition"),
        ("transport", "transport_query"),
        ("email", "email_addcontact"),
        ("email", "email_query"),
        ("email", "email_querycontact"),
        ("email", "email_sendemail"),
    ):
        assert unsafe_pair not in MASSIVE_LABEL_SCENES


def test_clinc_rejects_schema_drift_empty_and_duplicate_data_members(tmp_path: Path) -> None:
    from tools.content_pipeline.clinc_source import iter_clinc150_utterances

    wrong = tmp_path / "wrong.zip"
    with zipfile.ZipFile(wrong, "w") as archive:
        archive.writestr("data_full.json", json.dumps({"train": []}))
    with pytest.raises(ValueError, match="CLINC150.*结构"):
        list(iter_clinc150_utterances(wrong, normalization_version=1))

    empty = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr(
            "oos-eval-rev/data/data_full.json",
            json.dumps({"train": [["unknown", "not_allowed"]], "val": [], "test": []}),
        )
    with pytest.raises(ValueError, match="CLINC150.*有效记录"):
        list(iter_clinc150_utterances(empty, normalization_version=1))

    duplicate = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr(
            "oos-eval-rev/data/data_full.json",
            json.dumps({"train": [["one", "directions"]], "val": [], "test": []}),
        )
        archive.writestr(
            "another-root/data/data_full.json",
            json.dumps({"train": [["two", "directions"]], "val": [], "test": []}),
        )
    with pytest.raises(ValueError, match="结构漂移"):
        list(iter_clinc150_utterances(duplicate, normalization_version=1))


@pytest.mark.parametrize("unsafe_root", ["..", ".", "C:/escape", "/absolute"])
def test_clinc_rejects_unsafe_member_paths(tmp_path: Path, unsafe_root: str) -> None:
    from tools.content_pipeline.clinc_source import iter_clinc150_utterances

    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            f"{unsafe_root}/data/data_full.json",
            json.dumps({"train": [["where", "directions"]], "val": [], "test": []}),
        )

    with pytest.raises(ValueError, match="不安全路径"):
        list(iter_clinc150_utterances(archive_path, normalization_version=1))


def test_archive_member_validator_rejects_backslashes_before_zip_normalization() -> None:
    with pytest.raises(ValueError, match="不安全路径"):
        validate_archive_member_path("root\\escape/data.json", label="测试归档")


@pytest.mark.parametrize("member_kind", ["symlink", "fifo"])
def test_clinc_rejects_non_regular_matching_zip_member(
    tmp_path: Path, member_kind: str
) -> None:
    from tools.content_pipeline.clinc_source import iter_clinc150_utterances

    archive_path = tmp_path / "special.zip"
    info = zipfile.ZipInfo("root/data/data_full.json")
    info.create_system = 3
    file_type = stat.S_IFLNK if member_kind == "symlink" else stat.S_IFIFO
    info.external_attr = (file_type | 0o644) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, "target")

    with pytest.raises(ValueError, match="普通文件"):
        list(iter_clinc150_utterances(archive_path, normalization_version=1))


def _write_massive_archive(
    path: Path, rows: list[dict], member: str = "1.0/data/en-US.jsonl"
) -> None:
    payload = "".join(json.dumps(row) + "\n" for row in rows).encode()
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(member)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))


def test_massive_maps_explicit_labels_and_preserves_normalized_worker(tmp_path: Path) -> None:
    from tools.content_pipeline.massive_source import iter_massive_utterances

    archive_path = tmp_path / "massive.tar.gz"
    _write_massive_archive(
        archive_path,
        [
            {
                "id": "42",
                "locale": "en-US",
                "scenario": "play",
                "intent": "play_music",
                "utt": "Play the next song!”",
                "worker_id": "  Worker 7  ",
            },
            {
                "id": "43",
                "locale": "en-US",
                "scenario": "unsupported",
                "intent": "unsupported",
                "utt": "Do not import me",
                "worker_id": "8",
            },
        ],
    )

    [item] = list(iter_massive_utterances(archive_path, normalization_version=1))
    assert (item.text, item.source_item_id, item.top_scene, item.sub_scene) == (
        "Play the next song!”",
        "massive-1.0:en-US:42:norm-v1",
        "culture",
        "culture_music",
    )
    assert item.source_author == "massive-worker:Worker 7"


def test_massive_keeps_missing_worker_id_anonymous(tmp_path: Path) -> None:
    from tools.content_pipeline.massive_source import iter_massive_utterances

    archive_path = tmp_path / "massive.tar.gz"
    _write_massive_archive(
        archive_path,
        [
            {
                "id": "42",
                "locale": "en-US",
                "scenario": "play",
                "intent": "play_music",
                "utt": "Play the next song",
                "worker_id": None,
            }
        ],
    )

    [item] = list(iter_massive_utterances(archive_path, normalization_version=1))
    assert item.source_author == ""


def test_massive_rejects_path_drift_symlinks_empty_data_and_duplicate_ids(tmp_path: Path) -> None:
    from tools.content_pipeline.massive_source import iter_massive_utterances

    wrong = tmp_path / "wrong.tar.gz"
    _write_massive_archive(wrong, [], member="data/en-US.jsonl")
    with pytest.raises(ValueError, match="MASSIVE.*结构"):
        list(iter_massive_utterances(wrong, normalization_version=1))

    symlink = tmp_path / "symlink.tar.gz"
    with tarfile.open(symlink, "w:gz") as archive:
        info = tarfile.TarInfo("1.0/data/en-US.jsonl")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../escape"
        archive.addfile(info)
    with pytest.raises(ValueError, match="普通文件"):
        list(iter_massive_utterances(symlink, normalization_version=1))

    empty = tmp_path / "empty.tar.gz"
    _write_massive_archive(
        empty,
        [{"id": "1", "locale": "fr-FR", "scenario": "play", "intent": "play_music", "utt": "x"}],
    )
    with pytest.raises(ValueError, match="MASSIVE.*有效记录"):
        list(iter_massive_utterances(empty, normalization_version=1))

    duplicate = tmp_path / "duplicate.tar.gz"
    row = {
        "id": "same",
        "locale": "en-US",
        "scenario": "play",
        "intent": "play_music",
        "utt": "Play music",
        "worker_id": "1",
    }
    _write_massive_archive(duplicate, [row, row])
    with pytest.raises(ValueError, match="重复稳定 ID"):
        list(iter_massive_utterances(duplicate, normalization_version=1))


def test_massive_rejects_non_regular_fifo_member(tmp_path: Path) -> None:
    from tools.content_pipeline.massive_source import iter_massive_utterances

    archive_path = tmp_path / "fifo.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("1.0/data/en-US.jsonl")
        info.type = tarfile.FIFOTYPE
        archive.addfile(info)

    with pytest.raises(ValueError, match="普通文件"):
        list(iter_massive_utterances(archive_path, normalization_version=1))


@pytest.mark.parametrize("unsafe_root", ["..", ".", "root\\escape", "/absolute"])
def test_massive_rejects_unsafe_member_paths(tmp_path: Path, unsafe_root: str) -> None:
    from tools.content_pipeline.massive_source import iter_massive_utterances

    archive_path = tmp_path / "unsafe.tar.gz"
    _write_massive_archive(
        archive_path,
        [],
        member=f"{unsafe_root}/1.0/data/en-US.jsonl",
    )

    with pytest.raises(ValueError, match="不安全路径"):
        list(iter_massive_utterances(archive_path, normalization_version=1))


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("id", 7),
        ("locale", 7),
        ("scenario", 7),
        ("intent", 7),
        ("utt", 7),
        ("worker_id", 7),
    ],
)
def test_massive_rejects_invalid_json_field_types(
    tmp_path: Path, field: str, invalid_value: object
) -> None:
    from tools.content_pipeline.massive_source import iter_massive_utterances

    row = {
        "id": "strict",
        "locale": "en-US",
        "scenario": "play",
        "intent": "play_music",
        "utt": "Play music.",
        "worker_id": "w1",
    }
    row[field] = invalid_value
    archive_path = tmp_path / "strict.tar.gz"
    _write_massive_archive(archive_path, [row])

    with pytest.raises(ValueError, match="字段类型错误"):
        list(iter_massive_utterances(archive_path, normalization_version=1))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('He said “hello”', 'He said “hello.”'),
        ("Ask 'where'", "Ask 'where.'"),
        ('He asked “where?”', 'He asked “where?”'),
        ("She shouted “stop!”", "She shouted “stop!”"),
    ],
)
def test_labeled_normalization_inserts_punctuation_before_closing_quotes(
    text: str, expected: str
) -> None:
    from tools.content_pipeline.clinc_source import _append_terminal_punctuation as clinc
    from tools.content_pipeline.massive_source import _append_terminal_punctuation as massive

    assert clinc(text) == expected
    assert massive(text) == expected


def test_import_all_integrates_labeled_sources_with_lock_and_scene_metadata(
    tmp_path: Path,
) -> None:
    sgd_path = tmp_path / "sgd.zip"
    _write_sgd_archive(
        sgd_path,
        [
            {
                "dialogue_id": "flight",
                "services": ["Flights_1"],
                "turns": [
                    {"speaker": "USER", "utterance": "Book a flight.", "frames": []}
                ],
            }
        ],
        [{"service_name": "Flights_1", "description": "Search flights."}],
    )
    clinc_path = tmp_path / "clinc.zip"
    with zipfile.ZipFile(clinc_path, "w") as archive:
        archive.writestr(
            "oos-eval-rev/data/data_full.json",
            json.dumps(
                {"train": [["show directions", "directions"]], "val": [], "test": []}
            ),
        )
    massive_path = tmp_path / "massive.tar.gz"
    _write_massive_archive(
        massive_path,
        [
            {
                "id": "m1",
                "locale": "en-US",
                "scenario": "play",
                "intent": "play_music",
                "utt": "Play music",
                "worker_id": "w1",
            }
        ],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            [
                {"key": "sgd", "kind": "sgd", "url": sgd_path.as_uri()},
                {
                    "key": "clinc150",
                    "kind": "clinc150",
                    "url": clinc_path.as_uri(),
                    "normalization_version": 1,
                },
                {
                    "key": "massive-1-0",
                    "kind": "massive",
                    "url": massive_path.as_uri(),
                    "normalization_version": 1,
                },
            ]
        ),
        encoding="utf-8",
    )
    database = WorkDatabase(tmp_path / "work.db")
    database.initialize()
    lock_path = tmp_path / "source-lock.json"

    counts = import_all_sources(database, manifest_path, lock_path)

    assert counts == {"sgd": 1, "clinc150": 1, "massive": 1}
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock["complete"] is True
    assert {
        entry["key"]: entry["config"].get("normalization_version")
        for entry in lock["sources"]
    } == {"sgd": None, "clinc150": 1, "massive-1-0": 1}
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT source_name, source_item_id, source_author, top_scene, sub_scene
            FROM raw_items ORDER BY source_name
            """
        ).fetchall()
    assert rows == [
        ("clinc150", "clinc150:train:0:norm-v1", "", "travel", "travel_directions"),
        (
            "massive-1.0",
            "massive-1.0:en-US:m1:norm-v1",
            "massive-worker:w1",
            "culture",
            "culture_music",
        ),
        ("sgd", "sgd:train:flight:turn:0", "", "travel", "travel_transport"),
    ]
