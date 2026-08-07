"""Property 25: Generation pass-rate aggregation (design.md Correctness Properties).

*For any* multiset of per-item verdicts (pass, fail, error) across metrics,
categories, and languages, each reported pass rate equals pass / (pass + fail)
with error verdicts excluded from numerator and denominator, and the reported
error count per metric equals the number of error verdicts.

**Validates: Requirements 8.7**

Pure in-memory Hypothesis test — no AWS calls. `aggregate` is a pure
module-level function over `ItemGenerationScores`, so the property is checked
against an independent brute-force recomputation: for every group (overall,
each category, each language) and every rubric, the pass/fail/error counts
are re-counted by hand over the computed items in that group and the pass
rate re-derived from those counts. Not-computed items (failed during
execution, Req 8.9) must be excluded from every group entirely.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from evals.metrics.generation import (
    ERROR,
    FAIL,
    PASS,
    ItemGenerationScores,
    MetricPassRate,
    RubricOutcome,
    aggregate,
)

CATEGORIES = ("direct_lookup", "paraphrase", "cross_lingual", "out_of_corpus")
LANGUAGES = ("ar", "en")
RUBRIC_NAMES = ("faithfulness", "citation_accuracy", "answer_relevancy", "abstention")

# -- strategies ----------------------------------------------------------------

rationales = st.text(max_size=40)

rubric_outcomes = st.builds(
    RubricOutcome,
    rubric=st.sampled_from(RUBRIC_NAMES),
    outcome=st.sampled_from([PASS, FAIL, ERROR]),
    rationale=rationales,
)


@st.composite
def item_scores(draw) -> ItemGenerationScores:
    """One per-item score record: computed items carry an arbitrary outcome
    mix (including repeated rubrics — aggregation is over the multiset);
    not-computed items carry an empty outcomes tuple per the model contract."""
    computed = draw(st.booleans())
    outcomes: tuple[RubricOutcome, ...] = ()
    if computed:
        outcomes = tuple(draw(st.lists(rubric_outcomes, max_size=6)))
    return ItemGenerationScores(
        item_id=draw(st.uuids()).hex,
        category=draw(st.sampled_from(CATEGORIES)),
        language=draw(st.sampled_from(LANGUAGES)),
        computed=computed,
        outcomes=outcomes,
    )


score_lists = st.lists(item_scores(), max_size=12)

# -- brute-force oracle --------------------------------------------------------


def brute_force_rates(group: list[ItemGenerationScores]) -> dict[str, MetricPassRate]:
    """Independent recomputation: manual counts per rubric over one group of
    computed items, pass rate derived directly from the definition."""
    rates: dict[str, MetricPassRate] = {}
    all_outcomes = [o for s in group for o in s.outcomes]
    for rubric in {o.rubric for o in all_outcomes}:
        of_rubric = [o for o in all_outcomes if o.rubric == rubric]
        n_pass = sum(1 for o in of_rubric if o.outcome == PASS)
        n_fail = sum(1 for o in of_rubric if o.outcome == FAIL)
        n_error = sum(1 for o in of_rubric if o.outcome == ERROR)
        rates[rubric] = MetricPassRate(
            pass_rate=n_pass / (n_pass + n_fail) if (n_pass + n_fail) else None,
            pass_count=n_pass,
            fail_count=n_fail,
            error_count=n_error,
        )
    return rates


def assert_rates_match(
    actual: dict[str, MetricPassRate], expected: dict[str, MetricPassRate]
) -> None:
    """Counts must match exactly; pass rates via approx (or both None)."""
    assert set(actual) == set(expected)
    for rubric, want in expected.items():
        got = actual[rubric]
        assert got.pass_count == want.pass_count
        assert got.fail_count == want.fail_count
        assert got.error_count == want.error_count
        if want.pass_rate is None:
            assert got.pass_rate is None
        else:
            assert got.pass_rate == pytest.approx(want.pass_rate)


# -- properties ----------------------------------------------------------------


class TestProperty25GenerationPassRateAggregation:
    @settings(max_examples=150)
    @given(scores=score_lists)
    def test_overall_rates_match_brute_force(self, scores):
        """Overall per-rubric counts and pass rates equal a manual recount
        over all computed items; pass rate = pass / (pass + fail) with
        errors excluded, None when the denominator is zero (Req 8.7)."""
        result = aggregate(scores)
        computed = [s for s in scores if s.computed]
        assert_rates_match(result.overall, brute_force_rates(computed))

    @settings(max_examples=150)
    @given(scores=score_lists)
    def test_by_category_rates_match_brute_force(self, scores):
        """Each category group contains exactly the categories of computed
        items, and its per-rubric rates equal a manual recount over the
        computed items of that category (Req 8.7, 8.9)."""
        result = aggregate(scores)
        computed = [s for s in scores if s.computed]
        assert set(result.by_category) == {s.category for s in computed}
        for category, rates in result.by_category.items():
            group = [s for s in computed if s.category == category]
            assert_rates_match(rates, brute_force_rates(group))

    @settings(max_examples=150)
    @given(scores=score_lists)
    def test_by_language_rates_match_brute_force(self, scores):
        """Each language group contains exactly the languages of computed
        items, and its per-rubric rates equal a manual recount over the
        computed items of that language (Req 8.7, 8.9)."""
        result = aggregate(scores)
        computed = [s for s in scores if s.computed]
        assert set(result.by_language) == {s.language for s in computed}
        for language, rates in result.by_language.items():
            group = [s for s in computed if s.language == language]
            assert_rates_match(rates, brute_force_rates(group))

    @settings(max_examples=150)
    @given(scores=score_lists)
    def test_rubric_appears_iff_some_computed_item_has_outcome(self, scores):
        """A rubric appears in a group's mapping iff at least one computed
        item in that group carries an outcome for it — not-computed items
        never introduce rubrics or groups (Req 8.7, 8.9)."""
        result = aggregate(scores)
        computed = [s for s in scores if s.computed]

        expected_overall = {o.rubric for s in computed for o in s.outcomes}
        assert set(result.overall) == expected_overall

        for category, rates in result.by_category.items():
            expected = {
                o.rubric
                for s in computed
                if s.category == category
                for o in s.outcomes
            }
            assert set(rates) == expected
        for language, rates in result.by_language.items():
            expected = {
                o.rubric
                for s in computed
                if s.language == language
                for o in s.outcomes
            }
            assert set(rates) == expected

    @settings(max_examples=150)
    @given(scores=score_lists)
    def test_per_item_preserved_verbatim(self, scores):
        """`per_item` carries every input score record — computed or not —
        unchanged and in order (Req 8.7)."""
        result = aggregate(scores)
        assert result.per_item == tuple(scores)
