"""Property 2: Request_ID reaches the client before the stream ends (design.md).

*For any* streamed chat response, an event carrying the Request_ID is
delivered no later than the final response event, so the client always
holds the Request_ID by stream completion.

**Validates: Requirements 1.3**

Pure in-memory Hypothesis tests — no AWS calls. Arbitrary scripted agent
streams (token and tool events in any order, optionally terminated by the
chain's bare ``done`` event, plain exhaustion, or an exception) are served
by a stub chat service swapped in for the module-level ``chat_service`` in
``src.app``, and the real ``/api/ask`` endpoint is driven through FastAPI's
TestClient. For every generated stream the NDJSON response must satisfy:

(a) the FIRST event is ``meta`` carrying a ``request_id``;
(b) the stream ends with ``done`` (success) or ``error`` (mid-stream
    failure) carrying the SAME ``request_id``;
(c) the ``request_id`` parses as a version-4 UUID.

Tracing is kept out of the way deterministically: ``TRACE_ENABLED=false``
is set and the wiring lru_caches are cleared *before* ``src.app`` is
imported (so the module-level ``build_trace_finalizer()`` builds a
disabled finalizer), and, belt-and-suspenders, every example additionally
swaps ``src.app.finalizer`` for a freshly-constructed disabled
``TraceFinalizer`` so no example can ever reach the Dynamo repository —
regardless of module import order across the test session.

TestClient buffers the streamed body, so the NDJSON is recovered from
``response.text``. Lines are split on ``\\n`` only (never ``splitlines()``):
``json.dumps(..., ensure_ascii=False)`` leaves U+2028/U+2029 unescaped
inside token text, and those must not be treated as event delimiters.
"""
# Feature: rag-evaluation-observability, Property 2: Request_ID reaches the client before the stream ends
import json
import os
import uuid
from contextlib import contextmanager

from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

# TRACE_ENABLED must be false before src.app is imported: app.py calls the
# lru_cached build_trace_finalizer() at import time, and only a disabled
# finalizer is guaranteed never to touch the real DynamoTraceRepository.
os.environ["TRACE_ENABLED"] = "false"

from src.observability.wiring import (  # noqa: E402
    build_trace_finalizer,
    build_trace_repository,
)

build_trace_finalizer.cache_clear()
build_trace_repository.cache_clear()

from src import app as app_module  # noqa: E402
from src.observability.cost import CostEstimator  # noqa: E402
from src.observability.finalizer import TraceFinalizer  # noqa: E402
from src.observability.truncation import TraceTruncator  # noqa: E402
from src.streaming.agent_events import AgentEvent  # noqa: E402


class NullSink:
    """`TraceSink` fake — a disabled finalizer never reaches it anyway."""

    def emit(self, trace) -> None:  # pragma: no cover — disabled path
        raise AssertionError("sink must never be touched: tracing is disabled")


class NullRepository:
    """`TraceRepository` fake — a disabled finalizer never reaches it."""

    def put(self, trace) -> None:  # pragma: no cover — disabled path
        raise AssertionError("repository must never be touched: tracing is disabled")

    def get(self, request_id):  # pragma: no cover — disabled path
        raise AssertionError("repository must never be touched: tracing is disabled")


class ScriptedChatService:
    """Stub for the module-level ``chat_service`` in src.app.

    Replays an arbitrary scripted stream of agent events, then either ends
    with the chain's bare ``done`` event (mirroring the real
    ConversationChain), simply exhausts, or raises an exception mid-stream.
    """

    def __init__(self, events, terminal: str, error_detail: str = "") -> None:
        self._events = list(events)
        self._terminal = terminal
        self._error_detail = error_detail

    async def ask_stream(self, request):
        for event in self._events:
            yield event
        if self._terminal == "bare_done":
            yield AgentEvent.done()
        elif self._terminal == "exception":
            raise RuntimeError(self._error_detail)


@contextmanager
def scripted_client(events, terminal: str, error_detail: str = ""):
    """TestClient against the real app, with the scripted chat service and
    a guaranteed-disabled TraceFinalizer swapped in for one example."""
    original_service = app_module.chat_service
    original_finalizer = app_module.finalizer
    app_module.chat_service = ScriptedChatService(events, terminal, error_detail)
    app_module.finalizer = TraceFinalizer(
        estimator=CostEstimator(pricing={}),
        truncator=TraceTruncator(),
        sink=NullSink(),
        repository=NullRepository(),
        enabled=False,
    )
    try:
        yield TestClient(app_module.app)
    finally:
        app_module.chat_service = original_service
        app_module.finalizer = original_finalizer


