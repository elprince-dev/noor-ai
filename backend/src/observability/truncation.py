"""Fit a Trace into a byte budget (pure) — Req 3.8.

CloudWatch Logs caps a single event at 256 KiB; DynamoDB items at 400 KB.
`TraceTruncator` shortens only `final_prompt` and `response` (the two
unbounded free-text fields) until the serialized trace fits, leaving every
other field untouched, and flags the trace as truncated only when content
was actually removed.
"""
import json
import math
from dataclasses import replace

from src.observability.models import Trace


class TraceTruncator:
    """Deterministic, pure truncation of oversized traces (Req 3.8)."""

    def __init__(self, max_bytes: int = 250_000) -> None:
        # Default sits under the 256 KiB CloudWatch Logs entry limit,
        # leaving headroom for the log_type field and DynamoDB metadata.
        self._max_bytes = max_bytes

    def truncate_to_fit(self, trace: Trace) -> Trace:
        """Return a Trace whose serialized form fits within `max_bytes`.

        Shortens `final_prompt` and `response` longest-first,
        proportionally to their lengths; sets `truncated=True` only when
        content was actually removed. All other fields are untouched.
        A trace that already fits is returned unchanged.
        """
        if self._serialized_size(trace) <= self._max_bytes:
            return trace

        candidate = trace
        prompt = trace.final_prompt
        response = trace.response

        while (prompt or response):
            size = self._serialized_size(candidate)
            if size <= self._max_bytes:
                break
            prompt, response = self._cut(prompt, response, size - self._max_bytes)
            candidate = replace(
                trace, final_prompt=prompt, response=response, truncated=True
            )
        return candidate

    def _serialized_size(self, trace: Trace) -> int:
        """UTF-8 byte length of the trace's JSON form (as the sink emits it)."""
        return len(
            json.dumps(trace.to_dict(), ensure_ascii=False).encode("utf-8")
        )

    @staticmethod
    def _cut(
        prompt: str | None, response: str | None, excess_bytes: int
    ) -> tuple[str | None, str | None]:
        """Drop at least `excess_bytes` characters across the two fields.

        Each field loses a share proportional to its length, so the longest
        field is cut first and most. Each removed character frees at least
        one serialized byte, so cutting `excess_bytes` characters guarantees
        progress toward fitting (multi-byte/escaped characters free more,
        which only makes the result smaller). `None` fields stay `None`.
        """
        prompt_len = len(prompt) if prompt else 0
        response_len = len(response) if response else 0
        total = prompt_len + response_len
        if total == 0:
            return prompt, response

        cut_prompt = min(prompt_len, math.ceil(excess_bytes * prompt_len / total))
        cut_response = min(response_len, math.ceil(excess_bytes * response_len / total))

        new_prompt = prompt[: prompt_len - cut_prompt] if prompt is not None else None
        new_response = (
            response[: response_len - cut_response] if response is not None else None
        )
        return new_prompt, new_response
