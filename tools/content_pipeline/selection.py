from __future__ import annotations

import heapq
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable

from tools.content_pipeline.candidates import generate_variants
from tools.content_pipeline.categorize import CATEGORIES, CategoryClassifier
from tools.content_pipeline.clean import clean_sentence, normalized_hash, rejection_reason
from tools.content_pipeline.dedupe import jaccard_similarity
from tools.content_pipeline.models import CollectedSentence
from tools.content_pipeline.scenes import SCENES, SceneDefinition


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
        scene_selected, scene_conflicts = _select_scene(scene, candidates[scene.key])
        selected[scene.key].extend(scene_selected)
        conflicts.extend(scene_conflicts)

    shortages = {scene.key: max(scene.quota - len(selected[scene.key]), 0) for scene in SCENES}
    if conflicts or any(shortages.values()):
        raise SceneQuotaError(shortages, conflicts)
    return selected


def select_scene_quota[RowT](scene: SceneDefinition, rows: Iterable[RowT]) -> list[RowT]:
    """选择单个场景，供生产流水线逐场景限制内存峰值。"""
    selected = select_scene_partial(scene, rows)
    shortage = max(scene.quota - len(selected), 0)
    if shortage:
        raise SceneQuotaError({scene.key: shortage})
    return selected


def select_scene_partial[RowT](scene: SceneDefinition, rows: Iterable[RowT]) -> list[RowT]:
    """返回满足集中度约束的最大可行子集，不因配额不足而丢失容量信息。"""
    candidates = [
        row
        for row in rows
        if getattr(row, "sub_scene", None) == scene.key
        and getattr(row, "top_scene", None) == scene.top_key
    ]
    selected, conflicts = _select_scene(scene, candidates)
    if conflicts:
        raise SceneQuotaError({scene.key: max(scene.quota - len(selected), 0)}, conflicts)
    return selected


def select_with_remaining_capacity[RowT](
    rows: Iterable[RowT],
    *,
    needed: int,
    source_limit: int,
    author_limit: int,
    source_counts: Counter[str],
    author_counts: Counter[str],
) -> list[RowT]:
    """在现有来源与作者占用基础上选择最大质量的新增可行集合。"""
    return _select_regular_rows(
        list(rows),
        needed=needed,
        source_limit=source_limit,
        author_limit=author_limit,
        source_counts=source_counts.copy(),
        author_counts=author_counts.copy(),
    )


def _select_scene[RowT](
    scene: SceneDefinition, scene_rows: list[RowT]
) -> tuple[list[RowT], list[str]]:
    conflicts: list[str] = []
    protected = [row for row in scene_rows if bool(getattr(row, "protected", False))]
    protected.sort(key=_selection_key)
    source_limit = max(1, math.floor(scene.quota * 0.45))
    author_limit = max(1, math.floor(scene.quota * 0.08))
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
    selected = protected[: scene.quota]
    if conflicts:
        return selected, conflicts
    regular = [row for row in scene_rows if not bool(getattr(row, "protected", False))]
    selected.extend(
        _select_regular_rows(
            regular,
            needed=scene.quota - len(protected),
            source_limit=source_limit,
            author_limit=author_limit,
            source_counts=source_counts,
            author_counts=author_counts,
        )
    )
    return selected, conflicts


def _selection_key(row: object) -> tuple[float, str, str]:
    return (
        -float(getattr(row, "confidence", 0.0)),
        normalized_hash(str(getattr(row, "text", ""))),
        str(getattr(row, "id", "")),
    )


class _FlowEdge:
    __slots__ = ("capacity", "cost", "original", "reverse", "row", "target")

    def __init__(
        self,
        target: int,
        reverse: int,
        capacity: int,
        *,
        cost: int = 0,
        row: object | None = None,
    ) -> None:
        self.target = target
        self.reverse = reverse
        self.capacity = capacity
        self.cost = cost
        self.original = capacity
        self.row = row


def _add_flow_edge(
    graph: list[list[_FlowEdge]],
    start: int,
    end: int,
    capacity: int,
    *,
    cost: int = 0,
    row: object | None = None,
) -> _FlowEdge:
    forward = _FlowEdge(end, len(graph[end]), capacity, cost=cost, row=row)
    backward = _FlowEdge(start, len(graph[start]), 0, cost=-cost)
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
    ordered_rows = sorted(rows, key=_selection_key)
    grouped: dict[tuple[str, str], list[RowT]] = defaultdict(list)
    for row in ordered_rows:
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

    # 置信度先量化为百万分之一；tie_scale 保证任意 1 个置信度单位的总收益
    # 都严格高于整批候选的哈希及 ID 次序差异。
    tie_scale = needed * max(len(ordered_rows), 1) + 1
    candidate_edges: list[_FlowEdge] = []
    for tie_rank, row in enumerate(ordered_rows):
        source = str(getattr(row, "source_name", ""))
        author = str(getattr(row, "source_author", "")).strip()
        target = author_nodes[author] if author else end
        confidence = min(max(float(getattr(row, "confidence", 0.0)), 0.0), 1.0)
        quality_loss = 1_000_000 - round(confidence * 1_000_000)
        candidate_edges.append(
            _add_flow_edge(
                graph,
                source_nodes[source],
                target,
                1,
                cost=quality_loss * tie_scale + tie_rank,
                row=row,
            )
        )

    _minimum_cost_flow(graph, start, end, needed)
    selected = [edge.row for edge in candidate_edges if edge.capacity == 0]
    return sorted(selected, key=_selection_key)


def _minimum_cost_flow(graph: list[list[_FlowEdge]], start: int, end: int, limit: int) -> int:
    """以逐次最短增广路求固定流量的最小费用，并保持节点次序确定。"""
    total = 0
    potentials = [0] * len(graph)
    infinity = 10**30
    while total < limit:
        distances = [infinity] * len(graph)
        previous: list[tuple[int, int] | None] = [None] * len(graph)
        distances[start] = 0
        queue = [(0, start)]
        while queue:
            distance, node = heapq.heappop(queue)
            if distance != distances[node]:
                continue
            for edge_index, edge in enumerate(graph[node]):
                if edge.capacity <= 0:
                    continue
                next_distance = distance + edge.cost + potentials[node] - potentials[edge.target]
                if next_distance >= distances[edge.target]:
                    continue
                distances[edge.target] = next_distance
                previous[edge.target] = (node, edge_index)
                heapq.heappush(queue, (next_distance, edge.target))
        if previous[end] is None:
            break
        for node, distance in enumerate(distances):
            if distance < infinity:
                potentials[node] += distance
        amount = limit - total
        node = end
        while node != start:
            previous_node, edge_index = previous[node] or (start, 0)
            amount = min(amount, graph[previous_node][edge_index].capacity)
            node = previous_node
        node = end
        while node != start:
            previous_node, edge_index = previous[node] or (start, 0)
            edge = graph[previous_node][edge_index]
            edge.capacity -= amount
            graph[node][edge.reverse].capacity += amount
            node = previous_node
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
