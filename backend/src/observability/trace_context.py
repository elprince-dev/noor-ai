"""Request-scoped mutable trace accumulation (Req 1.1, 2.1–2.4, 2.6, 2.10).

`TraceContext` is created in /api/ask before any pipeline step runs and is
readable from anywhere in the same asyncio task via `TraceContext.current()`.
The ContextVar is the propagation mechanism: it is asyncio-task-local, so
`RetrievalService.retrieve` (called deep inside a LangGraph tool with no
access to request state) records into the correct request's context without
signature changes (Req 1.2).

The context only accumulates — cost estimation, serialization, truncation,
emission, and persistence belong to the other collaborators in this package.
`build_trace()` is the only producer of the immutable `Trace` model.
"""
import time
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone

from src.observability.models import (
    CostEstimate,
    RetrievalRecord,
    RetrievalResult,
    Trace,
    TraceFailure,
)

_current_trace: ContextVar["TraceContext | None"] = ContextVar(
    "noor_trace", default=None
)


def _render_messages(messages) -> str:
    """Render a prompt payload into a single string for the Trace.

    Tolerates the shapes LangGraph's `on_chat_model_start` produces:
    a plain string, message objects (with `.type`/`.content`), dicts
    (`role`/`content`), and nested lists thereof.
    """
    if isinstance(messages, str):
        return messages
    parts: list[str] = []
    stack = list(messages) if isinstance(messages, (list, tuple)) else [messages]
    for item in stack:
        if isinstance(item, (list, tuple)):
            parts.append(_render_messages(item))
        elif isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            role = item.get("role", "unknown")
            parts.append(f"{role}: {item.get('content', '')}")
        else:
            role = getattr(item, "type", None) or type(item).__name__
            content = getattr(item, "content", item)
            parts.append(f"{role}: {content}")
    return "\n".join(parts)


class TraceContext:
    """Mutable per-request accumulator for one chat request's Trace.

    Created before any pipeline step so the Request_ID exists from the very
    start (Req 1.1). Recording methods are called by the pipeline hooks;
    `build_trace()` freezes the accumulated state at finalization time.
    """

    def __init__(self, query: str, session_id: str, model_id: str | None = None) -> None:
        self.request_id: str = str(uuid.uuid4())
        self.received_at: datetime = datetime.now(timezone.utc)
        self._t0: float = time.monotonic()
        self.query = query
        self.session_id = session_id
        if model_id is None:
            from src.config import config

            model_id = config.bedrock_model_id
        self.model_id = model_id

        # Accumulated state — None means "not captured (yet)".
        self.current_step: str = "generation"
        self._retrieval: list[RetrievalRecord] = []
        self._final_prompt: str | None = None
        self._response: str | None = None
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        self._ttft_ms: int | None = None
        self._failure: TraceFailure | None = None

    # ------------------------------------------------------------------ #
    # ContextVar propagation
    # ------------------------------------------------------------------ #

    @classmethod
    def current(cls) -> "TraceContext | None":
        """The context of the current asyncio task, or None outside a request."""
        return _current_trace.get()

    def activate(self) -> Token:
        """Install this context as current; returns the token for `deactivate`."""
        return _current_trace.set(self)

    @staticmethod
    def deactivate(token: Token) -> None:
        """Restore the previous context (pass the token from `activate`)."""
        _current_trace.reset(token)

    # ------------------------------------------------------------------ #
    # Recording methods (called by pipeline hooks)
    # ------------------------------------------------------------------ #

    def record_retrieval(self, chunks, latency_ms: int, tool: str = "retrieve") -> None:
        """Append one retrieval tool call's ordered results (Req 2.2).

        `chunks` are `RetrievedChunk`-shaped objects (`citation`, `score`);
        Source_ID = citation. Zero chunks record an explicit empty list.
        """
        results = tuple(
            RetrievalResult(source_id=str(c.citation), score=float(c.score))
            for c in chunks
        )
        self._retrieval.append(
            RetrievalRecord(tool=tool, latency_ms=latency_ms, results=results)
        )

    def mark_first_token(self) -> None:
        """Set TTFT once, on the first streamed token; later calls no-op (Req 2.10)."""
        if self._ttft_ms is None:
            self._ttft_ms = int((time.monotonic() - self._t0) * 1000)

    def record_prompt(self, messages) -> None:
        """Record the prompt sent to the model — last call wins (Req 2.3)."""
        self._final_prompt = _render_messages(messages)

    def record_usage(self, input_tokens: int | None, output_tokens: int | None) -> None:
        """Record token counts; None means unavailable and stays None (Req 2.8)."""
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    def record_response(self, answer: str) -> None:
        """Record the complete response assembled from all streamed tokens (Req 2.3)."""
        self._response = answer

    def record_failure(self, step: str, error: str) -> None:
        """Record the failing pipeline step and error message (Req 2.6)."""
        self._failure = TraceFailure(step=step, error=error)

    # ------------------------------------------------------------------ #
    # Finalization
    # ------------------------------------------------------------------ #

    def build_trace(self, cost: CostEstimate) -> Trace:
        """Freeze the accumulated state into the immutable Trace model.

        Missing token counts stay None, TTFT stays None when never marked;
        total latency runs from request receipt to now (Req 2.4, 2.8, 2.10).
        """
        received_at = self.received_at.isoformat(timespec="milliseconds")
        received_at = received_at.replace("+00:00", "Z")
        return Trace(
            request_id=self.request_id,
            session_id=self.session_id,
            received_at=received_at,
            query=self.query,
            model_id=self.model_id,
            retrieval=tuple(self._retrieval),
            final_prompt=self._final_prompt,
            response=self._response,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cost=cost,
            ttft_ms=self._ttft_ms,
            total_latency_ms=int((time.monotonic() - self._t0) * 1000),
            failure=self._failure,
        )

    # Read access for the finalizer (cost estimation needs these).
    @property
    def input_tokens(self) -> int | None:
        return self._input_tokens

    @property
    def output_tokens(self) -> int | None:
        return self._output_tokens

    @property
    def failure(self) -> TraceFailure | None:
        return self._failure
