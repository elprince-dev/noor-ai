"""Property 8: Trace emission round trip (design.md Correctness Properties).

*For any* Trace (including Arabic text and unusual characters), emission
produces exactly one line of valid JSON that parses back into an
equivalent Trace.

**Validates: Requirements 3.1**

Pure in-memory Hypothesis test — no AWS calls. `CloudWatchTraceSink`
writes to stdout (Lambda routes stdout to CloudWatch Logs), so the test
captures stdout and asserts: exactly one line, valid JSON, tagged
`log_type: "trace"`, payload equal to `trace.to_dict()` field for field,
and non-ASCII text (Arabic, CJK, emoji) present literally rather than
as `\\uXXXX` escapes (`ensure_ascii=False`).
"""
import io
import json
from contextlib import redirect_stdout

from hypothesis import given, settings
from hypothesis import strategies as st

from src.observability.models import (
    CostEstimate,
    RetrievalRecord,
    RetrievalResult,
    Trace,
    TraceFailure,
)
from src.observability.sink import CloudWatchTraceSink

# Text mixing ASCII (including JSON-significant quotes/backslashes),
# Arabic, CJK, and 4-byte emoji so emission is exercised against the
# "unusual characters" the property calls out (Req 3.1).
mixed_text = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),  # ASCII
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),  # Arabic
        st.characters(min_codepoint=0x4E00, max_codepoint=0x4E2F),  # CJK
        st.sampled_from("🕌📖☪"),  # 4-byte emoji
    ),
    max_size=60,
)

optional_body = st.none() | mixed_text

scores = st.floats(allow_nan=False, allow_infinity=False, width=32)

retrieval_results = st.builds(RetrievalResult, source_id=mixed_text, score=scores)

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
    st.builds(CostEstimate, computed=st.just(False), reason=mixed_text),
)

failures = st.none() | st.builds(TraceFailure, step=mixed_text, error=mixed_text)

traces = st.builds(
    Trace,
    request_id=st.uuids().map(str),
    session_id=mixed_text,
    received_at=st.just("2026-02-11T09:15:02.412Z"),
    query=mixed_text,
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
    truncated=st.booleans(),
)


def emit_and_capture(trace: Trace) -> str:
    """Emit the trace and return everything written to stdout."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        CloudWatchTraceSink().emit(trace)
    return buffer.getvalue()


class TestProperty8TraceEmissionRoundTrip:
    @settings(max_examples=200)
    @given(trace=traces)
    def test_emission_is_one_json_line_that_round_trips(self, trace):
        """Exactly one line; parses as JSON; tagged log_type "trace";
        payload round-trips every trace field (Req 3.1)."""
        out = emit_and_capture(trace)

        # Exactly one line: a single trailing newline, none embedded.
        assert out.endswith("\n")
        lines = out.splitlines()
        assert len(lines) == 1, f"expected exactly one log line, got {len(lines)}"

        record = json.loads(lines[0])
        assert record["log_type"] == "trace"

        # Round trip: the parsed payload equals the trace's serialized
        # form — every field survives emission unchanged.
        assert record == {"log_type": "trace", **trace.to_dict()}

    @settings(max_examples=100)
    @given(trace=traces)
    def test_non_ascii_text_is_emitted_unescaped(self, trace):
        """ensure_ascii=False: every non-ASCII character in the trace
        (Arabic, CJK, emoji) appears literally in the log line, never as
        a \\uXXXX escape (Req 3.1)."""
        raw = emit_and_capture(trace)

        text_fields = [
            trace.session_id,
            trace.query,
            trace.final_prompt or "",
            trace.response or "",
        ]
        if trace.failure is not None:
            text_fields += [trace.failure.step, trace.failure.error]
        if trace.cost.reason is not None:
            text_fields.append(trace.cost.reason)
        for record in trace.retrieval:
            text_fields += [result.source_id for result in record.results]

        non_ascii = {ch for text in text_fields for ch in text if ord(ch) > 0x7E}
        for ch in non_ascii:
            assert ch in raw, f"non-ASCII char {ch!r} (U+{ord(ch):04X}) was escaped"
