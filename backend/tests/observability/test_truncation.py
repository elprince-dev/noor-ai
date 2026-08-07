"""Unit tests for TraceTruncator — fitting traces into a byte budget (Req 3.8)."""
import json

from src.observability.models import (
    CostEstimate,
    RetrievalRecord,
    RetrievalResult,
    Trace,
)
from src.observability.truncation import TraceTruncator


def make_trace(**overrides) -> Trace:
    """A representative trace; fields overridable per test."""
    defaults = dict(
        request_id="req-truncation-test",
        session_id="sess-1",
        received_at="2026-02-11T09:15:02.412Z",
        query="ما حكم صلاة الوتر؟",
        model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        retrieval=(
            RetrievalRecord(
                tool="search_hadith",
                latency_ms=412,
                results=(RetrievalResult(source_id="Sahih al-Bukhari 990", score=0.72),),
            ),
        ),
        final_prompt="prompt text",
        response="response text",
        input_tokens=1842,
        output_tokens=512,
        cost=CostEstimate(computed=True, usd=0.004402),
        ttft_ms=620,
        total_latency_ms=4180,
    )
    defaults.update(overrides)
    return Trace(**defaults)


def serialized_size(trace: Trace) -> int:
    return len(json.dumps(trace.to_dict(), ensure_ascii=False).encode("utf-8"))


class TestTruncateToFit:
    def test_small_trace_returned_unchanged(self):
        """A trace already within budget is untouched — truncated stays False."""
        trace = make_trace()
        result = TraceTruncator().truncate_to_fit(trace)
        assert result is trace
        assert result.truncated is False

    def test_oversized_trace_fits_after_truncation(self):
        """An oversized trace is cut until its serialized form fits (Req 3.8)."""
        truncator = TraceTruncator(max_bytes=2_000)
        trace = make_trace(final_prompt="p" * 5_000, response="r" * 3_000)
        result = truncator.truncate_to_fit(trace)
        assert serialized_size(result) <= 2_000
        assert result.truncated is True

    def test_default_budget_is_250_kb(self):
        """The default max_bytes sits under the CloudWatch 256 KiB entry limit."""
        trace = make_trace(final_prompt="p" * 300_000, response="r" * 10_000)
        result = TraceTruncator().truncate_to_fit(trace)
        assert serialized_size(result) <= 250_000
        assert result.truncated is True

    def test_only_prompt_and_response_are_modified(self):
        """Every field except final_prompt/response/truncated is untouched."""
        truncator = TraceTruncator(max_bytes=2_000)
        trace = make_trace(final_prompt="p" * 5_000, response="r" * 3_000)
        result = truncator.truncate_to_fit(trace)
        original = trace.to_dict()
        truncated = result.to_dict()
        for key in original:
            if key in ("final_prompt", "response", "truncated"):
                continue
            assert truncated[key] == original[key], f"field {key} was modified"

    def test_longest_field_loses_more(self):
        """Cuts are proportional to length — the longer field is cut more."""
        truncator = TraceTruncator(max_bytes=2_000)
        trace = make_trace(final_prompt="p" * 8_000, response="r" * 2_000)
        result = truncator.truncate_to_fit(trace)
        prompt_removed = 8_000 - len(result.final_prompt)
        response_removed = 2_000 - len(result.response)
        assert prompt_removed > response_removed

    def test_truncated_fields_are_prefixes_of_originals(self):
        """Truncation only shortens content from the end — no rewriting."""
        truncator = TraceTruncator(max_bytes=2_000)
        prompt, response = "p" * 5_000 + "END", "r" * 3_000 + "END"
        trace = make_trace(final_prompt=prompt, response=response)
        result = truncator.truncate_to_fit(trace)
        assert prompt.startswith(result.final_prompt)
        assert response.startswith(result.response)

    def test_none_prompt_handled_gracefully(self):
        """A None final_prompt stays None; only the response is cut."""
        truncator = TraceTruncator(max_bytes=2_000)
        trace = make_trace(final_prompt=None, response="r" * 5_000)
        result = truncator.truncate_to_fit(trace)
        assert result.final_prompt is None
        assert serialized_size(result) <= 2_000
        assert result.truncated is True

    def test_none_response_handled_gracefully(self):
        """A None response stays None; only the prompt is cut."""
        truncator = TraceTruncator(max_bytes=2_000)
        trace = make_trace(final_prompt="p" * 5_000, response=None)
        result = truncator.truncate_to_fit(trace)
        assert result.response is None
        assert serialized_size(result) <= 2_000
        assert result.truncated is True

    def test_both_none_returns_trace_unchanged(self):
        """With nothing to cut, the trace is returned as-is — never flagged."""
        truncator = TraceTruncator(max_bytes=10)  # impossible budget
        trace = make_trace(final_prompt=None, response=None)
        result = truncator.truncate_to_fit(trace)
        assert result is trace
        assert result.truncated is False

    def test_multibyte_arabic_content_fits(self):
        """UTF-8 multi-byte content is measured in bytes, not characters."""
        truncator = TraceTruncator(max_bytes=2_000)
        trace = make_trace(final_prompt="ص" * 3_000, response="و" * 2_000)
        result = truncator.truncate_to_fit(trace)
        assert serialized_size(result) <= 2_000
        assert result.truncated is True

    def test_result_is_a_frozen_trace(self):
        """The truncator produces a new immutable Trace via replace()."""
        truncator = TraceTruncator(max_bytes=2_000)
        trace = make_trace(final_prompt="p" * 5_000, response="r" * 3_000)
        result = truncator.truncate_to_fit(trace)
        assert isinstance(result, Trace)
        assert result is not trace
