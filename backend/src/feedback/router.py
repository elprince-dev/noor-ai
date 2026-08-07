"""HTTP boundary for the Feedback API (Req 11.2, 11.3, 11.4).

Route, status codes, and service invocation only — no persistence logic.
Pydantic validation on `FeedbackRequest` yields a 422 for a missing/empty
`request_id` or a rating outside {up, down}, and the service is never
invoked, so nothing is persisted for invalid submissions (Req 11.4).
"""
import os
from functools import lru_cache

from fastapi import APIRouter, Depends

from src.feedback.models import FeedbackRequest
from src.feedback.repository import DynamoFeedbackRepository
from src.feedback.service import FeedbackService

router = APIRouter(prefix="/api")


@lru_cache(maxsize=1)
def build_feedback_service() -> FeedbackService:
    """Composition root: production FeedbackService over the DynamoDB table.

    Reads FEEDBACK_TABLE on first call (Lambda sets it before the first
    request); DynamoFeedbackRepository is lazy, so building the graph
    needs no AWS credentials.
    """
    return FeedbackService(
        repository=DynamoFeedbackRepository(
            table_name=os.environ.get("FEEDBACK_TABLE", "noor-ai-feedback"),
        )
    )


@router.post("/feedback", status_code=204)
async def feedback(
    req: FeedbackRequest,
    service: FeedbackService = Depends(build_feedback_service),
) -> None:
    """Persist a rating keyed by Request_ID; 204 on success (Req 11.2, 11.3)."""
    service.submit(req)
