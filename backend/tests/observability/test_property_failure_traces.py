"""Property 7: Failure traces are partial, attributed, emitted, and never persisted (design.md).

*For any* chat request with a failure injected at any pipeline point, the
Trace records the failing step name and error message, retains all fields
captured before the failure, marks TTFT as not recorded when the failure
precedes the first token, is emitted to logs, is **not** persisted to the
Trace_Store, and the error response delivered to the client includes the
Request_ID.

**Validates: Requirements 1.5, 2.6, 2.10, 3.3**

Pure in-memory Hypothesis tests — no AWS calls. Arbitrary *partial* request
recordings that end in a failure at an arbitrary step are replayed against a
real `TraceContext`, then finalized through a real enabled `TraceFinalizer`
wired with in-memory fakes. The failure trace must (a) carry the failing
step name and error message verbatim (Req 2.6); (b) retain every field
recorded before the failure — retrieval records, prompt, token counts,
partial response (Req 2.6); (c) mark TTFT as not recorded when the failure
preceded the first streamed token (Req 2.10); (d) still be emitted via the
sink but never persisted — the repository sees no put at all (Req 3.3);
and (e) carry the request's Request_ID so the client-facing error response
links back to the trace (Req 1.5).

Recording building blocks (`text_content`, `retrieval_call`) are reused
from the Property 3 completeness test; the replay driver from the
Property 11 disabled-tracing test; the in-memory repository fake from the
Property 9 store test.
"""
# Feature: rag-evaluation-observability, Property 7: Failure traces are partial, attributed, emitted, and never persisted
import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from src.observability.cost import CostEstimator
from src.observability.finalizer import TraceFinalizer
from src.observability.models import Trace
from src.observability.trace_context import TraceContext
from src.observability.truncation import TraceTruncator
from tests.observability.test_property_disabled_tracing import (
    RecordingSink,
    replay,
)
from tests.observability.test_property_trace_completeness import (
    retrieval_call,
    text_content,
)
from tests.observability.test_property_trace_store import InMemoryTraceRepository


class RecordingRepository(InMemoryTraceRepository):
    """In-memory repository that additionally records every `put` call,
    so "never persisted" is provable as zero puts — not merely an absent
    key after the fact."""

    def __init__(self) -> None:
        super().__init__()
        self.put_calls: list[Trace] = []

    def put(self, trace: Trace) -> None:
        self.put_calls.append(trace)
        super().put(trace)


# --------------------------------------------------------------------------- #
# Strategy: one arbitrary partial recording ending in a failure
# --------------------------------------------------------------------------- #

# The failure may strike at a known pipeline step or any arbitrary step name.
failing_step = st.one_of(
    st.sampled_from(["retrieval", "generation", "streaming"]),
    st.text(min_size=1, max_size=40),
)

# Same shape as the Property 11 recording, but the failure is mandatory:
# every generated request ends with record_failure(step, error). All other
# fields are optional/partial — whatever happened before the failure.
failure_recording = st.fixed_dictionaries(
    {
        "query": text_content,
        "session_id": st.text(min_size=1, max_size=64),
        "model_id": st.text(min_size=1, max_size=64),
        "retrieval_calls": st.lists(retrieval_call, max_size=4),
        "prompt": st.none() | text_content,
        "input_tokens": st.none() | st.integers(min_value=0, max_value=1_000_000),
        "output_tokens": st.none() | st.integers(min_value=0, max_value=1_000_000),
        # 0 marks ⇒ the failure struck before any token was streamed.
        "first_token_marks": st.integers(min_value=0, max_value=3),
        "answer": st.none() | text_content,
        "failure": st.tuples(failing_step, text_content),
    }
)


def finalize_failed(rec: dict) -> tuple[TraceContext, RecordingSink, RecordingRepository]:
    """Replay one failed request and finalize it through a real enabled
    TraceFinalizer wired with in-memory fakes."""
    ctx = replay(rec)
    sink = RecordingSink()
    repository = RecordingRepository()
    finalizer = TraceFinalizer(
        estimator=CostEstimator(pricing={}),
        truncator=TraceTruncator(),
        sink=sink,
        repository=repository,
        enabled=True,
    )
    finalizer.finalize(ctx)
    return ctx, sink, repository


