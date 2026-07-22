from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.models import CollectedSentence

_SOURCE_URL = "http://yanran.li/dailydialog"
_LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"


def iter_dailydialog_utterances(archive_path: Path) -> Iterator[CollectedSentence]:
    with zipfile.ZipFile(archive_path) as archive:
        text_files = [
            name for name in archive.namelist() if Path(name).name == "dialogues_text.txt"
        ]
        if len(text_files) != 1:
            raise ValueError(f"DailyDialog 压缩包应只包含一个 dialogues_text.txt: {archive_path}")
        content = archive.read(text_files[0]).decode("utf-8-sig")

    for dialogue_number, line in enumerate(content.splitlines(), start=1):
        for turn_number, raw_text in enumerate(line.split("__eou__"), start=1):
            text = raw_text.strip()
            if not text:
                continue
            yield CollectedSentence(
                text=text,
                source_item_id=f"dialogue:{dialogue_number}:turn:{turn_number}",
                source_author="",
                source_url=_SOURCE_URL,
                source_name="daily-dialog",
                license_name="CC BY-NC-SA 4.0",
                license_url=_LICENSE_URL,
            )
