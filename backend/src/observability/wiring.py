"""Composition root for the observability package (Req 3.6, 3.7).

The only place the production trace object graph is assembled. Everything
else in the package is constructor-injected, so tests build their own
graphs from pure objects or in-memory fakes and never import this module.

Environment is read when each builder is first called (then cached via
lru_cache), matching the design: Lambda sets TRACE_TABLE, TRACE_ENABLED,
and TRACE_RETENTION_DAYS before the first request. `DynamoTraceRepository`
is lazy, so building the graph needs no AWS credentials.
"""
import os
from functools import lru_cache

from src.config import MODEL_PRICING
from src.observability.cost import CostEstimator
from src.observability.finalizer import TraceFinalizer
from src.observability.repository import DynamoTraceRepository, TraceRepository
from src.observability.sink import CloudWatchTraceSink
from src.observability.truncation import TraceTruncator

_TRUTHY = {"1", "true", "yes"}


def _trace_enabled() -> bool:
    """Parse TRACE_ENABLED (default on) — Req 3.7's kill switch."""
    return os.environ.get("TRACE_ENABLED", "true").strip().lower() in _TRUTHY


@lru_cache(maxsize=1)
def build_trace_repository() -> TraceRepository:
    """Production Trace_Store gateway, shared by wiring and triage tooling.

    Reads TRACE_TABLE and TRACE_RETENTION_DAYS (90-day default, Req 3.6).
    """
    return DynamoTraceRepository(
        table_name=os.environ.get("TRACE_TABLE", "noor-ai-traces"),
        retention_days=int(os.environ.get("TRACE_RETENTION_DAYS", "90")),
    )


@lru_cache(maxsize=1)
def build_trace_finalizer() -> TraceFinalizer:
    """Assemble the production TraceFinalizer graph; app.py calls this once.

    Reads TRACE_TABLE, TRACE_ENABLED, TRACE_RETENTION_DAYS, and
    MODEL_PRICING; constructs CostEstimator + TraceTruncator +
    CloudWatchTraceSink + DynamoTraceRepository + TraceFinalizer.
    """
    return TraceFinalizer(
        estimator=CostEstimator(MODEL_PRICING),
        truncator=TraceTruncator(),
        sink=CloudWatchTraceSink(),
        repository=build_trace_repository(),
        enabled=_trace_enabled(),
    )
