from __future__ import annotations

import bz2
import csv
from collections.abc import Iterator
from pathlib import Path

from tools.content_pipeline.models import CollectedSentence

TATOEBA_LICENSE_NAME = "CC BY 2.0 FR"
TATOEBA_LICENSE_URL = "https://creativecommons.org/licenses/by/2.0/fr/"


def iter_tatoeba_detailed(path: str | Path) -> Iterator[CollectedSentence]:
    with bz2.open(path, "rt", encoding="utf-8", errors="replace", newline="") as stream:
        for row in csv.reader(stream, delimiter="\t"):
            if len(row) < 4 or row[1] != "eng":
                continue
            sentence_id, _, text, author = row[:4]
            if not sentence_id.isdigit() or not author or author == r"\N":
                continue
            yield CollectedSentence(
                text=text,
                source_url=f"https://tatoeba.org/en/sentences/show/{sentence_id}",
                source_name="Tatoeba",
                license_name=TATOEBA_LICENSE_NAME,
                license_url=TATOEBA_LICENSE_URL,
                source_author=author,
            )