def post_ask(client: TestClient):
    return client.post(
        "/api/ask",
        json={"question": "What is zakat?", "session_id": "prop2-session"},
    )


def ndjson_lines(response) -> list[dict]:
    """Parse the buffered NDJSON body: split on \\n only (see module doc)."""
    lines = [line for line in response.text.split("\n") if line]
    return [json.loads(line) for line in lines]


def assert_uuid4(request_id) -> None:
    assert isinstance(request_id, str)
    assert uuid.UUID(request_id).version == 4  # (c)


# --------------------------------------------------------------------------- #
# Strategies: arbitrary scripted agent streams
# --------------------------------------------------------------------------- #

text_content = st.text(max_size=40)  # unicode incl. Arabic, U+2028, empty

token_events = st.builds(AgentEvent.token, text_content)
tool_start_events = st.builds(
    AgentEvent.tool_start,
    st.uuids().map(str),
    st.sampled_from(["search_quran", "search_hadith"]),
    text_content,
)
tool_end_events = st.builds(
    AgentEvent.tool_end,
    st.uuids().map(str),
    st.sampled_from(["search_quran", "search_hadith"]),
    st.integers(min_value=0, max_value=60_000),
    st.integers(min_value=0, max_value=50),
)

agent_events = st.one_of(token_events, tool_start_events, tool_end_events)
scripted_streams = st.lists(agent_events, max_size=8)


# --------------------------------------------------------------------------- #
# Property 2
# --------------------------------------------------------------------------- #


class TestProperty2RequestIdStreamDelivery:
    @settings(max_examples=100, deadline=None)
    @given(
        events=scripted_streams,
        terminal=st.sampled_from(["bare_done", "exhausted"]),
    )
    def test_successful_stream_delivers_request_id_first_and_last(
        self, events, terminal
    ):
        """For any successful scripted stream — with or without the chain's
        bare ``done`` — the NDJSON response starts with a ``meta`` event
        carrying a uuid4 Request_ID and ends with a ``done`` event
        repeating the SAME Request_ID (Req 1.3)."""
        with scripted_client(events, terminal) as client:
            response = post_ask(client)

        assert response.status_code == 200
        parsed = ndjson_lines(response)
        assert len(parsed) >= 2

        first, last = parsed[0], parsed[-1]
        assert first["type"] == "meta"  # (a) meta before any token
        assert_uuid4(first["request_id"])

        assert last["type"] == "done"  # (b) final event carries the id
        assert last["request_id"] == first["request_id"]

        # The chain's bare done is replaced, never leaked mid-stream.
        assert all(event["type"] != "done" for event in parsed[:-1])
        assert all(event["type"] != "meta" for event in parsed[1:])

    @settings(max_examples=100, deadline=None)
    @given(
        events=st.lists(agent_events, min_size=1, max_size=8),
        error_detail=text_content,
    )
    def test_midstream_failure_stream_ends_with_error_carrying_same_request_id(
        self, events, error_detail
    ):
        """For any scripted stream that raises after at least one event,
        the NDJSON response still starts with ``meta`` and ends with an
        ``error`` event carrying the SAME uuid4 Request_ID — the client
        holds the Request_ID by stream completion even on failure
        (Req 1.3)."""
        with scripted_client(events, "exception", error_detail) as client:
            response = post_ask(client)

        assert response.status_code == 200
        parsed = ndjson_lines(response)
        assert len(parsed) >= 2

        first, last = parsed[0], parsed[-1]
        assert first["type"] == "meta"  # (a)
        assert_uuid4(first["request_id"])

        assert last["type"] == "error"  # (b) failure still carries the id
        assert last["request_id"] == first["request_id"]
        assert last["detail"] == str(RuntimeError(error_detail))

    @settings(max_examples=100, deadline=None)
    @given(error_detail=text_content)
    def test_prestream_failure_response_still_carries_uuid4_request_id(
        self, error_detail
    ):
        """For any exception raised before the first event is produced, no
        stream starts — the client gets an HTTP 500 whose detail carries a
        uuid4 Request_ID, so the Request_ID is always held by the client
        when the exchange ends (Req 1.3 boundary, Req 1.5)."""
        with scripted_client([], "exception", error_detail) as client:
            response = post_ask(client)

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail["detail"] == str(RuntimeError(error_detail))
        assert_uuid4(detail["request_id"])
