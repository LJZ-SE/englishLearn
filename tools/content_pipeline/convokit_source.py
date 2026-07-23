from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from tools.content_pipeline.models import CollectedSentence

_SOURCE_TERMS: dict[str, tuple[str, str]] = {
    "cornell-movie-dialogs": (
        "https://convokit.cornell.edu/documentation/movie.html",
        "https://convokit.cornell.edu/documentation/movie.html",
    ),
    "switchboard": (
        "https://convokit.cornell.edu/documentation/switchboard.html",
        "https://convokit.cornell.edu/documentation/switchboard.html",
    ),
}


def iter_convokit_utterances(
    path: str | Path, source_name: str
) -> Iterator[CollectedSentence]:
    source_url, license_url = _SOURCE_TERMS[source_name]
    utterances_path = Path(path)
    if utterances_path.is_dir():
        utterances_path = utterances_path / "utterances.jsonl"
    speakers = _load_speakers(utterances_path.with_name("speakers.json"))
    with utterances_path.open(encoding="utf-8") as stream:
        for line in stream:
            record = _json_object(line)
            if record is None:
                continue
            item_id = record.get("id")
            text = record.get("text")
            if (
                not isinstance(item_id, str)
                or not item_id
                or not isinstance(text, str)
                or not text.strip()
            ):
                continue
            speaker = record.get("speaker")
            speaker_id = speaker.get("id") if isinstance(speaker, dict) else speaker
            author = _speaker_name(speaker, speakers, speaker_id)
            if not author:
                continue
            yield CollectedSentence(
                text=text,
                source_url=source_url,
                source_name=source_name,
                license_name="source terms",
                license_url=license_url,
                source_author=author,
                source_item_id=item_id,
            )


def _load_speakers(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(decoded, dict):
        return decoded
    if isinstance(decoded, list):
        return {
            speaker["id"]: speaker
            for speaker in decoded
            if isinstance(speaker, dict) and isinstance(speaker.get("id"), str)
        }
    return {}


def _json_object(line: str) -> dict[str, Any] | None:
    if not line.strip():
        return None
    decoded = json.loads(line)
    return decoded if isinstance(decoded, dict) else None


def _speaker_name(speaker: object, speakers: dict[str, Any], speaker_id: object) -> str:
    details = speaker if isinstance(speaker, dict) else speakers.get(speaker_id)
    if isinstance(details, dict):
        metadata = details.get("meta")
        if isinstance(metadata, dict):
            name = metadata.get("name")
            if isinstance(name, str) and name:
                return name
        name = details.get("name")
        if isinstance(name, str) and name:
            return name
    return speaker_id if isinstance(speaker_id, str) else ""
