"""Tests for observability models — immutable trace data types (schema v1)."""
import dataclasses
import json

import pytest

from src.observability.models import (
    SCHEMA_VERSION,
    CostEstimate,
    ModelPricing,
    RetrievalRecord,
    RetrievalResult,
    Trace,
    TraceFailure,
)


def make_trace(**overrides) -> Trace:
    """A representative successful trace; fields overridable per test."""
    defaults = dict(
        request_id="3f2a-test-uuid",
        session_id="sess-1",
        received_at="2026-02-11T09:15:02.412Z",
        query="ما حكم صلاة الوتر؟",
        model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        retrieval=(
            RetrievalRecord(
                tool="search_hadith",
                latency_ms=412,
                results=(RetrievalResult(source_id="Sahih al-Bukhari 990", score=0.7213),),
            ),
        ),
        final_prompt="…messages…",
        response="…answer…",
        input_tokens=1842,
        output_tokens=512,
        cost=CostEstimate(computed=True, usd=0.004402),
        ttft_ms=620,
        total_latency_ms=4180,
    )
    defaults.update(overrides)
    return Trace(**defaults)


class TestTraceModel:
    def test_carries_schema_version_1(self):
        """Every Trace identifies its schema version (Req 2.7)."""
        assert SCHEMA_VERSION == 1
        assert make_trace().schema_version == 1
        assert make_trace().to_dict()["schema_version"] == 1

    def test_is_immutable(self):
        """Trace is frozen — accumulation belongs to TraceContext only."""
        trace = make_trace()
        with pytest.raises(dataclasses.FrozenInstanceError):
            trace.response = "mutated"

    def test_to_dict_is_json_serializable_with_arabic(self):
        """The full trace shape serializes cleanly, Arabic text intact."""
        payload = json.dumps(make_trace().to_dict(), ensure_ascii=False)
        parsed = json.loads(payload)
        assert parsed["query"] == "ما حكم صلاة الوتر؟"
        assert parsed["retrieval"][0]["results"][0]["source_id"] == "Sahih al-Bukhari 990"
        assert parsed["failure"] is None
        assert parsed["truncated"] is False

    def test_none_fields_mean_not_captured(self):
        """Unavailable tokens / unrecorded TTFT stay None (Req 2.8, 2.10)."""
        trace = make_trace(
            input_tokens=None,
            output_tokens=None,
            ttft_ms=None,
            cost=CostEstimate(computed=False, reason="token counts unavailable"),
        )
        d = trace.to_dict()
        assert d["input_tokens"] is None
        assert d["output_tokens"] is None
        assert d["ttft_ms"] is None
        assert d["cost"] == {"computed": False, "reason": "token counts unavailable"}

    def test_failure_serializes_step_and_error(self):
        """Failure traces name the failing step and error (Req 2.6)."""
        trace = make_trace(failure=TraceFailure(step="retrieval", error="boom"))
        assert trace.to_dict()["failure"] == {"step": "retrieval", "error": "boom"}


class TestCostEstimate:
    def test_computed_shape(self):
        assert CostEstimate(computed=True, usd=0.01).to_dict() == {
            "computed": True,
            "usd": 0.01,
        }

    def test_not_computed_shape_carries_reason_not_zero(self):
        """Not-computed cost is explicit — never a zero value (Req 2.8, 2.9)."""
        d = CostEstimate(computed=False, reason="no pricing entry").to_dict()
        assert d == {"computed": False, "reason": "no pricing entry"}
        assert "usd" not in d


class TestModelPricing:
    def test_is_immutable_value_object(self):
        pricing = ModelPricing(input_per_1k=0.001, output_per_1k=0.005)
        assert pricing.input_per_1k == 0.001
        with pytest.raises(dataclasses.FrozenInstanceError):
            pricing.input_per_1k = 0.002
