from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.archive_safety import (
    validate_archive_member_path,
    validate_regular_zip_member,
)
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import scene_by_key

_REVISION = "828f8093932c8fe6ca7936c3d2e52903b1c523de"
_SOURCE_URL = f"https://github.com/clinc/oos-eval/tree/{_REVISION}"
_LICENSE_URL = "https://creativecommons.org/licenses/by/3.0/"
_DATA_PATH = re.compile(r"^(?:[^/]+/)?data/data_full[.]json$")
_SPLITS = ("train", "val", "test")

# 只有语义与现有场景一一对应的意图才进入题库，未知意图一律跳过。
CLINC_INTENT_SCENES = {
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


def iter_clinc150_utterances(
    archive_path: Path,
    *,
    normalization_version: int,
) -> Iterator[CollectedSentence]:
    if normalization_version != 1:
        raise ValueError(f"CLINC150 不支持 normalization_version={normalization_version}")
    if not zipfile.is_zipfile(archive_path):
        raise ValueError(f"CLINC150 下载内容不是有效 ZIP: {archive_path}")
    with zipfile.ZipFile(archive_path) as archive:
        candidates = [
            info
            for info in archive.infolist()
            if info.filename.endswith("data/data_full.json")
        ]
        for info in candidates:
            validate_archive_member_path(info.filename, label="CLINC150")
        members = [info for info in candidates if _DATA_PATH.fullmatch(info.filename)]
        if len(members) != 1 or members[0].is_dir():
            raise ValueError(f"CLINC150 压缩包结构漂移: {archive_path}")
        validate_regular_zip_member(members[0], label="CLINC150")
        payload = json.loads(archive.read(members[0]))
    if not isinstance(payload, dict) or any(
        not isinstance(payload.get(split), list) for split in _SPLITS
    ):
        raise ValueError(f"CLINC150 data_full.json schema 漂移: {archive_path}")

    emitted_ids: set[str] = set()
    emitted = 0
    for split in _SPLITS:
        for row_index, row in enumerate(payload[split]):
            if not isinstance(row, list) or len(row) != 2:
                raise ValueError(f"CLINC150 {split} 第 {row_index} 行 schema 漂移")
            text, intent = row
            if not isinstance(text, str) or not isinstance(intent, str):
                raise ValueError(f"CLINC150 {split} 第 {row_index} 行字段类型错误")
            sub_scene = CLINC_INTENT_SCENES.get(intent)
            if not sub_scene:
                continue
            normalized_text = _append_terminal_punctuation(text)
            if not normalized_text:
                continue
            stable_id = f"clinc150:{split}:{row_index}:norm-v1"
            if stable_id in emitted_ids:
                raise ValueError(f"CLINC150 存在重复稳定 ID: {stable_id}")
            emitted_ids.add(stable_id)
            scene = scene_by_key(sub_scene)
            emitted += 1
            yield CollectedSentence(
                text=normalized_text,
                source_item_id=stable_id,
                source_author="",
                source_url=_SOURCE_URL,
                source_name="clinc150",
                license_name="CC BY 3.0",
                license_url=_LICENSE_URL,
                top_scene=scene.top_key,
                sub_scene=scene.key,
            )
    if emitted == 0:
        raise ValueError(f"CLINC150 压缩包没有可映射的有效记录: {archive_path}")


def _append_terminal_punctuation(text: str) -> str:
    stripped = text.strip()
    sentence_end = stripped.rstrip("\"'”’")
    if not sentence_end or sentence_end[-1] in ".?!":
        return stripped
    return f"{sentence_end}.{stripped[len(sentence_end):]}"
