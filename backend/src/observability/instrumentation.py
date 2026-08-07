"""LangGraph event → TraceContext mapping (Req 1.2, 2.3, 2.4, 2.6, 2.8).

`AgentEventRecorder` translates the `astream_events` stream produced by the
agent into recordings on the current request's `TraceContext`. It is
stateless apart from reading `TraceContext.current()`, and no-ops safely
when no context is current (e.g. in unit tests or outside a request).
Recording failures are logged and swallowed — observability never breaks
the product.
"""
from src.observability.logging import log_json
from src.observability.trace_context import TraceContext


def _chunk_text(chunk) -> str:
    """Extract plain text from a streamed chunk's content payload.

    ChatBedrockConverse (Converse API) emits content as a list of blocks,
    e.g. [{"type": "text", "text": "..."}], while other providers emit a
    plain string. Non-text blocks (tool use, etc.) yield no text. Kept local
    so the observability package stays free of service-layer imports.
    """
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


class AgentEventRecorder:
    """Translates LangGraph astream_events into TraceContext recordings.

    Stateless apart from the context it reads via `TraceContext.current()`.
    Event mapping:

    - ``on_chat_model_start``  → ``record_prompt`` (last call wins = the
      final prompt after tool results, Req 2.3)
    - ``on_chat_model_stream`` → ``mark_first_token`` on the first chunk
      carrying text (Req 2.4; later calls no-op inside the context)
    - ``on_chat_model_end``    → ``record_usage`` from the output message's
      ``usage_metadata``; absent metadata ⇒ counts stay ``None`` (Req 2.8)
    - ``on_tool_start`` / ``on_tool_end`` → ``current_step`` flips to
      ``"retrieval"`` / back to ``"generation"`` so ``record_failure`` can
      name the failing step (Req 2.6)
    - ``on_complete(answer)``  → ``record_response`` (Req 2.3)
    """

    def on_event(self, event: dict) -> None:
        """Record one LangGraph event; never raises into the pipeline."""
        ctx = TraceContext.current()
        if ctx is None:
            return
        try:
            self._record(ctx, event)
        except Exception as exc:  # observability never breaks the product
            log_json("warning", "trace event recording failed", error=str(exc))

    def on_complete(self, answer: str) -> None:
        """Record the fully assembled answer; never raises into the pipeline."""
        ctx = TraceContext.current()
        if ctx is None:
            return
        try:
            ctx.record_response(answer)
        except Exception as exc:  # observability never breaks the product
            log_json("warning", "trace response recording failed", error=str(exc))

    @staticmethod
    def _record(ctx: TraceContext, event: dict) -> None:
        kind = event.get("event")
        data = event.get("data") or {}

        if kind == "on_chat_model_start":
            payload = data.get("input")
            if isinstance(payload, dict):
                payload = payload.get("messages")
            if payload is not None:
                ctx.record_prompt(payload)

        elif kind == "on_chat_model_stream":
            if _chunk_text(data.get("chunk")):
                ctx.mark_first_token()

        elif kind == "on_chat_model_end":
            usage = getattr(data.get("output"), "usage_metadata", None)
            if usage:  # absent metadata ⇒ counts stay None (Req 2.8)
                ctx.record_usage(
                    usage.get("input_tokens"), usage.get("output_tokens")
                )

        elif kind == "on_tool_start":
            ctx.current_step = "retrieval"

        elif kind == "on_tool_end":
            ctx.current_step = "generation"
