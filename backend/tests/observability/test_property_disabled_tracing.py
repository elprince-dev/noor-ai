"""Property 11: Disabled tracing preserves Request_ID behavior (design.md).

*For any* chat request processed with trace logging disabled, no Trace is
emitted or persisted, yet a fresh Request_ID is still generated and
delivered in the response stream.

**Validates: Requirements 3.7**

Pure in-memory Hypothesis tests — no AWS calls. Arbitrary request
recordings (successful, partial, or failed) are replayed against a real
`TraceContext`, then finalized through a `TraceFinalizer` constructed with
`enabled=False` and in-memory fakes. The disabled finalizer must (a) never
emit (the recording sink stays empty), (b) never persist (the in-memory
repository stays empty), (c) produce no stdout output, and (d) never raise
— even when every collaborator is poisoned to explode on first touch,
which proves the disabled path never reaches them.

Meanwhile the `TraceContext` — created before any pipeline step regardless
of the tracing flag — still carries a valid uuid4 Request_ID, and the
ContextVar propagation (`activate` / `current` / `deactivate`) still works,
so streaming events and feedback keep functioning with tracing off.

Recording strategies are reused from the Property 3 completeness test;
the in-memory repository fake from the Property 9 store test.
"""
# Feature: rag-evaluation-observability, Property 11: Disabled tracing preserves Request_ID behavior
import io
import uuid
from contextlib import redirect_stdout

from hypothesis import given, settings
from hypothesis import strategies as st

from src.observability.cost import CostEstimator
from src.observability.finalizer import TraceFinalizer
from src.observability.models import Trace
from src.observability.trace_context import TraceContext
from src.observability.truncation import TraceTruncator
from tests.observability.test_property_trace_completeness import (
    retrieval_call,
    text_content,
)
from tests.observability.test_property_trace_store import InMemoryTraceRepository


class RecordingSink:
    """`TraceSink` fake that records every emitted trace in memory."""

    def __init__(self) -> None:
        self.emitted: list[Trace] = []

    def emit(self, trace: Trace) -> None:
        self.emitted.append(trace)


class PoisonedSink:
    """Sink that explodes on any touch — proves the disabled path never
    reaches the sink."""

    def emit(self, trace: Trace) -> None:
        raise RuntimeError("sink must never be touched when tracing is disabled")


class PoisonedRepository:
    """Repository that explodes on any touch — proves the disabled path
    never reaches persistence."""

    def put(self, trace: Trace) -> None:
        raise RuntimeError("repository must never be touched when tracing is disabled")

    def get(self, request_id: str) -> Trace | None:
        raise RuntimeError("repository must never be touched when tracing is disabled")


class PoisonedEstimator:
    """Estimator that explodes on any touch — the disabled finalizer must
    not even begin trace assembly."""

    def estimate(self, input_tokens, output_tokens, model_id):
        raise RuntimeError("estimator must never be touched when tracing is disabled")


# --------------------------------------------------------------------------- #
# Strategy: one arbitrary request recording — successful, partial, or failed
# --------------------------------------------------------------------------- #

request_recording = st.fixed_dictionaries(
    {
        "query": text_content,
        "session_id": st.text(min_size=1, max_size=64),
        "model_id": st.text(min_size=1, max_size=64),
        "retrieval_calls": st.lists(retrieval_call, max_size=4),
        "prompt": st.none() | text_content,
        "input_tokens": st.none() | st.integers(min_value=0, max_value=1_000_000),
        "output_tokens": st.none() | st.integers(min_value=0, max_value=1_000_000),
        # A failed request may never stream a token (zero marks).
        "first_token_marks": st.integers(min_value=0, max_value=3),
        "answer": st.none() | text_content,
        "failure": st.none()
        | st.tuples(
            st.sampled_from(["retrieval", "generation", "streaming"]), text_content
        ),
    }
)


