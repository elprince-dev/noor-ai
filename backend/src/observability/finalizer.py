"""Trace finalization orchestration (Req 3.1, 3.3, 3.5, 3.7).

`TraceFinalizer` is the only class that knows the finalization *sequence*:
build → estimate cost → truncate → emit → persist. Each collaborator knows
only its own step, and every dependency is constructor-injected so tests
run against pure objects or in-memory fakes.

The finalizer also owns the error policy: observability never breaks the
product. Persistence failures are logged and swallowed (Req 3.5); any
other internal exception degrades to a logged warning.
"""
from src.observability.cost import CostEstimator
from src.observability.logging import log_json
from src.observability.repository import TraceRepository, TraceStoreError
from src.observability.sink import TraceSink
from src.observability.trace_context import TraceContext
from src.observability.truncation import TraceTruncator


class TraceFinalizer:
    """Orchestrates trace assembly, emission, and persistence for one request."""

    def __init__(
        self,
        estimator: CostEstimator,
        truncator: TraceTruncator,
        sink: TraceSink,
        repository: TraceRepository,
        enabled: bool,
    ) -> None:
        self._estimator = estimator
        self._truncator = truncator
        self._sink = sink
        self._repository = repository
        self._enabled = enabled

    def finalize(self, ctx: TraceContext) -> None:
        """Assemble, emit, and persist the request's trace.

        No-op when tracing is disabled — the context (and its Request_ID)
        still exists so streaming and feedback keep working (Req 3.7).

        Otherwise: estimate cost → build the immutable Trace → truncate to
        fit → emit via the sink (Req 3.1) → persist via the repository,
        but only when the request had no failure (Req 3.3 — failed requests
        are emitted, never persisted).

        Never raises: persistence failures are logged as
        `{"log_type": "trace_persist_error", "request_id": ...}` and
        swallowed (Req 3.5); any other internal exception degrades to a
        logged warning — the response path is never disturbed.
        """
        if not self._enabled:
            return
        try:
            cost = self._estimator.estimate(
                ctx.input_tokens, ctx.output_tokens, ctx.model_id
            )
            trace = ctx.build_trace(cost)
            trace = self._truncator.truncate_to_fit(trace)
            self._sink.emit(trace)
            if ctx.failure is None:
                self._persist(trace)
        except Exception as exc:  # noqa: BLE001 — observability must not break the product
            log_json(
                "warning",
                "trace finalization failed",
                request_id=ctx.request_id,
                error=str(exc),
            )

    def _persist(self, trace) -> None:
        """Persist the trace, converting store failures into a logged error."""
        try:
            self._repository.put(trace)
        except TraceStoreError as exc:
            log_json(
                "error",
                "failed to persist trace",
                log_type="trace_persist_error",
                request_id=trace.request_id,
                error=str(exc),
            )
