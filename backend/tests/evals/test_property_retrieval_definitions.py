"""Property 19: Retrieval metric definitional correctness (design.md Correctness Properties).

*For any* expected Source_ID list, retrieved Source_ID list, and top-k,
recall@k equals |expected ∩ top-k| / |expected|, precision@k equals
|top-k ∩ expected| / k (dividing by k even when fewer than k results were
retrieved), and MRR equals the reciprocal of the rank of the first expected
hit or 0 when there is none — each verified against an independent
brute-force reference computation.

**Validates: Requirements 7.1, 7.2, 7.3**

Pure Hypothesis test over the metric functions — no I/O, no AWS calls. The
reference implementations below are deliberately naive (linear scans over
lists, no set algebra) so a shared bug with the production code is unlikely.
Retrieved lists may contain duplicates; per Req 7.5 both the production code
and the references collapse duplicates to their first (highest-rank)
occurrence before scoring, so the definitional comparison is exercised on
the same deduplicated ranking.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.metrics.retrieval import mrr, precision_at_k, recall_at_k

# -- strategies ----------------------------------------------------------------

# A small shared pool of Source_ID-like strings so expected/retrieved overlap
# is common, plus free-form text so non-matching IDs also appear.
POOL = (
    [f"Quran {s}:{v}" for s in (1, 2, 3) for v in (1, 2, 3, 4)]
    + [f"Sahih al-Bukhari {n}" for n in (1, 7, 42, 100)]
    + [f"Sahih Muslim {n}" for n in (1, 9, 55)]
)
pool_ids = st.sampled_from(POOL)
free_ids = st.text(min_size=1, max_size=20)
any_id = pool_ids | free_ids

# Expected Source_IDs: a non-empty set (recall is undefined for empty
# expected lists per Req 7.4 — those items are not computed at all).
expected_sets = st.lists(any_id, min_size=1, max_size=8, unique=True)

# Retrieved Source_IDs: rank-ordered, possibly empty, possibly with duplicates.
retrieved_lists = st.lists(any_id, min_size=0, max_size=15)

ks = st.integers(min_value=1, max_value=20)


# -- independent brute-force references ----------------------------------------


def ref_dedupe(retrieved: list[str]) -> list[str]:
    """Keep only the first occurrence of each ID, preserving rank order."""
    out: list[str] = []
    for source_id in retrieved:
        if source_id not in out:
            out.append(source_id)
    return out


def ref_recall_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    """|expected ∩ top-k retrieved| / |expected| by linear scan (Req 7.1)."""
    top_k = ref_dedupe(retrieved)[:k]
    hits = 0
    for expected_id in expected:  # expected is unique by construction
        if expected_id in top_k:
            hits += 1
    return hits / len(expected)


def ref_precision_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    """|top-k retrieved ∩ expected| / k — always dividing by k (Req 7.2)."""
    top_k = ref_dedupe(retrieved)[:k]
    hits = 0
    for retrieved_id in top_k:
        if retrieved_id in expected:
            hits += 1
    return hits / k


def ref_mrr(expected: list[str], retrieved: list[str]) -> float:
    """1 / rank of the first retrieved ID that is expected, else 0.0 (Req 7.3)."""
    for rank, source_id in enumerate(ref_dedupe(retrieved), start=1):
        if source_id in expected:
            return 1.0 / rank
    return 0.0


# -- properties ------------------------------------------------------------------


class TestProperty19RetrievalMetricDefinitionalCorrectness:
    @settings(max_examples=200)
    @given(expected=expected_sets, retrieved=retrieved_lists, k=ks)
    def test_recall_at_k_matches_brute_force_definition(self, expected, retrieved, k):
        """recall@k == |expected ∩ top-k retrieved| / |expected| (Req 7.1)."""
        assert recall_at_k(expected, retrieved, k) == ref_recall_at_k(
            expected, retrieved, k
        )

    @settings(max_examples=200)
    @given(expected=expected_sets, retrieved=retrieved_lists, k=ks)
    def test_precision_at_k_matches_brute_force_definition(self, expected, retrieved, k):
        """precision@k == |top-k retrieved ∩ expected| / k, dividing by k even
        when fewer than k results were retrieved (Req 7.2)."""
        assert precision_at_k(expected, retrieved, k) == ref_precision_at_k(
            expected, retrieved, k
        )

    @settings(max_examples=200)
    @given(expected=expected_sets, retrieved=retrieved_lists, k=ks)
    def test_precision_denominator_is_k_when_fewer_retrieved(
        self, expected, retrieved, k
    ):
        """When fewer than k distinct IDs are retrieved, the denominator is
        still k: precision@k is bounded by |deduped retrieved| / k (Req 7.2)."""
        deduped = ref_dedupe(retrieved)
        if len(deduped) < k:
            assert precision_at_k(expected, retrieved, k) <= len(deduped) / k

    @settings(max_examples=200)
    @given(expected=expected_sets, retrieved=retrieved_lists)
    def test_mrr_matches_brute_force_definition(self, expected, retrieved):
        """MRR == 1 / rank of the first expected hit, 0 when none (Req 7.3)."""
        assert mrr(expected, retrieved) == ref_mrr(expected, retrieved)

    @settings(max_examples=100)
    @given(expected=expected_sets, retrieved=retrieved_lists)
    def test_mrr_is_zero_iff_no_expected_id_retrieved(self, expected, retrieved):
        """MRR is exactly 0.0 precisely when no retrieved ID is expected (Req 7.3)."""
        any_hit = any(source_id in expected for source_id in retrieved)
        if any_hit:
            assert mrr(expected, retrieved) > 0.0
        else:
            assert mrr(expected, retrieved) == 0.0
