"""Turns a validated feedback request into a stored, timestamped record (Req 11.3, 11.5).

The service owns the timestamp so the stored `FeedbackAt` always reflects
when the API accepted the rating, not when the client sent it. Storage is
constructor-injected, so Property 29 tests run against an in-memory fake.
"""
from datetime import datetime, timezone

from src.feedback.models import FeedbackRecord, FeedbackRequest
from src.feedback.repository import FeedbackRepository


class FeedbackService:
    def __init__(self, repository: FeedbackRepository) -> None:
        self._repository = repository

    def submit(self, req: FeedbackRequest) -> None:
        """Build {RequestId, Rating, Comment?, FeedbackAt: iso-utc} and store it.

        repository.put() is an unconditional overwrite, so a repeat rating
        for the same Request_ID replaces the prior one (Req 11.5).
        """
        record = FeedbackRecord(
            request_id=req.request_id,
            rating=req.rating,
            feedback_at=datetime.now(timezone.utc).isoformat(),
            comment=req.comment,
        )
        self._repository.put(record)
