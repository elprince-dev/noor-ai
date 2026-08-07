"""Tests for TraceContext — request-scoped trace accumulation.

Covers Req 1.1 (Request_ID before any pipeline step), 2.1 (identity fields),
2.2 (retrieval fidelity), 2.3 (prompt/response), 2.4 (TTFT + total latency),
2.6 (failure step + message), 2.10 (TTFT stays unrecorded).
"""
import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from src.observability.models import CostEstimate, Trace
from src.observability.trace_context import TraceContext, _current_trace

NOT_COMPUTED = CostEstimate(computed=False, reason="test")


@dataclass(frozen=True)
class FakeChunk:
    """Mirrors the RetrievedChunk attributes record_retrieval reads."""

    citation: str
    score: float


def make_ctx(**overrides) -> TraceContext:
    kwargs = dict(query="ما حكم صلاة الوتر؟", session_id="sess-1", model_id="test-model")
    kwargs.update(overrides)
    return TraceContext(**kwargs)


class TestConstructor:
    def test_generates_uuid4_request_id_immediately(self):
        """Request_ID exists before any pipeline step runs (Req 1.1)."""
        ctx = make_ctx()
        parsed = uuid.UUID(ctx.request_id)
        assert parsed.version == 4

    def test_request_ids_are_unique_across_requests(self):
        ids = {make_ctx().request_id for _ in range(50)}
        assert len(ids) == 50

    def test_received_at_is_utc(self):
        """Receipt timestamp captured in UTC at construction (Req 2.1)."""
        before = datetime.now(timezone.utc)
        ctx = make_ctx()
        after = datetime.now(timezone.utc)
        assert ctx.received_at.tzinfo == timezone.utc
        assert before <= ctx.received_at <= after

    def test_holds_query_session_and_model(self):
        ctx = make_ctx()
        assert ctx.query == "ما حكم صلاة الوتر؟"
        assert ctx.session_id == "sess-1"
        assert ctx.model_id == "test-model"


class TestCurrentContextPropagation:
    def test_current_is_none_outside_a_request(self):
        assert TraceContext.current() is None

    def test_activate_makes_context_current_and_deactivate_restores(self):
        ctx = make_ctx()
        token = ctx.activate()
        try:
            assert TraceContext.current() is ctx
        finally:
            TraceContext.deactivate(token)
        assert TraceContext.current() is None

    async def test_concurrent_tasks_see_their_own_context(self):
        """ContextVar isolation: two asyncio tasks never see each other's
        context (Req 1.2 — async-safe propagation)."""

        async def request(ctx: TraceContext) -> str:
            token = _current_trace.set(ctx)
            try:
                await asyncio.sleep(0.01)  # force interleaving
                current = TraceContext.current()
                assert current is ctx
                return current.request_id
            finally:
                _current_trace.reset(token)

        ctx_a, ctx_b = make_ctx(), make_ctx()
        id_a, id_b = await asyncio.gather(request(ctx_a), request(ctx_b))
        assert id_a == ctx_a.request_id
        assert id_b == ctx_b.request_id


class TestRecordRetrieval:
    def test_maps_citation_to_source_id_preserving_order_and_scores(self):
        """Retrieved chunks recorded in order with their scores (Req 2.2)."""
        ctx = make_ctx()
        chunks = [
            FakeChunk(citation="Quran 2:255", score=0.91),
            FakeChunk(citation="Sahih al-Bukhari 990", score=0.72),
        ]
        ctx.record_retrieval(chunks, latency_ms=412, tool="search_quran")
        trace = ctx.build_trace(NOT_COMPUTED)
        record = trace.retrieval[0]
        assert record.tool == "search_quran"
        assert record.latency_ms == 412
        assert [r.source_id for r in record.results] == [
            "Quran 2:255",
            "Sahih al-Bukhari 990",
        ]
        assert [r.score for r in record.results] == [0.91, 0.72]

    def test_zero_chunks_record_an_explicit_empty_list(self):
        """Empty retrieval is recorded, not omitted (Req 2.2)."""
        ctx = make_ctx()
        ctx.record_retrieval([], latency_ms=88)
        trace = ctx.build_trace(NOT_COMPUTED)
        assert len(trace.retrieval) == 1
        assert trace.retrieval[0].results == ()

    def test_multiple_tool_calls_append_in_order(self):
        ctx = make_ctx()
        ctx.record_retrieval([FakeChunk("Quran 1:1", 0.9)], 100, tool="search_quran")
        ctx.record_retrieval([FakeChunk("Sahih Muslim 8", 0.8)], 200, tool="search_hadith")
        trace = ctx.build_trace(NOT_COMPUTED)
        assert [r.tool for r in trace.retrieval] == ["search_quran", "search_hadith"]