def replay(rec: dict) -> TraceContext:
    """Drive a real TraceContext through one arbitrary request recording."""
    ctx = TraceContext(
        query=rec["query"], session_id=rec["session_id"], model_id=rec["model_id"]
    )
    for chunks, latency_ms in rec["retrieval_calls"]:
        ctx.record_retrieval(chunks, latency_ms=latency_ms)
    if rec["prompt"] is not None:
        ctx.record_prompt(rec["prompt"])
    for _ in range(rec["first_token_marks"]):
        ctx.mark_first_token()
    ctx.record_usage(rec["input_tokens"], rec["output_tokens"])
    if rec["answer"] is not None:
        ctx.record_response(rec["answer"])
    if rec["failure"] is not None:
        step, error = rec["failure"]
        ctx.record_failure(step, error)
    return ctx


def disabled_finalizer(sink, repository) -> TraceFinalizer:
    """A TraceFinalizer wired exactly like production, but with enabled=False."""
    return TraceFinalizer(
        estimator=CostEstimator(pricing={}),
        truncator=TraceTruncator(),
        sink=sink,
        repository=repository,
        enabled=False,
    )


# --------------------------------------------------------------------------- #
# Property 11
# --------------------------------------------------------------------------- #


class TestProperty11DisabledTracing:
    @settings(max_examples=150)
    @given(rec=request_recording)
    def test_disabled_finalize_never_emits_persists_or_prints(self, rec):
        """With enabled=False, finalize is a complete no-op: the sink stays
        empty, the repository stays empty, nothing is written to stdout,
        and no exception escapes (Req 3.7)."""
        ctx = replay(rec)
        sink = RecordingSink()
        repository = InMemoryTraceRepository()
        finalizer = disabled_finalizer(sink, repository)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            finalizer.finalize(ctx)  # (d) must not raise

        assert sink.emitted == []  # (a) never emits
        assert repository.get(ctx.request_id) is None  # (b) never persists
        assert buffer.getvalue() == ""  # (c) no stdout output

    @settings(max_examples=150)
    @given(rec=request_recording)
    def test_disabled_finalize_never_touches_any_collaborator(self, rec):
        """With enabled=False, finalize returns before touching the
        estimator, sink, or repository — proven by poisoned fakes that
        raise on first use. No exception escapes and nothing is printed
        (Req 3.7)."""
        ctx = replay(rec)
        finalizer = TraceFinalizer(
            estimator=PoisonedEstimator(),
            truncator=TraceTruncator(),
            sink=PoisonedSink(),
            repository=PoisonedRepository(),
            enabled=False,
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            finalizer.finalize(ctx)  # would raise if any collaborator were touched

        assert buffer.getvalue() == ""

    @settings(max_examples=150)
    @given(rec=request_recording)
    def test_request_id_and_context_propagation_survive_disabled_tracing(self, rec):
        """With tracing disabled, the TraceContext still carries a fresh
        valid uuid4 Request_ID (generated in the constructor, before any
        pipeline step), and ContextVar propagation still works — activate
        makes the context current for streaming/feedback, deactivate
        restores the previous state (Req 3.7)."""
        before = TraceContext.current()
        ctx = replay(rec)

        # Fresh, valid uuid4 Request_ID exists regardless of the flag.
        assert uuid.UUID(ctx.request_id).version == 4

        # Propagation: the pipeline (retrieval hook, streaming, feedback)
        # can still find the context while it is active.
        token = ctx.activate()
        try:
            assert TraceContext.current() is ctx
            # Finalizing with tracing disabled changes nothing observable.
            finalizer = disabled_finalizer(RecordingSink(), InMemoryTraceRepository())
            finalizer.finalize(ctx)
            assert TraceContext.current() is ctx
            assert uuid.UUID(ctx.request_id).version == 4
        finally:
            TraceContext.deactivate(token)

        # Deactivation restores whatever was current before the request.
        assert TraceContext.current() is before

    @settings(max_examples=100)
    @given(rec_a=request_recording, rec_b=request_recording)
    def test_request_ids_are_fresh_per_request_when_disabled(self, rec_a, rec_b):
        """Two requests processed with tracing disabled still get distinct
        Request_IDs — the ID is generated per request, not gated on the
        tracing flag (Req 3.7)."""
        ctx_a = replay(rec_a)
        ctx_b = replay(rec_b)
        assert ctx_a.request_id != ctx_b.request_id
