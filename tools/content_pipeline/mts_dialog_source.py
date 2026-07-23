from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.models import CollectedSentence

_SOURCE_URL = (
    "https://github.com/abachaa/MTS-Dialog/tree/"
    "3ff0801933608d6f570468c13125125fb5cabdea/Main-Dataset"
)
_LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
_SPEAKER = re.compile(
    r"(?i)(?<!\S)(Doctor|Patient|Physician|Provider|Clinician|Guest_family|D|P)"
    r"[ \t]*:[ \t]*"
)


def iter_mts_dialog_utterances(archive_path: Path) -> Iterator[CollectedSentence]:
    with zipfile.ZipFile(archive_path) as archive:
        dataset_files = [
            name
            for name in archive.namelist()
            if "/Main-Dataset/" in f"/{name}" and name.lower().endswith(".csv")
        ]
        if not dataset_files:
            raise ValueError(f"MTS-Dialog 压缩包缺少 Main-Dataset CSV: {archive_path}")
        for name in sorted(dataset_files):
            split = _dataset_split(Path(name).name)
            with archive.open(name) as binary_stream:
                text_stream = io.TextIOWrapper(binary_stream, encoding="utf-8-sig", newline="")
                for row_number, row in enumerate(csv.DictReader(text_stream), start=1):
                    normalized = {
                        str(key).strip().lower(): str(value or "")
                        for key, value in row.items()
                        if key is not None
                    }
                    dialogue = normalized.get("dialogue", "").strip()
                    if not dialogue:
                        continue
                    record_id = normalized.get("id", "").strip() or str(row_number)
                    for turn_number, (_speaker, text) in enumerate(
                        _iter_dialogue_turns(dialogue), start=1
                    ):
                        yield CollectedSentence(
                            text=text,
                            source_item_id=(f"{split}:{record_id}:turn:{turn_number}"),
                            source_author="",
                            source_url=_SOURCE_URL,
                            source_name="mts-dialog",
                            license_name="CC BY 4.0",
                            license_url=_LICENSE_URL,
                        )


def _dataset_split(filename: str) -> str:
    lowered = filename.lower()
    if "training" in lowered:
        return "train"
    if "validation" in lowered:
        return "validation"
    if "testset-1" in lowered:
        return "test-1"
    if "testset-2" in lowered:
        return "test-2"
    raise ValueError(f"无法识别 MTS-Dialog 数据集分片: {filename}")


def _iter_dialogue_turns(dialogue: str) -> Iterator[tuple[str, str]]:
    matches = list(_SPEAKER.finditer(dialogue))
    if not matches:
        yield "Unknown speaker", dialogue.strip()
        return
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(dialogue)
        text = dialogue[match.end() : end].strip()
        if not text:
            continue
        yield _canonical_speaker(match.group(1)), text


def _canonical_speaker(value: str) -> str:
    lowered = value.lower()
    if lowered in {"doctor", "physician", "provider", "clinician", "d"}:
        return "Doctor"
    if lowered == "guest_family":
        return "Guest family"
    return "Patient"
