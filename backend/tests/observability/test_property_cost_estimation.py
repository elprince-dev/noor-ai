"""Property 6: Cost estimation correctness (design.md Correctness Properties).

*For any* combination of input token count, output token count (each possibly
unavailable), and model identifier (possibly without configured pricing), the
cost estimate equals `input/1000 × price_in + output/1000 × price_out` when
both counts and pricing are available, and is marked not-computed (never zero
or substituted) when any input is missing.

**Validates: Requirements 2.5, 2.8, 2.9**

Pure in-memory Hypothesis test — no AWS, no monkeypatching. Pricing tables
are injected via the `CostEstimator` constructor with arbitrary generated
entries; lookup matches a pricing key as a substring of the model ID.
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.observability.cost import CostEstimator
from src.observability.models import ModelPricing

# Token counts: realistic non-negative ints, or None (unavailable — Req 2.8).
token_counts = st.integers(min_value=0, max_value=10_000_000)
maybe_token_counts = st.none() | token_counts

# Per-1K prices: finite non-negative USD amounts.
prices = st.floats(
    min_value=0, max_value=1_000, allow_nan=False, allow_infinity=False
)
pricings = st.builds(ModelPricing, input_per_1k=prices, output_per_1k=prices)

# Pricing keys that CAN match: built from the model-ID alphabet.
matchable_keys = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-", min_size=1, max_size=30
)

# Pricing keys that can NEVER match: every key carries "§", a character we
# never put in generated model IDs, so no substring match is possible.
unmatchable_keys = matchable_keys.map(lambda k: f"§{k}")

# Model-ID fragments (prefix/suffix around an embedded pricing key), e.g.
# cross-region prefixes like "us." — same alphabet, no "§".
id_fragments = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789.:-", max_size=20
)

unmatchable_tables = st.dictionaries(
    unmatchable_keys, pricings, min_size=0, max_size=5
)


class TestProperty6CostEstimationCorrectness:
    @settings(max_examples=150)
    @given(
        input_tokens=token_counts,
        output_tokens=token_counts,
        key=matchable_keys,
        pricing=pricings,
        prefix=id_fragments,
        suffix=id_fragments,
        other_entries=unmatchable_tables,
    )
    def test_formula_when_counts_and_pricing_available(
        self, input_tokens, output_tokens, key, pricing, prefix, suffix, other_entries
    ):
        """Both counts present and a pricing key a substring of the model ID
        (including with cross-region-style prefixes) ⇒ computed=True and
        usd == (input/1000)·price_in + (output/1000)·price_out (Req 2.5)."""
        # Exactly one entry can match: all others contain "§", which the
        # generated model ID never does.
        table = {**other_entries, key: pricing}
        model_id = f"{prefix}{key}{suffix}"

        estimate = CostEstimator(table).estimate(input_tokens, output_tokens, model_id)

        assert estimate.computed is True
        assert estimate.reason is None
        expected = (
            (input_tokens / 1000) * pricing.input_per_1k
            + (output_tokens / 1000) * pricing.output_per_1k
        )
        assert estimate.usd == pytest.approx(expected)

    @settings(max_examples=150)
    @given(
        input_tokens=maybe_token_counts,
        output_tokens=maybe_token_counts,
        key=matchable_keys,
        pricing=pricings,
        prefix=id_fragments,
        suffix=id_fragments,
    )
    def test_missing_token_count_is_not_computed_regardless_of_pricing(
        self, input_tokens, output_tokens, key, pricing, prefix, suffix
    ):
        """Either token count None ⇒ not-computed with a reason and no USD
        value, even when pricing for the model exists (Req 2.8)."""
        if input_tokens is not None and output_tokens is not None:
            input_tokens = None  # ensure at least one count is unavailable

        table = {key: pricing}
        model_id = f"{prefix}{key}{suffix}"

        estimate = CostEstimator(table).estimate(input_tokens, output_tokens, model_id)

        assert estimate.computed is False
        assert estimate.usd is None  # never zero or substituted
        assert estimate.reason  # explicit reason carried

    @settings(max_examples=150)
    @given(
        input_tokens=token_counts,
        output_tokens=token_counts,
        table=unmatchable_tables,
        model_id=id_fragments,
    )
    def test_no_matching_pricing_is_not_computed(
        self, input_tokens, output_tokens, table, model_id
    ):
        """No pricing key a substring of the model ID ⇒ not-computed with a
        reason and no USD value, never zero or substituted (Req 2.9)."""
        estimate = CostEstimator(table).estimate(input_tokens, output_tokens, model_id)

        assert estimate.computed is False
        assert estimate.usd is None  # never zero or substituted
        assert estimate.reason  # explicit reason carried

    @settings(max_examples=150)
    @given(
        input_tokens=maybe_token_counts,
        output_tokens=maybe_token_counts,
        table=st.dictionaries(
            matchable_keys | unmatchable_keys, pricings, min_size=0, max_size=5
        ),
        model_id=id_fragments,
    )
    def test_not_computed_always_carries_reason_and_no_usd(
        self, input_tokens, output_tokens, table, model_id
    ):
        """Across arbitrary inputs: every not-computed estimate carries a
        reason and usd=None; every computed estimate carries a float USD
        value and no reason (Req 2.8, 2.9)."""
        estimate = CostEstimator(table).estimate(input_tokens, output_tokens, model_id)

        if estimate.computed:
            assert isinstance(estimate.usd, float)
            assert estimate.reason is None
        else:
            assert estimate.usd is None
            assert estimate.reason
