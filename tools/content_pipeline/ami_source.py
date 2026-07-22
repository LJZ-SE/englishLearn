from __future__ import annotations

import re
import xml.etree.ElementTree as element_tree
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tools.content_pipeline.archive_safety import validate_regular_zip_member
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import scene_by_key

_SOURCE_URL = (
    "https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/"
    "ami_public_manual_1.6.2.zip"
)
_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
_MEETINGS_PATH = re.compile(r"^(?:[^/]+/)?corpusResources/meetings[.]xml$")
_WORDS_PATH = re.compile(
    r"^(?:[^/]+/)?words/(?P<meeting>[A-Z]{2}[0-9]{4}[a-d])[.]"
    r"(?P<speaker>[A-D])[.]words[.]xml$"
)
_SEGMENTS_PATH = re.compile(
    r"^(?:[^/]+/)?segments/(?P<meeting>[A-Z]{2}[0-9]{4}[a-d])[.]"
    r"(?P<speaker>[A-D])[.]segments[.]xml$"
)
_WORD_RANGE = re.compile(
    r"^(?P<file>[^/#]+[.]words[.]xml)#id\((?P<start>[^)]+)\)"
    r"(?:[.][.]id\((?P<end>[^)]+)\))?$"
)
_PUNCTUATION = re.compile(r"^[,.;:?!]+$")
_LEXICAL = re.compile(r"[A-Za-z0-9]")
_ENGINEERING_CONTEXT = re.compile(
    r"\b(?:circuit|electronics?|mechanical|hardware|firmware|schematic|"
    r"connector|component|technical\s+specification|engineering)\b",
    re.IGNORECASE,
)
_MIN_LEXICAL_WORDS = 4
_MAX_LEXICAL_WORDS = 48


@dataclass(frozen=True, slots=True)
class _WordDocument:
    order: tuple[str, ...]
    tokens: dict[str, tuple[str, bool] | None]


