"""Property 30: Triage listing completeness and order (design.md Correctness
Properties).

*For any* population of Feedback_Records and Traces (including feedback whose
trace is missing or expired), the triage listing contains exactly the records
rated down, ordered by feedback timestamp descending, each showing its
Request_ID and timestamp plus the query and response from its linked Trace —
or a trace-unavailable indication when no Trace exists.

**Validates: Requirements 12.2, 12.5**

Pure in-memory Hypothesis tests — no AWS calls. Both repositories are
constructor-injected fakes: the feedback fake mirrors the DynamoDB
`RatingIndex` semantics (one record per Request_ID, down-rated records
returned newest-first by `FeedbackAt`), the trace fake is a dict-backed
`TraceRepository` where `get` returns the Trace or None. Whether each
feedback record has a linked Trace is drawn independently, and extra
unrelated Traces are mixed in, so the join is exercised in every
combination: all traces present, all missing, and everything between.
"""
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from evals.triage import TriageService
from src.feedback.models import FeedbackRecord
from src.observability.models import CostEstimate, Trace

_EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)


# -- fakes ---------------------------------------------------------------------


class FakeFeedbackRepository:
    """In-memory `FeedbackRepository` with `RatingIndex` read semantics:
    `list_down_rated` returns only down-rated records, newest-first by
    `feedback_at` (the GSI sort key, ScanIndexForward=False)."""

    def __init__(self, records: list[FeedbackRecord]) -> None:
        self._records = records

    def put(self, record: FeedbackRecord) -> None:  # pragma: no cover
        raise NotImplementedError("listing never writes")

    def list_down_rated(self) -> list[FeedbackRecord]:
        down = [r for r in self._records if r.rating == "down"]
        return sorted(down, key=lambda r: r.feedback_at, reverse=True)


class FakeTraceRepository:
    """Dict-backed `TraceRepository`: `get` returns the Trace or None."""

    def __init__(self, traces: dict[str, Trace]) -> None:
        self._traces = traces

    def get(self, request_id: str) -> Trace | None:
        return self._traces.get(request_id)


def make_trace(request_id: str, query: str, response: str) -> Trace:
    """A minimal but complete persisted Trace carrying query/response."""
    return Trace(
        request_id=request_id,
        session_id="session-1",
        received_at="2024-01-01T00:00:00+00:00",
        query=query,
        model_id="anthropic.claude-haiku-4-5",
        retrieval=(),
        final_prompt="prompt",
        response=response,
        input_tokens=10,
        output_tokens=20,
        cost=CostEstimate(computed=False, reason="test"),
        ttft_ms=100,
        total_latency_ms=500,
    )


def never_load_dataset():
    """The listing must never consult the Golden_Dataset (design §triage.py)."""
    raise AssertionError("list_down_rated must not load the dataset")


# -- strategies (all bounded: no filters, small max_size everywhere) -----------

# ISO-8601 UTC timestamps whose lexicographic order equals chronological
# order (fixed format, fixed offset). Duplicates are allowed so ties in
# `FeedbackAt` are exercised.
timestamps = st.integers(min_value=0, max_value=10_000_000).map(
    lambda s: (_EPOCH + timedelta(seconds=s)).isoformat()
)

ratings = st.sampled_from(["up", "down"])
short_text = st.text(max_size=20)

# One drawn feedback row: (rating, timestamp, has_trace, query, response).
# Request_IDs are assigned positionally afterwards, guaranteeing uniqueness
# (DynamoDB: at most one feedback record per Request_ID) without filtering.
feedback_rows = st.tuples(
    ratings, timestamps, st.booleans(), short_text, short_text
)
populations = st.lists(feedback_rows, min_size=0, max_size=10)

# Traces for Request_IDs no feedback references — present in the Trace_Store
# but invisible to the listing.
extra_traces = st.lists(st.tuples(short_text, short_text), max_size=3)


def build_world(
    rows: list[tuple[str, str, bool, str, str]],
    extras: list[tuple[str, str]],
) -> tuple[TriageService, list[FeedbackRecord], dict[str, Trace]]:
    """Materialize drawn rows into records, traces, and the wired service."""
    records: list[FeedbackRecord] = []
    traces: dict[str, Trace] = {}
    for i, (rating, feedback_at, has_trace, query, response) in enumerate(rows):
        request_id = f"req-{i}"
        records.append(
            FeedbackRecord(
                request_id=request_id, rating=rating, feedback_at=feedback_at
            )
        )
        if has_trace:
            traces[request_id] = make_trace(request_id, query, response)
    for j, (query, response) in enumerate(extras):
        request_id = f"unreferenced-{j}"
        traces[request_id] = make_trace(request_id, query, response)
    service = TriageService(
        feedback=FakeFeedbackRepository(records),
        traces=FakeTraceRepository(traces),
        load_dataset=never_load_dataset,
    )
    return service, records, traces


# -- tests ---------------------------------------------------------------------


class TestProperty30TriageListingCompletenessAndOrder:
    @settings(max_examples=100)
    @given(rows=populations, extras=extra_traces)
    def test_listing_is_exactly_the_down_rated_newest_first_with_trace_join(
        self, rows, extras
    ):
        """For any population of Feedback_Records and Traces, the listing
        contains exactly the down-rated records (up-rated and unreferenced
        Traces never appear), ordered by feedback timestamp descending,
        each carrying its Request_ID and timestamp; a record with a linked
        Trace shows that Trace's query and response (Req 12.2), and one
        without shows the trace-unavailable indication instead of being
        dropped (Req 12.5)."""
        service, records, traces = build_world(rows, extras)

        entries = service.list_down_rated()

        # Completeness: exactly the down-rated records — no more, no less.
        down = [r for r in records if r.rating == "down"]
        assert len(entries) == len(down)
        assert {e.request_id for e in entries} == {r.request_id for r in down}

        # Order: newest-first by feedback timestamp (ties permitted).
        stamps = [e.feedback_at for e in entries]
        assert all(a >= b for a, b in zip(stamps, stamps[1:]))

        # Per-entry fields: Request_ID + its own timestamp, and the trace
        # join — query/response from the linked Trace, or the
        # trace-unavailable indication when no Trace exists.
        by_id = {r.request_id: r for r in down}
        for entry in entries:
            assert entry.feedback_at == by_id[entry.request_id].feedback_at
            trace = traces.get(entry.request_id)
            if trace is not None:
                assert entry.trace_available is True
                assert entry.query == trace.query
                assert entry.response == trace.response
            else:
                assert entry.trace_available is False
                assert entry.query is None
                assert entry.response is None

    @settings(max_examples=100)
    @given(
        offsets=st.sets(
            st.integers(min_value=0, max_value=10_000_000), min_size=1, max_size=10
        ),
        data=st.data(),
    )
    def test_distinct_timestamps_give_the_exact_descending_sequence(
        self, offsets, data
    ):
        """When all down-rated feedback timestamps are distinct, the listing
        is the unique strictly-descending sequence — an exact independent
        oracle for the newest-first order (Req 12.2)."""
        stamps = [(_EPOCH + timedelta(seconds=s)).isoformat() for s in sorted(offsets)]
        rows = [
            (
                "down",
                stamp,
                data.draw(st.booleans(), label=f"has_trace[{i}]"),
                "q",
                "r",
            )
            for i, stamp in enumerate(stamps)
        ]
        service, records, _ = build_world(rows, [])

        entries = service.list_down_rated()

        expected = sorted(records, key=lambda r: r.feedback_at, reverse=True)
        assert [(e.request_id, e.feedback_at) for e in entries] == [
            (r.request_id, r.feedback_at) for r in expected
        ]
