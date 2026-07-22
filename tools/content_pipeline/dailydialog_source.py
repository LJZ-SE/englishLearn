from __future__ import annotations

import json
import zipfile
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.models import CollectedSentence

_SOURCE_URL = (
    "https://huggingface.co/datasets/ConvLab/dailydialog/tree/"
    "745c1796cfe209b469394567f496815d2bc495d2"
)
_LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"


def iter_dailydialog_utterances(archive_path: Path) -> Iterator[CollectedSentence]:
    with zipfile.ZipFile(archive_path) as archive:
        dialogue_files = [name for name in archive.namelist() if name == "data/dialogues.json"]
        if len(dialogue_files) != 1:
            raise ValueError(f"DailyDialog 压缩包缺少 data/dialogues.json: {archive_path}")
        payload = json.loads(archive.read(dialogue_files[0]))
    if not isinstance(payload, list):
        raise ValueError(f"DailyDialog dialogues.json 不是数组: {archive_path}")

    for dialogue in payload:
        if not isinstance(dialogue, dict):
            raise ValueError("DailyDialog 对话条目不是对象")
        dialogue_id = str(
            dialogue.get("original_id") or dialogue.get("dialogue_id") or ""
        ).strip()
        turns = dialogue.get("turns")
        if not dialogue_id or not isinstance(turns, list):
            raise ValueError("DailyDialog 对话缺少稳定 ID 或 turns")
        for turn in turns:
            if not isinstance(turn, dict):
                raise ValueError(f"DailyDialog turn 不是对象: {dialogue_id}")
            turn_index = turn.get("utt_idx")
            if isinstance(turn_index, bool) or not isinstance(turn_index, int):
                raise ValueError(f"DailyDialog turn 缺少整数 utt_idx: {dialogue_id}")
            text = str(turn.get("utterance", "")).strip()
            if not text:
                continue
            yield CollectedSentence(
                text=text,
                source_item_id=f"{dialogue_id}:turn:{turn_index}",
                source_author="",
                source_url=_SOURCE_URL,
                source_name="daily-dialog",
                license_name="CC BY-NC-SA 4.0",
                license_url=_LICENSE_URL,
            )
