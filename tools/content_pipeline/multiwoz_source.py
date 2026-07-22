from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.models import CollectedSentence

_DIALOGUE_FILE = re.compile(r"(?:^|/)data/MultiWOZ_2[.]2/(train|dev|test)/dialogues_[0-9]+[.]json$")
_SOURCE_URL = "https://github.com/budzianowski/multiwoz/tree/master/data/MultiWOZ_2.2"
_LICENSE_URL = "https://github.com/budzianowski/multiwoz/blob/master/LICENSE"


def iter_multiwoz_utterances(archive_path: Path) -> Iterator[CollectedSentence]:
    with zipfile.ZipFile(archive_path) as archive:
        dialogue_files = [
            (match.group(1), name)
            for name in archive.namelist()
            if (match := _DIALOGUE_FILE.search(name))
        ]
        if not dialogue_files:
            raise ValueError(f"MultiWOZ 压缩包缺少 2.2 对话文件: {archive_path}")
        for split, name in sorted(dialogue_files, key=lambda row: row[1]):
            payload = json.loads(archive.read(name))
            if not isinstance(payload, list):
                raise ValueError(f"MultiWOZ 对话文件不是数组: {name}")
            for dialogue in payload:
                if not isinstance(dialogue, dict):
                    raise ValueError(f"MultiWOZ 对话条目不是对象: {name}")
                dialogue_id = str(dialogue.get("dialogue_id", "")).strip()
                turns = dialogue.get("turns")
                if not dialogue_id or not isinstance(turns, list):
                    raise ValueError(f"MultiWOZ 对话缺少稳定 ID 或 turns: {name}")
                for turn_number, turn in enumerate(turns, start=1):
                    if not isinstance(turn, dict):
                        raise ValueError(f"MultiWOZ turn 不是对象: {dialogue_id}")
                    text = str(turn.get("utterance", "")).strip()
                    speaker = str(turn.get("speaker", "")).strip()
                    if not text:
                        continue
                    if not speaker:
                        raise ValueError(f"MultiWOZ turn 缺少 speaker: {dialogue_id}")
                    yield CollectedSentence(
                        text=text,
                        source_item_id=(f"{split}:{dialogue_id}:turn:{turn_number}"),
                        source_author="",
                        source_url=_SOURCE_URL,
                        source_name="multiwoz-2-2",
                        license_name="MIT",
                        license_url=_LICENSE_URL,
                    )
