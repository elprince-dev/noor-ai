"""Property 4: Retrieval recording fidelity (design.md Correctness Properties).

*For any* sequence of retrieval results (including empty results), the Trace
records the retrieved Source_IDs in their original order with their relevance
scores and the retrieval latency, recording an empty list when zero chunks
were retrieved.

**Validates: Requirements 2.2**

Pure in-memory Hypothesis test — no AWS, no monkeypatching. Chunk stand-ins
only need `.citation` and `.score`, matching what
`TraceContext.record_retrieval` reads from `RetrievedChunk`-shaped objects.
"""
from dataclasses import dataclass

from hypothesis import given, settings
from hypothesis import strategies as st

from src.observability.models import CostEstimate
from src.observability.trace_context import TraceContext

NOT_COMPUTED = CostEstimate(computed=False, reason="test")


@dataclass(frozen=True)
class FakeChunk:
    """Mirrors the RetrievedChunk attributes record_retrieval reads."""

    citation: str
    score: float


def make_ctx() -> TraceContext:
    return TraceContext(
        query="ما حكم صلاة الوتر؟", session_id="sess-1", model_id="test-model"
    )


# Citations: arbitrary text including Arabic and unusual characters — the
# recorder must preserve them exactly, not just well-formed Source_IDs.
citations = st.text(min_size=0, max_size=60)

# Scores: finite floats only (NaN breaks equality and never occurs in
# relevance scores); float32-representable via width to keep values exact.
scores = st.floats(allow_nan=False, allow_infinity=False, width=32)

chunks = st.builds(FakeChunk, citation=citations, score=scores)

# One retrieval tool call: an ordered chunk list (possibly empty), a
# non-negative latency, and a tool name.
retrieval_calls = st.tuples(
    st.lists(chunks, min_size=0, max_size=8),
    st.integers(min_value=0, max_value=60_000),
    st.sampled_from(["retrieve", "search_quran", "search_hadith"]),
)


class TestProperty4RetrievalRecordingFidelity:
    @settings(max_examples=150)
    @given(calls=st.lists(retrieval_calls, min_size=0, max_size=6))
    def test_arbitrary_call_sequences_are_recorded_exactly(self, calls):
        """Every retrieval call appears in the Trace in call order, with
        Source_IDs (chunk.citation), scores, and latency preserved exactly;
        zero chunks yield an explicit empty results list (Req 2.2)."""
        ctx = make_ctx()
        for chunk_list, latency_ms, tool in calls:
            ctx.record_retrieval(chunk_list, latency_ms=latency_ms, tool=tool)

        trace = ctx.build_trace(NOT_COMPUTED)

        # One record per call, in the original call order.
        assert len(trace.retrieval) == len(calls)

        for record, (chunk_list, latency_ms, tool) in zip(trace.retrieval, calls):
            assert record.tool == tool
            assert record.latency_ms == latency_ms

            # Source_ID = chunk.citation, order and scores preserved exactly.
            assert [r.source_id for r in record.results] == [
                c.citation for c in chunk_list
            ]
            assert [r.score for r in record.results] == [c.score for c in chunk_list]

            # Zero chunks ⇒ explicit empty results list, never omitted.
            if not chunk_list:
                assert record.results == ()

    @settings(max_examples=100)
    @given(
        latency_ms=st.integers(min_value=0, max_value=60_000),
        tool=st.sampled_from(["retrieve", "search_quran", "search_hadith"]),
    )
    def test_zero_chunks_always_yield_an_explicit_empty_record(self, latency_ms, tool):
        """An empty retrieval is a first-class record carrying its latency
        and tool name with an empty results list (Req 2.2)."""
        ctx = make_ctx()
        ctx.record_retrieval([], latency_ms=latency_ms, tool=tool)
        trace = ctx.build_trace(NOT_COMPUTED)
        assert len(trace.retrieval) == 1
        record = trace.retrieval[0]
        assert record.results == ()
        assert record.latency_ms == latency_ms
        assert record.tool == tool
