"""Property 12: Truncation fits, flags, and preserves (design.md Correctness Properties).

*For any* Trace, applying size truncation yields a Trace whose serialized
form fits within the log-entry limit, whose fields other than final prompt
and response are byte-identical to the original, and whose truncation
indicator is set if and only if content was actually removed.

**Validates: Requirements 3.8**

Pure in-memory Hypothesis test — no AWS calls. Uses small, per-example
byte budgets (a parametrized ``TraceTruncator``) so oversized traces are
tractable to generate. Budgets are always at least the trace's floor size
(its serialized size with ``final_prompt``/``response`` emptied), since the
truncator can only shorten those two fields. Generated text mixes ASCII
with Arabic and other multi-byte characters.
"""
import json
from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from src.observability.models import (
    CostEstimate,
    RetrievalRecord,
    RetrievalResult,
    Trace,
    TraceFailure,
)
from src.observability.truncation import TraceTruncator

# Text mixing ASCII, Arabic (2-byte UTF-8), and CJK/emoji (3–4 byte UTF-8)
# so byte budgets are exercised against multi-byte content (Req 3.8).
mixed_text = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),  # ASCII
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),  # Arabic
        st.characters(min_codepoint=0x4E00, max_codepoint=0x4E2F),  # CJK
        st.sampled_from("🕌📖☪"),  # 4-byte emoji
    ),
)

short_text = mixed_text.filter(lambda s: len(s) <= 40)

# The two truncatable fields: absent, or up to a few hundred characters —
# large relative to the small budgets drawn below, so both oversized and
# already-fitting traces occur.
optional_body = st.none() | st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),
        st.sampled_from("🕌📖☪"),
    ),
    max_size=400,
)

scores = st.floats(allow_nan=False, allow_infinity=False, width=32)

retrieval_results = st.builds(RetrievalResult, source_id=short_text, score=scores)

retrieval_records = st.builds(
    RetrievalRecord,
    tool=st.sampled_from(["retrieve", "search_quran", "search_hadith"]),
    latency_ms=st.integers(min_value=0, max_value=60_000),
    results=st.lists(retrieval_results, max_size=4).map(tuple),
)

costs = st.one_of(
    st.builds(
        CostEstimate,
        computed=st.just(True),
        usd=st.floats(min_value=0, max_value=10, allow_nan=False),
    ),
    st.builds(CostEstimate, computed=st.just(False), reason=short_text),
)

failures = st.none() | st.builds(TraceFailure, step=short_text, error=short_text)

traces = st.builds(
    Trace,
    request_id=st.uuids().map(str),
    session_id=short_text,
    received_at=st.just("2026-02-11T09:15:02.412Z"),
    query=short_text,
    model_id=st.sampled_from(
        ["us.anthropic.claude-haiku-4-5-20251001-v1:0", "test-model"]
    ),
    retrieval=st.lists(retrieval_records, max_size=3).map(tuple),
    final_prompt=optional_body,
    response=optional_body,
    input_tokens=st.none() | st.integers(min_value=0, max_value=1_000_000),
    output_tokens=st.none() | st.integers(min_value=0, max_value=1_000_000),
    cost=costs,
    ttft_ms=st.none() | st.integers(min_value=0, max_value=120_000),
    total_latency_ms=st.integers(min_value=0, max_value=600_000),
    failure=failures,
    truncated=st.just(False),
)


def serialized_size(trace: Trace) -> int:
    """UTF-8 byte length of the trace's JSON form, as the sink emits it."""
    return len(json.dumps(trace.to_dict(), ensure_ascii=False).encode("utf-8"))


def floor_size(trace: Trace) -> int:
    """Serialized size with both truncatable fields emptied.

    The truncator can only shorten ``final_prompt`` and ``response``, so no
    budget below this floor is achievable; drawn budgets start here.
    """
    emptied = replace(
        trace,
        final_prompt="" if trace.final_prompt is not None else None,
        response="" if trace.response is not None else None,
    )
    return serialized_size(emptied)


@st.composite
def trace_and_budget(draw):
    """A Trace plus an achievable byte budget (floor + small slack)."""
    trace = draw(traces)
    slack = draw(st.integers(min_value=0, max_value=800))
    return trace, floor_size(trace) + slack


class TestProperty12TruncationFitsFlagsPreserves:
    @settings(max_examples=200)
    @given(case=trace_and_budget())
    def test_truncation_fits_flags_and_preserves(self, case):
        """Result fits the budget; ``truncated`` is set iff content was
        removed; every other field is byte-identical (Req 3.8)."""
        trace, max_bytes = case
        result = TraceTruncator(max_bytes=max_bytes).truncate_to_fit(trace)

        # Fits: the serialized form is within the log-entry limit.
        assert serialized_size(result) <= max_bytes

        # Flags: truncated=True exactly when content was removed.
        content_removed = (
            result.final_prompt != trace.final_prompt
            or result.response != trace.response
        )
        assert result.truncated == content_removed

        # Preserves: all fields other than final_prompt/response/truncated
        # are byte-identical to the original's serialized form.
        original, truncated = trace.to_dict(), result.to_dict()
        for key in original:
            if key in ("final_prompt", "response", "truncated"):
                continue
            assert truncated[key] == original[key], f"field {key} was modified"

        # Shortens only: surviving content is a prefix of the original,
        # and None fields stay None.
        for kept, orig in (
            (result.final_prompt, trace.final_prompt),
            (result.response, trace.response),
        ):
            if orig is None:
                assert kept is None
            else:
                assert orig.startswith(kept)

    @settings(max_examples=100)
    @given(case=trace_and_budget())
    def test_already_fitting_traces_are_returned_unchanged(self, case):
        """A trace already within budget is the same object — no cutting,
        no flag (Req 3.8)."""
        trace, max_bytes = case
        if serialized_size(trace) <= max_bytes:
            result = TraceTruncator(max_bytes=max_bytes).truncate_to_fit(trace)
            assert result is trace
            assert result.truncated is False

    @settings(max_examples=100)
    @given(trace=traces)
    def test_default_budget_admits_ordinary_traces_untouched(self, trace):
        """Under the production 250 KB default, generated traces (well under
        the limit) pass through unchanged."""
        result = TraceTruncator().truncate_to_fit(trace)
        assert result is trace
        assert result.truncated is False
