"""Property 29: Feedback persistence is validated last-write-wins (design.md).

*For any* sequence of feedback submissions for arbitrary Request_IDs,
every valid submission (present request_id, rating in {up, down}) is
persisted with rating and timestamp; every invalid submission is
rejected with a 4xx and persists nothing; and the stored record for
each Request_ID always equals the most recent valid submission for it.

**Validates: Requirements 11.3, 11.4, 11.5**

Pure in-memory Hypothesis tests — no AWS calls. The property exercises
the real HTTP boundary (a FastAPI app including the production feedback
router, driven through TestClient) with the production `FeedbackService`
injected over an in-memory `FeedbackRepository` fake via
`dependency_overrides`. A minimal app containing just the feedback
router keeps the test independent of the chat pipeline imports.

A fresh app/client/repository is built inside each test body because
Hypothesis reruns the function body per example while pytest fixtures
are created once per test function — building inside the body guarantees
a clean store for every generated example.
"""
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from src.feedback.models import FeedbackRecord
from src.feedback.router import build_feedback_service
from src.feedback.router import router as feedback_router
from src.feedback.service import FeedbackService


class InMemoryFeedbackRepository:
    """Dict-backed `FeedbackRepository` fake with DynamoDB PutItem
    semantics: put is an unconditional overwrite keyed by Request_ID,
    so at most one record exists per Request_ID (Req 11.5)."""

    def __init__(self) -> None:
        self.records: dict[str, FeedbackRecord] = {}

    def put(self, record: FeedbackRecord) -> None:
        self.records[record.request_id] = record

    def list_down_rated(self) -> list[FeedbackRecord]:
        down = [r for r in self.records.values() if r.rating == "down"]
        return sorted(down, key=lambda r: r.feedback_at, reverse=True)


def make_client() -> tuple[TestClient, InMemoryFeedbackRepository]:
    """Minimal app: just the production feedback router, with the
    production service wired over the in-memory fake (no AWS)."""
    repo = InMemoryFeedbackRepository()
    app = FastAPI()
    app.include_router(feedback_router)
    app.dependency_overrides[build_feedback_service] = lambda: FeedbackService(repo)
    return TestClient(app), repo


# --- Strategies -----------------------------------------------------------

ratings = st.sampled_from(["up", "down"])
request_ids = st.text(min_size=1, max_size=64)
comments = st.text(max_size=2000)

# A valid submission: (request_id, rating, comment | None). None means
# the comment field is omitted from the JSON body entirely.
valid_submissions = st.tuples(request_ids, ratings, st.none() | comments)

bad_ratings = st.one_of(
    st.sampled_from(["", "UP", "Down", "thumbs_up", "upp", "neutral"]),
    st.text().filter(lambda s: s not in {"up", "down"}),
    st.integers(),
    st.booleans(),
    st.lists(ratings, max_size=2),
)

# Invalid submissions per Req 11.4 plus schema violations: missing/empty
# request_id, rating outside {up, down}, over-long comment, wrong types.
invalid_payloads = st.one_of(
    # missing request_id
    st.builds(lambda r: {"rating": r}, ratings),
    # empty request_id (fails min_length=1)
    st.builds(lambda r: {"request_id": "", "rating": r}, ratings),
    # missing rating
    st.builds(lambda rid: {"request_id": rid}, request_ids),
    # rating outside {up, down} (including wrong types)
    st.builds(lambda rid, r: {"request_id": rid, "rating": r}, request_ids, bad_ratings),
    # comment over 2000 chars
    st.builds(
        lambda rid, r, extra: {"request_id": rid, "rating": r, "comment": "x" * (2001 + extra)},
        request_ids,
        ratings,
        st.integers(min_value=0, max_value=100),
    ),
    # wrong type for request_id
    st.builds(
        lambda rid, r: {"request_id": rid, "rating": r},
        st.one_of(st.integers(), st.booleans(), st.lists(st.text(), max_size=2)),
        ratings,
    ),
    # wrong type for comment
    st.builds(
        lambda rid, r, c: {"request_id": rid, "rating": r, "comment": c},
        request_ids,
        ratings,
        st.one_of(st.integers(), st.lists(st.text(), max_size=2)),
    ),
)


