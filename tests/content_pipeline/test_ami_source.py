from __future__ import annotations

import importlib
import zipfile
from pathlib import Path

import pytest


def _reader():
    try:
        module = importlib.import_module("tools.content_pipeline.ami_source")
    except ModuleNotFoundError:
        pytest.fail("尚未实现 AMI Meeting Corpus 来源解析器")
    return module.iter_ami_utterances


def _write_ami_archive(
    path: Path,
    *,
    scenario: str = "ES2002a",
    extra_meetings: str = "",
    words: str,
    segments: str,
) -> None:
    meetings = f'''<?xml version="1.0" encoding="UTF-8"?>
<nite:root xmlns:nite="http://nite.sourceforge.net/">
  <meeting nite:id="meet_1" type="scenario" observation="{scenario}">
    <speaker nxt_agent="A" global_name="MIE001" role="ID"/>
  </meeting>
  {extra_meetings}
</nite:root>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("corpusResources/meetings.xml", meetings)
        archive.writestr(f"words/{scenario}.A.words.xml", words)
        archive.writestr(f"segments/{scenario}.A.segments.xml", segments)


def _words_xml(*tokens: tuple[str, str, str]) -> str:
    body = "\n".join(
        f'  <w nite:id="{word_id}"{attribute}>{text}</w>'
        for word_id, text, attribute in tokens
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<nite:root xmlns:nite="http://nite.sourceforge.net/">\n'
        f"{body}\n"
        "</nite:root>"
    )


def _segments_xml(*segments: tuple[str, str]) -> str:
    body = "\n".join(
        f'  <segment nite:id="{segment_id}"><nite:child href="{href}"/></segment>'
        for segment_id, href in segments
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<nite:root xmlns:nite="http://nite.sourceforge.net/">\n'
        f"{body}\n"
        "</nite:root>"
    )


def test_ami_reader_emits_scenario_segments_with_stable_provenance_and_scenes(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "ami.zip"
    _write_ami_archive(
        archive_path,
        words=_words_xml(
            ("ES2002a.A.words0", "Could", ""),
            ("ES2002a.A.words1", "we", ""),
            ("ES2002a.A.words2", "revise", ""),
            ("ES2002a.A.words3", "the", ""),
            ("ES2002a.A.words4", "agenda", ""),
            ("ES2002a.A.words5", "?", ' punc="true"'),
            ("ES2002a.A.words6", "The", ""),
            ("ES2002a.A.words7", "circuit", ""),
            ("ES2002a.A.words8", "board", ""),
            ("ES2002a.A.words9", "needs", ""),
            ("ES2002a.A.words10", "a", ""),
            ("ES2002a.A.words11", "new", ""),
            ("ES2002a.A.words12", "connector", ""),
            ("ES2002a.A.words13", ".", ' punc="true"'),
        ),
        segments=_segments_xml(
            (
                "ES2002a.sync.4",
                "ES2002a.A.words.xml#id(ES2002a.A.words0)..id(ES2002a.A.words5)",
            ),
            (
                "ES2002a.sync.6",
                "ES2002a.A.words.xml#id(ES2002a.A.words6)..id(ES2002a.A.words13)",
            ),
        ),
    )

    items = list(_reader()(archive_path))

    assert [(item.text, item.source_item_id, item.top_scene, item.sub_scene) for item in items] == [
        ("Could we revise the agenda?", "ami:ES2002a:A:ES2002a.sync.4", "work", "work_meetings"),
        (
            "The circuit board needs a new connector.",
            "ami:ES2002a:A:ES2002a.sync.6",
            "technology",
            "technology_engineering",
        ),
    ]
    assert all(item.source_name == "ami-meeting-corpus-v1.6.2" for item in items)
    assert all(item.source_author == "MIE001" for item in items)
    assert all(item.license_name == "CC BY 4.0" for item in items)


def test_ami_reader_excludes_non_scenario_meetings_and_noise_or_short_fragments(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "ami.zip"
    _write_ami_archive(
        archive_path,
        extra_meetings=(
            '<meeting nite:id="meet_2" type="non-scenario" observation="EN2001a">'
            '<speaker nxt_agent="A" global_name="MIE002" role="ID"/>'
            "</meeting>"
        ),
        words=_words_xml(
            ("ES2002a.A.words0", "Okay", ""),
            ("ES2002a.A.words1", ".", ' punc="true"'),
            ("ES2002a.A.words2", "We", ""),
            ("ES2002a.A.words3", "should", ""),
            ("ES2002a.A.words4", "compare", ""),
            ("ES2002a.A.words5", "three", ""),
            ("ES2002a.A.words6", "prototype", ""),
            ("ES2002a.A.words7", "options", ""),
            ("ES2002a.A.words8", ".", ' punc="true"'),
        ),
        segments=_segments_xml(
            ("ES2002a.sync.1", "ES2002a.A.words.xml#id(ES2002a.A.words0)..id(ES2002a.A.words1)"),
            ("ES2002a.sync.2", "ES2002a.A.words.xml#id(ES2002a.A.words2)..id(ES2002a.A.words8)"),
        ),
    )
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(
            "words/EN2001a.A.words.xml",
            _words_xml(
                ("EN2001a.A.words0", "This", ""),
                ("EN2001a.A.words1", "must", ""),
                ("EN2001a.A.words2", "not", ""),
                ("EN2001a.A.words3", "be", ""),
                ("EN2001a.A.words4", "included", ""),
                ("EN2001a.A.words5", ".", ' punc="true"'),
            ),
        )
        archive.writestr(
            "segments/EN2001a.A.segments.xml",
            _segments_xml(
                ("EN2001a.sync.1", "EN2001a.A.words.xml#id(EN2001a.A.words0)..id(EN2001a.A.words5)")
            ),
        )

    [item] = list(_reader()(archive_path))

    assert item.text == "We should compare three prototype options."
    assert item.sub_scene == "work_meetings"


def test_ami_reader_rejects_malformed_word_ranges_and_unsafe_archive_paths(tmp_path: Path) -> None:
    archive_path = tmp_path / "malformed.zip"
    _write_ami_archive(
        archive_path,
        words=_words_xml(
            ("ES2002a.A.words0", "Please", ""),
            ("ES2002a.A.words1", "review", ""),
            ("ES2002a.A.words2", "the", ""),
            ("ES2002a.A.words3", "design", ""),
            ("ES2002a.A.words4", "brief", ""),
            ("ES2002a.A.words5", ".", ' punc="true"'),
        ),
        segments=_segments_xml(
            ("ES2002a.sync.4", "ES2002a.A.words.xml#id(ES2002a.A.words4)..id(ES2002a.A.words0)")
        ),
    )

    with pytest.raises(ValueError, match="范围"):
        list(_reader()(archive_path))

    unsafe_path = tmp_path / "unsafe.zip"
    _write_ami_archive(
        unsafe_path,
        words=_words_xml(
            ("ES2002a.A.words0", "Please", ""),
            ("ES2002a.A.words1", "review", ""),
            ("ES2002a.A.words2", "the", ""),
            ("ES2002a.A.words3", "design", ""),
            ("ES2002a.A.words4", "brief", ""),
            ("ES2002a.A.words5", ".", ' punc="true"'),
        ),
        segments=_segments_xml(
            ("ES2002a.sync.4", "ES2002a.A.words.xml#id(ES2002a.A.words0)..id(ES2002a.A.words5)")
        ),
    )
    with zipfile.ZipFile(unsafe_path, "a") as archive:
        archive.writestr("../escape.xml", "not used")

    with pytest.raises(ValueError, match="不安全路径"):
        list(_reader()(unsafe_path))


def test_ami_reader_rejects_scenario_segments_without_matching_word_document(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "orphan-segments.zip"
    _write_ami_archive(
        archive_path,
        words=_words_xml(
            ("ES2002a.A.words0", "Please", ""),
            ("ES2002a.A.words1", "review", ""),
            ("ES2002a.A.words2", "the", ""),
            ("ES2002a.A.words3", "design", ""),
            ("ES2002a.A.words4", "brief", ""),
            ("ES2002a.A.words5", ".", ' punc="true"'),
        ),
        segments=_segments_xml(
            ("ES2002a.sync.4", "ES2002a.A.words.xml#id(ES2002a.A.words0)..id(ES2002a.A.words5)")
        ),
    )
    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(
            "segments/ES2002a.B.segments.xml",
            _segments_xml(
                ("ES2002a.sync.5", "ES2002a.B.words.xml#id(ES2002a.B.words0)")
            ),
        )

    with pytest.raises(ValueError, match="缺少 words"):
        list(_reader()(archive_path))
