from __future__ import annotations

import heapq
import re
from collections import defaultdict
from collections.abc import Iterable

from tools.content_pipeline.candidates import generate_variants
from tools.content_pipeline.categorize import CATEGORIES, CategoryClassifier
from tools.content_pipeline.clean import clean_sentence, normalized_hash, rejection_reason
from tools.content_pipeline.models import CollectedSentence

_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?")
_IGNORED = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def _content_words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.casefold()) if word not in _IGNORED}


def is_near_duplicate(first: str, second: str, *, threshold: float = 0.76) -> bool:
    left = _content_words(first)
    right = _content_words(second)
    if not left or not right:
        return False
    return len(left & right) / len(left | right) >= threshold


def curate_balanced(
    candidates: Iterable[CollectedSentence], *, quota: int = 75
) -> list[CollectedSentence]:
    classifier = CategoryClassifier()
    reservoir_size = max(quota * 8, quota + 4)
    reservoirs: dict[str, list[tuple[int, str, str, CollectedSentence]]] = defaultdict(list)
    retained_hashes: dict[str, set[str]] = defaultdict(set)
    for item in candidates:
        text = clean_sentence(item.text)
        if rejection_reason(text):
            continue
        digest = normalized_hash(text)
        category = classifier.classify(item)
        if digest in retained_hashes[category]:
            continue
        cleaned_item = CollectedSentence(
            text=text,
            source_url=item.source_url,
            source_name=item.source_name,
            license_name=item.license_name,
            license_url=item.license_url,
            category_hint=item.category_hint,
            source_author=item.source_author,
        )
        rank = int(digest, 16)
        entry = (-rank, digest, item.source_url, cleaned_item)
        heap = reservoirs[category]
        if len(heap) < reservoir_size:
            heapq.heappush(heap, entry)
            retained_hashes[category].add(digest)
        elif rank < -heap[0][0]:
            removed = heapq.heapreplace(heap, entry)
            retained_hashes[category].discard(removed[1])
            retained_hashes[category].add(digest)

    buckets: dict[str, list[CollectedSentence]] = defaultdict(list)
    seen_texts: list[str] = []
    for category in CATEGORIES:
        ordered = sorted(reservoirs[category], key=lambda entry: (-entry[0], entry[1]))
        for _, _, _, item in ordered:
            if any(is_near_duplicate(item.text, previous) for previous in seen_texts):
                continue
            try:
                generate_variants(item.text)
            except ValueError:
                continue
            buckets[category].append(item)
            seen_texts.append(item.text)
            if len(buckets[category]) == quota:
                break

    shortages = {
        category: quota - len(buckets[category])
        for category in CATEGORIES
        if len(buckets[category]) < quota
    }
    if shortages:
        raise ValueError(f"无法完成平衡选句: {shortages}")
    return [item for category in CATEGORIES for item in buckets[category]]


def curate_category(
    candidates: Iterable[CollectedSentence], *, category: str, quota: int = 75
) -> list[CollectedSentence]:
    if category not in CATEGORIES:
        raise ValueError(f"不支持的类别: {category}")
    classifier = CategoryClassifier()
    ranked: dict[str, CollectedSentence] = {}
    for item in candidates:
        text = clean_sentence(item.text)
        if rejection_reason(text) or classifier.classify(item) != category:
            continue
        digest = normalized_hash(text)
        ranked[digest] = CollectedSentence(
            text=text,
            source_url=item.source_url,
            source_name=item.source_name,
            license_name=item.license_name,
            license_url=item.license_url,
            category_hint=item.category_hint,
            source_author=item.source_author,
        )

    selected: list[CollectedSentence] = []
    for _, item in sorted(ranked.items()):
        if any(is_near_duplicate(item.text, previous.text) for previous in selected):
            continue
        try:
            generate_variants(item.text)
        except ValueError:
            continue
        selected.append(item)
        if len(selected) == quota:
            return selected
    raise ValueError(f"类别 {category} 无法选出 {quota} 句，只找到 {len(selected)} 句")
