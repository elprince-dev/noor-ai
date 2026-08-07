"""Property 1: Request_ID uniqueness and universal propagation.

*For any* sequence of chat requests processed through the (mocked) pipeline,
every request is assigned a distinct Request_ID before any pipeline step
executes, and for each request, the identical Request_ID value appears in its
trace, in every structured log line emitted during it, and in its response
stream.

**Validates: Requirements 1.1, 1.2, 1.4**

Pure in-memory Hypothesis test — no AWS calls. Requests are simulated as
asyncio pipelines: `TraceContext` is created first (Req 1.1), activated via
its ContextVar, and arbitrary "pipeline steps" (direct calls and spawned
asyncio tasks, mirroring how LangGraph tools run) record into whatever
`TraceContext.current()` resolves to (Req 1.2). Structured log lines are
captured from stdout and parsed to check request_id injection (Req 1.4).
"""
# Feature: rag-evaluation-observability, Property 1: Request_ID uniqueness and universal propagation
import asyncio
import io
import json
import uuid
from contextlib import redirect_stdout
from dataclasses import dataclass

from hypothesis import given, settings
from hypothesis import strategies as st

from src.observability.logging import log_json
from src.observability.models import CostEstimate, Trace
from src.observability.trace_context import TraceContext

NOT_COMPUTED = CostEstimate(computed=False, reason="test")


@dataclass(frozen=True)
class FakeChunk:
    """Mirrors the RetrievedChunk attributes record_retrieval reads."""

    citation: str
    score: float


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #

# Queries/answers include Arabic, Latin, and arbitrary printable unicode.
text_content = st.text(min_size=1, max_size=100)

chunk = st.builds(
    FakeChunk,
    citation=st.text(min_size=1, max_size=60),
    score=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
)

# One "pipeline step": a retrieval-style recording, executed either as a
# direct call or inside a spawned asyncio task (LangGraph tools run in tasks
# that inherit the request's ContextVar).
pipeline_step = st.fixed_dictionaries(
    {
        "chunks": st.lists(chunk, max_size=5),
        "latency_ms": st.integers(min_value=0, max_value=60_000),
        "in_task": st.booleans(),
    }
)

request_recording = st.fixed_dictionaries(
    {
        "query": text_content,
        "session_id": st.text(min_size=1, max_size=64),
        "steps": st.lists(pipeline_step, min_size=1, max_size=5),
        "answer": text_content,
    }
)

# Structured log calls emitted mid-request. Field keys deliberately exclude
# "request_id" — an explicit one wins by contract, which is not what this
# property exercises.
log_call = st.fixed_dictionaries(
    {
        "level": st.sampled_from(["info", "warning", "error"]),
        "message": text_content,
        "fields": st.dictionaries(
            st.sampled_from(["step", "table", "detail"]),
            st.text(max_size=30),
            max_size=2,
        ),
        "in_task": st.booleans(),
    }
)


# --------------------------------------------------------------------------- #
# Mocked pipeline
# --------------------------------------------------------------------------- #


async def run_pipeline(rec: dict) -> tuple[TraceContext, Trace, list[str]]:
    """Simulate one request: create + activate a context, run every pipeline
    step (direct call or spawned task), record the response, build the Trace.

    Returns the context, the frozen Trace, and the request_id each step
    observed via `TraceContext.current()`.
    """
    # Context is created before any pipeline step executes (Req 1.1).
    ctx = TraceContext(
        query=rec["query"], session_id=rec["session_id"], model_id="test-model"
    )
    assert ctx.request_id  # assigned at construction, before any step

    observed_ids: list[str] = []
    token = ctx.activate()
    try:
        async def step(chunks, latency_ms: int) -> None:
            # Yield so concurrent requests interleave mid-pipeline.
            await asyncio.sleep(0)
            current = TraceContext.current()
            assert current is not None, "pipeline step ran without a context"
            observed_ids.append(current.request_id)
            current.record_retrieval(chunks, latency_ms=latency_ms)

        for s in rec["steps"]:
            if s["in_task"]:
                # Spawned task (how LangGraph runs tools) — inherits the
                # ContextVar snapshot of this request (Req 1.2).
                await asyncio.create_task(step(s["chunks"], s["latency_ms"]))
            else:
                await step(s["chunks"], s["latency_ms"])

        current = TraceContext.current()
        current.record_response(rec["answer"])
        trace = current.build_trace(NOT_COMPUTED)
    finally:
        TraceContext.deactivate(token)
    return ctx, trace, observed_ids


# --------------------------------------------------------------------------- #
# (a) Uniqueness — Req 1.1
# --------------------------------------------------------------------------- #


