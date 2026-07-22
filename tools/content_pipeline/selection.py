from __future__ import annotations

import heapq
import json
import math
from collections import Counter, defaultdict, deque
from collections.abc import Iterable

from tools.content_pipeline.candidates import generate_variants
from tools.content_pipeline.categorize import CATEGORIES, CategoryClassifier
from tools.content_pipeline.clean import clean_sentence, normalized_hash, rejection_reason
from tools.content_pipeline.dedupe import jaccard_similarity
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import SCENES


class SceneQuotaError(ValueError):
    def __init__(self, shortages: dict[str, int], conflicts: list[str] | None = None) -> None:
        self.shortages = shortages
        self.conflicts = tuple(conflicts or ())
        detail = f"场景配额差额: {json.dumps(shortages, ensure_ascii=False, sort_keys=True)}"
        if self.conflicts:
            detail = f"{'; '.join(self.conflicts)}; {detail}"
        super().__init__(detail)


def is_near_duplicate(first: str, second: str, *, threshold: float = 0.76) -> bool:
    return jaccard_similarity(first, second) >= threshold


def select_scene_quotas[RowT](rows: Iterable[RowT]) -> dict[str, list[RowT]]:
    candidates: dict[str, list[RowT]] = defaultdict(list)
    valid_scenes = {scene.key: scene for scene in SCENES}
    for row in rows:
        sub_scene = getattr(row, "sub_scene", None)
        scene = valid_scenes.get(sub_scene)
        if scene is None or getattr(row, "top_scene", None) != scene.top_key:
            continue
        candidates[scene.key].append(row)

    selected: dict[str, list[RowT]] = {scene.key: [] for scene in SCENES}
    conflicts: list[str] = []
    for scene in SCENES:
        conflict_count = len(conflicts)
        scene_rows = candidates[scene.key]
        protected = [row for row in scene_rows if bool(getattr(row, "protected", False))]
        protected.sort(key=_selection_key)
        source_limit = math.floor(scene.quota * 0.45)
        author_limit = math.floor(scene.quota * 0.08)
        source_counts = Counter(str(getattr(row, "source_name", "")) for row in protected)
        author_counts = Counter(
            author
            for row in protected
            if (author := str(getattr(row, "source_author", "")).strip())
        )
        if len(protected) > scene.quota:
            conflicts.append(
                f"protected quota conflict in {scene.key}: {len(protected)} > {scene.quota}"
            )
        for source, count in sorted(source_counts.items()):
            if count > source_limit:
                conflicts.append(
                    f"protected source conflict in {scene.key}: {source!r} {count} > {source_limit}"
                )
        for author, count in sorted(author_counts.items()):
            if count > author_limit:
                conflicts.append(
                    f"protected author conflict in {scene.key}: {author!r} {count} > {author_limit}"
                )
        selected[scene.key].extend(protected[: scene.quota])
        if len(conflicts) > conflict_count:
            continue

        regular = [row for row in scene_rows if not bool(getattr(row, "protected", False))]
        selected[scene.key].extend(
            _select_regular_rows(
                regular,
                needed=scene.quota - len(protected),
                source_limit=source_limit,
                author_limit=author_limit,
                source_counts=source_counts,
                author_counts=author_counts,
            )
        )

    shortages = {scene.key: max(scene.quota - len(selected[scene.key]), 0) for scene in SCENES}
    if conflicts or any(shortages.values()):
        raise SceneQuotaError(shortages, conflicts)
    return selected


def _selection_key(row: object) -> tuple[str, str]:
    return normalized_hash(str(getattr(row, "text", ""))), str(getattr(row, "id", ""))


class _FlowEdge:
    __slots__ = ("capacity", "original", "reverse", "target")

    def __init__(self, target: int, reverse: int, capacity: int) -> None:
        self.target = target
        self.reverse = reverse
        self.capacity = capacity
        self.original = capacity


def _add_flow_edge(graph: list[list[_FlowEdge]], start: int, end: int, capacity: int) -> _FlowEdge:
    forward = _FlowEdge(end, len(graph[end]), capacity)
    backward = _FlowEdge(start, len(graph[start]), 0)
    graph[start].append(forward)
    graph[end].append(backward)
    return forward


def _select_regular_rows[RowT](
    rows: list[RowT],
    *,
    needed: int,
    source_limit: int,
    author_limit: int,
    source_counts: Counter[str],
    author_counts: Counter[str],
) -> list[RowT]:
    if needed <= 0:
        return []
    grouped: dict[tuple[str, str], list[RowT]] = defaultdict(list)
    for row in sorted(rows, key=_selection_key):
        source = str(getattr(row, "source_name", ""))
        author = str(getattr(row, "source_author", "")).strip()
        grouped[(source, author)].append(row)

    sources = sorted({source for source, _ in grouped})
    authors = sorted({author for _, author in grouped if author})
    source_nodes = {source: index + 2 for index, source in enumerate(sources)}
    author_nodes = {author: index + 2 + len(source_nodes) for index, author in enumerate(authors)}
    graph: list[list[_FlowEdge]] = [[] for _ in range(2 + len(source_nodes) + len(author_nodes))]
    start, end = 0, 1
    for source in sources:
        remaining = max(source_limit - source_counts[source], 0)
        _add_flow_edge(graph, start, source_nodes[source], remaining)
    for author in authors:
        remaining = max(author_limit - author_counts[author], 0)
        _add_flow_edge(graph, author_nodes[author], end, remaining)

    pair_edges: dict[tuple[str, str], _FlowEdge] = {}
    grouped_by_source: dict[str, list[tuple[str, list[RowT]]]] = defaultdict(list)
    for (source, author), pair_rows in grouped.items():
        grouped_by_source[source].append((author, pair_rows))
    for source in sources:
        ordered_groups = sorted(
            grouped_by_source[source], key=lambda item: _selection_key(item[1][0])
        )
        for author, pair_rows in ordered_groups:
            target = author_nodes[author] if author else end
            pair_edges[(source, author)] = _add_flow_edge(
                graph, source_nodes[source], target, len(pair_rows)
            )

    _maximum_flow(graph, start, end, needed)
    selected: list[RowT] = []
    for pair in sorted(grouped, key=lambda key: _selection_key(grouped[key][0])):
        edge = pair_edges[pair]
        selected.extend(grouped[pair][: edge.original - edge.capacity])
    return sorted(selected, key=_selection_key)


def _maximum_flow(graph: list[list[_FlowEdge]], start: int, end: int, limit: int) -> int:
    total = 0
    while total < limit:
        levels = [-1] * len(graph)
        levels[start] = 0
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for edge in graph[node]:
                if edge.capacity > 0 and levels[edge.target] < 0:
                    levels[edge.target] = levels[node] + 1
                    queue.append(edge.target)
        if levels[end] < 0:
            break
        positions = [0] * len(graph)

        def send(
            node: int,
            available: int,
            current_levels: list[int] = levels,
            current_positions: list[int] = positions,
        ) -> int:
            if node == end:
                return available
            while current_positions[node] < len(graph[node]):
                edge = graph[node][current_positions[node]]
                if edge.capacity > 0 and current_levels[edge.target] == current_levels[node] + 1:
                    amount = send(edge.target, min(available, edge.capacity))
                    if amount:
                        edge.capacity -= amount
                        graph[edge.target][edge.reverse].capacity += amount
                        return amount
                current_positions[node] += 1
            return 0

        while total < limit and (amount := send(start, limit - total)):
            total += amount
    return total


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
