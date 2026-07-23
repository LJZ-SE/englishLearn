from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


def _reader():
    try:
        module = importlib.import_module("tools.content_pipeline.taskmaster_source")
    except ModuleNotFoundError:
        pytest.fail("尚未实现 Taskmaster-2 来源解析器")
    return module.iter_taskmaster2_utterances


def _write_domain(path: Path, conversations: list[object]) -> None:
    path.write_text(json.dumps(conversations), encoding="utf-8")


def _conversation(
    conversation_id: object = "movie-1",
    utterances: object | None = None,
    instruction_id: object = "movie-default",
) -> dict[str, object]:
    if utterances is None:
        utterances = [
            {"speaker": "USER", "text": "Can you recommend a mystery movie?"},
            {"speaker": "ASSISTANT", "text": "Try a classic detective story."},
        ]
    if isinstance(utterances, list):
        utterances = [
            ({"index": index, **utterance} if isinstance(utterance, dict) else utterance)
            for index, utterance in enumerate(utterances)
        ]
    return {
        "conversation_id": conversation_id,
        "instruction_id": instruction_id,
        "utterances": utterances,
    }


def test_taskmaster2_movies_emits_fixed_scene_and_stable_provenance(tmp_path: Path) -> None:
    source = tmp_path / "movies.json"
    _write_domain(source, [_conversation()])

    items = list(_reader()(source, domain="movies"))

    assert [(item.text, item.source_item_id, item.top_scene, item.sub_scene) for item in items] == [
        (
            "Can you recommend a mystery movie?",
            "taskmaster2:movies:conversation:0:movie-1:utterance:0",
            "culture",
            "culture_movies",
        ),
        (
            "Try a classic detective story.",
            "taskmaster2:movies:conversation:0:movie-1:utterance:1",
            "culture",
            "culture_movies",
        ),
    ]
    assert all(item.source_name == "taskmaster2-movies" for item in items)
    assert all(item.source_author == "" for item in items)
    assert all(item.license_name == "CC BY 4.0" for item in items)
    assert all(
        item.source_url
        == "https://github.com/google-research-datasets/Taskmaster/blob/"
        "d92cb6af3005f1dc09c39e75e7daf4a04905e00b/TM-2-2020/data/movies.json"
        for item in items
    )


def test_taskmaster2_sports_uses_domain_not_annotations_for_scene(tmp_path: Path) -> None:
    source = tmp_path / "sports.json"
    _write_domain(
        source,
        [
            {
                **_conversation(
                    "sports-7",
                    [{"speaker": "USER", "text": "Who won the match?"}],
                    instruction_id="nfl-default",
                ),
                "annotations": {"topic": "travel"},
            }
        ],
    )

    [item] = list(_reader()(source, domain="sports"))

    assert (item.top_scene, item.sub_scene) == ("culture", "culture_sports")
    assert item.source_name == "taskmaster2-sports"


def test_taskmaster2_rejects_unknown_domain_before_reading_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Taskmaster-2 不支持 domain"):
        list(_reader()(tmp_path / "missing.json", domain="restaurants"))


@pytest.mark.parametrize(
    ("conversations", "expected_message"),
    [
        ({"conversation_id": "not-an-array"}, "JSON 根节点必须是数组"),
        ([{"utterances": []}], "conversation_id 必须是非空字符串"),
        ([_conversation(7)], "conversation_id 必须是非空字符串"),
        ([_conversation("  ")], "conversation_id 必须是非空字符串"),
        ([_conversation(utterances="not-an-array")], "utterances 必须是数组"),
        ([_conversation(utterances=["not-an-object"])], "utterance 必须是对象"),
        ([_conversation(utterances=[{"speaker": 7, "text": "Hello."}])], "speaker 必须是字符串"),
        ([_conversation(utterances=[{"speaker": "USER", "text": 7}])], "text 必须是字符串"),
    ],
)
def test_taskmaster2_rejects_schema_drift(
    tmp_path: Path, conversations: object, expected_message: str
) -> None:
    source = tmp_path / "movies.json"
    source.write_text(json.dumps(conversations), encoding="utf-8")

    with pytest.raises(ValueError, match=expected_message):
        list(_reader()(source, domain="movies"))


@pytest.mark.parametrize(
    ("conversation", "domain", "expected_message"),
    [
        (
            {
                "conversation_id": "movie-1",
                "utterances": [{"index": 0, "speaker": "USER", "text": "Hello."}],
            },
            "movies",
            "instruction_id 必须是非空字符串",
        ),
        (
            _conversation(instruction_id=7),
            "movies",
            "instruction_id 必须是非空字符串",
        ),
        (
            _conversation(instruction_id="nfl-wrong-domain"),
            "movies",
            "instruction_id 与 movies 域不匹配",
        ),
        (
            {
                "conversation_id": "movie-1",
                "instruction_id": "movie-missing-index",
                "utterances": [{"speaker": "USER", "text": "Hello."}],
            },
            "movies",
            "utterance.index 必须是整数",
        ),
        (
            _conversation(
                instruction_id="movie-wrong-domain",
                utterances=[{"speaker": "USER", "text": "Hello."}],
            ),
            "sports",
            "instruction_id 与 sports 域不匹配",
        ),
        (
            _conversation(utterances=[{"index": 1, "speaker": "USER", "text": "Hello."}]),
            "movies",
            "utterance.index 必须等于原始下标",
        ),
        (
            _conversation(utterances=[{"index": True, "speaker": "USER", "text": "Hello."}]),
            "movies",
            "utterance.index 必须是整数",
        ),
        (
            _conversation(utterances=[{"speaker": "SYSTEM", "text": "Hello."}]),
            "movies",
            "speaker 必须是 USER 或 ASSISTANT",
        ),
    ],
)
def test_taskmaster2_requires_real_schema_contracts(
    tmp_path: Path,
    conversation: dict[str, object],
    domain: str,
    expected_message: str,
) -> None:
    source = tmp_path / f"{domain}.json"
    _write_domain(source, [conversation])

    with pytest.raises(ValueError, match=expected_message):
        list(_reader()(source, domain=domain))


def test_taskmaster2_skips_empty_text_but_keeps_original_utterance_index(tmp_path: Path) -> None:
    source = tmp_path / "movies.json"
    _write_domain(
        source,
        [
            _conversation(
                utterances=[
                    {"speaker": "USER", "text": " \t\n "},
                    {"speaker": "ASSISTANT", "text": "The cinema opens at eight."},
                ]
            )
        ],
    )

    [item] = list(_reader()(source, domain="movies"))

    assert item.text == "The cinema opens at eight."
    assert item.source_item_id == "taskmaster2:movies:conversation:0:movie-1:utterance:1"


def test_taskmaster2_keeps_repeated_conversation_ids_uniquely_traceable(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    _write_domain(
        duplicate,
        [
            _conversation("same", [{"speaker": "USER", "text": "First movie request."}]),
            _conversation("same", [{"speaker": "USER", "text": "Second movie request."}]),
        ],
    )

    items = list(_reader()(duplicate, domain="movies"))

    assert [item.source_item_id for item in items] == [
        "taskmaster2:movies:conversation:0:same:utterance:0",
        "taskmaster2:movies:conversation:1:same:utterance:0",
    ]


def test_taskmaster2_rejects_an_empty_source(tmp_path: Path) -> None:

    empty = tmp_path / "empty.json"
    _write_domain(empty, [_conversation(utterances=[{"speaker": "USER", "text": "  "}])])

    with pytest.raises(ValueError, match="没有可用的有效记录"):
        list(_reader()(empty, domain="movies"))