# --------------------------------------------------------------------------- #
# Property 7
# --------------------------------------------------------------------------- #


class TestProperty7FailureTraces:
    @settings(max_examples=150)
    @given(rec=failure_recording)
    def test_failure_trace_is_attributed_and_carries_request_id(self, rec):
        """(a) The emitted trace records the failing step name and error
        message verbatim (Req 2.6), and (e) carries the request's valid
        uuid4 Request_ID — the same ID the error response delivers to the
        client, so the client-visible error links to this trace (Req 1.5)."""
        ctx, sink, _ = finalize_failed(rec)

        assert len(sink.emitted) == 1
        trace = sink.emitted[0]

        step, error = rec["failure"]
        assert trace.failure is not None
        assert trace.failure.step == step
        assert trace.failure.error == error

        assert trace.request_id == ctx.request_id
        assert uuid.UUID(trace.request_id).version == 4

        # The serialized shape carries both too — what CloudWatch sees.
        payload = trace.to_dict()
        assert payload["failure"] == {"step": step, "error": error}
        assert payload["request_id"] == ctx.request_id

    @settings(max_examples=150)
    @given(rec=failure_recording)
    def test_fields_recorded_before_the_failure_are_retained(self, rec):
        """(b) Every field captured before the failure survives into the
        partial trace exactly as recorded: identity fields, retrieval
        records in order with scores and latencies, the prompt, token
        counts, and any partial response. Fields never recorded stay None —
        partial, not fabricated (Req 2.6)."""
        _, sink, _ = finalize_failed(rec)
        trace = sink.emitted[0]

        # Identity fields recorded at construction, before any step ran.
        assert trace.query == rec["query"]
        assert trace.session_id == rec["session_id"]
        assert trace.model_id == rec["model_id"]

        # Retrieval records: same count, order, Source_IDs, scores, latency.
        assert len(trace.retrieval) == len(rec["retrieval_calls"])
        for record, (chunks, latency_ms) in zip(
            trace.retrieval, rec["retrieval_calls"]
        ):
            assert record.latency_ms == latency_ms
            assert [r.source_id for r in record.results] == [
                str(c.citation) for c in chunks
            ]
            assert [r.score for r in record.results] == [
                float(c.score) for c in chunks
            ]

        # Prompt, token counts, and partial answer: retained when recorded,
        # None when the failure struck before they were captured.
        assert trace.final_prompt == rec["prompt"]
        assert trace.input_tokens == rec["input_tokens"]
        assert trace.output_tokens == rec["output_tokens"]
        assert trace.response == rec["answer"]

    @settings(max_examples=150)
    @given(rec=failure_recording)
    def test_ttft_not_recorded_when_failure_precedes_first_token(self, rec):
        """(c) TTFT is marked as not recorded (None) exactly when the
        failure struck before any token was streamed; once a first token
        was marked, the TTFT captured before the failure is retained
        (Req 2.10)."""
        _, sink, _ = finalize_failed(rec)
        trace = sink.emitted[0]

        if rec["first_token_marks"] == 0:
            assert trace.ttft_ms is None
            assert trace.to_dict()["ttft_ms"] is None
        else:
            assert trace.ttft_ms is not None
            assert isinstance(trace.ttft_ms, int) and trace.ttft_ms >= 0

    @settings(max_examples=150)
    @given(rec=failure_recording)
    def test_failure_trace_is_emitted_but_never_persisted(self, rec):
        """(d) The finalizer still emits the partial trace to the sink —
        exactly one emission — but never persists it: the repository sees
        zero put calls and stays empty (Req 3.3)."""
        ctx, sink, repository = finalize_failed(rec)

        # Emitted: the sink received exactly the one partial trace.
        assert len(sink.emitted) == 1
        assert sink.emitted[0].request_id == ctx.request_id

        # Never persisted: no put was ever attempted, and the store has
        # no trace under this Request_ID.
        assert repository.put_calls == []
        assert repository.get(ctx.request_id) is None
