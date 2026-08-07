"""Property 10: Persistence failures never disturb the response (design.md).

*For any* chat request during which Trace_Store persistence fails, the
response stream completes without any error indication to the user, and a
persistence-error log line containing the Request_ID is emitted.

**Validates: Requirements 3.5**

Pure in-memory Hypothesis tests — no AWS calls. Arbitrary successful
request recordings (reused from Property 3) are finalized through a real
`TraceFinalizer` wired with in-memory fakes and a repository configured to
raise `TraceStoreError`. The property asserts the three isolation
guarantees: (a) `finalize` never raises, (b) the trace is still emitted
via the sink, and (c) a `{"log_type": "trace_persist_error"}` log line
carrying the Request_ID appears on stdout.

A second property extends the same isolation to *any* internal exception:
a sink (or repository) raising an arbitrary non-TraceStoreError never
propagates to the response path — it degrades to a logged warning
(finalizer error policy, Req 3.5).
"""
# Feature: rag-evaluation-observability, Property 10: Persistence failures never disturb the response
import io
import json
from contextlib import redirect_stdout

from hypothesis import given, settings
from hypothesis import strategies as st

from src.observability.cost import CostEstimator
from src.observability.finalizer import TraceFinalizer
from src.observability.models import Trace
from src.observability.truncation import TraceTruncator
from tests.observability.test_property_trace_completeness import (
    replay_success,
    success_recording,
)
from tests.observability.test_property_trace_store import FailingTraceRepository


def parse_log_lines(raw: str) -> list[dict]:
    """Parse stdout into JSON log records.

    Splits on "\\n" only (what print() emits) — str.splitlines() would
    also split on Unicode line separators (e.g. U+0085) that may appear
    *inside* a JSON string field such as an error message.
    """
    return [json.loads(line) for line in raw.split("\n") if line]


class RecordingTraceSink:
    """In-memory `TraceSink` fake that records every emitted trace."""

    def __init__(self) -> None:
        self.emitted: list[Trace] = []

    def emit(self, trace: Trace) -> None:
        self.emitted.append(trace)


class RaisingTraceSink:
    """Sink that fails with an arbitrary non-TraceStoreError exception."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def emit(self, trace: Trace) -> None:
        raise self._exc


class InMemoryOkRepository:
    """Repository fake that always succeeds (used with the raising sink)."""

    def __init__(self) -> None:
        self.stored: list[Trace] = []

    def put(self, trace: Trace) -> None:
        self.stored.append(trace)

    def get(self, request_id: str) -> Trace | None:  # pragma: no cover - protocol
        for trace in self.stored:
            if trace.request_id == request_id:
                return trace
        return None


def make_finalizer(sink, repository) -> TraceFinalizer:
    """Real finalizer wired with pure collaborators and the given fakes."""
    return TraceFinalizer(
        estimator=CostEstimator(pricing={}),
        truncator=TraceTruncator(),
        sink=sink,
        repository=repository,
        enabled=True,
    )


# Arbitrary non-TraceStoreError internal exceptions.
internal_exceptions = st.builds(
    lambda cls, msg: cls(msg),
    st.sampled_from([RuntimeError, ValueError, KeyError, OSError, TypeError]),
    st.text(max_size=40),
)


class TestProperty10PersistenceFailureIsolation:
    @settings(max_examples=150)
    @given(rec=success_recording)
    def test_persistence_failure_never_raises_and_still_emits_and_logs(self, rec):
        """For any successful request recording, finalizing with a
        repository that raises TraceStoreError (a) never raises, (b) still
        emits the trace via the sink, and (c) logs a trace_persist_error
        line containing the Request_ID (Req 3.5)."""
        ctx, _ = replay_success(rec)
        sink = RecordingTraceSink()
        finalizer = make_finalizer(sink, FailingTraceRepository())

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            finalizer.finalize(ctx)  # (a) must not raise

        # (b) The trace still reached the sink, for this request.
        assert len(sink.emitted) == 1
        assert sink.emitted[0].request_id == ctx.request_id
        assert sink.emitted[0].failure is None

        # (c) Exactly one persist-error log line, tagged and carrying the
        # Request_ID, is emitted on stdout.
        records = parse_log_lines(buffer.getvalue())
        persist_errors = [
            r for r in records if r.get("log_type") == "trace_persist_error"
        ]
        assert len(persist_errors) == 1
        assert persist_errors[0]["request_id"] == ctx.request_id
        assert persist_errors[0]["level"] == "error"

        # No other error escaped into the response path's log stream as an
        # unexpected finalization warning.
        assert all(
            r.get("log_type") == "trace_persist_error"
            or r.get("message") != "trace finalization failed"
            for r in records
        )

    @settings(max_examples=100)
    @given(rec=success_recording, exc=internal_exceptions)
    def test_arbitrary_internal_exception_never_propagates(self, rec, exc):
        """For any successful recording and any non-TraceStoreError internal
        exception (raised by the sink), finalize never propagates it — the
        failure degrades to a logged warning naming the request (Req 3.5)."""
        ctx, _ = replay_success(rec)
        repository = InMemoryOkRepository()
        finalizer = make_finalizer(RaisingTraceSink(exc), repository)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            finalizer.finalize(ctx)  # must not raise

        # The sink blew up before persistence, so nothing was stored —
        # and nothing propagated to the caller.
        assert repository.stored == []

        # The degradation is visible as a logged warning with the Request_ID.
        records = parse_log_lines(buffer.getvalue())
        warnings = [r for r in records if r.get("level") == "warning"]
        assert len(warnings) == 1
        assert warnings[0]["request_id"] == ctx.request_id
        assert warnings[0]["message"] == "trace finalization failed"
