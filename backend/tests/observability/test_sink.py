"""Tests for CloudWatchTraceSink — one JSON line per trace (Req 3.1)."""
import json

from src.observability.models import (
    CostEstimate,
    RetrievalRecord,
    RetrievalResult,
    Trace,
    TraceFailure,
)
from src.observability.sink import CloudWatchTraceSink, TraceSink


def make_trace(**overrides) -> Trace:
    defaults = dict(
        request_id="req-123",
        session_id="sess-456",
        received_at="2025-01-01T00:00:00+00:00",
        query="ما حكم صلاة الوتر؟",
        model_id="us.anthropic.claude-haiku-4-5",
        retrieval=(
            RetrievalRecord(
                tool="retrieve",
                latency_ms=42,
                results=(RetrievalResult(source_id="Quran 2:255", score=0.91),),
            ),
        ),
        final_prompt="prompt text",
        response="الوتر سنة مؤكدة",
        input_tokens=100,
        output_tokens=50,
        cost=CostEstimate(computed=True, usd=0.000125),
        ttft_ms=350,
        total_latency_ms=1200,
    )
    defaults.update(overrides)
    return Trace(**defaults)


def emitted_line(capsys) -> str:
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one log line, got {len(lines)}"
    return lines[0]


class TestCloudWatchTraceSink:
    def test_satisfies_trace_sink_protocol(self):
        sink: TraceSink = CloudWatchTraceSink()
        assert isinstance(sink, CloudWatchTraceSink)

    def test_emits_exactly_one_json_line_with_log_type_and_all_fields(self, capsys):
        trace = make_trace()
        CloudWatchTraceSink().emit(trace)
        record = json.loads(emitted_line(capsys))
        assert record == {"log_type": "trace", **trace.to_dict()}

    def test_arabic_text_not_escaped(self, capsys):
        """ensure_ascii=False keeps Arabic readable in CloudWatch."""
        CloudWatchTraceSink().emit(make_trace())
        raw = emitted_line(capsys)
        assert "ما حكم صلاة الوتر؟" in raw
        assert "\\u0645" not in raw

    def test_none_fields_serialize_as_null(self, capsys):
        """Failure traces keep uncaptured fields as null, not omitted."""
        trace = make_trace(
            final_prompt=None,
            response=None,
            input_tokens=None,
            output_tokens=None,
            ttft_ms=None,
            cost=CostEstimate(computed=False, reason="token counts unavailable"),
            failure=TraceFailure(step="generation", error="boom"),
        )
        CloudWatchTraceSink().emit(trace)
        record = json.loads(emitted_line(capsys))
        assert record["response"] is None
        assert record["ttft_ms"] is None
        assert record["failure"] == {"step": "generation", "error": "boom"}
        assert record["cost"] == {"computed": False, "reason": "token counts unavailable"}
