from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from tools.content_pipeline.clean import normalized_hash, normalized_text

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
    "this",
    "to",
    "with",
}


def content_words(text: str) -> tuple[str, ...]:
    return tuple(word for word in _WORD.findall(normalized_text(text)) if word not in _IGNORED)


def _shingles(text: str) -> tuple[str, ...]:
    words = content_words(text)
    if len(words) < 3:
        return (" ".join(words),) if words else ()
    return tuple(" ".join(words[index : index + 3]) for index in range(len(words) - 2))


def simhash64(text: str) -> int:
    """返回基于规范化内容词三元组的稳定 64 位 SimHash。"""
    shingles = _shingles(text)
    if not shingles:
        return 0
    weights = [0] * 64
    for shingle in shingles:
        digest = hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            weights[bit] += 1 if value & (1 << bit) else -1
    return sum(1 << bit for bit, weight in enumerate(weights) if weight >= 0)


def jaccard_similarity(first: str, second: str) -> float:
    left = set(content_words(first))
    right = set(content_words(second))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True, slots=True)
class _IndexedText:
    text: str
    normalized_hash: str


class NearDuplicateIndex:
    """用 SimHash 分桶缩小候选集，再以 Jaccard 做最终判定。"""

    def __init__(self, threshold: float = 0.76) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("Jaccard 阈值必须位于 0 到 1 之间")
        self.threshold = threshold
        self.duplicate_hash: str | None = None
        self._items: list[_IndexedText] = []
        self._bands: dict[tuple[int, int], list[int]] = {}

    def add(self, text: str) -> bool:
        fingerprint = simhash64(text)
        band_keys = tuple((band, (fingerprint >> (band * 16)) & 0xFFFF) for band in range(4))
        candidate_ids: set[int] = set()
        for key in band_keys:
            candidate_ids.update(self._bands.get(key, ()))
        for item_id in sorted(candidate_ids):
            candidate = self._items[item_id]
            if jaccard_similarity(text, candidate.text) >= self.threshold:
                self.duplicate_hash = candidate.normalized_hash
                return False

        self.duplicate_hash = None
        item_id = len(self._items)
        self._items.append(_IndexedText(text=text, normalized_hash=normalized_hash(text)))
        for key in band_keys:
            self._bands.setdefault(key, []).append(item_id)
        return True
