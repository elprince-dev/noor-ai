"""Unit tests for persistence ordering and retention (Req 3.2, 3.6).

Persistence ordering: /api/ask finalizes the trace in the stream
generator's ``finally`` block — after the last token, before the generator
returns (Req 3.2). The test drives the real endpoint with a stubbed chat
stream and the module-level finalizer replaced by a real ``TraceFinalizer``
wired over in-memory fakes, consumes the streaming response, and asserts
the repository holds the trace (keyed by the ``meta`` event's request_id)
by the time the stream is fully consumed.

Retention: ``DynamoTraceRepository.put`` stamps ``ExpiresAt = now +
retention_days`` (epoch seconds) on every item, and the wiring composition
root defaults ``TRACE_RETENTION_DAYS`` to 90 days (Req 3.6). Verified with
a stubbed table object capturing the PutItem payload — no AWS calls.
"""
import json
import time

from fastapi.testclient import TestClient

import src.app as app_module
from src.observability.cost import CostEstimator
from src.observability.finalizer import TraceFinalizer
from src.observability.models import CostEstimate, Trace
from src.observability.repository import DynamoTraceRepository
from src.observability.truncation import TraceTruncator
from src.observability.wiring import build_trace_repository
from src.streaming.agent_events import AgentEvent
from tests.observability.test_property_trace_store import InMemoryTraceRepository

_SECONDS_PER_DAY = 86_400


class RecordingTraceSink:
    """In-memory `TraceSink` fake — keeps test stdout free of log lines."""

    def __init__(self) -> None:
        self.emitted: list[Trace] = []

    def emit(self, trace: Trace) -> None:
        self.emitted.append(trace)


class StubChatService:
    """`ChatService` stand-in whose stream yields a fixed event sequence."""

    def __init__(self, events: list[AgentEvent]) -> None:
        self._events = events

    async def ask_stream(self, request):
        for event in self._events:
            yield event


def make_finalizer(repository, sink) -> TraceFinalizer:
    """Real finalizer over pure collaborators and in-memory fakes."""
    return TraceFinalizer(
        estimator=CostEstimator(pricing={}),
        truncator=TraceTruncator(),
        sink=sink,
        repository=repository,
        enabled=True,
    )


class TestPersistenceOrdering:
    def test_trace_persisted_before_stream_generator_completes(self, monkeypatch):
        """Consuming /api/ask's stream to exhaustion means the generator
        returned — and by then the trace must already be persisted in the
        repository under the meta event's request_id (Req 3.2)."""
        repository = InMemoryTraceRepository()
        sink = RecordingTraceSink()
        monkeypatch.setattr(app_module, "finalizer", make_finalizer(repository, sink))
        monkeypatch.setattr(
            app_module,
            "chat_service",
            StubChatService(
                [
                    AgentEvent.token("In the name "),
                    AgentEvent.token("of Allah."),
                    AgentEvent.done(),
                ]
            ),
        )

        client = TestClient(app_module.app)
        with client.stream(
            "POST",
            "/api/ask",
            json={"question": "What is Surah Al-Fatiha?", "session_id": "sess-1"},
        ) as response:
            assert response.status_code == 200
            lines = [json.loads(line) for line in response.iter_lines() if line]

            # The meta event announces the Request_ID before any token.
            assert lines[0]["type"] == "meta"
            request_id = lines[0]["request_id"]

            # The stream iterator is exhausted, so the generator has
            # completed — the trace must already be in the store.
            stored = repository.get(request_id)
            assert stored is not None
            assert stored.request_id == request_id
            assert stored.query == "What is Surah Al-Fatiha?"
            assert stored.session_id == "sess-1"
            assert stored.failure is None

        # Sanity on the stream shape: tokens then a request_id-carrying done.
        assert [l["type"] for l in lines] == ["meta", "token", "token", "done"]
        assert lines[-1]["request_id"] == request_id

        # The trace was also emitted (emit precedes persist in finalize).
        assert [t.request_id for t in sink.emitted] == [request_id]


class CapturingTable:
    """Stubbed DynamoDB Table capturing every put_item payload."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def put_item(self, Item: dict) -> None:  # noqa: N803 — boto3 kwarg casing
        self.items.append(Item)


def make_trace(request_id: str = "req-1") -> Trace:
    return Trace(
        request_id=request_id,
        session_id="sess-1",
        received_at="2025-01-01T00:00:00.000Z",
        query="q",
        model_id="model",
        retrieval=(),
        final_prompt=None,
        response="answer",
        input_tokens=None,
        output_tokens=None,
        cost=CostEstimate(computed=False, reason="token counts unavailable"),
        ttft_ms=None,
        total_latency_ms=10,
    )


class TestExpiresAtRetention:
    # ExpiresAt is int(time.time()) + retention; bracket the call with
    # before/after timestamps so the assertion tolerates clock ticks.

    def test_expires_at_is_now_plus_configured_retention(self):
        """put stamps ExpiresAt = now + retention_days in epoch seconds
        for a custom retention (Req 3.6)."""
        repository = DynamoTraceRepository(table_name="traces", retention_days=7)
        table = CapturingTable()
        repository._table = table  # inject stub — put never touches AWS

        before = int(time.time())
        repository.put(make_trace())
        after = int(time.time())

        assert len(table.items) == 1
        item = table.items[0]
        assert item["RequestId"] == "req-1"
        assert before + 7 * _SECONDS_PER_DAY <= item["ExpiresAt"]
        assert item["ExpiresAt"] <= after + 7 * _SECONDS_PER_DAY

    def test_wiring_defaults_retention_to_90_days(self, monkeypatch):
        """With TRACE_RETENTION_DAYS unset, the composition root builds the
        repository with the 90-day default, and put stamps ExpiresAt
        accordingly (Req 3.6)."""
        monkeypatch.delenv("TRACE_RETENTION_DAYS", raising=False)
        build_trace_repository.cache_clear()
        try:
            repository = build_trace_repository()
            assert isinstance(repository, DynamoTraceRepository)
            assert repository._retention_days == 90

            table = CapturingTable()
            repository._table = table
            before = int(time.time())
            repository.put(make_trace())
            after = int(time.time())

            expires_at = table.items[0]["ExpiresAt"]
            assert before + 90 * _SECONDS_PER_DAY <= expires_at
            assert expires_at <= after + 90 * _SECONDS_PER_DAY
        finally:
            # Don't leak the test-environment repository to other tests.
            build_trace_repository.cache_clear()
