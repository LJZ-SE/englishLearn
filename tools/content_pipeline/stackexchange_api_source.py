from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import scene_by_key
from tools.content_pipeline.stackexchange_source import (
    _LEXICAL_WORD,
    _MAX_WORDS,
    _MIN_WORDS,
    _SENTENCE_BOUNDARY,
    _SPACE,
    _TAG_TOKEN,
    _normalize_license,
    _scene_for_tags,
    _VisibleTextParser,
)

_SUPPORTED_SITES = frozenset({"workplace", "academia", "softwareengineering"})
_LICENSE_HELP_URL = "https://stackoverflow.com/help/licensing"
_QUESTION_PATH = re.compile(r"/questions/(?P<question_id>[1-9][0-9]*)(?:/[a-z0-9-]+)?/?")


def iter_stackexchange_api_sentences(
    snapshot_path: Path, *, site: str
) -> Iterator[CollectedSentence]:
    """解析固定版本的 Stack Exchange 官方 API JSON 快照。"""
    requested_site = _validated_site(site, label="请求 site")
    payload = _load_snapshot(snapshot_path)
    root = _required_object(payload, label="Stack Exchange API 快照根对象")

    version = _required_field(root, "snapshot_version", label="快照根对象")
    if type(version) is not int or version != 1:
        raise ValueError("Stack Exchange API snapshot_version 必须是整数 1")

    snapshot_site = _validated_site(
        _required_field(root, "site", label="快照根对象"),
        label="快照 site",
    )
    if snapshot_site != requested_site:
        raise ValueError("Stack Exchange API 快照 site 与请求 site 不一致")

    _validated_tags(
        _required_field(root, "queries", label="快照根对象"),
        label="Stack Exchange API queries",
    )
    raw_items = _required_field(root, "items", label="快照根对象")
    if not isinstance(raw_items, list):
        raise ValueError("Stack Exchange API items 必须是数组")

    seen_question_ids: set[int] = set()
    seen_stable_ids: set[str] = set()
    emitted = 0
    for item_index, raw_item in enumerate(raw_items, start=1):
        item = _required_object(raw_item, label=f"Stack Exchange API item {item_index}")
        question_id = _validated_question_id(
            _required_field(item, "question_id", label=f"item {item_index}")
        )
        if question_id in seen_question_ids:
            raise ValueError(f"Stack Exchange API 存在重复 question_id: {question_id}")
        seen_question_ids.add(question_id)

        body = _required_nonempty_string(
            _required_field(item, "body", label=f"item {item_index}"),
            label=f"item {item_index} body",
        )
        tags = _validated_tags(
            _required_field(item, "tags", label=f"item {item_index}"),
            label=f"item {item_index} tags",
        )
        owner = _required_object(
            _required_field(item, "owner", label=f"item {item_index}"),
            label=f"item {item_index} owner",
        )
        author = _validated_author(
            _required_field(owner, "display_name", label=f"item {item_index} owner"),
        )
        license_name = _validated_license(
            _required_field(item, "content_license", label=f"item {item_index}")
        )
        source_url = _validated_question_url(
            _required_field(item, "link", label=f"item {item_index}"),
            site=requested_site,
            question_id=question_id,
        )

        sub_scene = _scene_for_tags(requested_site, tags)
        if sub_scene is None:
            continue
        scene = scene_by_key(sub_scene)
        for sentence_index, text in _indexed_body_sentences(body):
            stable_id = (
                f"stackexchange-api:{requested_site}:question:{question_id}:"
                f"sentence:{sentence_index}"
            )
            if stable_id in seen_stable_ids:
                raise ValueError(f"Stack Exchange API 存在重复稳定 ID: {stable_id}")
            seen_stable_ids.add(stable_id)
            emitted += 1
            yield CollectedSentence(
                text=text,
                source_item_id=stable_id,
                source_author=author,
                source_url=source_url,
                source_name=(f"stackexchange-{requested_site}-official-api-snapshot"),
                license_name=license_name,
                license_url=_LICENSE_HELP_URL,
                top_scene=scene.top_key,
                sub_scene=scene.key,
            )

    if emitted == 0:
        raise ValueError(f"Stack Exchange API 快照没有可映射的自然句: {snapshot_path}")


def _load_snapshot(path: Path) -> object:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_json_number,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Stack Exchange API 快照不是有效 JSON: {path}") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Stack Exchange API JSON 存在重复字段: {key}")
        result[key] = value
    return result


def _reject_non_json_number(value: str) -> None:
    raise ValueError(f"Stack Exchange API JSON 包含非法数字: {value}")


def _required_object(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label}必须是对象")
    return value


def _required_field(mapping: dict[str, Any], name: str, *, label: str) -> Any:
    if name not in mapping:
        raise ValueError(f"{label}缺少 {name}")
    return mapping[name]


def _validated_site(value: object, *, label: str) -> str:
    if not isinstance(value, str) or value not in _SUPPORTED_SITES:
        raise ValueError(f"Stack Exchange API {label} 不受支持或不规范")
    return value


def _validated_tags(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label}必须是非空数组")
    tags: list[str] = []
    for tag in value:
        if (
            not isinstance(tag, str)
            or tag != tag.casefold().strip()
            or _TAG_TOKEN.fullmatch(tag) is None
        ):
            raise ValueError(f"{label}包含不规范 tag")
        tags.append(tag)
    if len(set(tags)) != len(tags):
        raise ValueError(f"{label}包含重复 tag")
    return tuple(tags)


def _validated_question_id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Stack Exchange API question_id 必须是正整数")
    return value


def _required_nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Stack Exchange API {label} 必须是非空字符串")
    return value.strip()


def _validated_author(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Stack Exchange API item owner.display_name 必须是非空字符串")
    decoded = html.unescape(value).strip()
    if not decoded:
        raise ValueError("Stack Exchange API item owner.display_name 必须是非空字符串")
    return decoded


def _validated_license(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Stack Exchange API content_license 必须是非空字符串")
    try:
        return _normalize_license(value)
    except ValueError:
        raise ValueError("Stack Exchange API content_license 不受支持") from None


def _validated_question_url(value: object, *, site: str, question_id: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Stack Exchange API link 必须是规范非空字符串")
    parsed = urlparse(value)
    expected_host = f"{site}.stackexchange.com"
    match = _QUESTION_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != expected_host
        or parsed.params
        or parsed.query
        or parsed.fragment
        or match is None
        or int(match.group("question_id")) != question_id
    ):
        raise ValueError("Stack Exchange API link 必须是对应站点与问题的 HTTPS URL")
    return value


def _indexed_body_sentences(body: str) -> Iterator[tuple[int, str]]:
    # 复用 dump 解析器的 HTML 与句子规则，同时保留过滤前的原始句序。
    parser = _VisibleTextParser()
    try:
        parser.feed(body)
        parser.close()
    except (UnicodeError, ValueError) as error:
        raise ValueError("Stack Exchange API body 不是有效 HTML 文本") from error
    for sentence_index, raw_sentence in enumerate(_SENTENCE_BOUNDARY.split(parser.text()), start=1):
        sentence = _SPACE.sub(" ", raw_sentence).strip()
        if not sentence or sentence[-1] not in ".?!":
            continue
        if not _MIN_WORDS <= len(_LEXICAL_WORD.findall(sentence)) <= _MAX_WORDS:
            continue
        if "http://" in sentence.casefold() or "https://" in sentence.casefold():
            continue
        yield sentence_index, sentence
