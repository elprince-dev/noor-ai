"""Trace persistence in the DynamoDB Trace_Store (Req 3.2, 3.4, 3.6, 3.9).

`TraceRepository` keeps persistence swappable — property tests use an
in-memory fake. `DynamoTraceRepository` is the single Trace_Store gateway
for both the write side (finalizer) and the read side (feedback triage,
future tooling).

Failure semantics: `get` returns `None` only for a genuine not-found;
transport/permission failures raise `TraceStoreError` instead, so callers
can always tell "no trace" apart from "could not check" (Req 3.9).

The boto3 Table resource is created lazily on first use so importing this
module (and constructing the repository) needs no AWS credentials.
"""
import time
from decimal import Decimal
from typing import Any, Mapping, Protocol

import boto3

from src.observability.models import (
    SCHEMA_VERSION,
    CostEstimate,
    RetrievalRecord,
    RetrievalResult,
    Trace,
    TraceFailure,
)

_SECONDS_PER_DAY = 86_400


class TraceStoreError(Exception):
    """The Trace_Store could not be read or written (transport, permission,
    or malformed-item failure) — distinct from a not-found `None` (Req 3.9)."""


class TraceRepository(Protocol):
    """Persists and reads traces keyed by Request_ID."""

    def put(self, trace: Trace) -> None: ...

    def get(self, request_id: str) -> Trace | None: ...


class DynamoTraceRepository:
    """Trace_Store backed by the DynamoDB trace table.

    Items carry the trace's schema-version-1 shape plus the `RequestId`
    partition key and an `ExpiresAt` TTL attribute (epoch seconds) set to
    now + retention (Req 3.6). Floats are stored as Decimal (DynamoDB
    rejects Python floats) and converted back on read.
    """

    def __init__(self, table_name: str, retention_days: int) -> None:
        self._table_name = table_name
        self._retention_days = retention_days
        self._table = None  # lazy: no AWS touch until first put/get

    def _get_table(self):
        if self._table is None:
            self._table = boto3.resource("dynamodb").Table(self._table_name)
        return self._table

    def put(self, trace: Trace) -> None:
        """PutItem with ExpiresAt = now + retention (Req 3.2, 3.6).

        Raises TraceStoreError on any failure — caller decides handling.
        """
        item = _floats_to_decimal(trace.to_dict())
        item["RequestId"] = trace.request_id
        item["ExpiresAt"] = int(time.time()) + self._retention_days * _SECONDS_PER_DAY
        try:
            self._get_table().put_item(Item=item)
        except Exception as exc:
            raise TraceStoreError(
                f"failed to store trace {trace.request_id!r} "
                f"in table {self._table_name!r}: {exc}"
            ) from exc

    def get(self, request_id: str) -> Trace | None:
        """GetItem by RequestId (Req 3.4).

        Returns None for not-found; raises TraceStoreError on
        transport/permission failure or a malformed item (Req 3.9).
        """
        try:
            response = self._get_table().get_item(Key={"RequestId": request_id})
        except Exception as exc:
            raise TraceStoreError(
                f"failed to read trace {request_id!r} "
                f"from table {self._table_name!r}: {exc}"
            ) from exc

        item = response.get("Item")
        if item is None:
            return None
        try:
            return _trace_from_item(item)
        except (KeyError, TypeError, ValueError) as exc:
            raise TraceStoreError(
                f"malformed trace item for {request_id!r} "
                f"in table {self._table_name!r}: {exc}"
            ) from exc


def _floats_to_decimal(value: Any) -> Any:
    """Recursively convert floats to Decimal for the DynamoDB serializer.

    Decimal(str(f)) preserves the float's shortest repr instead of its
    binary expansion, so scores/cost round-trip cleanly.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _floats_to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_floats_to_decimal(v) for v in value]
    return value


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _trace_from_item(item: Mapping[str, Any]) -> Trace:
    """Rebuild an immutable Trace from a stored item (Decimals → numbers)."""
    cost_d = item["cost"]
    cost = CostEstimate(
        computed=bool(cost_d["computed"]),
        usd=_opt_float(cost_d.get("usd")),
        reason=cost_d.get("reason"),
    )

    retrieval = tuple(
        RetrievalRecord(
            tool=str(record["tool"]),
            latency_ms=int(record["latency_ms"]),
            results=tuple(
                RetrievalResult(
                    source_id=str(result["source_id"]),
                    score=float(result["score"]),
                )
                for result in record["results"]
            ),
        )
        for record in item.get("retrieval") or []
    )

    failure_d = item.get("failure")
    failure = (
        TraceFailure(step=str(failure_d["step"]), error=str(failure_d["error"]))
        if failure_d is not None
        else None
    )

    return Trace(
        request_id=str(item["request_id"]),
        session_id=str(item["session_id"]),
        received_at=str(item["received_at"]),
        query=str(item["query"]),
        model_id=str(item["model_id"]),
        retrieval=retrieval,
        final_prompt=item.get("final_prompt"),
        response=item.get("response"),
        input_tokens=_opt_int(item.get("input_tokens")),
        output_tokens=_opt_int(item.get("output_tokens")),
        cost=cost,
        ttft_ms=_opt_int(item.get("ttft_ms")),
        total_latency_ms=int(item["total_latency_ms"]),
        failure=failure,
        truncated=bool(item.get("truncated", False)),
        schema_version=int(item.get("schema_version", SCHEMA_VERSION)),
    )
