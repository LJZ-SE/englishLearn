from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

from tools.content_pipeline.clean import clean_sentence, rejection_reason
from tools.content_pipeline.models import CollectedSentence

_DATE_LINE = re.compile(
    r"^(?P<published>(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\s*",
)
_SENTENCE_BOUNDARY = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"']))\s+(?=[\"']?[A-Z])")


def _split_sentences(extract: str) -> list[str]:
    text = _DATE_LINE.sub("", extract.strip(), count=1)
    text = re.sub(r"\s+", " ", text).strip()
    protected = re.sub(
        r"\b(Dr|Mr|Mrs|Ms|Prof|Sr|Jr)\.",
        r"\1<DOT>",
        text,
        flags=re.IGNORECASE,
    )
    protected = re.sub(r"\b([A-Z])\.(?=\s+[A-Z][a-z])", r"\1<DOT>", protected)
    return [
        clean_sentence(part.replace("<DOT>", "."))
        for part in _SENTENCE_BOUNDARY.split(protected)
        if part.strip()
    ]


def _license_for_extract(extract: str) -> tuple[str, str]:
    matched = _DATE_LINE.match(extract.strip())
    if matched is None:
        return "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"
    published = datetime.strptime(matched.group("published"), "%A, %B %d, %Y").date()
    if published < date(2005, 9, 25):
        return "Public domain", "https://creativecommons.org/publicdomain/mark/1.0/"
    if published < date(2024, 12, 16):
        return "CC BY 2.5", "https://creativecommons.org/licenses/by/2.5/"
    return "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"


def iter_wikinews_extracts(
    path: str | Path, *, max_per_article: int = 6
) -> Iterator[CollectedSentence]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    pages = payload.get("query", {}).get("pages", [])
    if not isinstance(pages, list):
        raise ValueError("Wikinews API 响应缺少 query.pages 数组")
    for page in pages:
        if not isinstance(page, dict):
            continue
        source_url = page.get("fullurl")
        extract = page.get("extract")
        if not isinstance(source_url, str) or not isinstance(extract, str):
            continue
        license_name, license_url = _license_for_extract(extract)
        source_key = page.get("pageid") or page.get("title") or source_url
        if not isinstance(source_key, (str, int)):
            continue
        emitted = 0
        for sentence_index, text in enumerate(_split_sentences(extract), start=1):
            if rejection_reason(text):
                continue
            yield CollectedSentence(
                text=text,
                source_url=source_url,
                source_name="English Wikinews",
                license_name=license_name,
                license_url=license_url,
                category_hint="news_podcasts",
                source_author="Wikinews",
                source_item_id=f"{source_key}:{sentence_index}",
            )
            emitted += 1
            if emitted == max_per_article:
                break
