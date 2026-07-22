from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CollectedSentence:
    text: str
    source_url: str
    source_name: str
    license_name: str
    license_url: str
    category_hint: str | None = None
    source_author: str = ""
    translation_zh: str = ""


@dataclass(frozen=True, slots=True)
class QuestionVariant:
    difficulty: str
    answer_start: int
    answer_end: int
    canonical_answer: str
    blank_count: int
    score: float
    rationale: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BuildResult:
    sentence_count: int
    variant_count: int
    rejected_count: int
