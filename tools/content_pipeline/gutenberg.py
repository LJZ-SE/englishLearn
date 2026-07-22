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
    paragraph: list[str] = []
    with Path(path).open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not in_body:
                matched = _AUTHOR.match(line.strip())
                if matched:
                    author = matched.group("author").strip()
                if _START.match(line):
                    in_body = True
                continue
            if _END.match(line):
                for text in _paragraph_sentences(paragraph):
                    sentence_number += 1
                    yield _item(text, source_url, ebook_id, sentence_number, author)
                break
            stripped = line.strip()
            if not stripped:
                for text in _paragraph_sentences(paragraph):
                    sentence_number += 1
                    yield _item(text, source_url, ebook_id, sentence_number, author)
                paragraph = []
                continue
            paragraph.append(stripped)
        else:
            for text in _paragraph_sentences(paragraph):
                sentence_number += 1
                yield _item(text, source_url, ebook_id, sentence_number, author)


def _paragraph_sentences(lines: list[str]) -> Iterator[str]:
    for text in _SENTENCE_BOUNDARY.split(" ".join(lines)):
        if text:
            yield text


def _item(
    text: str, source_url: str, ebook_id: int, sentence_number: int, author: str
) -> CollectedSentence:
    return CollectedSentence(
        text=text,
        source_url=source_url,
        source_name="Project Gutenberg",
        license_name="per-item terms",
        license_url="https://www.gutenberg.org/policy/license.html",
        source_author=author,
        source_item_id=f"{ebook_id}:{sentence_number}",
    )
