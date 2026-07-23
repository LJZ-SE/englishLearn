from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import scene_by_key

_COMMIT = "d92cb6af3005f1dc09c39e75e7daf4a04905e00b"
_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
_DOMAIN_SCENES = {
    "movies": "culture_movies",
    "sports": "culture_sports",
}
_DOMAIN_INSTRUCTION_PREFIXES = {
    "movies": ("movie-",),
    "sports": ("epl-", "mlb-", "mls-", "nba-", "nfl-"),
}
_SPEAKERS = {"USER", "ASSISTANT"}


def iter_taskmaster2_utterances(
    path: Path,
    *,
    domain: str,
) -> Iterator[CollectedSentence]:
    """读取 Taskmaster-2 的单个固定域，避免从自由文本推测场景。"""
    sub_scene = _DOMAIN_SCENES.get(domain)
    if sub_scene is None:
        raise ValueError(f"Taskmaster-2 不支持 domain: {domain!r}")

    conversations = _read_conversations(path)
    scene = scene_by_key(sub_scene)
    source_url = (
        "https://github.com/google-research-datasets/Taskmaster/blob/"
        f"{_COMMIT}/TM-2-2020/data/{domain}.json"
    )
    emitted_ids: set[str] = set()
    emitted = 0
    for conversation_index, conversation in enumerate(conversations):
        if not isinstance(conversation, dict):
            raise ValueError(
                f"Taskmaster-2 第 {conversation_index} 个 conversation 必须是对象"
            )
        conversation_id = _required_nonempty_string(
            conversation.get("conversation_id"),
            "conversation_id",
            conversation_index,
        )
        instruction_id = _required_nonempty_string(
            conversation.get("instruction_id"),
            "instruction_id",
            conversation_index,
        )
        if not instruction_id.startswith(_DOMAIN_INSTRUCTION_PREFIXES[domain]):
            raise ValueError(
                f"Taskmaster-2 {conversation_id} 的 instruction_id 与 {domain} 域不匹配"
            )
        utterances = conversation.get("utterances")
        if not isinstance(utterances, list):
            raise ValueError(
                f"Taskmaster-2 {conversation_id} 的 utterances 必须是数组"
            )
        for utterance_index, utterance in enumerate(utterances):
            if not isinstance(utterance, dict):
                raise ValueError(
                    f"Taskmaster-2 {conversation_id} 第 {utterance_index} 个 utterance 必须是对象"
                )
            source_index = utterance.get("index")
            if isinstance(source_index, bool) or not isinstance(source_index, int):
                raise ValueError(
                    f"Taskmaster-2 {conversation_id} 第 {utterance_index} 个 "
                    "utterance.index 必须是整数"
                )
            if source_index != utterance_index:
                raise ValueError(
                    f"Taskmaster-2 {conversation_id} 第 {utterance_index} 个 "
                    "utterance.index 必须等于原始下标"
                )
            speaker = utterance.get("speaker")
            if not isinstance(speaker, str):
                raise ValueError(
                    f"Taskmaster-2 {conversation_id} 第 {utterance_index} 个 speaker 必须是字符串"
                )
            if speaker not in _SPEAKERS:
                raise ValueError(
                    f"Taskmaster-2 {conversation_id} 第 {utterance_index} 个 speaker "
                    "必须是 USER 或 ASSISTANT"
                )
            text = utterance.get("text")
            if not isinstance(text, str):
                raise ValueError(
                    f"Taskmaster-2 {conversation_id} 第 {utterance_index} 个 text 必须是字符串"
                )
            normalized_text = text.strip()
            if not normalized_text:
                continue
            stable_id = (
                f"taskmaster2:{domain}:conversation:{conversation_index}:"
                f"{conversation_id}:utterance:{utterance_index}"
            )
            if stable_id in emitted_ids:
                raise ValueError(f"Taskmaster-2 存在重复稳定 ID: {stable_id}")
            emitted_ids.add(stable_id)
            emitted += 1
            yield CollectedSentence(
                text=normalized_text,
                source_item_id=stable_id,
                source_author="",
                source_url=source_url,
                source_name=f"taskmaster2-{domain}",
                license_name="CC BY 4.0",
                license_url=_LICENSE_URL,
                top_scene=scene.top_key,
                sub_scene=scene.key,
            )
    if emitted == 0:
        raise ValueError(f"Taskmaster-2 来源没有可用的有效记录: {path}")


def _read_conversations(path: Path) -> list[object]:
    try:
        payload = path.read_text(encoding="utf-8")
        conversations = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Taskmaster-2 JSON 无法读取: {path}") from error
    if not isinstance(conversations, list):
        raise ValueError("Taskmaster-2 JSON 根节点必须是数组")
    return conversations


def _required_nonempty_string(value: object, field: str, index: int) -> str:
    if not isinstance(value, str) or not (normalized := value.strip()):
        raise ValueError(
            f"Taskmaster-2 第 {index} 个 conversation 的 {field} 必须是非空字符串"
        )
    return normalized
