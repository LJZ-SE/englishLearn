from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import scene_by_key

_REVISION = "e852981ae34990f4358979625854259302feaa78"
_SOURCE_URL = (
    "https://github.com/google-research-datasets/dstc8-schema-guided-dialogue/tree/"
    f"{_REVISION}"
)
_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
_DIALOGUE_PATH = re.compile(
    r"^(?:[^/]+/)?(train|dev|test)/dialogues_[0-9]+[.]json$"
)
_SCHEMA_PATH = re.compile(r"^(?:[^/]+/)?(train|dev|test)/schema[.]json$")

_SERVICE_SCENES = {
    "Flights": "travel_transport",
    "Buses": "travel_transport",
    "Trains": "travel_transport",
    "RideSharing": "travel_transport",
    "RentalCars": "travel_transport",
    "Hotels": "travel_hotel",
    "Restaurants": "daily_food",
    "Movies": "culture_movies",
    "Music": "culture_music",
    "Weather": "news_environment",
    "Travel": "travel_tourism",
}


def iter_sgd_utterances(archive_path: Path) -> Iterator[CollectedSentence]:
    if not zipfile.is_zipfile(archive_path):
        raise ValueError(f"SGD 下载内容不是有效 ZIP: {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        dialogue_files = _matched_paths(archive, _DIALOGUE_PATH, "SGD 对话")
        schema_files = _matched_paths(archive, _SCHEMA_PATH, "SGD schema")
        if not dialogue_files or not schema_files:
            raise ValueError(f"SGD 压缩包结构漂移: {archive_path}")
        roots = {
            _member_root(name, split)
            for split, name in (*dialogue_files, *schema_files)
        }
        if len(roots) != 1:
            raise ValueError(f"SGD 压缩包根目录不一致: {archive_path}")
        dialogue_splits = {split for split, _name in dialogue_files}
        schema_splits = {split for split, _name in schema_files}
        if not dialogue_splits <= schema_splits:
            raise ValueError(f"SGD 对话 split 缺少对应 schema: {archive_path}")
        schemas = _read_schemas(archive, schema_files)
        emitted_ids: set[str] = set()
        emitted = 0
        for split, name in dialogue_files:
            payload = json.loads(archive.read(name))
            if not isinstance(payload, list):
                raise ValueError(f"SGD 对话文件不是数组: {name}")
            for dialogue in payload:
                if not isinstance(dialogue, dict):
                    raise ValueError(f"SGD 对话条目不是对象: {name}")
                dialogue_id = str(dialogue.get("dialogue_id", "")).strip()
                services = dialogue.get("services")
                turns = dialogue.get("turns")
                if not dialogue_id or not isinstance(services, list) or not isinstance(turns, list):
                    raise ValueError(f"SGD 对话缺少稳定 ID、services 或 turns: {name}")
                dialogue_services = _clean_services(services)
                for turn_index, turn in enumerate(turns):
                    if not isinstance(turn, dict):
                        raise ValueError(f"SGD turn 不是对象: {dialogue_id}")
                    text = str(turn.get("utterance", "")).strip()
                    speaker = str(turn.get("speaker", "")).strip()
                    frames = turn.get("frames")
                    if not speaker or not isinstance(frames, list):
                        raise ValueError(f"SGD turn 缺少 speaker 或 frames: {dialogue_id}")
                    if not text:
                        continue
                    service = _unambiguous_service(frames, dialogue_services)
                    sub_scene = _service_scene(service, schemas[split]) if service else None
                    if not sub_scene:
                        continue
                    stable_id = f"sgd:{split}:{dialogue_id}:turn:{turn_index}"
                    if stable_id in emitted_ids:
                        raise ValueError(f"SGD 存在重复稳定 ID: {stable_id}")
                    emitted_ids.add(stable_id)
                    scene = scene_by_key(sub_scene)
                    emitted += 1
                    yield CollectedSentence(
                        text=text,
                        source_item_id=stable_id,
                        source_author="",
                        source_url=_SOURCE_URL,
                        source_name="sgd",
                        license_name="CC BY-SA 4.0",
                        license_url=_LICENSE_URL,
                        top_scene=scene.top_key,
                        sub_scene=scene.key,
                    )
        if emitted == 0:
            raise ValueError(f"SGD 压缩包没有可映射的有效记录: {archive_path}")


def _matched_paths(
    archive: zipfile.ZipFile, pattern: re.Pattern[str], label: str
) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    seen: set[str] = set()
    for info in archive.infolist():
        match = pattern.fullmatch(info.filename)
        if not match:
            continue
        if info.is_dir() or info.filename in seen:
            raise ValueError(f"{label}存在重复或非文件成员: {info.filename}")
        seen.add(info.filename)
        matches.append((match.group(1), info.filename))
    return sorted(matches, key=lambda row: row[1])


def _member_root(name: str, split: str) -> str:
    marker = f"/{split}/"
    wrapped = f"/{name}"
    if marker in wrapped:
        return wrapped.split(marker, 1)[0].lstrip("/")
    raise ValueError(f"SGD 成员路径无法确定根目录: {name}")


def _read_schemas(
    archive: zipfile.ZipFile, schema_files: list[tuple[str, str]]
) -> dict[str, dict[str, str]]:
    by_split: dict[str, dict[str, str]] = {}
    for split, name in schema_files:
        descriptions = by_split.setdefault(split, {})
        payload = json.loads(archive.read(name))
        if not isinstance(payload, list):
            raise ValueError(f"SGD schema 不是数组: {name}")
        for service in payload:
            if not isinstance(service, dict):
                raise ValueError(f"SGD schema 服务不是对象: {name}")
            service_name = str(service.get("service_name", "")).strip()
            description = str(service.get("description", "")).strip()
            if not service_name or not description:
                raise ValueError(f"SGD schema 缺少 service_name 或 description: {name}")
            previous = descriptions.get(service_name)
            if previous is not None and previous != description:
                raise ValueError(f"SGD schema 服务描述冲突: {service_name}")
            descriptions[service_name] = description
    return by_split


def _clean_services(values: list[object]) -> set[str]:
    services = {str(value).strip() for value in values if str(value).strip()}
    if len(services) != len(values):
        raise ValueError("SGD services 包含空值或重复值")
    return services


def _unambiguous_service(frames: list[object], dialogue_services: set[str]) -> str | None:
    frame_services: set[str] = set()
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("SGD frame 不是对象")
        service = str(frame.get("service", "")).strip()
        if not service:
            raise ValueError("SGD frame 缺少 service")
        if service not in dialogue_services:
            raise ValueError(
                f"SGD frame service 不属于 dialogue services: {service}"
            )
        frame_services.add(service)
    if len(frame_services) == 1:
        return next(iter(frame_services))
    if len(frame_services) > 1:
        return None
    if len(dialogue_services) == 1:
        return next(iter(dialogue_services))
    return None


def _service_scene(service: str, descriptions: dict[str, str]) -> str | None:
    if service not in descriptions:
        return None
    family = service.split("_", 1)[0]
    if family == "Media":
        return "culture_movies" if service in {"Media_1", "Media_2"} else None
    direct = _SERVICE_SCENES.get(family)
    if direct:
        return direct
    if service not in {"Services_2", "Services_3", "Services_4"}:
        return None
    description = descriptions.get(service, "").casefold()
    if service in {"Services_2", "Services_3"} and any(
        word in description for word in ("dentist", "dental", "doctor", "physician", "medical")
    ):
        return "health_clinic"
    if service == "Services_4" and any(
        word in description for word in ("therapist", "therapy", "counsel", "mental")
    ):
        return "health_wellbeing"
    return None
