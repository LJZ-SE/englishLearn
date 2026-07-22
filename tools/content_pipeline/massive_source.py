from __future__ import annotations

import json
import re
import tarfile
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import scene_by_key

_SOURCE_URL = "https://amazon-massive-nlu-dataset.s3.amazonaws.com/amazon-massive-dataset-1.0.tar.gz"
_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
_DATA_PATH = re.compile(r"^(?:[^/]+/)?1[.]0/data/en-US[.]jsonl$")

# MASSIVE 的 scenario 与 intent 必须同时命中此白名单，避免用宽泛 scenario 兜底。
MASSIVE_LABEL_SCENES = {
    ("audio", "audio_volume_down"): "technology_devices",
    ("audio", "audio_volume_mute"): "technology_devices",
    ("audio", "audio_volume_up"): "technology_devices",
    ("iot", "iot_cleaning"): "technology_devices",
    ("iot", "iot_coffee"): "technology_devices",
    ("iot", "iot_hue_lightchange"): "technology_devices",
    ("iot", "iot_hue_lightdim"): "technology_devices",
    ("iot", "iot_hue_lightoff"): "technology_devices",
    ("iot", "iot_hue_lighton"): "technology_devices",
    ("iot", "iot_hue_lightup"): "technology_devices",
    ("iot", "iot_wemo_off"): "technology_devices",
    ("iot", "iot_wemo_on"): "technology_devices",
    ("cooking", "cooking_recipe"): "daily_food",
    ("takeaway", "takeaway_order"): "daily_food",
    ("takeaway", "takeaway_query"): "daily_food",
    ("email", "email_addcontact"): "work_contact",
    ("email", "email_query"): "work_contact",
    ("email", "email_querycontact"): "work_contact",
    ("email", "email_sendemail"): "work_contact",
    ("music", "music_dislikeness"): "culture_music",
    ("music", "music_likeness"): "culture_music",
    ("music", "music_query"): "culture_music",
    ("music", "music_settings"): "culture_music",
    ("play", "play_music"): "culture_music",
    ("news", "news_query"): "news_current",
    ("social", "social_post"): "daily_social",
    ("social", "social_query"): "daily_social",
    ("weather", "weather_query"): "news_environment",
    ("play", "play_audiobook"): "culture_books",
    ("recommendation", "recommendation_movies"): "culture_movies",
    ("qa", "qa_currency"): "news_business",
    ("qa", "qa_stock"): "news_business",
    ("qa", "qa_definition"): "study_language",
    ("transport", "transport_directions"): "travel_directions",
    ("transport", "transport_query"): "travel_transport",
    ("transport", "transport_taxi"): "travel_transport",
    ("transport", "transport_ticket"): "travel_transport",
    ("transport", "transport_traffic"): "travel_transport",
}


def iter_massive_utterances(
    archive_path: Path,
    *,
    normalization_version: int,
) -> Iterator[CollectedSentence]:
    if normalization_version != 1:
        raise ValueError(f"MASSIVE 不支持 normalization_version={normalization_version}")
    if not tarfile.is_tarfile(archive_path):
        raise ValueError(f"MASSIVE 下载内容不是有效 TAR.GZ: {archive_path}")
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            yield from _iter_archive(archive, archive_path)
    except (tarfile.TarError, OSError) as error:
        raise ValueError(f"MASSIVE 下载内容不是有效 gzip/tar: {archive_path}") from error


def _iter_archive(
    archive: tarfile.TarFile, archive_path: Path
) -> Iterator[CollectedSentence]:
    members = [member for member in archive.getmembers() if _DATA_PATH.fullmatch(member.name)]
    if len(members) != 1:
        raise ValueError(f"MASSIVE 压缩包结构漂移: {archive_path}")
    member = members[0]
    if not member.isfile():
        raise ValueError(f"MASSIVE 数据成员不是普通文件: {member.name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"MASSIVE 无法读取数据成员: {member.name}")
    emitted_ids: set[str] = set()
    emitted = 0
    for line_number, raw_line in enumerate(stream, start=1):
        try:
            row = json.loads(raw_line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError(f"MASSIVE JSONL 第 {line_number} 行无效") from error
        if not isinstance(row, dict):
            raise ValueError(f"MASSIVE JSONL 第 {line_number} 行不是对象")
        locale = str(row.get("locale", "")).strip()
        if locale != "en-US":
            continue
        item_id = str(row.get("id", "")).strip()
        scenario = str(row.get("scenario", "")).strip()
        intent = str(row.get("intent", "")).strip()
        utterance = row.get("utt")
        raw_worker_id = row.get("worker_id")
        worker_id = str(raw_worker_id).strip() if raw_worker_id is not None else ""
        if not item_id or not scenario or not intent or not isinstance(utterance, str):
            raise ValueError(f"MASSIVE en-US 第 {line_number} 行 schema 漂移")
        sub_scene = MASSIVE_LABEL_SCENES.get((scenario, intent))
        if not sub_scene:
            continue
        text = _append_terminal_punctuation(utterance)
        if not text:
            continue
        stable_id = f"massive-1.0:en-US:{item_id}:norm-v1"
        if stable_id in emitted_ids:
            raise ValueError(f"MASSIVE 存在重复稳定 ID: {stable_id}")
        emitted_ids.add(stable_id)
        author = f"massive-worker:{' '.join(worker_id.split())}" if worker_id else ""
        scene = scene_by_key(sub_scene)
        emitted += 1
        yield CollectedSentence(
            text=text,
            source_item_id=stable_id,
            source_author=author,
            source_url=_SOURCE_URL,
            source_name="massive-1.0",
            license_name="CC BY 4.0",
            license_url=_LICENSE_URL,
            top_scene=scene.top_key,
            sub_scene=scene.key,
        )
    if emitted == 0:
        raise ValueError(f"MASSIVE 压缩包没有可映射的有效记录: {archive_path}")


def _append_terminal_punctuation(text: str) -> str:
    stripped = text.strip()
    sentence_end = stripped.rstrip("\"'”’")
    if stripped and (not sentence_end or sentence_end[-1] not in ".?!"):
        return stripped + "."
    return stripped
