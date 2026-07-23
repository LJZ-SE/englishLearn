from __future__ import annotations

import re
import xml.etree.ElementTree as element_tree
import zipfile
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.archive_safety import (
    validate_archive_member_path,
    validate_regular_zip_member,
)
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import scene_by_key

_REVISION = "577bd37b96c02d1833b2c9eed2de9f96964e96cb"
_SOURCE_URL = f"https://github.com/abachaa/MedQuAD/tree/{_REVISION}"
_LICENSE_URL = (
    f"https://github.com/abachaa/MedQuAD/blob/{_REVISION}/LICENSE.txt"
)
_XML_PATH = re.compile(
    r"^(?:[^/]+/)?"
    r"([A-Za-z0-9][A-Za-z0-9_.-]*)/"
    r"([A-Za-z0-9][A-Za-z0-9_.-]*[.]xml)$"
)
_COLLECTION_PREFIX = re.compile(r"^(\d+)_")

_CLINIC_COLLECTIONS = frozenset(
    {
        "1_CancerGov_QA",
        "2_GARD_QA",
        "3_GHR_QA",
        "5_NIDDK_QA",
        "6_NINDS_QA",
        "8_NHLBI_QA_XML",
    }
)
_PHARMACY_COLLECTIONS = frozenset({"11_MPlusDrugs_QA", "12_MPlusHerbsSupplements_QA"})
_BROAD_HEALTH_COLLECTIONS = frozenset(
    {"4_MPlus_Health_Topics_QA", "7_SeniorHealth_QA", "10_MPlus_ADAM_QA"}
)
_SUPPORTED_COLLECTIONS = _CLINIC_COLLECTIONS | _PHARMACY_COLLECTIONS | _BROAD_HEALTH_COLLECTIONS
_FITNESS_FOCUS = ("exercise", "physical activity", "fitness")
_WELLBEING_FOCUS = (
    "emotional wellness",
    "mental health",
    "stress",
    "depression",
    "anxiety",
)


def iter_medquad_questions(archive_path: Path) -> Iterator[CollectedSentence]:
    """只导出有明确健康场景归属的 MedQuAD 问句，不保留答案正文。"""
    if not zipfile.is_zipfile(archive_path):
        raise ValueError(f"MedQuAD 下载内容不是有效 ZIP: {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        members = _xml_members(archive, archive_path)
        emitted_ids: set[str] = set()
        emitted = 0
        for collection, file_name, info in members:
            root = _read_xml(archive, info)
            focus_tag, pairs_tag, pair_tag, question_tag, answer_tag = _xml_tags(
                collection, root, info.filename
            )
            focus = _required_child_text(root, focus_tag, info.filename)
            sub_scene = _scene_for(collection, focus)
            qa_pairs = _required_direct_child(root, pairs_tag, info.filename)
            pairs = list(qa_pairs)
            for qa_index, pair in enumerate(pairs):
                if pair.tag != pair_tag:
                    raise ValueError(f"MedQuAD QAPairs 子项不是 QAPair: {info.filename}")
                question = _required_child_text(pair, question_tag, info.filename)
                # 答案不进入任何输出；只确认 XML QA 对包含 Answer 节点。
                _required_direct_child(pair, answer_tag, info.filename)
                if not sub_scene:
                    continue
                stable_id = f"medquad:{collection}:{file_name}:qa:{qa_index}"
                if stable_id in emitted_ids:
                    raise ValueError(f"MedQuAD 存在重复稳定 ID: {stable_id}")
                emitted_ids.add(stable_id)
                scene = scene_by_key(sub_scene)
                emitted += 1
                yield CollectedSentence(
                    text=question,
                    source_item_id=stable_id,
                    source_author="",
                    source_url=_SOURCE_URL,
                    source_name="medquad",
                    license_name="CC BY 4.0",
                    license_url=_LICENSE_URL,
                    top_scene=scene.top_key,
                    sub_scene=scene.key,
                )
    if emitted == 0:
        raise ValueError(f"MedQuAD 压缩包没有可映射的有效记录: {archive_path}")


def _xml_members(
    archive: zipfile.ZipFile, archive_path: Path
) -> list[tuple[str, str, zipfile.ZipInfo]]:
    members: list[tuple[str, str, zipfile.ZipInfo]] = []
    seen_paths: set[str] = set()
    for info in archive.infolist():
        if not info.is_dir():
            validate_archive_member_path(info.filename, label="MedQuAD")
        match = _XML_PATH.fullmatch(info.filename)
        if not match:
            continue
        validate_regular_zip_member(info, label="MedQuAD XML")
        collection, file_name = match.groups()
        if collection not in _SUPPORTED_COLLECTIONS:
            continue
        if info.filename in seen_paths:
            raise ValueError(f"MedQuAD 存在重复 XML 成员: {info.filename}")
        seen_paths.add(info.filename)
        members.append((collection, file_name, info))
    if not members:
        raise ValueError(f"MedQuAD 压缩包结构漂移: {archive_path}")
    return sorted(members, key=lambda row: (_collection_order(row[0]), row[2].filename))


def _read_xml(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> element_tree.Element:
    try:
        root = element_tree.fromstring(archive.read(info))
    except (element_tree.ParseError, UnicodeDecodeError) as error:
        raise ValueError(f"MedQuAD XML 无效: {info.filename}") from error
    return root


def _xml_tags(
    collection: str, root: element_tree.Element, path: str
) -> tuple[str, str, str, str, str]:
    if collection == "6_NINDS_QA" and root.tag == "doc":
        return ("doctitle-focus", "qaPairs", "pair", "question", "answer")
    if root.tag in {"Document", "DiseaseFile"}:
        return ("Focus", "QAPairs", "QAPair", "Question", "Answer")
    raise ValueError(f"MedQuAD XML 根节点不受支持: {path}")


def _required_direct_child(
    parent: element_tree.Element, tag: str, path: str
) -> element_tree.Element:
    children = [child for child in parent if child.tag == tag]
    if len(children) != 1:
        raise ValueError(f"MedQuAD {tag} 必须恰好出现一次: {path}")
    return children[0]


def _required_child_text(parent: element_tree.Element, tag: str, path: str) -> str:
    child = _required_direct_child(parent, tag, path)
    if list(child):
        raise ValueError(f"MedQuAD {tag} 不能包含嵌套节点: {path}")
    value = child.text
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"MedQuAD {tag} 必须是非空字符串: {path}")
    return value.strip()


def _scene_for(collection: str, focus: str) -> str | None:
    normalized_focus = " ".join(focus.casefold().split())
    if collection in _CLINIC_COLLECTIONS:
        return "health_clinic"
    if collection in _PHARMACY_COLLECTIONS:
        return "health_pharmacy"
    if collection in _BROAD_HEALTH_COLLECTIONS:
        if _contains_any(normalized_focus, _FITNESS_FOCUS):
            return "health_fitness"
        if _contains_any(normalized_focus, _WELLBEING_FOCUS):
            return "health_wellbeing"
    return None


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _collection_order(collection: str) -> int:
    match = _COLLECTION_PREFIX.match(collection)
    if match is None:
        return 1_000_000
    return int(match.group(1))
