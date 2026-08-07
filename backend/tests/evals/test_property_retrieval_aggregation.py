"""Property 21: Retrieval aggregation over applicable items only (design.md).

*For any* collection of per-item results with mixed categories, languages,
empty-expected items, and failed items, aggregate Retrieval_Metrics equal the
arithmetic mean over exactly the applicable items (non-empty expected
Source_IDs and not failed) — overall, per category, and per language — with
inapplicable items marked not-computed.

**Validates: Requirements 7.4, 7.6, 7.8**

Pure in-memory Hypothesis test — no AWS calls, no I/O. `aggregate` is a pure
module-level function over `RetrievalItemInput`, so the property is checked
against an independent brute-force oracle: per-item recall@k, precision@k,
and MRR are recomputed from their set-based definitions, and group means are
re-derived by summing over the hand-selected applicable items of each group.
An empty applicable set must yield `overall=None` and empty breakdown maps —
never a division by zero.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.metrics.retrieval import (
    MetricMeans,
    RetrievalItemInput,
    aggregate,
)

CATEGORIES = ("direct_lookup", "paraphrase", "cross_lingual", "out_of_corpus")
LANGUAGES = ("ar", "en")

# Small Source_ID pool so expected and retrieved lists overlap often.
SOURCE_IDS = tuple(f"Quran {s}:{v}" for s in (1, 2, 3) for v in (1, 2, 3, 4)) + (
    "Sahih al-Bukhari 1",
    "Sahih Muslim 7",
)

# -- strategies ----------------------------------------------------------------

source_id = st.sampled_from(SOURCE_IDS)


@st.composite
def item_inputs(draw) -> RetrievalItemInput:
    """One per-item result: expected may be empty (out-of-corpus style),
    retrieved may contain duplicates and be shorter or longer than k,
    and failed is drawn independently of everything else."""
    expected = tuple(
        draw(st.lists(source_id, unique=True, max_size=5))
    )
    retrieved = tuple(draw(st.lists(source_id, max_size=8)))
    return RetrievalItemInput(
        item_id=draw(st.uuids()).hex,
        category=draw(st.sampled_from(CATEGORIES)),
        language=draw(st.sampled_from(LANGUAGES)),
        expected_source_ids=expected,
        retrieved_source_ids=retrieved,
        failed=draw(st.booleans()),
    )


input_lists = st.lists(item_inputs(), max_size=15)
ks = st.integers(min_value=1, max_value=8)

# -- brute-force oracle --------------------------------------------------------


def ref_dedupe(retrieved: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in retrieved:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def ref_recall(item: RetrievalItemInput, k: int) -> float:
    expected = set(item.expected_source_ids)
    top_k = set(ref_dedupe(item.retrieved_source_ids)[:k])
    return len(expected & top_k) / len(expected)


def ref_precision(item: RetrievalItemInput, k: int) -> float:
    expected = set(item.expected_source_ids)
    top_k = ref_dedupe(item.retrieved_source_ids)[:k]
    return sum(1 for s in top_k if s in expected) / k


def ref_mrr(item: RetrievalItemInput) -> float:
    expected = set(item.expected_source_ids)
    for rank, s in enumerate(ref_dedupe(item.retrieved_source_ids), start=1):
        if s in expected:
            return 1.0 / rank
    return 0.0


def is_applicable(item: RetrievalItemInput) -> bool:
    """Req 7.4, 7.6, 7.8: non-empty expected Source_IDs AND not failed."""
    return bool(item.expected_source_ids) and not item.failed


def ref_means(group: list[RetrievalItemInput], k: int) -> MetricMeans:
    """Independent recomputation of the arithmetic means over one non-empty
    group of applicable items, straight from the metric definitions."""
    n = len(group)
    return MetricMeans(
        recall_at_k=sum(ref_recall(i, k) for i in group) / n,
        precision_at_k=sum(ref_precision(i, k) for i in group) / n,
        mrr=sum(ref_mrr(i) for i in group) / n,
        item_count=n,
    )


def assert_means_match(actual: MetricMeans, expected: MetricMeans) -> None:
    assert actual.item_count == expected.item_count
    assert actual.recall_at_k == pytest.approx(expected.recall_at_k)
    assert actual.precision_at_k == pytest.approx(expected.precision_at_k)
    assert actual.mrr == pytest.approx(expected.mrr)


# -- properties ----------------------------------------------------------------


class TestProperty21RetrievalAggregationOverApplicableItems:
    @settings(max_examples=150)
    @given(inputs=input_lists, k=ks)
    def test_overall_means_match_brute_force(self, inputs, k):
        """Overall aggregates equal the arithmetic mean over exactly the
        applicable items; an empty applicable set yields None rather than
        a division by zero (Req 7.4, 7.6, 7.8)."""
        result = aggregate(inputs, k)
        applicable = [i for i in inputs if is_applicable(i)]
        if not applicable:
            assert result.overall is None
        else:
            assert_means_match(result.overall, ref_means(applicable, k))

    @settings(max_examples=150)
    @given(inputs=input_lists, k=ks)
    def test_by_category_means_match_brute_force(self, inputs, k):
        """Category breakdown contains exactly the categories with at least
        one applicable item, each averaged over the applicable items of
        that category only (Req 7.6)."""
        result = aggregate(inputs, k)
        applicable = [i for i in inputs if is_applicable(i)]
        assert set(result.by_category) == {i.category for i in applicable}
        for category, means in result.by_category.items():
            group = [i for i in applicable if i.category == category]
            assert_means_match(means, ref_means(group, k))

    @settings(max_examples=150)
    @given(inputs=input_lists, k=ks)
    def test_by_language_means_match_brute_force(self, inputs, k):
        """Language breakdown contains exactly the languages with at least
        one applicable item, each averaged over the applicable items of
        that language only (Req 7.6)."""
        result = aggregate(inputs, k)
        applicable = [i for i in inputs if is_applicable(i)]
        assert set(result.by_language) == {i.language for i in applicable}
        for language, means in result.by_language.items():
            group = [i for i in applicable if i.language == language]
            assert_means_match(means, ref_means(group, k))

    @settings(max_examples=150)
    @given(inputs=input_lists, k=ks)
    def test_inapplicable_items_marked_not_computed(self, inputs, k):
        """Items with empty expected Source_IDs or a failed record are marked
        not-computed with no metric values; every applicable item is computed
        with values matching the brute-force definitions (Req 7.4, 7.8)."""
        result = aggregate(inputs, k)
        assert len(result.per_item) == len(inputs)
        for item, metrics in zip(inputs, result.per_item):
            assert metrics.item_id == item.item_id
            if is_applicable(item):
                assert metrics.computed is True
                assert metrics.recall_at_k == pytest.approx(ref_recall(item, k))
                assert metrics.precision_at_k == pytest.approx(ref_precision(item, k))
                assert metrics.mrr == pytest.approx(ref_mrr(item))
            else:
                assert metrics.computed is False
                assert metrics.recall_at_k is None
                assert metrics.precision_at_k is None
                assert metrics.mrr is None

    @settings(max_examples=150)
    @given(inputs=input_lists, k=ks)
    def test_group_item_counts_partition_applicable_items(self, inputs, k):
        """Category and language item counts each sum to the total applicable
        count — inapplicable items are excluded from every aggregate and no
        item is counted twice within a breakdown (Req 7.4, 7.6, 7.8)."""
        result = aggregate(inputs, k)
        n_applicable = sum(1 for i in inputs if is_applicable(i))
        assert sum(m.item_count for m in result.by_category.values()) == n_applicable
        assert sum(m.item_count for m in result.by_language.values()) == n_applicable
        if result.overall is not None:
            assert result.overall.item_count == n_applicable
