"""Property 20: Retrieval metric matching invariants (design.md Correctness
Properties).

*For any* retrieval metric inputs, injecting duplicate retrieved Source_IDs
below their first occurrence never changes any metric value; near-miss ID
strings (case, whitespace, or digit perturbations) never count as matches;
and recomputing on identical inputs always yields identical values.

**Validates: Requirements 7.5, 7.7**

Pure Hypothesis test over the metric functions in
`evals.metrics.retrieval` — no AWS calls, no I/O, no LLM. Three invariants:

(a) duplicate collapse (Req 7.5) — metrics on a retrieved list containing
    duplicates equal metrics on its deduped form, and injecting extra copies
    of already-present IDs at any position below their first occurrence
    changes nothing;
(b) exact-match only (Req 7.5) — near-miss variants of the expected IDs
    (case changes, added whitespace, off-by-one digits) never match: when
    only near-misses are retrieved, recall, precision, and MRR are all 0;
(c) determinism (Req 7.7) — computing every metric twice on the same inputs
    yields identical values.
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.metrics.retrieval import (
    RetrievalItemInput,
    aggregate,
    dedupe_ranked,
    mrr,
    precision_at_k,
    recall_at_k,
)

# -- strategies ---------------------------------------------------------------

# Expected Source_IDs following the corpus citation grammar, so the near-miss
# perturbations (case, whitespace, digits) operate on realistic ID shapes.
source_ids = st.one_of(
    st.tuples(st.integers(1, 114), st.integers(1, 286)).map(
        lambda t: f"Quran {t[0]}:{t[1]}"
    ),
    st.integers(1, 7563).map(lambda n: f"Sahih al-Bukhari {n}"),
    st.integers(1, 3033).map(lambda n: f"Sahih Muslim {n}"),
)

expected_lists = st.lists(source_ids, min_size=1, max_size=5, unique=True)

ks = st.integers(min_value=1, max_value=10)


def _near_misses(source_id: str) -> list[str]:
    """Near-miss variants of a Source_ID: case, whitespace, digit off-by-one."""
    return [
        source_id.upper(),
        source_id.lower(),
        source_id.swapcase(),
        f" {source_id}",
        f"{source_id} ",
        source_id.replace(" ", "  ", 1),
        # off-by-one on the trailing number ("Quran 2:255" -> "Quran 2:256")
        _bump_last_digit_run(source_id),
    ]


def _bump_last_digit_run(source_id: str) -> str:
    """Increment the trailing integer of a Source_ID by one."""
    i = len(source_id)
    while i > 0 and source_id[i - 1].isdigit():
        i -= 1
    return source_id[:i] + str(int(source_id[i:]) + 1)


@st.composite
def matching_inputs(draw):
    """(expected, retrieved, k) where retrieved mixes hits, misses, and dupes."""
    expected = draw(expected_lists)
    # Retrieved: expected hits, plain misses, and near-misses of expected IDs,
    # in arbitrary rank order, possibly with duplicates already present.
    pool = (
        expected
        + [m for sid in expected for m in _near_misses(sid)]
        + draw(st.lists(source_ids, max_size=3))
    )
    retrieved = draw(st.lists(st.sampled_from(pool), min_size=0, max_size=12))
    k = draw(ks)
    return expected, retrieved, k


@st.composite
def duplicate_injections(draw):
    """(expected, retrieved, injected, k): `injected` re-inserts copies of
    already-present retrieved IDs strictly below their first occurrence."""
    expected, retrieved, k = draw(matching_inputs())
    injected = list(retrieved)
    if retrieved:
        n_copies = draw(st.integers(min_value=1, max_value=4))
        for _ in range(n_copies):
            sid = draw(st.sampled_from(retrieved))
            # Any insertion position strictly after the current first
            # occurrence keeps the highest rank of `sid` unchanged (the
            # first occurrence must be located in `injected`, since earlier
            # insertions shift positions).
            first = injected.index(sid)
            pos = draw(st.integers(min_value=first + 1, max_value=len(injected)))
            injected.insert(pos, sid)
    return expected, retrieved, injected, k


# -- the property --------------------------------------------------------------


class TestProperty20RetrievalMetricMatchingInvariants:
    @settings(max_examples=100)
    @given(data=duplicate_injections())
    def test_duplicates_count_once_at_their_highest_rank(self, data):
        """Req 7.5: duplicate retrieved IDs collapse to their highest rank."""
        expected, retrieved, injected, k = data

        # Injecting copies below the first occurrence changes no metric.
        assert recall_at_k(expected, injected, k) == recall_at_k(expected, retrieved, k)
        assert precision_at_k(expected, injected, k) == precision_at_k(
            expected, retrieved, k
        )
        assert mrr(expected, injected) == mrr(expected, retrieved)

        # Metrics on any list with duplicates equal metrics on its deduped
        # form — duplicates never contribute a second occurrence.
        deduped = dedupe_ranked(injected)
        assert len(deduped) == len(set(deduped))  # dedupe_ranked truly dedupes
        assert deduped == dedupe_ranked(retrieved)  # first occurrences preserved
        assert recall_at_k(expected, injected, k) == recall_at_k(expected, deduped, k)
        assert precision_at_k(expected, injected, k) == precision_at_k(
            expected, deduped, k
        )
        assert mrr(expected, injected) == mrr(expected, deduped)

    @settings(max_examples=100)
    @given(expected=expected_lists, k=ks, data=st.data())
    def test_near_miss_ids_never_match(self, expected, k, data):
        """Req 7.5: exact string equality only — case, whitespace, and digit
        perturbations of expected IDs never count as matches."""
        expected_set = set(expected)
        near_misses = [
            m
            for sid in expected
            for m in _near_misses(sid)
            if m != sid and m not in expected_set
        ]
        retrieved = data.draw(
            st.lists(st.sampled_from(near_misses), min_size=1, max_size=12)
        )

        assert recall_at_k(expected, retrieved, k) == 0.0
        assert precision_at_k(expected, retrieved, k) == 0.0
        assert mrr(expected, retrieved) == 0.0

    @settings(max_examples=100)
    @given(data=matching_inputs())
    def test_recomputation_is_deterministic(self, data):
        """Req 7.7: identical inputs always yield identical metric values,
        for the individual metrics and for the full aggregation."""
        expected, retrieved, k = data

        assert recall_at_k(expected, retrieved, k) == recall_at_k(expected, retrieved, k)
        assert precision_at_k(expected, retrieved, k) == precision_at_k(
            expected, retrieved, k
        )
        assert mrr(expected, retrieved) == mrr(expected, retrieved)
        assert dedupe_ranked(retrieved) == dedupe_ranked(retrieved)

        item = RetrievalItemInput(
            item_id="item-000",
            category="direct_lookup",
            language="en",
            expected_source_ids=tuple(expected),
            retrieved_source_ids=tuple(retrieved),
        )
        assert aggregate([item], k) == aggregate([item], k)
