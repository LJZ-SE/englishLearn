from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.models import CollectedSentence

_START = re.compile(r"^\*\*\* START OF (?:THE |THIS )?PROJECT GUTENBERG EBOOK", re.IGNORECASE)
_END = re.compile(r"^\*\*\* END OF (?:THE |THIS )?PROJECT GUTENBERG EBOOK", re.IGNORECASE)
_AUTHOR = re.compile(r"^Author:\s*(?P<author>.+)$", re.IGNORECASE)
_SENTENCE_BOUNDARY = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"']))\s+(?=[\"']?[A-Z])")


def iter_gutenberg_text(path: str | Path, ebook_id: int) -> Iterator[CollectedSentence]:
    source_url = f"https://www.gutenberg.org/ebooks/{ebook_id}"
    sentence_number = 0
    author = ""
    in_body = False
    metadata_finished = False
    with Path(path).open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not in_body:
                if _START.match(line):
                    in_body = True
                continue
            if _END.match(line):
                break
            stripped = line.strip()
            if not metadata_finished:
                matched = _AUTHOR.match(stripped)
                if matched:
                    author = matched.group("author").strip()
                if not stripped:
                    metadata_finished = True
                continue
            for text in _SENTENCE_BOUNDARY.split(stripped):
                if not text:
                    continue
                sentence_number += 1
                yield CollectedSentence(
                    text=text,
                    source_url=source_url,
                    source_name="Project Gutenberg",
                    license_name="per-item terms",
                    license_url="https://www.gutenberg.org/policy/license.html",
                    source_author=author,
                    source_item_id=f"{ebook_id}:{sentence_number}",
                )