class TestTtft:
    def test_mark_first_token_sets_ttft_once(self):
        """TTFT is set by the first token only; later marks no-op (Req 2.4)."""
        ctx = make_ctx()
        ctx.mark_first_token()
        first = ctx.build_trace(NOT_COMPUTED).ttft_ms
        assert first is not None
        ctx.mark_first_token()
        assert ctx.build_trace(NOT_COMPUTED).ttft_ms == first

    def test_ttft_stays_none_when_never_marked(self):
        """No first token ⇒ TTFT not recorded (Req 2.10)."""
        trace = make_ctx().build_trace(NOT_COMPUTED)
        assert trace.ttft_ms is None


class TestRecordingMethods:
    def test_record_prompt_last_call_wins(self):
        """The final prompt after tool results is the one kept (Req 2.3)."""
        ctx = make_ctx()
        ctx.record_prompt("first prompt")
        ctx.record_prompt("final prompt with tool results")
        assert ctx.build_trace(NOT_COMPUTED).final_prompt == (
            "final prompt with tool results"
        )

    def test_record_prompt_renders_message_dicts(self):
        ctx = make_ctx()
        ctx.record_prompt(
            [
                {"role": "system", "content": "You are Noor."},
                {"role": "user", "content": "ما حكم صلاة الوتر؟"},
            ]
        )
        prompt = ctx.build_trace(NOT_COMPUTED).final_prompt
        assert "system: You are Noor." in prompt
        assert "user: ما حكم صلاة الوتر؟" in prompt

    def test_record_prompt_renders_nested_message_objects(self):
        """on_chat_model_start payloads arrive as list[list[BaseMessage]]."""

        class Msg:
            type = "human"
            content = "hello"

        ctx = make_ctx()
        ctx.record_prompt([[Msg()]])
        assert ctx.build_trace(NOT_COMPUTED).final_prompt == "human: hello"

    def test_record_usage_and_response(self):
        ctx = make_ctx()
        ctx.record_usage(1842, 512)
        ctx.record_response("الوتر سنة مؤكدة…")
        trace = ctx.build_trace(NOT_COMPUTED)
        assert trace.input_tokens == 1842
        assert trace.output_tokens == 512
        assert trace.response == "الوتر سنة مؤكدة…"

    def test_record_failure_names_step_and_error(self):
        """Failure carries the failing step and message (Req 2.6)."""
        ctx = make_ctx()
        ctx.current_step = "retrieval"
        ctx.record_failure(step=ctx.current_step, error="KB timeout")
        failure = ctx.build_trace(NOT_COMPUTED).failure
        assert failure.step == "retrieval"
        assert failure.error == "KB timeout"

    def test_current_step_defaults_to_generation(self):
        assert make_ctx().current_step == "generation"


class TestBuildTrace:
    def test_freezes_accumulated_state_into_immutable_trace(self):
        ctx = make_ctx()
        ctx.record_retrieval([FakeChunk("Quran 2:255", 0.91)], 412)
        ctx.mark_first_token()
        ctx.record_prompt("prompt")
        ctx.record_usage(100, 50)
        ctx.record_response("answer")
        cost = CostEstimate(computed=True, usd=0.0004)
        trace = ctx.build_trace(cost)
        assert isinstance(trace, Trace)
        assert trace.request_id == ctx.request_id
        assert trace.session_id == "sess-1"
        assert trace.model_id == "test-model"
        assert trace.cost is cost
        assert trace.failure is None
        assert trace.truncated is False
        assert trace.schema_version == 1

    def test_missing_fields_stay_none(self):
        """Nothing recorded ⇒ None fields, never substituted values (Req 2.8, 2.10)."""
        trace = make_ctx().build_trace(NOT_COMPUTED)
        assert trace.final_prompt is None
        assert trace.response is None
        assert trace.input_tokens is None
        assert trace.output_tokens is None
        assert trace.ttft_ms is None
        assert trace.retrieval == ()

    def test_received_at_serialized_as_utc_iso8601_z(self):
        received_at = make_ctx().build_trace(NOT_COMPUTED).received_at
        assert received_at.endswith("Z")
        parsed = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None

    def test_total_latency_covers_receipt_to_build_and_bounds_ttft(self):
        """Total latency runs from request receipt; TTFT can never exceed it
        (Req 2.4)."""
        ctx = make_ctx()
        ctx.mark_first_token()
        trace = ctx.build_trace(NOT_COMPUTED)
        assert trace.total_latency_ms >= 0
        assert trace.ttft_ms <= trace.total_latency_ms

    def test_exposes_token_counts_and_failure_for_finalizer(self):
        """The finalizer reads these to estimate cost and gate persistence."""
        ctx = make_ctx()
        assert ctx.input_tokens is None
        assert ctx.failure is None
        ctx.record_usage(10, 20)
        ctx.record_failure("generation", "boom")
        assert ctx.input_tokens == 10
        assert ctx.output_tokens == 20
        assert ctx.failure.step == "generation"
