"""Tests for AgentEventRecorder — LangGraph event → TraceContext mapping."""
from unittest.mock import MagicMock

import pytest

from src.observability.instrumentation import AgentEventRecorder
from src.observability.trace_context import TraceContext


@pytest.fixture
def ctx():
    """An active TraceContext, deactivated after the test."""
    context = TraceContext(query="q", session_id="s", model_id="model-x")
    token = context.activate()
    yield context
    TraceContext.deactivate(token)


def _chunk(content):
    chunk = MagicMock()
    chunk.content = content
    return chunk


def _output_message(usage_metadata):
    message = MagicMock()
    message.usage_metadata = usage_metadata
    return message


class TestNoContext:
    def test_on_event_noops_without_context(self):
        # Must not raise when no TraceContext is current (e.g. unit tests).
        AgentEventRecorder().on_event({"event": "on_chat_model_start", "data": {}})

    def test_on_complete_noops_without_context(self):
        AgentEventRecorder().on_complete("answer")


class TestEventMapping:
    def test_chat_model_start_records_prompt_last_wins(self, ctx):
        recorder = AgentEventRecorder()
        recorder.on_event(
            {"event": "on_chat_model_start",
             "data": {"input": {"messages": [["first prompt"]]}}}
        )
        recorder.on_event(
            {"event": "on_chat_model_start",
             "data": {"input": {"messages": [["final prompt"]]}}}
        )
        trace = ctx.build_trace(cost=MagicMock())
        assert trace.final_prompt == "final prompt"

    def test_first_text_chunk_marks_first_token(self, ctx):
        recorder = AgentEventRecorder()
        # Non-text chunk (tool use) must not mark TTFT.
        recorder.on_event(
            {"event": "on_chat_model_stream",
             "data": {"chunk": _chunk([{"type": "tool_use", "id": "t1"}])}}
        )
        trace = ctx.build_trace(cost=MagicMock())
        assert trace.ttft_ms is None

        recorder.on_event(
            {"event": "on_chat_model_stream",
             "data": {"chunk": _chunk([{"type": "text", "text": "hi"}])}}
        )
        trace = ctx.build_trace(cost=MagicMock())
        assert trace.ttft_ms is not None

    def test_chat_model_end_records_usage(self, ctx):
        AgentEventRecorder().on_event(
            {"event": "on_chat_model_end",
             "data": {"output": _output_message(
                 {"input_tokens": 120, "output_tokens": 45, "total_tokens": 165}
             )}}
        )
        assert ctx.input_tokens == 120
        assert ctx.output_tokens == 45

    def test_absent_usage_metadata_leaves_counts_none(self, ctx):
        AgentEventRecorder().on_event(
            {"event": "on_chat_model_end",
             "data": {"output": _output_message(None)}}
        )
        assert ctx.input_tokens is None
        assert ctx.output_tokens is None

    def test_tool_events_track_current_step(self, ctx):
        recorder = AgentEventRecorder()
        assert ctx.current_step == "generation"
        recorder.on_event({"event": "on_tool_start", "data": {}})
        assert ctx.current_step == "retrieval"
        recorder.on_event({"event": "on_tool_end", "data": {}})
        assert ctx.current_step == "generation"

    def test_on_complete_records_response(self, ctx):
        AgentEventRecorder().on_complete("the full answer")
        trace = ctx.build_trace(cost=MagicMock())
        assert trace.response == "the full answer"

    def test_unknown_events_are_ignored(self, ctx):
        AgentEventRecorder().on_event({"event": "on_chain_start", "data": {}})
        trace = ctx.build_trace(cost=MagicMock())
        assert trace.final_prompt is None


class TestNeverRaises:
    def test_malformed_event_is_swallowed(self, ctx, capsys):
        # A record_* explosion must degrade to a logged warning (Req: the
        # recorder never raises into the streaming pipeline).
        ctx.record_prompt = MagicMock(side_effect=RuntimeError("boom"))
        AgentEventRecorder().on_event(
            {"event": "on_chat_model_start", "data": {"input": "p"}}
        )
        assert "trace event recording failed" in capsys.readouterr().out

    def test_on_complete_failure_is_swallowed(self, ctx, capsys):
        ctx.record_response = MagicMock(side_effect=RuntimeError("boom"))
        AgentEventRecorder().on_complete("answer")
        assert "trace response recording failed" in capsys.readouterr().out
