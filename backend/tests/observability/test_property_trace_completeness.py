"""Property 3: Trace completeness for successful requests.

*For any* successfully completed chat request, the assembled Trace contains
the Request_ID, query text, session identifier, a UTC receipt timestamp, the
schema version field, TTFT, and total latency.

**Validates: Requirements 2.1, 2.4, 2.7**

Pure in-memory: arbitrary successful request recordings are replayed against
`TraceContext` and the frozen `Trace` is checked — no AWS calls, no patching.
"""
# Feature: rag-evaluation-observability, Property 3: Trace completeness for successful requests
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from src.observability.models import SCHEMA_VERSION, CostEstimate
from src.observability.trace_context import TraceContext


@dataclass(frozen=True)
class FakeChunk:
    """Mirrors the RetrievedChunk attributes record_retrieval reads."""

    citation: str
    score: float


# --------------------------------------------------------------------------- #
# Strategies: one arbitrary *successful* request recording
# --------------------------------------------------------------------------- #

# Queries and answers include Arabic, Latin, and arbitrary printable unicode.
text_content = st.text(min_size=1, max_size=200)

chunk = st.builds(
    FakeChunk,
    citation=st.text(min_size=1, max_size=60),
    score=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
)

retrieval_call = st.tuples(
    st.lists(chunk, max_size=8),  # zero chunks is a valid retrieval result
    st.integers(min_value=0, max_value=60_000),  # latency_ms
)

cost = st.one_of(
    st.builds(
        CostEstimate,
        computed=st.just(True),
        usd=st.floats(min_value=0, max_value=100, allow_nan=False),
    ),
    st.builds(
        CostEstimate,
        computed=st.just(False),
        reason=st.sampled_from(["missing_token_counts", "no_pricing_for_model"]),
    ),
)

success_recording = st.fixed_dictionaries(
    {
        "query": text_content,
        "session_id": st.text(min_size=1, max_size=64),
        "model_id": st.text(min_size=1, max_size=64),
        "retrieval_calls": st.lists(retrieval_call, max_size=4),
        "prompt": text_content,
        "input_tokens": st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000)),
        "output_tokens": st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000)),
        "answer": text_content,
        "cost": cost,
        # A successful stream may deliver TTFT marks more than once (only the
        # first token counts) but always at least once.
        "first_token_marks": st.integers(min_value=1, max_value=3),
    }
)


def replay_success(rec: dict) -> tuple[TraceContext, "object"]:
    """Drive TraceContext through one successful request and freeze the Trace."""
    ctx = TraceContext(
        query=rec["query"], session_id=rec["session_id"], model_id=rec["model_id"]
    )
    for chunks, latency_ms in rec["retrieval_calls"]:
        ctx.record_retrieval(chunks, latency_ms=latency_ms)
    ctx.record_prompt(rec["prompt"])
    for _ in range(rec["first_token_marks"]):
        ctx.mark_first_token()
    ctx.record_usage(rec["input_tokens"], rec["output_tokens"])
    ctx.record_response(rec["answer"])
    # Success: no record_failure ever called.
    return ctx, ctx.build_trace(rec["cost"])


# --------------------------------------------------------------------------- #
# Property 3
# --------------------------------------------------------------------------- #


class TestProperty3TraceCompletenessOnSuccess:
    @settings(max_examples=100)
    @given(rec=success_recording)
    def test_successful_trace_contains_all_identity_and_timing_fields(self, rec):
        """The built Trace carries request_id, query, session_id, UTC
        received_at, ttft_ms, total_latency_ms, and schema_version 1
        (Req 2.1, 2.4, 2.7)."""
        ctx, trace = replay_success(rec)

        # Request_ID: present, matches the context's, and is a valid uuid4.
        assert trace.request_id == ctx.request_id
        assert uuid.UUID(trace.request_id).version == 4

        # Identity fields survive verbatim (Req 2.1).
        assert trace.query == rec["query"]
        assert trace.session_id == rec["session_id"]

        # Receipt timestamp: UTC ISO-8601 with Z suffix, equal to the
        # instant captured at construction (Req 2.1).
        assert trace.received_at.endswith("Z")
        parsed = datetime.fromisoformat(trace.received_at.replace("Z", "+00:00"))
        assert parsed.utcoffset().total_seconds() == 0
        assert parsed == ctx.received_at.replace(
            microsecond=(ctx.received_at.microsecond // 1000) * 1000
        )

        # Timing: TTFT recorded (success ⇒ at least one token streamed) and
        # total latency covers receipt through finalization (Req 2.4).
        assert trace.ttft_ms is not None
        assert isinstance(trace.ttft_ms, int) and trace.ttft_ms >= 0
        assert trace.total_latency_ms is not None
        assert isinstance(trace.total_latency_ms, int)
        assert trace.ttft_ms <= trace.total_latency_ms

        # Schema version field identifies the trace shape (Req 2.7).
        assert trace.schema_version == SCHEMA_VERSION == 1

    @settings(max_examples=100)
    @given(rec=success_recording)
    def test_serialized_trace_exposes_the_same_required_fields(self, rec):
        """The schema-version-1 JSON shape carries every required field, so
        the emitted/persisted record is as complete as the model (Req 2.7)."""
        _, trace = replay_success(rec)
        payload = trace.to_dict()

        assert payload["schema_version"] == 1
        assert payload["request_id"] == trace.request_id
        assert payload["query"] == rec["query"]
        assert payload["session_id"] == rec["session_id"]
        assert payload["received_at"] == trace.received_at
        assert payload["ttft_ms"] == trace.ttft_ms
        assert payload["total_latency_ms"] == trace.total_latency_ms
