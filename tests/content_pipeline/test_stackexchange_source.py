from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import py7zr
import pytest


def _reader():
    try:
        module = importlib.import_module("tools.content_pipeline.stackexchange_source")
    except ModuleNotFoundError:
        pytest.fail("尚未实现 Stack Exchange 官方 dump 来源解析器")
    return module.iter_stackexchange_sentences


def _write_dump(path: Path, *, posts: str, users: str, extra: dict[str, str] | None = None) -> None:
    with py7zr.SevenZipFile(path, "w") as archive:
        archive.writestr(posts, "Posts.xml")
        archive.writestr(users, "Users.xml")
        for name, payload in (extra or {}).items():
            archive.writestr(payload, name)


def _posts_xml(*rows: str) -> str:
    return "<?xml version=\"1.0\" encoding=\"utf-8\"?><posts>" + "".join(rows) + "</posts>"


def _users_xml(*rows: str) -> str:
    return "<?xml version=\"1.0\" encoding=\"utf-8\"?><users>" + "".join(rows) + "</users>"


def test_stackexchange_reader_emits_clean_question_sentences_with_author_scene_and_license(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "workplace.7z"
    _write_dump(
        archive_path,
        posts=_posts_xml(
            '<row Id="27" PostTypeId="1" OwnerUserId="8" OwnerDisplayName="Stale Name" '
            'CreationDate="2016-08-01T12:00:00.000" ContentLicense="CC BY-SA 3.0" '
            'Tags="&lt;interviewing&gt;&lt;job-search&gt;" '
            'Title="How should I prepare?" '
            'Body="&lt;p&gt;I have an interview next week.&lt;/p&gt;'
            '&lt;p&gt;How should I prepare for the panel?&lt;/p&gt;" />',
            '<row Id="28" PostTypeId="2" OwnerUserId="8" CreationDate="2016-08-01T12:00:00.000" '
            'Tags="&lt;interviewing&gt;" '
            'Body="&lt;p&gt;Answers must never be emitted.&lt;/p&gt;" />',
        ),
        users=_users_xml('<row Id="8" DisplayName="Ada Lovelace" />'),
    )

    items = list(_reader()(archive_path, site="workplace"))

    assert [
        (item.text, item.source_item_id, item.source_author, item.sub_scene)
        for item in items
    ] == [
        (
            "I have an interview next week.",
            "stackexchange:workplace:post:27:sentence:1",
            "Ada Lovelace",
            "work_jobs",
        ),
        (
            "How should I prepare for the panel?",
            "stackexchange:workplace:post:27:sentence:2",
            "Ada Lovelace",
            "work_jobs",
        ),
    ]
    assert all(item.top_scene == "work" for item in items)
    assert all(item.source_name == "stackexchange-workplace-official-dump" for item in items)
    assert all(
        item.source_url == "https://workplace.stackexchange.com/questions/27"
        for item in items
    )
    assert all(item.license_name == "CC BY-SA 3.0" for item in items)
    assert all(item.license_url == "https://stackoverflow.com/help/licensing" for item in items)


def test_stackexchange_reader_uses_owner_display_name_and_date_accurate_license(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "softwareengineering.7z"
    _write_dump(
        archive_path,
        posts=_posts_xml(
            '<row Id="1" PostTypeId="1" OwnerDisplayName="Archived User" '
            'CreationDate="2010-06-01T00:00:00.000" ContentLicense="cc by-sa 4.0" '
            'Tags="&lt;design&gt;" '
            'Body="&lt;p&gt;How can we keep this design simple?&lt;/p&gt;" />',
            '<row Id="2" PostTypeId="1" OwnerDisplayName="Modern User" '
            'CreationDate="2018-05-02T00:00:00.000" ContentLicense="CC BY-SA 3.0" '
            'Tags="&lt;testing&gt;" '
            'Body="&lt;p&gt;The test suite should remain deterministic.&lt;/p&gt;" />',
        ),
        users=_users_xml(),
    )

    items = list(_reader()(archive_path, site="softwareengineering"))

    assert [(item.source_author, item.license_name, item.sub_scene) for item in items] == [
        ("Archived User", "CC BY-SA 4.0", "technology_software"),
        ("Modern User", "CC BY-SA 3.0", "technology_software"),
    ]


def test_stackexchange_reader_uses_only_strong_site_tag_mappings_and_never_crosses_scenes(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "academia.7z"
    _write_dump(
        archive_path,
        posts=_posts_xml(
            '<row Id="1" PostTypeId="1" CreationDate="2020-01-01T00:00:00.000" '
            'ContentLicense="CC BY-SA 4.0" '
            'Tags="&lt;research&gt;&lt;literature-review&gt;" '
            'Body="&lt;p&gt;How should I organize a literature review?&lt;/p&gt;" />',
            '<row Id="2" PostTypeId="1" CreationDate="2020-01-01T00:00:00.000" '
            'ContentLicense="CC BY-SA 4.0" '
            'Tags="&lt;teaching&gt;" '
            'Body="&lt;p&gt;This broad question must not be emitted.&lt;/p&gt;" />',
            '<row Id="3" PostTypeId="1" CreationDate="2020-01-01T00:00:00.000" '
            'ContentLicense="CC BY-SA 4.0" '
            'Tags="&lt;exams&gt;&lt;research&gt;" '
            'Body="&lt;p&gt;How do I prepare students for oral exams?&lt;/p&gt;" />',
        ),
        users=_users_xml(),
    )

    items = list(_reader()(archive_path, site="academia"))

    assert [(item.source_item_id, item.sub_scene) for item in items] == [
        ("stackexchange:academia:post:1:sentence:1", "study_academic"),
        ("stackexchange:academia:post:3:sentence:1", "study_exams"),
    ]


def test_stackexchange_reader_discards_code_quotes_lists_links_and_title_fragments(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "fitness.7z"
    _write_dump(
        archive_path,
        posts=_posts_xml(
            '<row Id="9" PostTypeId="1" CreationDate="2020-01-01T00:00:00.000" '
            'ContentLicense="CC BY-SA 4.0" '
            'Tags="|protein|nutrition|" Title="A title fragment" '
            'Body="&lt;p&gt;I train three times a week.&lt;/p&gt;'
            '&lt;pre&gt;ignored code();&lt;/pre&gt;'
            '&lt;blockquote&gt;Ignored quotation.&lt;/blockquote&gt;'
            '&lt;ul&gt;&lt;li&gt;Ignored list item.&lt;/li&gt;&lt;/ul&gt;'
            '&lt;p&gt;Can I increase the weight gradually? '
            '&lt;a href=&quot;/x&quot;&gt;only a link&lt;/a&gt;&lt;/p&gt;" />',
        ),
        users=_users_xml(),
    )

    items = list(_reader()(archive_path, site="fitness"))

    assert [item.text for item in items] == [
        "I train three times a week.",
        "Can I increase the weight gradually?",
    ]
    assert all(item.sub_scene == "health_fitness" for item in items)


def test_stackexchange_reader_rejects_archive_member_drift_duplicates_and_unsafe_names(
    tmp_path: Path,
) -> None:
    missing_users = tmp_path / "missing-users.7z"
    with py7zr.SevenZipFile(missing_users, "w") as archive:
        archive.writestr(_posts_xml(), "Posts.xml")
    with pytest.raises(ValueError, match="结构漂移"):
        list(_reader()(missing_users, site="workplace"))

    duplicate_posts = tmp_path / "duplicate-posts.7z"
    _write_dump(
        duplicate_posts,
        posts=_posts_xml(),
        users=_users_xml(),
        extra={"nested/Posts.xml": _posts_xml()},
    )
    with pytest.raises(ValueError, match="重复"):
        list(_reader()(duplicate_posts, site="workplace"))

    unsafe_archive = SimpleNamespace(
        list=lambda: [
            SimpleNamespace(
                filename="../escape.xml",
                is_symlink=False,
                is_file=True,
                is_directory=False,
                uncompressed=1,
            )
        ]
    )
    with pytest.raises(ValueError, match="不安全路径"):
        importlib.import_module(
            "tools.content_pipeline.stackexchange_source"
        )._validated_target_members(unsafe_archive)


def test_stackexchange_reader_rejects_unknown_sites_and_schema_drift(tmp_path: Path) -> None:
    archive_path = tmp_path / "invalid.7z"
    _write_dump(
        archive_path,
        posts="<wrong><row /></wrong>",
        users=_users_xml(),
    )

    with pytest.raises(ValueError, match="site"):
        list(_reader()(archive_path, site="unknown"))
    with pytest.raises(ValueError, match="Posts.xml"):
        list(_reader()(archive_path, site="workplace"))


def test_stackexchange_xml_reader_closes_file_after_schema_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("tools.content_pipeline.stackexchange_source")
    xml_path = tmp_path / "invalid.xml"
    xml_path.write_text("<wrong><row /></wrong>", encoding="utf-8")
    opened_streams = []
    original_open = Path.open

    def tracked_open(path: Path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        opened_streams.append(stream)
        return stream

    monkeypatch.setattr(Path, "open", tracked_open)

    with pytest.raises(ValueError, match="根节点"):
        list(module._iter_rows(xml_path, expected_root="posts", label="Posts.xml"))

    assert opened_streams
    assert all(stream.closed for stream in opened_streams)


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("ContentLicense", "CC BY-SA 9.0", "ContentLicense"),
        ("ContentLicense", " ", "ContentLicense"),
        ("CreationDate", "not-a-date", "CreationDate"),
        ("CreationDate", "2024-06-30", "CreationDate"),
        ("CreationDate", "20240630T120000", "CreationDate"),
        ("CreationDate", "2024-W26-7T12:00:00", "CreationDate"),
    ],
)
def test_stackexchange_reader_rejects_unknown_license_and_invalid_creation_date(
    tmp_path: Path,
    attribute: str,
    value: str,
    message: str,
) -> None:
    archive_path = tmp_path / f"invalid-{attribute}.7z"
    attributes = {
        "CreationDate": "2020-01-01T00:00:00.000",
        "ContentLicense": "CC BY-SA 4.0",
    }
    attributes[attribute] = value
    rendered_attributes = " ".join(
        f'{name}="{attribute_value}"' for name, attribute_value in attributes.items()
    )
    _write_dump(
        archive_path,
        posts=_posts_xml(
            '<row Id="90" PostTypeId="1" '
            f'{rendered_attributes} Tags="&lt;interviewing&gt;" '
            'Body="&lt;p&gt;I have an interview next week.&lt;/p&gt;" />'
        ),
        users=_users_xml(),
    )

    with pytest.raises(ValueError, match=message):
        list(_reader()(archive_path, site="workplace"))


@pytest.mark.parametrize(
    "tags",
    [
        "strength-training|nutrition|",
        "|strength-training|nutrition",
        "|strength-training||nutrition|",
        "|strength-training|strength-training|",
        "|strength training|nutrition|",
    ],
)
def test_stackexchange_reader_rejects_malformed_pipe_tags(
    tmp_path: Path,
    tags: str,
) -> None:
    archive_path = tmp_path / "malformed-tags.7z"
    _write_dump(
        archive_path,
        posts=_posts_xml(
            '<row Id="91" PostTypeId="1" CreationDate="2020-01-01T00:00:00.000" '
            'ContentLicense="CC BY-SA 4.0" '
            f'Tags="{tags}" Body="&lt;p&gt;I train three times a week.&lt;/p&gt;" />'
        ),
        users=_users_xml(),
    )

    with pytest.raises(ValueError, match="Tags"):
        list(_reader()(archive_path, site="fitness"))


@pytest.mark.parametrize(
    "exception_name",
    ["CrcError", "UnsupportedCompressionMethodError", "InternalError"],
)
def test_stackexchange_reader_wraps_low_level_7z_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception_name: str,
) -> None:
    module = importlib.import_module("tools.content_pipeline.stackexchange_source")
    error_type = getattr(module.py7zr.exceptions, exception_name)
    if exception_name == "CrcError":
        error = error_type("expected", "actual", "Posts.xml")
    elif exception_name == "UnsupportedCompressionMethodError":
        error = error_type(b"method", "unsupported")
    else:
        error = error_type("internal failure")

    def _raise_error(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise error

    monkeypatch.setattr(module.py7zr, "SevenZipFile", _raise_error)

    with pytest.raises(ValueError, match="有效 7z"):
        list(module.iter_stackexchange_sentences(tmp_path / "broken.7z", site="fitness"))


@pytest.mark.parametrize("post_id", ["0", "-1", "abc"])
def test_stackexchange_reader_requires_positive_question_ids(
    tmp_path: Path,
    post_id: str,
) -> None:
    archive_path = tmp_path / "invalid-post-id.7z"
    _write_dump(
        archive_path,
        posts=_posts_xml(
            f'<row Id="{post_id}" PostTypeId="1" '
            'CreationDate="2020-01-01T00:00:00.000" ContentLicense="CC BY-SA 4.0" '
            'Tags="|protein|" Body="&lt;p&gt;I train three times a week.&lt;/p&gt;" />'
        ),
        users=_users_xml(),
    )

    with pytest.raises(ValueError, match="Id"):
        list(_reader()(archive_path, site="fitness"))


@pytest.mark.parametrize("owner_user_id", ["0", "-2", "abc"])
def test_stackexchange_reader_rejects_invalid_owner_user_ids(
    tmp_path: Path,
    owner_user_id: str,
) -> None:
    archive_path = tmp_path / "invalid-owner-id.7z"
    _write_dump(
        archive_path,
        posts=_posts_xml(
            f'<row Id="92" PostTypeId="1" OwnerUserId="{owner_user_id}" '
            'CreationDate="2020-01-01T00:00:00.000" ContentLicense="CC BY-SA 4.0" '
            'Tags="|protein|" Body="&lt;p&gt;I train three times a week.&lt;/p&gt;" />'
        ),
        users=_users_xml(),
    )

    with pytest.raises(ValueError, match="OwnerUserId"):
        list(_reader()(archive_path, site="fitness"))


@pytest.mark.parametrize("user_id", ["0", "-2", "abc"])
def test_stackexchange_reader_rejects_invalid_user_ids(
    tmp_path: Path,
    user_id: str,
) -> None:
    archive_path = tmp_path / "invalid-user-id.7z"
    _write_dump(
        archive_path,
        posts=_posts_xml(
            '<row Id="93" PostTypeId="1" OwnerUserId="-1" '
            'CreationDate="2020-01-01T00:00:00.000" ContentLicense="CC BY-SA 4.0" '
            'Tags="|protein|" Body="&lt;p&gt;I train three times a week.&lt;/p&gt;" />'
        ),
        users=_users_xml(f'<row Id="{user_id}" DisplayName="Invalid User" />'),
    )

    with pytest.raises(ValueError, match="Users.xml.*Id"):
        list(_reader()(archive_path, site="fitness"))


def test_stackexchange_reader_accepts_reserved_community_user_id(tmp_path: Path) -> None:
    archive_path = tmp_path / "community-user.7z"
    _write_dump(
        archive_path,
        posts=_posts_xml(
            '<row Id="94" PostTypeId="1" OwnerUserId="-1" '
            'CreationDate="2020-01-01T00:00:00.000Z" ContentLicense="CC BY-SA 4.0" '
            'Tags="|protein|" Body="&lt;p&gt;I train three times a week.&lt;/p&gt;" />'
        ),
        users=_users_xml('<row Id="-1" DisplayName="Community" />'),
    )

    [item] = list(_reader()(archive_path, site="fitness"))

    assert item.source_author == "Community"
