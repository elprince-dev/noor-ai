"""Feedback request validation and stored-record shape (Req 11.3, 11.4).

`FeedbackRequest` is the HTTP boundary model — Pydantic rejects a missing
or empty `request_id` and any rating outside {up, down} with a 422 before
anything touches the service (Req 11.4). `FeedbackRecord` is the immutable
shape the service builds and the repository stores.
"""
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

Rating = Literal["up", "down"]


class FeedbackRequest(BaseModel):
    """Body of POST /api/feedback."""

    request_id: str = Field(min_length=1)
    rating: Rating
    comment: str | None = Field(default=None, max_length=2000)


@dataclass(frozen=True)
class FeedbackRecord:
    """A timestamped rating keyed by Request_ID (Req 11.3).

    `feedback_at` is an ISO-8601 UTC timestamp; it doubles as the
    `RatingIndex` sort key so triage can list newest-first (Req 12.2).
    """

    request_id: str
    rating: Rating
    feedback_at: str
    comment: str | None = None
