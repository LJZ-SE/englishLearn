from __future__ import annotations

import importlib
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

import pytest


def _reader():
    try:
        module = importlib.import_module("tools.content_pipeline.stackexchange_api_source")
    except ModuleNotFoundError:
        pytest.fail("尚未实现 Stack Exchange 官方 API 快照解析器")
    return module.iter_stackexchange_api_sentences


def _write_snapshot(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _snapshot(*items: object, site: str = "workplace") -> dict[str, object]:
    return {
        "snapshot_version": 1,
        "site": site,
        "queries": ["interviewing"],
        "items": list(items),
        "generated_at": "2026-07-23T00:00:00Z",
    }


def _item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "question_id": 27,
        "body": ("<p>I have an interview next week.</p><p>How should I prepare for the panel?</p>"),
        "tags": ["interviewing", "job-search"],
        "owner": {"display_name": "Ada Lovelace"},
        "content_license": "CC BY-SA 4.0",
        "link": "https://workplace.stackexchange.com/questions/27/panel-interview",
        "title": "How should I prepare for a panel interview?",
    }
    item.update(overrides)
    return item


def test_stackexchange_api_reader_emits_provenanced_strong_tag_sentences(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "workplace.json"
    _write_snapshot(snapshot_path, _snapshot(_item()))

    items = list(_reader()(snapshot_path, site="workplace"))

    assert [
        (
            item.text,
            item.source_item_id,
            item.source_author,
            item.top_scene,
            item.sub_scene,
        )
        for item in items
    ] == [
        (
            "I have an interview next week.",
            "stackexchange-api:workplace:question:27:sentence:1",
            "Ada Lovelace",
            "work",
            "work_jobs",
        ),
        (
            "How should I prepare for the panel?",
            "stackexchange-api:workplace:question:27:sentence:2",
            "Ada Lovelace",
            "work",
            "work_jobs",
        ),
    ]
    assert all(
        item.source_name == "stackexchange-workplace-official-api-snapshot" for item in items
    )
    assert all(item.source_url == _item()["link"] for item in items)
    assert all(item.license_name == "CC BY-SA 4.0" for item in items)
    assert all(item.license_url == "https://stackoverflow.com/help/licensing" for item in items)


def test_stackexchange_api_reader_decodes_owner_display_name_once(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "workplace.json"
    _write_snapshot(
        snapshot_path,
        _snapshot(_item(owner={"display_name": "Ada &amp; Grace"})),
    )

    items = list(_reader()(snapshot_path, site="workplace"))

    assert {item.source_author for item in items} == {"Ada & Grace"}


def test_stackexchange_api_reader_keeps_escaped_angle_markup_as_visible_text(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "workplace.json"
    _write_snapshot(
        snapshot_path,
        _snapshot(
            _item(
                body=(
                    "<p>The sample prints &lt;script&gt;hello&lt;/script&gt; as visible text.</p>"
                )
            )
        ),
    )

    items = list(_reader()(snapshot_path, site="workplace"))

    assert [item.text for item in items] == [
        "The sample prints <script>hello</script> as visible text."
    ]


def _bundled_snapshot(site: str) -> Path:
    project_root = Path(__file__).resolve().parents[2]
    return (
        project_root
        / "tools"
        / "content_pipeline"
        / "snapshots"
        / f"stackexchange-{site}-api-v1.json"
    )


def _release_digest(items: list[object]) -> str:
    digest = sha256()
    records = sorted(
        (
            (
                item.source_item_id,
                item.text,
                item.sub_scene,
                item.license_name,
            )
            for item in items
        ),
        key=lambda record: record[0],
    )
    for record in records:
        canonical_line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        digest.update(f"{canonical_line}\n".encode())
    return digest.hexdigest()


@pytest.mark.parametrize(
    ("site", "expected_count", "expected_scenes", "expected_digest"),
    [
        (
            "academia",
            6475,
            {
                "study_academic": 3469,
                "study_campus": 2046,
                "study_exams": 960,
            },
            "76f39ce66cb597f213e36b6e8c13a08ed5afa255f8f6aa6a4bf0ce96d559dc54",
        ),
        (
            "softwareengineering",
            2981,
            {"technology_software": 2981},
            "bbabeb5cbabbf5f1f513ca869118942f0ee2511985f11ace182e667825193efd",
        ),
        (
            "workplace",
            3834,
            {"work_jobs": 2588, "work_office": 1246},
            "1abcb184cb7bf52cdea06d6e288b3014d18b9722adb5f0d30ab647ec1664a99b",
        ),
    ],
)
def test_bundled_stackexchange_api_snapshot_release_contract(
    site: str,
    expected_count: int,
    expected_scenes: dict[str, int],
    expected_digest: str,
) -> None:
    items = list(_reader()(_bundled_snapshot(site), site=site))

    assert len(items) == expected_count
    assert len({item.source_item_id for item in items}) == expected_count
    assert Counter(item.sub_scene for item in items) == expected_scenes
    assert _release_digest(items) == expected_digest


@pytest.mark.parametrize(
    ("site", "question_id", "expected_author"),
    [
        ("academia", 3540, "F'x"),
        ("softwareengineering", 60097, "Ant's"),
        ("workplace", 141511, "L'san"),
    ],
)
def test_bundled_stackexchange_api_snapshot_decodes_real_entity_author(
    site: str, question_id: int, expected_author: str
) -> None:
    items = list(_reader()(_bundled_snapshot(site), site=site))
    question_marker = f":question:{question_id}:"

    assert {item.source_author for item in items if question_marker in item.source_item_id} == {
        expected_author
    }


@pytest.mark.parametrize(
    ("site", "queries", "items", "expected"),
    [
        (
            "academia",
            ["exams", "admissions", "research"],
            [
                _item(
                    question_id=31,
                    tags=["research"],
                    link="https://academia.stackexchange.com/questions/31/review",
                ),
                _item(
                    question_id=32,
                    tags=["admissions"],
                    link="https://academia.stackexchange.com/questions/32/admissions",
                ),
                _item(
                    question_id=33,
                    tags=["research", "exams"],
                    link="https://academia.stackexchange.com/questions/33/exam",
                ),
            ],
            ["study_academic", "study_campus", "study_exams"],
        ),
        (
            "softwareengineering",
            ["testing", "architecture"],
            [
                _item(
                    question_id=41,
                    tags=["testing", "architecture"],
                    link=("https://softwareengineering.stackexchange.com/questions/41/testing"),
                )
            ],
            ["technology_software"],
        ),
    ],
)
def test_stackexchange_api_reader_uses_site_specific_strong_tag_scenes(
    tmp_path: Path,
    site: str,
    queries: list[str],
    items: list[dict[str, object]],
    expected: list[str],
) -> None:
    snapshot_path = tmp_path / f"{site}.json"
    payload = _snapshot(*items, site=site)
    payload["queries"] = queries
    _write_snapshot(snapshot_path, payload)

    emitted = list(_reader()(snapshot_path, site=site))

    assert [item.sub_scene for item in emitted[::2]] == expected


def test_stackexchange_api_reader_preserves_original_sentence_ordinals_and_cleans_html(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "workplace.json"
    _write_snapshot(
        snapshot_path,
        _snapshot(
            _item(
                body=(
                    "<p>No.</p><pre>Ignored code should never appear.</pre>"
                    "<blockquote>Ignored quotation should never appear.</blockquote>"
                    "<p>The hiring panel meets tomorrow morning.</p>"
                    "<p>Read <a href='https://example.test'>this external link</a> now.</p>"
                )
            )
        ),
    )

    items = list(_reader()(snapshot_path, site="workplace"))

    assert [(item.text, item.source_item_id) for item in items] == [
        (
            "The hiring panel meets tomorrow morning.",
            "stackexchange-api:workplace:question:27:sentence:2",
        )
    ]


def test_stackexchange_api_reader_skips_questions_without_strong_tags(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "workplace.json"
    _write_snapshot(
        snapshot_path,
        _snapshot(
            _item(
                question_id=28,
                tags=["salary"],
                link=("https://workplace.stackexchange.com/questions/28/salary"),
            ),
            _item(),
        ),
    )

    items = list(_reader()(snapshot_path, site="workplace"))

    assert {item.source_item_id for item in items} == {
        "stackexchange-api:workplace:question:27:sentence:1",
        "stackexchange-api:workplace:question:27:sentence:2",
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"snapshot_version": 2, "site": "workplace", "queries": ["office"], "items": []},
        {"snapshot_version": True, "site": "workplace", "queries": ["office"], "items": []},
        {"snapshot_version": 1, "site": "Workplace", "queries": ["office"], "items": []},
        {"snapshot_version": 1, "site": "workplace", "queries": [], "items": []},
        {
            "snapshot_version": 1,
            "site": "workplace",
            "queries": ["office", "office"],
            "items": [],
        },
        {
            "snapshot_version": 1,
            "site": "workplace",
            "queries": ["Office"],
            "items": [],
        },
        {"snapshot_version": 1, "site": "workplace", "queries": "office", "items": []},
        {"snapshot_version": 1, "site": "workplace", "queries": ["office"], "items": {}},
    ],
)
def test_stackexchange_api_reader_rejects_root_schema_drift(
    tmp_path: Path, payload: object
) -> None:
    snapshot_path = tmp_path / "invalid.json"
    _write_snapshot(snapshot_path, payload)

    with pytest.raises(ValueError):
        list(_reader()(snapshot_path, site="workplace"))


def _with_item_change(field: str, value: object) -> dict[str, object]:
    changed = _item()
    if field == "owner.display_name":
        changed["owner"] = {"display_name": value}
    else:
        changed[field] = value
    return changed


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("question_id", 0),
        ("question_id", True),
        ("question_id", "27"),
        ("body", ""),
        ("body", 123),
        ("tags", []),
        ("tags", ["office", "office"]),
        ("tags", ["Office"]),
        ("tags", "office"),
        ("owner", []),
        ("owner.display_name", ""),
        ("owner.display_name", "&nbsp;"),
        ("owner.display_name", 8),
        ("content_license", "CC BY-SA 2.0"),
        ("content_license", ""),
        ("link", "http://workplace.stackexchange.com/questions/27/title"),
        ("link", "https://academia.stackexchange.com/questions/27/title"),
        ("link", "https://workplace.stackexchange.com/questions/28/title"),
        ("link", "https://workplace.stackexchange.com/users/27/title"),
    ],
)
def test_stackexchange_api_reader_rejects_item_schema_drift(
    tmp_path: Path, field: str, value: object
) -> None:
    snapshot_path = tmp_path / "invalid-item.json"
    _write_snapshot(snapshot_path, _snapshot(_with_item_change(field, value)))

    with pytest.raises(ValueError):
        list(_reader()(snapshot_path, site="workplace"))


def test_stackexchange_api_reader_rejects_missing_required_item_fields(
    tmp_path: Path,
) -> None:
    for field in (
        "question_id",
        "body",
        "tags",
        "owner",
        "content_license",
        "link",
    ):
        item = _item()
        del item[field]
        snapshot_path = tmp_path / f"missing-{field}.json"
        _write_snapshot(snapshot_path, _snapshot(item))
        with pytest.raises(ValueError):
            list(_reader()(snapshot_path, site="workplace"))


@pytest.mark.parametrize("license_name", ["CC BY-SA 2.5", "cc by-sa 3.0", "CC  BY-SA  4.0"])
def test_stackexchange_api_reader_normalizes_supported_licenses(
    tmp_path: Path, license_name: str
) -> None:
    snapshot_path = tmp_path / "license.json"
    _write_snapshot(
        snapshot_path,
        _snapshot(_item(content_license=license_name)),
    )

    items = list(_reader()(snapshot_path, site="workplace"))

    assert {item.license_name for item in items} == {"CC BY-SA " + license_name.split()[-1]}


def test_stackexchange_api_reader_rejects_cross_site_argument_duplicate_ids_and_empty_source(
    tmp_path: Path,
) -> None:
    valid_path = tmp_path / "valid.json"
    _write_snapshot(valid_path, _snapshot(_item()))
    with pytest.raises(ValueError, match="site"):
        list(_reader()(valid_path, site="academia"))

    duplicate_path = tmp_path / "duplicate.json"
    _write_snapshot(duplicate_path, _snapshot(_item(), _item()))
    with pytest.raises(ValueError, match="重复"):
        list(_reader()(duplicate_path, site="workplace"))

    empty_path = tmp_path / "empty.json"
    _write_snapshot(
        empty_path,
        _snapshot(
            _item(
                tags=["salary"],
                body="<p>This sentence has no accepted strong tag.</p>",
            )
        ),
    )
    with pytest.raises(ValueError, match="没有可映射"):
        list(_reader()(empty_path, site="workplace"))


def test_stackexchange_api_reader_rejects_invalid_json_and_duplicate_object_keys(
    tmp_path: Path,
) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        list(_reader()(invalid_path, site="workplace"))

    duplicate_path = tmp_path / "duplicate-key.json"
    duplicate_path.write_text(
        '{"snapshot_version":1,"snapshot_version":1,"site":"workplace",'
        '"queries":["office"],"items":[]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="重复"):
        list(_reader()(duplicate_path, site="workplace"))
