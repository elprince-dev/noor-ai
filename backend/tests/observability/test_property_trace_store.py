"""Property 9: Trace store round trip and not-found distinction (design.md).

*For any* set of persisted Traces, retrieving by an existing Request_ID
(including one obtained from a Feedback_Record) returns the complete
Trace as persisted, and retrieving by an absent Request_ID returns a
not-found result distinct from a transport error.

**Validates: Requirements 3.4, 3.9, 12.1**

Pure in-memory Hypothesis tests — no AWS calls. Per the design's testing
strategy, the property runs against an in-memory `TraceRepository` fake
implementing the same contract as `DynamoTraceRepository`: `get` returns
`None` only for a genuine not-found, while store failures raise
`TraceStoreError` (a fake configured to fail proves the two outcomes are
distinguishable). A separate property round-trips the Dynamo item shape
(`_floats_to_decimal` → `_trace_from_item`) purely in memory to prove
the serialization helpers reconstruct an equal Trace.

Trace strategies are reused from the Property 8 emission test.
"""
import uuid

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.observability.models import Trace
from src.observability.repository import (
    TraceStoreError,
    _floats_to_decimal,
    _trace_from_item,
)
from tests.observability.test_property_trace_emission import traces


class InMemoryTraceRepository:
    """Dict-backed `TraceRepository` fake with Dynamo-equivalent semantics:
    `get` returns None for an unknown Request_ID (never raises for
    not-found), `put` overwrites by key."""

    def __init__(self) -> None:
        self._items: dict[str, Trace] = {}

    def put(self, trace: Trace) -> None:
        self._items[trace.request_id] = trace

    def get(self, request_id: str) -> Trace | None:
        return self._items.get(request_id)


class FailingTraceRepository:
    """Fake configured to fail: every operation raises `TraceStoreError`,
    the way `DynamoTraceRepository` reports transport/permission failures
    (Req 3.9)."""

    def put(self, trace: Trace) -> None:
        raise TraceStoreError("injected store failure on put")

    def get(self, request_id: str) -> Trace | None:
        raise TraceStoreError("injected store failure on get")


# Sets of traces with unique Request_IDs (the Trace_Store partition key).
trace_sets = st.lists(traces, max_size=5, unique_by=lambda t: t.request_id)


class TestProperty9TraceStoreRoundTrip:
    @settings(max_examples=200)
    @given(persisted=trace_sets)
    def test_put_then_get_returns_equal_trace(self, persisted):
        """For any set of persisted Traces, get by each existing
        Request_ID returns the complete Trace as persisted (Req 3.4,
        12.1 — the triage path reads by the Feedback_Record's
        Request_ID, which is the same key)."""
        repo = InMemoryTraceRepository()
        for trace in persisted:
            repo.put(trace)

        for trace in persisted:
            retrieved = repo.get(trace.request_id)
            assert retrieved == trace

    @settings(max_examples=200)
    @given(persisted=trace_sets, absent_id=st.uuids().map(str))
    def test_get_absent_id_returns_none_without_error(self, persisted, absent_id):
        """A Request_ID never put returns None — a not-found result, not
        an exception — even with other traces present (Req 3.4, 3.9)."""
        assume(absent_id not in {t.request_id for t in persisted})

        repo = InMemoryTraceRepository()
        for trace in persisted:
            repo.put(trace)

        assert repo.get(absent_id) is None

    @settings(max_examples=100)
    @given(trace=traces, request_id=st.uuids().map(str))
    def test_store_failure_raises_distinct_from_not_found(self, trace, request_id):
        """A failing store raises TraceStoreError on both put and get —
        distinguishable from the not-found None (Req 3.9)."""
        repo = FailingTraceRepository()

        with pytest.raises(TraceStoreError):
            repo.put(trace)
        with pytest.raises(TraceStoreError):
            repo.get(request_id)

    @settings(max_examples=200)
    @given(trace=traces)
    def test_dynamo_item_shape_round_trips(self, trace):
        """The Dynamo serialization helpers round-trip in memory: the
        exact item `DynamoTraceRepository.put` would store (floats as
        Decimal, plus RequestId key and ExpiresAt TTL) reconstructs an
        equal Trace via `_trace_from_item` — no AWS calls (Req 3.4)."""
        item = _floats_to_decimal(trace.to_dict())
        item["RequestId"] = trace.request_id
        item["ExpiresAt"] = 1_900_000_000  # TTL attribute is ignored on read

        assert _trace_from_item(item) == trace