def iter_ami_utterances(archive_path: Path) -> Iterator[CollectedSentence]:
    """读取 AMI v1.6.2 的手工标注，只保留官方情景设计会议中的自然片段。"""
    if not zipfile.is_zipfile(archive_path):
        raise ValueError(f"AMI 下载内容不是有效 ZIP: {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        _validate_archive_members(archive)
        meetings_member = _single_member(archive, _MEETINGS_PATH, "AMI meetings.xml")
        scenario_speakers = _read_scenario_speakers(archive.read(meetings_member))
        word_members = _indexed_members(archive, _WORDS_PATH, "AMI words")
        segment_members = _indexed_members(archive, _SEGMENTS_PATH, "AMI segments")
        orphan_segments = sorted(
            key
            for key in segment_members
            if key[0] in scenario_speakers and key not in word_members
        )
        if orphan_segments:
            meeting_id, speaker_id = orphan_segments[0]
            raise ValueError(
                f"AMI 情景会议 segments 缺少 words 文件: {meeting_id}.{speaker_id}"
            )
        target_keys = sorted(key for key in word_members if key[0] in scenario_speakers)
        if not target_keys:
            raise ValueError(f"AMI 压缩包没有情景设计会议词级转写: {archive_path}")

        emitted_ids: set[str] = set()
        emitted = 0
        for meeting_id, speaker_id in target_keys:
            key = (meeting_id, speaker_id)
            segment_member = segment_members.get(key)
            if segment_member is None:
                raise ValueError(f"AMI 情景会议缺少 segments 文件: {meeting_id}.{speaker_id}")
            words_member = word_members[key]
            words = _read_words(archive.read(words_member), words_member)
            speaker_author = scenario_speakers[meeting_id].get(speaker_id)
            if not speaker_author:
                raise ValueError(f"AMI 情景会议缺少说话人元数据: {meeting_id}.{speaker_id}")
            for segment_id, token_ids in _read_segments(
                archive.read(segment_member),
                segment_member,
                expected_words_name=Path(words_member).name,
                words=words,
            ):
                text, lexical_count = _render_tokens(token_ids, words)
                if not text or not _MIN_LEXICAL_WORDS <= lexical_count <= _MAX_LEXICAL_WORDS:
                    continue
                stable_id = f"ami:{meeting_id}:{speaker_id}:{segment_id}"
                if stable_id in emitted_ids:
                    raise ValueError(f"AMI 存在重复稳定 ID: {stable_id}")
                emitted_ids.add(stable_id)
                sub_scene = (
                    "technology_engineering"
                    if _ENGINEERING_CONTEXT.search(text)
                    else "work_meetings"
                )
                scene = scene_by_key(sub_scene)
                emitted += 1
                yield CollectedSentence(
                    text=text,
                    source_item_id=stable_id,
                    source_author=speaker_author,
                    source_url=_SOURCE_URL,
                    source_name="ami-meeting-corpus-v1.6.2",
                    license_name="CC BY 4.0",
                    license_url=_LICENSE_URL,
                    top_scene=scene.top_key,
                    sub_scene=scene.key,
                )
        if emitted == 0:
            raise ValueError(f"AMI 压缩包没有可用的自然语言片段: {archive_path}")


def _validate_archive_members(archive: zipfile.ZipFile) -> None:
    for info in archive.infolist():
        if info.is_dir():
            continue
        validate_regular_zip_member(info, label="AMI")


def _single_member(
    archive: zipfile.ZipFile, pattern: re.Pattern[str], label: str
) -> str:
    matches = [info.filename for info in archive.infolist() if pattern.fullmatch(info.filename)]
    if len(matches) != 1:
        raise ValueError(f"{label} 结构漂移")
    return matches[0]


def _indexed_members(
    archive: zipfile.ZipFile, pattern: re.Pattern[str], label: str
) -> dict[tuple[str, str], str]:
    members: dict[tuple[str, str], str] = {}
    for info in archive.infolist():
        match = pattern.fullmatch(info.filename)
        if not match:
            continue
        key = (match.group("meeting"), match.group("speaker"))
        if key in members:
            raise ValueError(f"{label} 存在重复成员: {info.filename}")
        members[key] = info.filename
    return members


def _read_scenario_speakers(payload: bytes) -> dict[str, dict[str, str]]:
    root = _parse_xml(payload, "AMI meetings.xml")
    scenarios: dict[str, dict[str, str]] = {}
    for meeting in root.iter():
        if _local_name(meeting.tag) != "meeting":
            continue
        if meeting.attrib.get("type") != "scenario":
            continue
        meeting_id = _required_attribute(meeting, "observation", "AMI meeting")
        if meeting_id in scenarios:
            raise ValueError(f"AMI meetings.xml 存在重复情景会议: {meeting_id}")
        speakers: dict[str, str] = {}
        for speaker in meeting:
            if _local_name(speaker.tag) != "speaker":
                continue
            agent = _required_attribute(speaker, "nxt_agent", "AMI speaker")
            author = _required_attribute(speaker, "global_name", "AMI speaker")
            if agent not in {"A", "B", "C", "D"} or agent in speakers:
                raise ValueError(f"AMI speaker 元数据无效: {meeting_id}.{agent}")
            speakers[agent] = author
        if not speakers:
            raise ValueError(f"AMI 情景会议没有说话人: {meeting_id}")
        scenarios[meeting_id] = speakers
    if not scenarios:
        raise ValueError("AMI meetings.xml 没有官方情景设计会议")
    return scenarios


def _read_words(payload: bytes, member_name: str) -> _WordDocument:
    root = _parse_xml(payload, f"AMI words: {member_name}")
    order: list[str] = []
    tokens: dict[str, tuple[str, bool] | None] = {}
    for element in root:
        item_id = _attribute_by_local_name(element, "id")
        if item_id is None:
            continue
        item_id = item_id.strip()
        if not item_id or item_id in tokens:
            raise ValueError(f"AMI words 存在缺失或重复 ID: {member_name}")
        order.append(item_id)
        if _local_name(element.tag) != "w":
            tokens[item_id] = None
            continue
        text = (element.text or "").strip()
        if not text:
            raise ValueError(f"AMI word 文本为空: {item_id}")
        tokens[item_id] = (text, element.attrib.get("punc") == "true")
    if not order:
        raise ValueError(f"AMI words 文件为空: {member_name}")
    return _WordDocument(order=tuple(order), tokens=tokens)


def _read_segments(
    payload: bytes,
    member_name: str,
    *,
    expected_words_name: str,
    words: _WordDocument,
) -> Iterator[tuple[str, tuple[str, ...]]]:
    root = _parse_xml(payload, f"AMI segments: {member_name}")
    positions = {word_id: index for index, word_id in enumerate(words.order)}
    seen: set[str] = set()
    segment_count = 0
    for segment in root:
        if _local_name(segment.tag) != "segment":
            continue
        segment_count += 1
        segment_id = _attribute_by_local_name(segment, "id")
        if not segment_id or not segment_id.strip() or segment_id in seen:
            raise ValueError(f"AMI segment 缺少或重复 ID: {member_name}")
        seen.add(segment_id)
        children = [child for child in segment if _local_name(child.tag) == "child"]
        if len(children) != 1:
            raise ValueError(f"AMI segment 必须恰好引用一个词级范围: {segment_id}")
        href = children[0].attrib.get("href")
        if not isinstance(href, str):
            raise ValueError(f"AMI segment 缺少 href: {segment_id}")
        match = _WORD_RANGE.fullmatch(href.strip())
        if not match or match.group("file") != expected_words_name:
            raise ValueError(f"AMI segment 词级引用无效: {segment_id}")
        start = match.group("start")
        end = match.group("end") or start
        if start not in positions or end not in positions:
            raise ValueError(f"AMI segment 引用了不存在的词: {segment_id}")
        if positions[start] > positions[end]:
            raise ValueError(f"AMI segment 词级范围顺序无效: {segment_id}")
        yield segment_id.strip(), words.order[positions[start] : positions[end] + 1]
    if segment_count == 0:
        raise ValueError(f"AMI segments 文件为空: {member_name}")


def _render_tokens(token_ids: tuple[str, ...], words: _WordDocument) -> tuple[str, int]:
    rendered: list[str] = []
    lexical_count = 0
    for token_id in token_ids:
        token = words.tokens[token_id]
        if token is None:
            continue
        text, is_punctuation = token
        if is_punctuation or _PUNCTUATION.fullmatch(text):
            if rendered:
                rendered[-1] = f"{rendered[-1]}{text}"
            continue
        if _is_noise(text):
            continue
        rendered.append(text)
        if _LEXICAL.search(text):
            lexical_count += 1
    sentence = " ".join(rendered).strip()
    if sentence and sentence[-1] not in ".?!":
        sentence = f"{sentence}."
    return sentence, lexical_count


def _is_noise(text: str) -> bool:
    stripped = text.strip()
    return (
        not stripped
        or stripped in {"@", "#", "$", "%", ".."}
        or (stripped.startswith("[") and stripped.endswith("]"))
        or not _LEXICAL.search(stripped)
    )


def _parse_xml(payload: bytes, label: str) -> element_tree.Element:
    try:
        return element_tree.fromstring(payload)
    except element_tree.ParseError as error:
        raise ValueError(f"{label} 不是有效 XML") from error


def _required_attribute(element: element_tree.Element, name: str, label: str) -> str:
    value = _attribute_by_local_name(element, name)
    if value is None or not value.strip():
        raise ValueError(f"{label} 缺少 {name}")
    return value.strip()


def _attribute_by_local_name(element: element_tree.Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if _local_name(key) == name:
            return value
    return None


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].split(":")[-1]
