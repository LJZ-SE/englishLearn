from __future__ import annotations

import bz2
import csv
import io
import json
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from tools.content_pipeline.models import CollectedSentence


@dataclass(frozen=True, slots=True)
class SourceConfig:
    name: str
    url: str
    format: str
    license_name: str
    license_url: str
    category_hint: str | None = None
    text_field: str = "text"
    item_url_field: str | None = None
    item_url_template: str | None = None
    item_selector: str = "p"
    delimiter: str = ","
    field_names: tuple[str, ...] | None = None
    author_field: str | None = None
    category_field: str | None = None
    compression: str | None = None


def load_source_configs(path: str | Path) -> list[SourceConfig]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("来源配置必须是 JSON 数组")
    configs: list[SourceConfig] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("每个来源配置必须是 JSON 对象")
        values = dict(raw)
        if isinstance(values.get("field_names"), list):
            values["field_names"] = tuple(values["field_names"])
        configs.append(SourceConfig(**values))
    return configs


class _ElementTextParser(HTMLParser):
    def __init__(self, element_name: str) -> None:
        super().__init__()
        self.element_name = element_name
        self.depth = 0
        self.current: list[str] = []
        self.items: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == self.element_name:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == self.element_name and self.depth:
            self.depth -= 1
            if self.depth == 0 and self.current:
                self.items.append(" ".join(self.current))
                self.current = []

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.current.append(data)


def _read_url(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ListeningClozeBuilder/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _records(source: SourceConfig, payload: bytes) -> list[dict[str, Any]]:
    if source.compression == "bz2" or source.url.endswith(".bz2"):
        payload = bz2.decompress(payload)
    text = payload.decode("utf-8-sig", errors="replace")
    if source.format == "json":
        decoded = json.loads(text)
        if not isinstance(decoded, list):
            raise ValueError(f"JSON source {source.name!r} must contain a list")
        return [item for item in decoded if isinstance(item, dict)]
    if source.format in {"csv", "tsv"}:
        delimiter = "\t" if source.format == "tsv" else source.delimiter
        return list(
            csv.DictReader(io.StringIO(text), delimiter=delimiter, fieldnames=source.field_names)
        )
    if source.format == "html":
        element_name = source.item_selector.strip().split()[-1].split(".")[0].split("#")[0]
        parser = _ElementTextParser(element_name or "p")
        parser.feed(text)
        return [{source.text_field: item} for item in parser.items]
    if source.format == "text":
        return [{source.text_field: line} for line in text.splitlines() if line.strip()]
    raise ValueError(f"Unsupported source format: {source.format}")


def collect_sources(
    sources: list[SourceConfig], *, timeout: float = 30.0
) -> list[CollectedSentence]:
    result: list[CollectedSentence] = []
    for source in sources:
        for record in _records(source, _read_url(source.url, timeout)):
            raw_text = record.get(source.text_field)
            if not isinstance(raw_text, str) or not raw_text.strip():
                continue
            item_url = source.url
            if source.item_url_field:
                candidate_url = record.get(source.item_url_field)
                if isinstance(candidate_url, str) and candidate_url.startswith(
                    ("http://", "https://")
                ):
                    item_url = candidate_url
            if source.item_url_template:
                item_url = source.item_url_template.format_map(record)
            category_hint = source.category_hint
            if source.category_field:
                record_category = record.get(source.category_field)
                if isinstance(record_category, str) and record_category:
                    category_hint = record_category
            source_author = ""
            if source.author_field:
                record_author = record.get(source.author_field)
                if isinstance(record_author, str):
                    source_author = record_author
            result.append(
                CollectedSentence(
                    text=raw_text,
                    source_url=item_url,
                    source_name=source.name,
                    license_name=source.license_name,
                    license_url=source.license_url,
                    category_hint=category_hint,
                    source_author=source_author,
                )
            )
    return result
