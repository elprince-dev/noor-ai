"""Pure retrieval metrics: recall@k, precision@k, MRR + aggregation (Req 7.1-7.8).

Deterministic, code-based functions comparing retrieved Source_IDs against
expected Source_IDs by exact string equality only — no partial or fuzzy
matching, no I/O, no LLM (Req 7.5). Identical inputs always produce identical
outputs (Req 7.7).

Duplicate retrieved Source_IDs collapse to a single occurrence at their
highest rank (`dedupe_ranked`, Req 7.5) before any metric is scored.

`aggregate` computes per-item metrics plus arithmetic-mean aggregates over
the applicable items (non-empty expected Source_IDs and not failed) —
overall, by category, and by language. Inapplicable items are marked
not-computed and excluded from every aggregate (Req 7.4, 7.6, 7.8).
"""
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalItemInput:
    """Everything the aggregator needs to know about one Golden_Item's run.

    Built by the runner from the Golden_Item (id, category, language,
    expected_source_ids) and its recorded execution result (retrieved
    Source_IDs in rank order, failed flag).
    """

    item_id: str
    category: str
    language: str
    expected_source_ids: tuple[str, ...]
    retrieved_source_ids: tuple[str, ...]  # rank order, may contain duplicates
    failed: bool = False


@dataclass(frozen=True, slots=True)
class ItemRetrievalMetrics:
    """Per-item Retrieval_Metrics; `computed=False` marks not-computed (Req 7.4, 7.8)."""

    item_id: str
    computed: bool
    recall_at_k: float | None = None
    precision_at_k: float | None = None
    mrr: float | None = None


@dataclass(frozen=True, slots=True)
class MetricMeans:
    """Arithmetic means of each metric over one group of applicable items (Req 7.6)."""

    recall_at_k: float
    precision_at_k: float
    mrr: float
    item_count: int


@dataclass(frozen=True, slots=True)
class RetrievalAggregates:
    """Per-item metrics plus overall / by-category / by-language means.

    `overall` is None when zero items are applicable; `by_category` and
    `by_language` contain only groups with at least one applicable item.
    """

    per_item: tuple[ItemRetrievalMetrics, ...]
    overall: MetricMeans | None
    by_category: dict[str, MetricMeans]
    by_language: dict[str, MetricMeans]


def dedupe_ranked(retrieved: Sequence[str]) -> list[str]:
    """Collapse duplicate Source_IDs, keeping the first (highest-rank) occurrence."""
    seen: set[str] = set()
    deduped: list[str] = []
    for source_id in retrieved:
        if source_id not in seen:
            seen.add(source_id)
            deduped.append(source_id)
    return deduped


def recall_at_k(expected: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    """|expected ∩ top-k retrieved| / |expected| (Req 7.1).

    Raises:
        ValueError: `expected` is empty (the metric is undefined; such items
            are not computed per Req 7.4) or `k` < 1.
    """
    expected_set = set(expected)
    if not expected_set:
        raise ValueError("recall_at_k is undefined for an empty expected Source_ID list")
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    top_k = set(dedupe_ranked(retrieved)[:k])
    return len(expected_set & top_k) / len(expected_set)


def precision_at_k(expected: Sequence[str], retrieved: Sequence[str], k: int) -> float:
    """|top-k retrieved ∩ expected| / k — divide by k even when fewer retrieved (Req 7.2).

    Raises:
        ValueError: `k` < 1.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    expected_set = set(expected)
    top_k = dedupe_ranked(retrieved)[:k]
    return sum(1 for source_id in top_k if source_id in expected_set) / k


def mrr(expected: Sequence[str], retrieved: Sequence[str]) -> float:
    """1 / rank of the highest-ranked retrieved Source_ID in expected, else 0 (Req 7.3)."""
    expected_set = set(expected)
    for rank, source_id in enumerate(dedupe_ranked(retrieved), start=1):
        if source_id in expected_set:
            return 1.0 / rank
    return 0.0


def aggregate(inputs: Sequence[RetrievalItemInput], k: int) -> RetrievalAggregates:
    """Compute per-item Retrieval_Metrics and arithmetic-mean aggregates (Req 7.4, 7.6, 7.8).

    Applicable items are those with a non-empty expected Source_ID list that
    were not recorded as failed; inapplicable items are marked not-computed
    and excluded from every aggregate. Means are reported overall, by
    category, and by language over the applicable items.

    Raises:
        ValueError: `k` < 1.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")

    per_item: list[ItemRetrievalMetrics] = []
    applicable: list[tuple[RetrievalItemInput, ItemRetrievalMetrics]] = []
    for item in inputs:
        if item.failed or not item.expected_source_ids:
            per_item.append(ItemRetrievalMetrics(item_id=item.item_id, computed=False))
            continue
        metrics = ItemRetrievalMetrics(
            item_id=item.item_id,
            computed=True,
            recall_at_k=recall_at_k(item.expected_source_ids, item.retrieved_source_ids, k),
            precision_at_k=precision_at_k(
                item.expected_source_ids, item.retrieved_source_ids, k
            ),
            mrr=mrr(item.expected_source_ids, item.retrieved_source_ids),
        )
        per_item.append(metrics)
        applicable.append((item, metrics))

    by_category: dict[str, MetricMeans] = {}
    by_language: dict[str, MetricMeans] = {}
    for category in sorted({item.category for item, _ in applicable}):
        by_category[category] = _means(
            [m for item, m in applicable if item.category == category]
        )
    for language in sorted({item.language for item, _ in applicable}):
        by_language[language] = _means(
            [m for item, m in applicable if item.language == language]
        )

    return RetrievalAggregates(
        per_item=tuple(per_item),
        overall=_means([m for _, m in applicable]) if applicable else None,
        by_category=by_category,
        by_language=by_language,
    )


def _means(metrics: list[ItemRetrievalMetrics]) -> MetricMeans:
    """Arithmetic mean of each metric over a non-empty group of computed items."""
    count = len(metrics)
    return MetricMeans(
        recall_at_k=sum(m.recall_at_k for m in metrics) / count,  # type: ignore[misc]
        precision_at_k=sum(m.precision_at_k for m in metrics) / count,  # type: ignore[misc]
        mrr=sum(m.mrr for m in metrics) / count,  # type: ignore[misc]
        item_count=count,
    )