class TestRequestIdUniqueness:
    @settings(max_examples=100)
    @given(
        queries=st.lists(text_content, min_size=2, max_size=20),
        concurrent=st.booleans(),
    )
    def test_request_ids_are_pairwise_distinct_valid_uuid4(self, queries, concurrent):
        """Contexts created sequentially or concurrently all carry distinct,
        valid uuid4 Request_IDs assigned at construction (Req 1.1)."""
        if concurrent:
            async def make(query: str) -> TraceContext:
                await asyncio.sleep(0)  # force task interleaving
                return TraceContext(query=query, session_id="s", model_id="m")

            async def make_all() -> list[TraceContext]:
                return await asyncio.gather(*(make(q) for q in queries))

            ctxs = asyncio.run(make_all())
        else:
            ctxs = [
                TraceContext(query=q, session_id="s", model_id="m") for q in queries
            ]

        ids = [c.request_id for c in ctxs]
        assert len(set(ids)) == len(ids), "Request_IDs must be pairwise distinct"
        for request_id in ids:
            assert uuid.UUID(request_id).version == 4


# --------------------------------------------------------------------------- #
# (b) Propagation into recordings and the Trace — Req 1.2
# --------------------------------------------------------------------------- #


class TestRequestIdPropagation:
    @settings(max_examples=100)
    @given(rec=request_recording)
    def test_every_step_sees_the_request_context_and_trace_carries_its_id(self, rec):
        """With a context active, every pipeline step (direct or in a task)
        resolves the same context, its recordings land there, and the built
        Trace repeats the identical Request_ID (Req 1.2)."""
        ctx, trace, observed_ids = asyncio.run(run_pipeline(rec))

        # Every step observed exactly this request's ID.
        assert observed_ids == [ctx.request_id] * len(rec["steps"])

        # The recordings landed in this context: one retrieval record per
        # step, with this request's own chunks, and the response captured.
        assert len(trace.retrieval) == len(rec["steps"])
        for record, s in zip(trace.retrieval, rec["steps"]):
            assert [r.source_id for r in record.results] == [
                c.citation for c in s["chunks"]
            ]
        assert trace.response == rec["answer"]

        # The frozen Trace carries the identical Request_ID.
        assert trace.request_id == ctx.request_id

    @settings(max_examples=100)
    @given(recs=st.lists(request_recording, min_size=2, max_size=4))
    def test_concurrent_requests_never_cross_contaminate(self, recs):
        """Concurrently processed requests each keep their own context: all
        Request_IDs distinct, every step lands in its own request's Trace
        (Req 1.1, 1.2)."""

        async def run_all():
            return await asyncio.gather(*(run_pipeline(rec) for rec in recs))

        results = asyncio.run(run_all())

        ids = [ctx.request_id for ctx, _, _ in results]
        assert len(set(ids)) == len(ids)

        for rec, (ctx, trace, observed_ids) in zip(recs, results):
            assert observed_ids == [ctx.request_id] * len(rec["steps"])
            assert trace.request_id == ctx.request_id
            assert len(trace.retrieval) == len(rec["steps"])
            for record, s in zip(trace.retrieval, rec["steps"]):
                assert [r.source_id for r in record.results] == [
                    c.citation for c in s["chunks"]
                ]
            assert trace.response == rec["answer"]


# --------------------------------------------------------------------------- #
# (c) Structured log lines — Req 1.4
# --------------------------------------------------------------------------- #


class TestRequestIdInLogLines:
    @settings(max_examples=100)
    @given(rec=request_recording, log_calls=st.lists(log_call, min_size=1, max_size=5))
    def test_every_log_line_during_the_request_carries_its_request_id(
        self, rec, log_calls
    ):
        """Every structured log line emitted while the request's context is
        active — from direct calls or spawned tasks — carries the identical
        Request_ID, auto-injected (Req 1.4)."""

        async def request_with_logs() -> TraceContext:
            ctx = TraceContext(
                query=rec["query"], session_id=rec["session_id"], model_id="test-model"
            )
            token = ctx.activate()
            try:
                async def emit(call: dict) -> None:
                    await asyncio.sleep(0)
                    log_json(call["level"], call["message"], **call["fields"])

                for call in log_calls:
                    if call["in_task"]:
                        await asyncio.create_task(emit(call))
                    else:
                        await emit(call)
            finally:
                TraceContext.deactivate(token)
            return ctx

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            ctx = asyncio.run(request_with_logs())

        # Split on "\n" only: json.dumps escapes literal newlines, but other
        # unicode line boundaries (e.g. U+0085) pass through raw and must not
        # be treated as line breaks by the test.
        lines = [line for line in buffer.getvalue().split("\n") if line.strip()]
        assert len(lines) == len(log_calls)
        for line, call in zip(lines, log_calls):
            record = json.loads(line)
            assert record["request_id"] == ctx.request_id
            assert record["level"] == call["level"]
            assert record["message"] == call["message"]