def _post(client: TestClient, request_id: str, rating: str, comment: str | None):
    body: dict = {"request_id": request_id, "rating": rating}
    if comment is not None:
        body["comment"] = comment
    return client.post("/api/feedback", json=body)


def _assert_utc_timestamp(value: str) -> None:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)


class TestProperty29FeedbackPersistence:
    @settings(max_examples=100, deadline=None)
    @given(submission=valid_submissions)
    def test_valid_submission_returns_204_and_persists(self, submission):
        """Any valid submission gets a 204 and persists a record keyed by
        Request_ID carrying the rating, a UTC timestamp, and the comment
        when one was given (Req 11.3)."""
        request_id, rating, comment = submission
        client, repo = make_client()

        response = _post(client, request_id, rating, comment)

        assert response.status_code == 204
        assert set(repo.records) == {request_id}
        record = repo.records[request_id]
        assert record.request_id == request_id
        assert record.rating == rating
        assert record.comment == comment
        _assert_utc_timestamp(record.feedback_at)

    @settings(max_examples=100, deadline=None)
    @given(request_id=request_ids, submissions=st.lists(st.tuples(ratings, st.none() | comments), min_size=1, max_size=6))
    def test_repeat_submissions_same_request_id_last_write_wins(self, request_id, submissions):
        """Any sequence of valid submissions for the same Request_ID ends
        with exactly one stored record carrying the last rating and
        comment — the prior record is overwritten (Req 11.5)."""
        client, repo = make_client()

        for rating, comment in submissions:
            assert _post(client, request_id, rating, comment).status_code == 204

        assert set(repo.records) == {request_id}
        last_rating, last_comment = submissions[-1]
        record = repo.records[request_id]
        assert record.rating == last_rating
        assert record.comment == last_comment
        _assert_utc_timestamp(record.feedback_at)

    @settings(max_examples=100, deadline=None)
    @given(payload=invalid_payloads)
    def test_invalid_submission_rejected_with_422_and_persists_nothing(self, payload):
        """Any invalid submission — missing/empty request_id, rating
        outside {up, down}, over-long comment, or wrong types — is
        rejected with a 422 and nothing is persisted (Req 11.4)."""
        client, repo = make_client()

        response = client.post("/api/feedback", json=payload)

        assert response.status_code == 422
        assert repo.records == {}

    @settings(max_examples=100, deadline=None)
    @given(
        sequence=st.lists(
            st.one_of(
                st.tuples(st.just("valid"), valid_submissions),
                st.tuples(st.just("invalid"), invalid_payloads),
            ),
            max_size=8,
        )
    )
    def test_mixed_sequence_store_equals_last_valid_submission_per_id(self, sequence):
        """For any interleaving of valid and invalid submissions across
        arbitrary Request_IDs: valid ones return 204, invalid ones 422,
        and the final store holds exactly one record per Request_ID that
        received a valid submission, equal to the most recent valid
        submission for it (Req 11.3, 11.4, 11.5)."""
        client, repo = make_client()
        expected: dict[str, tuple[str, str | None]] = {}

        for kind, item in sequence:
            if kind == "valid":
                request_id, rating, comment = item
                assert _post(client, request_id, rating, comment).status_code == 204
                expected[request_id] = (rating, comment)
            else:
                assert client.post("/api/feedback", json=item).status_code == 422

        assert set(repo.records) == set(expected)
        for request_id, (rating, comment) in expected.items():
            record = repo.records[request_id]
            assert record.request_id == request_id
            assert record.rating == rating
            assert record.comment == comment
            _assert_utc_timestamp(record.feedback_at)
